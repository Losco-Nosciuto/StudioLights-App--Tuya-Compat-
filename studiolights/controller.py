"""Parallel LAN controller built on tinytuya.BulbDevice.

Every device owns a persistent socket guarded by its own lock; bulk operations
fan out on a ThreadPoolExecutor so a dead bulb can never slow down the others.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any

import tinytuya

from .models import (
    ERROR_AUTH,
    ERROR_CONFIG,
    ERROR_OFFLINE,
    ERROR_PROTOCOL,
    ERROR_UNKNOWN,
    ERROR_UNSUPPORTED,
    LightDevice,
    LightResult,
    LightState,
    OperationReport,
)

LOGGER = logging.getLogger("studiolights.controller")

SOCKET_TIMEOUT = 1.5
SOCKET_RETRY_LIMIT = 1
MAX_WORKERS = max(8, min(32, (os.cpu_count() or 8) * 4))


class LightError(RuntimeError):
    def __init__(self, message: str, kind: str = ERROR_UNKNOWN) -> None:
        super().__init__(message)
        self.kind = kind


@dataclass
class ScanOutcome:
    found: dict[str, Any] = field(default_factory=dict)
    elapsed_ms: int = 0

    @property
    def count(self) -> int:
        return len(self.found)


def _error_text(response: Any) -> str | None:
    """Return a human-readable error for tinytuya error payloads, else None."""
    if response is None:
        return "Nessuna risposta dal dispositivo"
    if isinstance(response, dict):
        error = response.get("Error")
        if error:
            return str(error)
    return None


def classify_error(message: str) -> str:
    text = message.lower()
    if any(
        token in text
        for token in (
            "905",
            "timeout",
            "offline",
            "unreachable",
            "network error",
            "connection refused",
            "no route",
            "timed out",
        )
    ):
        return ERROR_OFFLINE
    if any(
        token in text
        for token in ("904", "key", "sign", "cipher", "decrypt", "crc", "payload")
    ):
        return ERROR_AUTH
    if any(token in text for token in ("not support", "unsupported", "function")):
        return ERROR_UNSUPPORTED
    if any(token in text for token in ("protocol", "version", "header", "device22")):
        return ERROR_PROTOCOL
    return ERROR_UNKNOWN


def _value_percent(raw: Any, maximum: Any, fallback: int) -> int:
    try:
        raw_value = float(raw)
        max_value = float(maximum)
    except (TypeError, ValueError):
        return fallback
    if max_value <= 0:
        return fallback
    return max(1, min(100, int(round(raw_value / max_value * 100.0))))


def fallback_configure(bulb: tinytuya.BulbDevice, response: Any) -> bool:
    """Best-effort DPS mapping when tinytuya cannot auto-detect the bulb type.

    Happens with some firmware that omits DPs while the bulb is off.
    """
    if not isinstance(response, dict):
        return False
    dps = response.get("dps")
    if not isinstance(dps, dict):
        return False
    keys = {str(key) for key in dps}
    bulb_type: str | None = None
    if keys & {str(index) for index in range(20, 29)}:
        bulb_type = "B"
    elif "1" in keys:
        bulb_type = "A"

    if not bulb_type:
        return False

    defaults = tinytuya.BulbDevice.DEFAULT_DPSET[bulb_type]
    for key, value in defaults.items():
        if key.startswith("value_"):
            bulb.dpset[key] = value
            continue
        if not value:
            continue
        dp = str(value)
        if bulb_type == "B" or dp in keys:
            bulb.dpset[key] = dp

    bulb.bulb_type = bulb_type
    bulb.bulb_configured = True
    bulb.tried_status = True
    for feature in ("brightness", "colourtemp", "colour"):
        setattr(bulb, f"has_{feature}", bool(bulb.dpset.get(feature)))
    LOGGER.warning(
        "Rilevamento automatico fallito: uso il profilo DPS '%s' (DP osservati: %s).",
        bulb_type,
        sorted(keys),
    )
    return True


def build_dps(bulb: tinytuya.BulbDevice, state: LightState) -> dict[str, Any]:
    """Build one atomic Tuya payload (single command, no popcorn effect)."""
    dpset = bulb.dpset
    switch_dp = dpset.get("switch")
    if not switch_dp:
        raise LightError("Il dispositivo non espone un DP di accensione.", ERROR_PROTOCOL)

    payload: dict[str, Any] = {switch_dp: bool(state.power)}
    if not state.power:
        return payload

    maximum = int(dpset.get("value_max") or 0)
    minimum = int(dpset.get("value_min") or 0)
    if maximum <= 0:
        raise LightError(
            "Range di luminosità non rilevato: riprova con «Aggiorna stato».",
            ERROR_PROTOCOL,
        )

    brightness_dp = dpset.get("brightness")
    if brightness_dp:
        raw_brightness = int(round(state.brightness / 100.0 * maximum))
        payload[brightness_dp] = max(minimum, min(maximum, raw_brightness))

    if state.mode == "colour" and state.hw_scene is None:
        colour_dp = dpset.get("colour")
        mode_dp = dpset.get("mode")
        if not colour_dp or not mode_dp:
            raise LightError(
                "Questa lampadina non supporta il colore RGB (solo bianco).",
                ERROR_UNSUPPORTED,
            )
        payload[colour_dp] = bulb.rgb_to_hexvalue(
            *state.rgb, dpset.get("value_hexformat") or "hsv16"
        )
        payload[mode_dp] = "colour"
    else:
        mode_dp = dpset.get("mode")
        if mode_dp:
            payload[mode_dp] = "white"
        colourtemp_dp = dpset.get("colourtemp")
        if colourtemp_dp:
            payload[colourtemp_dp] = int(round(state.colortemp / 100.0 * maximum))

    return payload


def state_from_status(
    bulb: tinytuya.BulbDevice,
    status: dict[str, Any],
    fallback: LightState,
) -> LightState:
    """Convert a decoded tinytuya state dict into our LightState model."""
    maximum = int(bulb.dpset.get("value_max") or 0)
    mode_raw = status.get("mode")
    mode_text = mode_raw.lower() if isinstance(mode_raw, str) else ""

    hw_scene: int | None = fallback.hw_scene
    mode = fallback.mode
    if mode_text.startswith("scene"):
        mode = "scene"
        suffix = mode_text.replace("scene", "").strip("_")
        if suffix.isdigit():
            hw_scene = int(suffix)
    elif mode_text.startswith("colour"):
        mode = "colour"
        hw_scene = None
    elif mode_text.startswith("white"):
        mode = "white"
        hw_scene = None

    rgb = fallback.rgb
    if mode == "colour":
        colour_value = status.get("colour")
        if colour_value:
            try:
                decoded = bulb.colour_rgb(state=status)
                if isinstance(decoded, (tuple, list)) and len(decoded) == 3:
                    rgb = tuple(max(0, min(255, int(channel))) for channel in decoded)  # type: ignore[assignment]
            except (ValueError, TypeError, RuntimeError):
                LOGGER.debug("Impossibile decodificare il colore del dispositivo.", exc_info=True)

    return LightState(
        power=bool(status.get("switch", fallback.power)),
        mode=mode,
        brightness=_value_percent(status.get("brightness"), maximum, fallback.brightness),
        colortemp=_value_percent(status.get("colourtemp"), maximum, fallback.colortemp),
        rgb=rgb,
        hw_scene=hw_scene,
        hw_data=fallback.hw_data if mode == "scene" else None,
    )


class LightController:
    def __init__(
        self,
        *,
        timeout: float = SOCKET_TIMEOUT,
        retry_limit: int = SOCKET_RETRY_LIMIT,
        max_workers: int = MAX_WORKERS,
        persistent: bool = True,
    ) -> None:
        self.timeout = timeout
        self.retry_limit = retry_limit
        self.persistent = persistent
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="tuya-bulb"
        )
        self._registry_lock = threading.Lock()
        self._devices: dict[str, LightDevice] = {}
        self._bulbs: dict[str, tinytuya.BulbDevice] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._closed = False

    # --------------------------------------------------------------- registry
    def sync_devices(self, devices: Iterable[LightDevice]) -> None:
        """Update the registry, dropping sockets when IP/key/version changed."""
        new_devices = {device.id: device for device in devices}
        with self._registry_lock:
            for device_id, bulb in list(self._bulbs.items()):
                old = self._devices.get(device_id)
                new = new_devices.get(device_id)
                if (
                    new is None
                    or old is None
                    or old.ip != new.ip
                    or old.local_key != new.local_key
                    or old.version != new.version
                ):
                    self._bulbs.pop(device_id, None)
                    try:
                        bulb.close()  # best effort; an in-flight command may fail once
                    except Exception:
                        pass
            self._devices = new_devices

    def invalidate(self, device_id: str) -> None:
        with self._registry_lock:
            bulb = self._bulbs.pop(device_id, None)
        if bulb:
            try:
                bulb.close()
            except Exception:
                pass

    def _lock_for(self, device_id: str) -> threading.Lock:
        with self._registry_lock:
            return self._locks.setdefault(device_id, threading.Lock())

    def _get_bulb(self, device: LightDevice) -> tinytuya.BulbDevice:
        with self._registry_lock:
            existing = self._bulbs.get(device.id)
            if existing is not None:
                return existing
            if not device.ip:
                raise LightError(
                    "IP mancante: aprile in Impostazioni o usa «Scansiona LAN».",
                    ERROR_CONFIG,
                )
            if not device.local_key:
                raise LightError("Local Key mancante.", ERROR_CONFIG)
            try:
                bulb = tinytuya.BulbDevice(
                    device.id,
                    device.ip,
                    device.local_key,
                    version=device.version,
                    connection_timeout=self.timeout,
                )
            except Exception as exc:  # pragma: no cover - constructor raises on bad input
                raise LightError(f"Impossibile creare il client: {exc}", ERROR_CONFIG) from exc
            bulb.set_socketTimeout(self.timeout)
            bulb.set_socketRetryLimit(self.retry_limit)
            bulb.set_socketPersistent(self.persistent)
            self._bulbs[device.id] = bulb
            return bulb

    def _ensure_configured(self, bulb: tinytuya.BulbDevice) -> None:
        if bulb.bulb_configured and bulb.dpset.get("switch"):
            return
        response = bulb.status()
        error = _error_text(response)
        if error:
            raise LightError(error, classify_error(error))
        if not bulb.bulb_configured:
            fallback_configure(bulb, response)
        if not bulb.bulb_configured:
            raise LightError(
                "Il dispositivo risponde ma non sembra una lampadina Tuya supportata.",
                ERROR_PROTOCOL,
            )

    # -------------------------------------------------------------- execution
    def _run_one(
        self,
        device: LightDevice,
        action: Callable[[tinytuya.BulbDevice], Any],
        result_state: LightState | None = None,
    ) -> LightResult:
        started = time.perf_counter()
        bulb: tinytuya.BulbDevice | None = None
        lock = self._lock_for(device.id)
        with lock:
            try:
                bulb = self._get_bulb(device)
                self._ensure_configured(bulb)
                output = action(bulb)
                elapsed = int((time.perf_counter() - started) * 1000)
                state = output if isinstance(output, LightState) else result_state
                return LightResult(
                    device_id=device.id,
                    name=device.name,
                    ok=True,
                    latency_ms=elapsed,
                    state=state,
                )
            except LightError as exc:
                elapsed = int((time.perf_counter() - started) * 1000)
                if exc.kind in (ERROR_OFFLINE, ERROR_AUTH, ERROR_PROTOCOL):
                    self._drop_socket(device.id, bulb)
                LOGGER.warning("%s: %s (%s)", device.name, exc, exc.kind)
                return LightResult(
                    device_id=device.id,
                    name=device.name,
                    ok=False,
                    latency_ms=elapsed,
                    error=str(exc),
                    kind=exc.kind,
                )
            except Exception as exc:  # pragma: no cover - defensive
                elapsed = int((time.perf_counter() - started) * 1000)
                LOGGER.exception("%s: errore inatteso", device.name)
                self._drop_socket(device.id, bulb)
                return LightResult(
                    device_id=device.id,
                    name=device.name,
                    ok=False,
                    latency_ms=elapsed,
                    error=f"Errore inatteso: {exc}",
                    kind=ERROR_UNKNOWN,
                )

    def _drop_socket(
        self, device_id: str, bulb: tinytuya.BulbDevice | None
    ) -> None:
        if bulb is not None:
            try:
                bulb.close()
            except Exception:
                pass
        with self._registry_lock:
            if bulb is not None and self._bulbs.get(device_id) is bulb:
                self._bulbs.pop(device_id, None)

    # ------------------------------------------------------------------ public
    def apply_states(self, targets: dict[str, LightState], action: str = "Comando") -> OperationReport:
        started = time.perf_counter()
        results: list[LightResult] = []

        with self._registry_lock:
            devices = {device_id: self._devices[device_id] for device_id in targets if device_id in self._devices}
            missing = [device_id for device_id in targets if device_id not in self._devices]

        for device_id in missing:
            results.append(
                LightResult(
                    device_id=device_id,
                    name=device_id,
                    ok=False,
                    error="Luce non presente nella configurazione.",
                    kind=ERROR_CONFIG,
                )
            )

        futures: dict[Future[LightResult], LightDevice] = {}
        for device_id, device in devices.items():
            state = targets[device_id]
            futures[
                self._executor.submit(
                    self._run_one,
                    device,
                    lambda bulb, desired=state: self._send_state(bulb, desired),
                    state,
                )
            ] = device

        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as exc:  # pragma: no cover - _run_one catches everything
                device = futures[future]
                results.append(
                    LightResult(
                        device_id=device.id,
                        name=device.name,
                        ok=False,
                        error=str(exc),
                        kind=ERROR_UNKNOWN,
                    )
                )

        results.sort(key=lambda item: item.name.lower())
        elapsed = int((time.perf_counter() - started) * 1000)
        report = OperationReport(action=action, results=results, elapsed_ms=elapsed)
        LOGGER.info(
            "%s: %d/%d ok in %d ms%s",
            action,
            report.success_count,
            report.total,
            elapsed,
            f" · offline: {', '.join(report.offline_names)}" if report.offline_names else "",
        )
        return report

    def _send_state(self, bulb: tinytuya.BulbDevice, state: LightState) -> dict[str, Any]:
        if not state.power:
            # A hardware scene always switches the bulb on: force the tiny off payload.
            response = bulb.set_multiple_values(build_dps(bulb, state))
        elif state.hw_scene is not None:
            scene_data = state.hw_data or None
            if scene_data:
                scene_data = "".join(character for character in scene_data if not character.isspace())
                if len(scene_data) % 2 or any(c not in "0123456789abcdefABCDEF" for c in scene_data):
                    raise LightError(
                        "Codice scena non valido: usa una stringa esadecimale pari.",
                        ERROR_CONFIG,
                    )
            try:
                response = bulb.set_scene(int(state.hw_scene), scene_data=scene_data)
            except ValueError as exc:
                raise LightError(str(exc), ERROR_UNSUPPORTED) from exc
        else:
            response = bulb.set_multiple_values(build_dps(bulb, state))
        error = _error_text(response)
        if error:
            raise LightError(error, classify_error(error))
        return response

    def set_power(self, devices: Iterable[LightDevice], states: dict[str, LightState], power: bool) -> OperationReport:
        targets: dict[str, LightState] = {}
        for device in devices:
            base = states.get(device.id, LightState())
            targets[device.id] = base.copy(power=power)
        return self.apply_states(targets, "Accensione" if power else "Spegnimento")

    def refresh(
        self,
        devices: Iterable[LightDevice],
        fallbacks: dict[str, LightState] | None = None,
    ) -> OperationReport:
        started = time.perf_counter()
        fallbacks = fallbacks or {}
        results: list[LightResult] = []
        futures: dict[Future[LightResult], LightDevice] = {}
        for device in devices:
            fallback = fallbacks.get(device.id, LightState())
            futures[
                self._executor.submit(
                    self._run_one,
                    device,
                    lambda bulb, base=fallback: self._read_state(bulb, base),
                )
            ] = device

        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as exc:  # pragma: no cover
                device = futures[future]
                results.append(
                    LightResult(
                        device_id=device.id,
                        name=device.name,
                        ok=False,
                        error=str(exc),
                        kind=ERROR_UNKNOWN,
                    )
                )

        results.sort(key=lambda item: item.name.lower())
        elapsed = int((time.perf_counter() - started) * 1000)
        report = OperationReport(action="Aggiornamento stato", results=results, elapsed_ms=elapsed)
        LOGGER.info(
            "Refresh: %d/%d online in %d ms", report.success_count, report.total, elapsed
        )
        return report

    def _read_state(self, bulb: tinytuya.BulbDevice, fallback: LightState) -> LightState:
        response = bulb.status()
        error = _error_text(response)
        if error:
            raise LightError(error, classify_error(error))
        if not bulb.bulb_configured:
            fallback_configure(bulb, response)
        if not bulb.bulb_configured:
            raise LightError("Tipo di lampadina non riconosciuto.", ERROR_PROTOCOL)
        status = bulb.state()
        error = _error_text(status)
        if error:
            raise LightError(error, classify_error(error))
        if not status:
            raise LightError("Stato vuoto dal dispositivo.", ERROR_PROTOCOL)
        return state_from_status(bulb, status, fallback)

    # ------------------------------------------------------------ diagnostics
    @staticmethod
    def test_connection(device: LightDevice, timeout: float = 2.0) -> tuple[bool, str]:
        bulb: tinytuya.BulbDevice | None = None
        try:
            if not device.ip:
                return False, "IP mancante."
            bulb = tinytuya.BulbDevice(
                device.id,
                device.ip,
                device.local_key,
                version=device.version,
                connection_timeout=timeout,
            )
            bulb.set_socketTimeout(timeout)
            bulb.set_socketRetryLimit(1)
            bulb.set_socketPersistent(False)
            response = bulb.status()
            error = _error_text(response)
            if error:
                return False, f"Errore: {error}"
            if not bulb.bulb_configured:
                fallback_configure(bulb, response)
            if not bulb.bulb_configured:
                return False, "Connesso, ma il dispositivo non sembra una lampadina Tuya."
            dps = response.get("dps", {}) if isinstance(response, dict) else {}
            state = bulb.state()
            summary = ""
            if isinstance(state, dict) and "switch" in state:
                summary = state_from_status(bulb, state, LightState()).summary()
            return True, (
                f"OK · protocollo {device.version} · tipo {bulb.bulb_type} · "
                f"{len(dps)} DP · {summary or 'stato letto'}"
            )
        except Exception as exc:
            return False, f"Errore: {exc}"
        finally:
            if bulb is not None:
                try:
                    bulb.close()
                except Exception:
                    pass

    def scan_lan(self) -> ScanOutcome:
        started = time.perf_counter()
        found = tinytuya.deviceScan(
            verbose=False, maxretry=2, color=False, poll=False
        )
        elapsed = int((time.perf_counter() - started) * 1000)
        if not isinstance(found, dict):
            found = {}
        LOGGER.info("Scansione LAN: %d dispositivi in %d ms", len(found), elapsed)
        return ScanOutcome(found=found, elapsed_ms=elapsed)

    @staticmethod
    def match_scan_ips(
        found: dict[str, Any], devices: Iterable[LightDevice]
    ) -> dict[str, str]:
        """Map configured device id -> IP found by the broadcast scan."""
        by_id: dict[str, str] = {}
        for ip, info in found.items():
            if not isinstance(info, dict):
                continue
            for key in ("gwId", "id", "devId"):
                value = info.get(key)
                if value:
                    by_id[str(value).lower()] = str(ip)
        matches: dict[str, str] = {}
        for device in devices:
            ip = by_id.get(device.id.lower())
            if ip:
                matches[device.id] = ip
        return matches

    # ----------------------------------------------------------------- cleanup
    def shutdown(self) -> None:
        self._closed = True
        with self._registry_lock:
            bulbs = list(self._bulbs.values())
            self._bulbs.clear()
        for bulb in bulbs:
            try:
                bulb.close()
            except Exception:
                pass
        self._executor.shutdown(wait=False, cancel_futures=True)
