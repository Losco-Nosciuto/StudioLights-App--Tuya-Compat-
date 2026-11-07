"""Screen Sync: capture a monitor, sample its colours and stream them to bulbs."""

from __future__ import annotations

import colorsys
import logging
import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, ImageStat

from .controller import LightController
from .models import (
    ERROR_AUTH,
    ERROR_OFFLINE,
    ERROR_PROTOCOL,
    ERROR_UNSUPPORTED,
    LightDevice,
    LightResult,
)
from .util import (
    atomic_write_json,
    backup_corrupt_file,
    clamp_float,
    clamp_int,
    kelvin_from_temp,
    kelvin_to_rgb,
    read_json,
)

LOGGER = logging.getLogger("studiolights.screen_sync")

SCREEN_CONFIG_FILE = "screen_sync.json"
ANALYSIS_WIDTH = 96
ANALYSIS_HEIGHT = 54

SCREEN_PRESETS: dict[str, dict[str, Any]] = {
    "Realistico": {"saturation": 1.05, "brightness_max": 78, "smoothing": 1.4},
    "Cinema": {"saturation": 1.20, "brightness_max": 65, "smoothing": 1.8},
    "Neon": {"saturation": 1.55, "brightness_max": 85, "smoothing": 0.8},
    "Naturale": {"saturation": 0.95, "brightness_max": 72, "smoothing": 1.6},
    "Bassa latenza": {
        "saturation": 1.10,
        "brightness_max": 75,
        "smoothing": 0.2,
        "fps": 30,
        "turbo": False,
    },
}


@dataclass
class MonitorInfo:
    index: int
    label: str
    left: int
    top: int
    width: int
    height: int
    primary: bool = False


def _mss_factory():
    import mss

    return getattr(mss, "MSS", None) or mss.mss


def list_monitors() -> list[MonitorInfo]:
    """Enumerate Windows/macOS/Linux monitors through mss."""
    try:
        factory = _mss_factory()
        with factory() as sct:
            monitors = list(sct.monitors[1:])
            results: list[MonitorInfo] = []
            resolutions: dict[tuple[int, int], int] = {}
            for monitor in monitors:
                size = (int(monitor["width"]), int(monitor["height"]))
                resolutions[size] = resolutions.get(size, 0) + 1
            for index, monitor in enumerate(monitors, start=1):
                width = int(monitor["width"])
                height = int(monitor["height"])
                left = int(monitor["left"])
                top = int(monitor["top"])
                primary = bool(monitor.get("is_primary"))
                label = f"Schermo {index} · {width}×{height}"
                if primary:
                    label += " · principale"
                if resolutions.get((width, height), 0) > 1:
                    label += f" · ({left},{top})"
                results.append(
                    MonitorInfo(
                        index=index,
                        label=label,
                        left=left,
                        top=top,
                        width=width,
                        height=height,
                        primary=primary,
                    )
                )
            if results:
                return results
    except Exception:
        LOGGER.warning("Enumerazione monitor non disponibile.", exc_info=True)
    return [MonitorInfo(1, "Schermo principale", 0, 0, 1920, 1080, True)]


@dataclass
class SensorZone:
    """A normalized rectangle on the captured screen (0..1 coordinates)."""

    x: float = 0.4
    y: float = 0.4
    w: float = 0.2
    h: float = 0.2

    def __post_init__(self) -> None:
        self.w = clamp_float(self.w, 0.02, 1.0, 0.2)
        self.h = clamp_float(self.h, 0.02, 1.0, 0.2)
        self.x = clamp_float(self.x, 0.0, 1.0 - self.w, 0.4)
        self.y = clamp_float(self.y, 0.0, 1.0 - self.h, 0.4)

    def to_dict(self) -> dict[str, float]:
        return {
            "x": round(self.x, 4),
            "y": round(self.y, 4),
            "w": round(self.w, 4),
            "h": round(self.h, 4),
        }

    @classmethod
    def from_dict(cls, data: Any) -> "SensorZone":
        if not isinstance(data, dict):
            return cls()
        return cls(
            x=data.get("x", 0.4),
            y=data.get("y", 0.4),
            w=data.get("w", 0.2),
            h=data.get("h", 0.2),
        )

    def copy(self) -> "SensorZone":
        return SensorZone.from_dict(self.to_dict())


