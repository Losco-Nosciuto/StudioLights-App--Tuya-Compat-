"""Software colour-flow engine.

Tuya bulbs do not expose a "fade over N seconds" command, so the fade is generated
host-side: small colour frames are streamed to each bulb while the palette position is
derived from the monotonic clock. Each light has at most one frame in flight, so a slow
or offline bulb cannot stall the others.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import Future

from .controller import LightController
from .models import (
    ERROR_AUTH,
    ERROR_OFFLINE,
    ERROR_PROTOCOL,
    ERROR_UNSUPPORTED,
    FlowConfig,
    LightDevice,
    LightResult,
)

LOGGER = logging.getLogger("studiolights.flow")


class FlowRunner:
    def __init__(self, controller: LightController) -> None:
        self.controller = controller
        self._config = FlowConfig()
        self._config_lock = threading.Lock()
        self._devices: list[LightDevice] = []
        self._pending: dict[str, Future[LightResult]] = {}
        self._last_rgb: dict[str, tuple[int, int, int]] = {}
        self._failed: set[str] = set()
        self._failed_details: dict[str, tuple[str, str]] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._started_at = 0.0

    # ------------------------------------------------------------------ public
    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and not self._stop.is_set())

    @property
    def failed_ids(self) -> set[str]:
        return set(self._failed)

    @property
    def failed_details(self) -> dict[str, tuple[str, str]]:
        """device_id -> (error_kind, error_message) for lights removed from the flow."""
        return dict(self._failed_details)

    def config_snapshot(self) -> FlowConfig:
        with self._config_lock:
            return self._config.copy()

    def update_config(self, config: FlowConfig) -> None:
        with self._config_lock:
            self._config = config.copy()

    def start(self, devices: list[LightDevice], config: FlowConfig) -> None:
        self.stop()
        if not devices:
            return
        self.update_config(config)
        self._devices = list(devices)
        self._pending = {}
        self._last_rgb = {}
        self._failed = set()
        self._failed_details = {}
        self._stop.clear()
        self._started_at = time.monotonic()
        self._thread = threading.Thread(
            target=self._loop, name="flow-runner", daemon=True
        )
        self._thread.start()
        LOGGER.info(
            "Flow avviato su %d luci: %s", len(devices), self.config_snapshot().summary
        )

    def stop(self) -> dict[str, tuple[int, int, int]]:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=0.4)
        self._thread = None
        colors = dict(self._last_rgb)
        if colors:
            LOGGER.info("Flow fermato (%d luci).", len(colors))
        return colors

    # ------------------------------------------------------------------- loop
    def _loop(self) -> None:
        while not self._stop.is_set():
            config = self.config_snapshot()
            interval = 1.0 / max(1, config.fps)
            elapsed = time.monotonic() - self._started_at
            count = max(1, len(self._devices))

            for index, device in enumerate(self._devices):
                if self._stop.is_set():
                    break

                pending = self._pending.get(device.id)
                if pending is not None:
                    if not pending.done():
                        # One frame in flight per bulb: never build a backlog.
                        continue
                    self._pending.pop(device.id, None)
                    try:
                        result = pending.result()
                    except Exception:  # pragma: no cover - _run_one catches everything
                        LOGGER.debug("Frame flow fallito su %s", device.name, exc_info=True)
                        result = None
                    if result is not None and not result.ok:
                        if result.kind in (
                            ERROR_OFFLINE,
                            ERROR_AUTH,
                            ERROR_PROTOCOL,
                            ERROR_UNSUPPORTED,
                        ):
                            self._failed.add(device.id)
                            self._failed_details[device.id] = (result.kind, result.error)
                            LOGGER.warning(
                                "Flow: %s rimosso (%s).", device.name, result.error
                            )
                            continue

                if device.id in self._failed:
                    continue

                position = elapsed / config.segment_seconds
                if config.phase_offset and count > 1:
                    position += index / count
                rgb = config.colour_at(position)
                self._last_rgb[device.id] = rgb
                try:
                    self._pending[device.id] = self.controller.submit_colour_frame(
                        device, rgb, config.brightness
                    )
                except Exception:  # pragma: no cover - executor shut down
                    LOGGER.exception("Flow: impossibile accodare il frame.")
                    self._failed.add(device.id)

            self._stop.wait(interval)