def default_sensor_zones(count: int = 3) -> list[SensorZone]:
    count = max(1, min(8, int(count)))
    if count == 1:
        return [SensorZone(x=0.3, y=0.15, w=0.4, h=0.6)]
    zones: list[SensorZone] = []
    band = 1.0 / count
    for index in range(count):
        zones.append(
            SensorZone(
                x=index * band + 0.01,
                y=0.12,
                w=max(0.04, band - 0.02),
                h=0.68,
            )
        )
    return zones


@dataclass
class ScreenSyncConfig:
    monitor_index: int = 1
    monitor_label: str = ""
    sampling_mode: str = "zones"
    sensor_zones: list[SensorZone] = field(default_factory=lambda: default_sensor_zones(3))
    zones: int = 3
    sample_grid: int = 2
    smoothing: float = 1.2
    saturation: float = 1.25
    brightness_min: int = 10
    brightness_max: int = 80
    brightness_gamma: float = 1.15
    fps: int = 8
    turbo: bool = False
    neutral_white: bool = True
    neutral_threshold: float = 0.08
    dark_off: bool = True
    dark_off_threshold: int = 5
    ignore_hud: bool = True
    hold_on_black: bool = True
    preset: str = "Realistico"
    zone_map: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.monitor_index = clamp_int(self.monitor_index, 1, 16, 1)
        self.sampling_mode = (
            self.sampling_mode if self.sampling_mode in ("bands", "zones") else "zones"
        )
        self.zones = clamp_int(self.zones, 1, 7, 3)
        cleaned_zones: list[SensorZone] = []
        for item in (self.sensor_zones or [])[:8]:
            cleaned_zones.append(
                item if isinstance(item, SensorZone) else SensorZone.from_dict(item)
            )
        if not cleaned_zones:
            cleaned_zones = default_sensor_zones(3)
        self.sensor_zones = cleaned_zones
        self.sample_grid = clamp_int(self.sample_grid, 1, 3, 2)
        self.smoothing = round(clamp_float(self.smoothing, 0.1, 3.0, 1.2), 2)
        self.saturation = round(clamp_float(self.saturation, 0.5, 2.0, 1.25), 2)
        self.brightness_min = clamp_int(self.brightness_min, 0, 40, 10)
        self.brightness_max = clamp_int(self.brightness_max, 20, 100, 80)
        if self.brightness_max < self.brightness_min:
            self.brightness_max = self.brightness_min
        self.brightness_gamma = round(
            clamp_float(self.brightness_gamma, 0.5, 2.0, 1.15), 2
        )
        self.fps = clamp_int(self.fps, 3, 60, 8)
        self.turbo = bool(self.turbo)
        self.neutral_white = bool(self.neutral_white)
        self.neutral_threshold = round(clamp_float(self.neutral_threshold, 0.0, 0.5, 0.08), 3)
        self.dark_off = bool(self.dark_off)
        self.dark_off_threshold = clamp_int(self.dark_off_threshold, 0, 20, 5)
        self.ignore_hud = bool(self.ignore_hud)
        self.hold_on_black = bool(self.hold_on_black)
        self.preset = self.preset if self.preset in SCREEN_PRESETS else "Realistico"
        count = self.zone_count
        cleaned: dict[str, int] = {}
        for device_id, zone in (self.zone_map or {}).items():
            cleaned[str(device_id)] = clamp_int(zone, -1, count - 1, -1)
        self.zone_map = cleaned

    @property
    def zone_count(self) -> int:
        return len(self.sensor_zones) if self.sampling_mode == "zones" else self.zones

    @property
    def sample_points(self) -> int:
        return self.sample_grid * self.sample_grid

    def assign_default_zones(self, devices: list[LightDevice]) -> None:
        count = max(1, self.zone_count)
        for index, device in enumerate(devices):
            if device.id not in self.zone_map:
                self.zone_map[device.id] = index % count if count > 1 else -1

    def zone_for(self, device: LightDevice, fallback_index: int = 0) -> int:
        zone = self.zone_map.get(device.id)
        if zone is None:
            zone = fallback_index % self.zone_count if self.zone_count > 1 else -1
        return zone

    def to_dict(self) -> dict[str, Any]:
        return {
            "monitor_index": self.monitor_index,
            "monitor_label": self.monitor_label,
            "sampling_mode": self.sampling_mode,
            "sensor_zones": [zone.to_dict() for zone in self.sensor_zones],
            "zones": self.zones,
            "sample_grid": self.sample_grid,
            "smoothing": self.smoothing,
            "saturation": self.saturation,
            "brightness_min": self.brightness_min,
            "brightness_max": self.brightness_max,
            "brightness_gamma": self.brightness_gamma,
            "fps": self.fps,
            "turbo": self.turbo,
            "neutral_white": self.neutral_white,
            "neutral_threshold": self.neutral_threshold,
            "dark_off": self.dark_off,
            "dark_off_threshold": self.dark_off_threshold,
            "ignore_hud": self.ignore_hud,
            "hold_on_black": self.hold_on_black,
            "preset": self.preset,
            "zone_map": dict(self.zone_map),
        }

    @classmethod
    def from_dict(cls, data: Any) -> "ScreenSyncConfig":
        if not isinstance(data, dict):
            return cls()
        return cls(
            monitor_index=data.get("monitor_index", 1),
            monitor_label=str(data.get("monitor_label") or ""),
            sampling_mode=data.get("sampling_mode", "zones"),
            sensor_zones=[
                SensorZone.from_dict(item)
                for item in (data.get("sensor_zones") or [])
                if isinstance(item, dict)
            ],
            zones=data.get("zones", 3),
            sample_grid=data.get("sample_grid", 2),
            smoothing=data.get("smoothing", 1.2),
            saturation=data.get("saturation", 1.25),
            brightness_min=data.get("brightness_min", 10),
            brightness_max=data.get("brightness_max", 80),
            brightness_gamma=data.get("brightness_gamma", 1.15),
            fps=data.get("fps", 8),
            turbo=data.get("turbo", False),
            neutral_white=data.get("neutral_white", True),
            neutral_threshold=data.get("neutral_threshold", 0.08),
            dark_off=data.get("dark_off", True),
            dark_off_threshold=data.get("dark_off_threshold", 5),
            ignore_hud=data.get("ignore_hud", True),
            hold_on_black=data.get("hold_on_black", True),
            preset=data.get("preset", "Realistico"),
            zone_map=data.get("zone_map") or {},
        )

    def copy(self) -> "ScreenSyncConfig":
        return ScreenSyncConfig.from_dict(self.to_dict())


class ScreenSyncStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.path = self.root / SCREEN_CONFIG_FILE

    def load(self) -> ScreenSyncConfig:
        if not self.path.exists():
            return ScreenSyncConfig()
        try:
            return ScreenSyncConfig.from_dict(read_json(self.path))
        except Exception:
            backup = backup_corrupt_file(self.path)
            LOGGER.error("screen_sync.json non leggibile: %s", backup)
            return ScreenSyncConfig()

    def save(self, config: ScreenSyncConfig) -> None:
        atomic_write_json(self.path, config.to_dict(), keep_backup=True)


@dataclass(frozen=True)
class ZoneTarget:
    rgb: tuple[int, int, int]
    brightness: int
    luma: float
    saturation: float
    mode: str = "colour"
    colortemp: int = 50


@dataclass
class ScreenFrame:
    zones: list[ZoneTarget]
    global_target: ZoneTarget
    timestamp: float
    capture_ms: int = 0
    analysis_ms: int = 0
    black: bool = False
    warning: str = ""


@dataclass
class _SampleState:
    rgb: tuple[float, float, float]
    luma: float


def _mean_box(image: Image.Image, box: tuple[int, int, int, int]) -> tuple[tuple[float, float, float], float]:
    left, top, right, bottom = box
    left = max(0, min(image.width, left))
    right = max(0, min(image.width, right))
    top = max(0, min(image.height, top))
    bottom = max(0, min(image.height, bottom))
    if right <= left or bottom <= top:
        return (0.0, 0.0, 0.0), 0.0
    stat = ImageStat.Stat(image.crop((left, top, right, bottom)))
    mean = stat.mean[:3]
    luma = (0.2126 * mean[0] + 0.7152 * mean[1] + 0.0722 * mean[2]) / 255.0
    return (float(mean[0]), float(mean[1]), float(mean[2])), luma


def _content_box(image: Image.Image) -> tuple[int, int, int, int]:
    """Strip black letterbox rows, if present."""
    grayscale = image.convert("L")
    pixels = grayscale.load()
    width, height = grayscale.size
    row_means = [
        sum(pixels[x, y] for x in range(width)) / max(1, width) for y in range(height)
    ]
    threshold = 7.0
    top = 0
    while top < int(height * 0.45) and row_means[top] < threshold:
        top += 1
    bottom = height
    while bottom > int(height * 0.55) and row_means[bottom - 1] < threshold:
        bottom -= 1
    if bottom - top < 4:
        return 0, 0, width, height
    return 0, top, width, bottom


class ScreenAnalyzer:
    """Stateful analyser: zone means -> smoothed RGB/luma -> bulb targets."""

    def __init__(self) -> None:
        self._state: list[_SampleState] = []
        self._global_state: _SampleState | None = None
        self._last_frame: ScreenFrame | None = None

    def update(
        self,
        image: Image.Image,
        config: ScreenSyncConfig,
        dt: float,
        capture_ms: int = 0,
    ) -> ScreenFrame:
        started = time.perf_counter()
        small = image.resize((ANALYSIS_WIDTH, ANALYSIS_HEIGHT), Image.Resampling.BILINEAR)
        gray = small.convert("L")
        gray_full = image.convert("L")
        frame_mean = ImageStat.Stat(gray).mean[0] / 255.0
        frame_median = ImageStat.Stat(gray_full).median[0] / 255.0
        dark_factor = 1.0
        if frame_mean > 0.001:
            # A dark desktop full of white text has a high mean but a low median:
            # dim it down so it does not keep the bulbs lit.
            dark_factor = max(0.35, min(1.0, frame_median / frame_mean))
        if config.sampling_mode == "zones":
            raw_zones: list[tuple[tuple[float, float, float], float]] = []
            raw_lumas: list[float] = []
            for sensor in config.sensor_zones:
                box = (
                    int(sensor.x * small.width),
                    int(sensor.y * small.height),
                    int((sensor.x + sensor.w) * small.width),
                    int((sensor.y + sensor.h) * small.height),
                )
                color, mean_luma = self._zone_mean(small, box, config.sample_grid)
                raw_zones.append((color, mean_luma))
                raw_lumas.append(mean_luma * dark_factor)
            if raw_zones:
                if len(raw_zones) == 1:
                    global_color = raw_zones[0][0]
                else:
                    global_color = (
                        sum(item[0][0] for item in raw_zones) / len(raw_zones),
                        sum(item[0][1] for item in raw_zones) / len(raw_zones),
                        sum(item[0][2] for item in raw_zones) / len(raw_zones),
                    )
                global_mean_luma = sum(item[1] for item in raw_zones) / len(raw_zones)
                global_luma = sum(raw_lumas) / len(raw_lumas)
            else:
                global_color = (0.0, 0.0, 0.0)
                global_mean_luma = 0.0
                global_luma = 0.0
        else:
            content = _content_box(small)
            left, top, right, bottom = content
            content_height = max(1, bottom - top)
            if config.ignore_hud:
                hud_top = top + int(content_height * 0.12)
                hud_bottom = bottom - int(content_height * 0.15)
            else:
                hud_top, hud_bottom = top, bottom
            if hud_bottom <= hud_top + 2:
                hud_top, hud_bottom = top, bottom

            zone_count = max(1, config.zones)
            raw_zones = []
            raw_lumas = []
            for zone_index in range(zone_count):
                zone_left = left + (right - left) * zone_index // zone_count
                zone_right = left + (right - left) * (zone_index + 1) // zone_count
                box = (zone_left, hud_top, zone_right, hud_bottom)
                color, mean_luma = self._zone_mean(small, box, config.sample_grid)
                raw_zones.append((color, mean_luma))
                raw_lumas.append(mean_luma * dark_factor)
            global_raw = self._zone_mean(small, (left, hud_top, right, hud_bottom), 1)
            global_color = global_raw[0]
            global_mean_luma = global_raw[1]
            global_luma = global_mean_luma * dark_factor

        if not self._state or len(self._state) != len(raw_zones):
            self._state = [
                _SampleState(rgb=color, luma=luma)
                for (color, _mean_luma), luma in zip(raw_zones, raw_lumas)
            ]
            self._global_state = _SampleState(rgb=global_color, luma=global_luma)
        alpha = 1.0
        if dt > 0:
            alpha = 1.0 - pow(2.718281828, -dt / max(0.05, config.smoothing))
            alpha = max(0.05, min(1.0, alpha))

        smoothed: list[_SampleState] = []
        for previous, (color, _mean_luma), luma in zip(self._state, raw_zones, raw_lumas):
            current = _SampleState(
                rgb=tuple(previous.rgb[i] + (color[i] - previous.rgb[i]) * alpha for i in range(3)),  # type: ignore[arg-type]
                luma=previous.luma + (luma - previous.luma) * alpha,
            )
            smoothed.append(current)
        assert self._global_state is not None
        global_smoothed = _SampleState(
            rgb=tuple(
                self._global_state.rgb[i] + (global_color[i] - self._global_state.rgb[i]) * alpha
                for i in range(3)
            ),  # type: ignore[arg-type]
            luma=self._global_state.luma + (global_luma - self._global_state.luma) * alpha,
        )
        self._state = smoothed
        self._global_state = global_smoothed

        black = global_mean_luma < 0.012
        targets = [self._target(state, config) for state in smoothed]
        global_target = self._target(global_smoothed, config)
        frame = ScreenFrame(
            zones=targets,
            global_target=global_target,
            timestamp=time.time(),
            capture_ms=capture_ms,
            analysis_ms=int((time.perf_counter() - started) * 1000),
            black=black,
        )
        if black:
            frame.warning = "Schermo nero o protetto: usa borderless / disattiva HDR."
        self._last_frame = frame
        return frame

    def _zone_mean(
        self,
        image: Image.Image,
        box: tuple[int, int, int, int],
        sample_grid: int,
    ) -> tuple[tuple[float, float, float], float]:
        left, top, right, bottom = box
        grid = max(1, sample_grid)
        if grid == 1 or right - left < grid or bottom - top < grid:
            return _mean_box(image, box)
        cells: list[tuple[float, float, float]] = []
        lumas: list[float] = []
        for row in range(grid):
            y0 = top + (bottom - top) * row // grid
            y1 = top + (bottom - top) * (row + 1) // grid
            for column in range(grid):
                x0 = left + (right - left) * column // grid
                x1 = left + (right - left) * (column + 1) // grid
                color, luma = _mean_box(image, (x0, y0, x1, y1))
                cells.append(color)
                lumas.append(luma)
        if not cells:
            return (0.0, 0.0, 0.0), 0.0
        return (
            (
                sum(cell[0] for cell in cells) / len(cells),
                sum(cell[1] for cell in cells) / len(cells),
                sum(cell[2] for cell in cells) / len(cells),
            ),
            sum(lumas) / len(lumas),
        )

    @staticmethod
    def _target(state: _SampleState, config: ScreenSyncConfig) -> ZoneTarget:
        red, green, blue = (max(0.0, min(255.0, channel)) for channel in state.rgb)
        hue, saturation, _value = colorsys.rgb_to_hsv(red / 255, green / 255, blue / 255)
        span = max(0, config.brightness_max - config.brightness_min)
        # Perceptual curve with a dark toe: a nearly black desktop must drive the
        # bulbs to (almost) zero instead of the old luma^0.75 shadow boost.
        luma = max(0.0, min(1.0, state.luma))
        toe = 0.02
        if luma <= toe:
            level = 0.0
        else:
            level = pow((luma - toe) / (1.0 - toe), config.brightness_gamma)
        brightness = config.brightness_min + int(round(span * level))
        brightness = max(config.brightness_min, min(config.brightness_max, brightness))

        if config.neutral_white and saturation <= config.neutral_threshold:
            # Near-neutral colours are unreliable in RGB colour mode: a 1–2%
            # blue tint becomes a visible blue/purple cast. Use the dedicated
            # white LEDs instead, choosing a warm/cool temperature from the tint.
            balance = (red - blue) / max(1.0, red + blue)
            if saturation <= 0.03:
                # Essentially grey/white: any residual tint is sensor noise.
                colortemp = 50
            else:
                colortemp = clamp_int(int(round(50 - balance * 50)), 5, 95, 50)
            preview = kelvin_to_rgb(kelvin_from_temp(colortemp))
            return ZoneTarget(
                rgb=preview,
                brightness=brightness,
                luma=state.luma,
                saturation=0.0,
                mode="white",
                colortemp=colortemp,
            )

        # Boost saturation with a soft curve: pale colours gain more than
        # already-saturated ones, so light yellows/creams stay recognisable.
        if saturation <= 0.03:
            boosted = 0.0
        else:
            boosted = min(1.0, pow(saturation, 0.85) * config.saturation)
        target_r, target_g, target_b = colorsys.hsv_to_rgb(hue, boosted, 1.0)
        return ZoneTarget(
            rgb=(
                int(round(target_r * 255)),
                int(round(target_g * 255)),
                int(round(target_b * 255)),
            ),
            brightness=brightness,
            luma=state.luma,
            saturation=boosted,
        )


class ScreenCapture:
    def __init__(self, monitor_index: int = 1) -> None:
        factory = _mss_factory()
        self._sct = factory()
        monitors = self._sct.monitors
        index = monitor_index if 1 <= monitor_index < len(monitors) else 1
        self._monitor = monitors[index]

    def grab(self) -> Image.Image:
        shot = self._sct.grab(self._monitor)
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")

    def close(self) -> None:
        try:
            self._sct.close()
        except Exception:
            pass


class ScreenSyncRunner:
    """Capture/analysis thread that streams per-light colours via the existing controller."""

    def __init__(self, controller: LightController) -> None:
        self.controller = controller
        self._config = ScreenSyncConfig()
        self._capture_factory = ScreenCapture
        self._devices: list[LightDevice] = []
        self._zone_map: dict[str, int] = {}
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._pending: dict[str, Future[LightResult]] = {}
        self._pending_turbo: dict[str, bool] = {}
        self._turbo_fallback: set[str] = set()
        self._dark_off: set[str] = set()
        self._failed_details: dict[str, tuple[str, str]] = {}
        self._last_colors: dict[str, tuple[int, int, int]] = {}
        self._last_targets: dict[str, tuple[tuple[int, int, int], int]] = {}
        self._last_frame: ScreenFrame | None = None
        self._frame_lock = threading.Lock()
        self._frame_count = 0
        self._analysis_frames = 0
        self._analysis_started = 0.0
        self._capture_error = ""
        self._started_at = 0.0

    # ------------------------------------------------------------------ public
    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and not self._stop.is_set())

    @property
    def last_frame(self) -> ScreenFrame | None:
        with self._frame_lock:
            return self._last_frame

    @property
    def failed_details(self) -> dict[str, tuple[str, str]]:
        return dict(self._failed_details)

    @property
    def last_targets(self) -> dict[str, tuple[tuple[int, int, int], int]]:
        return dict(self._last_targets)

    @property
    def power_off_ids(self) -> set[str]:
        return set(self._dark_off)

    @property
    def capture_error(self) -> str:
        return self._capture_error

    @property
    def frame_count(self) -> int:
        return self._frame_count

    @property
    def effective_fps(self) -> float:
        elapsed = time.monotonic() - self._analysis_started if self._analysis_started else 0.0
        if elapsed <= 0.001:
            return 0.0
        return self._analysis_frames / elapsed

    @property
    def target_fps(self) -> int:
        return self._config.fps

    @property
    def turbo_fallback_ids(self) -> set[str]:
        return set(self._turbo_fallback)

    def start(
        self,
        devices: list[LightDevice],
        config: ScreenSyncConfig,
        zone_map: dict[str, int] | None = None,
    ) -> None:
        self.stop()
        if not devices:
            return
        self._config = config.copy()
        self._devices = list(devices)
        self._zone_map = dict(zone_map or self._config.zone_map)
        self._pending = {}
        self._pending_turbo = {}
        self._turbo_fallback = set()
        self._dark_off = set()
        self._failed_details = {}
        self._last_colors = {}
        self._last_targets = {}
        self._last_frame = None
        self._capture_error = ""
        self._frame_count = 0
        self._analysis_frames = 0
        self._stop.clear()
        self._started_at = time.monotonic()
        self._analysis_started = self._started_at
        self._thread = threading.Thread(target=self._loop, name="screen-sync", daemon=True)
        self._thread.start()
        LOGGER.info(
            "Screen Sync avviato: %d luci, monitor %d, %d zone, %d fps%s",
            len(devices),
            config.monitor_index,
            config.zone_count,
            config.fps,
            " · turbo music" if config.turbo else "",
        )

    def stop(self) -> dict[str, tuple[int, int, int]]:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=0.5)
        self._thread = None
        colors = dict(self._last_colors)
        if colors:
            LOGGER.info("Screen Sync fermato (%d luci).", len(colors))
        return colors

    # ------------------------------------------------------------------- loop
    def _loop(self) -> None:
        try:
            capture = self._capture_factory(self._config.monitor_index)
        except Exception as exc:
            self._capture_error = f"Impossibile aprire il monitor: {exc}"
            LOGGER.exception("Screen Sync: capture init fallita")
            return

        analyzer = ScreenAnalyzer()
        last_time = time.monotonic()
        try:
            while not self._stop.is_set():
                frame_started = time.perf_counter()
                try:
                    image = capture.grab()
                except Exception as exc:
                    self._capture_error = f"Cattura fallita: {exc}"
                    LOGGER.warning("Screen Sync: cattura fallita (%s).", exc)
                    self._stop.wait(0.5)
                    continue
                now = time.monotonic()
                dt = max(0.01, min(1.0, now - last_time))
                last_time = now
                capture_ms = int((time.perf_counter() - frame_started) * 1000)
                frame = analyzer.update(
                    image,
                    self._config,
                    dt,
                    capture_ms=capture_ms,
                )
                self._analysis_frames += 1
                self._capture_error = ""
                with self._frame_lock:
                    self._last_frame = frame

                hold_black = (
                    frame.black
                    and self._config.hold_on_black
                    and not self._config.dark_off
                )
                if not hold_black:
                    for index, device in enumerate(self._devices):
                        pending = self._pending.get(device.id)
                        if pending is not None:
                            if not pending.done():
                                continue
                            self._pending.pop(device.id, None)
                            was_turbo = self._pending_turbo.pop(device.id, False)
                            try:
                                result = pending.result()
                            except Exception:
                                result = None
                            if result is not None and not result.ok:
                                if was_turbo and result.kind in (
                                    ERROR_PROTOCOL,
                                    ERROR_UNSUPPORTED,
                                ):
                                    self._turbo_fallback.add(device.id)
                                    LOGGER.warning(
                                        "Screen Sync: turbo non supportato su %s (%s), "
                                        "passo al frame normale.",
                                        device.name,
                                        result.error,
                                    )
                                    continue
                                if result.kind in (
                                    ERROR_OFFLINE,
                                    ERROR_AUTH,
                                    ERROR_PROTOCOL,
                                    ERROR_UNSUPPORTED,
                                ):
                                    self._failed_details[device.id] = (
                                        result.kind,
                                        result.error,
                                    )
                                    LOGGER.warning(
                                        "Screen Sync: %s rimosso (%s).",
                                        device.name,
                                        result.error,
                                    )
                                    continue
                        if device.id in self._failed_details:
                            continue
                        zone = self._zone_map.get(device.id)
                        zone_count = len(frame.zones)
                        if zone is None:
                            zone = index % zone_count if zone_count > 1 else -1
                        target = frame.global_target if zone < 0 else frame.zones[zone % zone_count]

                        threshold = self._config.dark_off_threshold
                        if self._config.dark_off:
                            limit = threshold + 2 if device.id in self._dark_off else threshold
                            is_dark = target.brightness <= limit or frame.black
                        else:
                            is_dark = False
                        if is_dark:
                            self._last_colors[device.id] = (0, 0, 0)
                            self._last_targets[device.id] = ((0, 0, 0), 0)
                            if device.id not in self._dark_off:
                                self._dark_off.add(device.id)
                                try:
                                    self._pending[device.id] = (
                                        self.controller.submit_colour_frame(
                                            device, (0, 0, 0), 0, power=False
                                        )
                                    )
                                    self._pending_turbo[device.id] = False
                                    LOGGER.info(
                                        "Screen Sync: %s spenta (schermo scuro).",
                                        device.name,
                                    )
                                except Exception:
                                    LOGGER.exception(
                                        "Screen Sync: impossibile spegnere la luce."
                                    )
                            continue
                        if device.id in self._dark_off:
                            self._dark_off.discard(device.id)

                        self._last_colors[device.id] = target.rgb
                        self._last_targets[device.id] = (target.rgb, target.brightness)
                        use_turbo = (
                            self._config.turbo
                            and target.mode == "colour"
                            and device.id not in self._turbo_fallback
                        )
                        try:
                            if use_turbo:
                                self._pending[device.id] = self.controller.submit_music_frame(
                                    device, target.rgb, target.brightness
                                )
                            else:
                                self._pending[device.id] = self.controller.submit_colour_frame(
                                    device,
                                    target.rgb,
                                    target.brightness,
                                    white=target.mode == "white",
                                    colortemp=target.colortemp,
                                )
                            self._pending_turbo[device.id] = use_turbo
                            self._frame_count += 1
                            if self._frame_count % 100 == 0:
                                LOGGER.info(
                                    "Screen Sync: %d frame · %s #%02x%02x%02x · %d%%%s%s",
                                    self._frame_count,
                                    device.name,
                                    *target.rgb,
                                    target.brightness,
                                    " · turbo" if use_turbo else "",
                                    " · white" if target.mode == "white" else "",
                                )
                        except Exception:
                            LOGGER.exception("Screen Sync: impossibile accodare il frame.")
                target_fps = max(1, self._config.fps)
                elapsed = time.perf_counter() - frame_started
                self._stop.wait(max(0.001, (1.0 / target_fps) - elapsed))
        finally:
            capture.close()
