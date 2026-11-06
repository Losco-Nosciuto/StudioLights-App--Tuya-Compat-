"""Shared helpers: logging, safe JSON persistence, colour maths."""

from __future__ import annotations

import colorsys
import json
import logging
import os
import shutil
import tempfile
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def setup_logging(log_dir: Path, level: int = logging.INFO) -> logging.Logger:
    """Configure console + rotating file logging. Safe to call twice."""
    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    if getattr(root, "_studiolights_configured", False):
        return logging.getLogger("studiolights")

    root.setLevel(level)
    formatter = logging.Formatter(LOG_FORMAT)

    file_handler = RotatingFileHandler(
        log_dir / "studiolights.log",
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.setLevel(logging.WARNING)
    root.addHandler(console)

    # tinytuya is extremely chatty at DEBUG; keep only useful warnings.
    logging.getLogger("tinytuya").setLevel(logging.WARNING)
    root._studiolights_configured = True  # type: ignore[attr-defined]
    return logging.getLogger("studiolights")


def read_json(path: Path) -> Any:
    """Read JSON tolerating an UTF-8 BOM (Windows editors love it)."""
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def backup_corrupt_file(path: Path) -> Path | None:
    """Keep a copy of an unreadable file instead of silently destroying it."""
    if not path.exists():
        return None
    target = path.with_name(f"{path.stem}.corrupt-{time.strftime('%Y%m%d-%H%M%S')}{path.suffix}")
    try:
        shutil.copy2(path, target)
        return target
    except OSError:
        return None


def atomic_write_json(path: Path, payload: Any, *, keep_backup: bool = True) -> None:
    """Write JSON atomically and keep a .bak of the previous good version."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if keep_backup and path.exists():
        try:
            shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
        except OSError:
            pass

    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def clamp_int(value: Any, minimum: int, maximum: int, default: int) -> int:
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def clamp_float(value: Any, minimum: float, maximum: float, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def hsv_to_hex(hue: float, saturation: float, value: float) -> str:
    """HSV (0-1 each) -> '#rrggbb'."""
    r, g, b = colorsys.hsv_to_rgb(hue % 1.0, saturation, value)
    return f"#{round(r * 255):02x}{round(g * 255):02x}{round(b * 255):02x}"


def rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    r, g, b = rgb
    return f"#{r:02x}{g:02x}{b:02x}"


def hex_to_rgb(value: str) -> tuple[int, int, int] | None:
    text = value.strip().lstrip("#")
    if len(text) != 6:
        return None
    try:
        return tuple(int(text[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return None


def normalize_hex_color(value: Any, fallback: str = "#ffffff") -> str:
    """Return a lower-case #rrggbb string; invalid values fall back safely."""
    rgb = hex_to_rgb(str(value or ""))
    if rgb is None:
        rgb = hex_to_rgb(fallback) or (255, 255, 255)
    return rgb_to_hex(rgb)


def interpolate_colour(
    first: tuple[int, int, int],
    second: tuple[int, int, int],
    amount: float,
) -> tuple[int, int, int]:
    """Blend two RGB colours.

    Saturated colours are interpolated through HSV (shortest hue path), which keeps
    studio palettes vivid. Near-grey/white pairs fall back to linear RGB so the
    transition does not take a random hue.
    """
    t = max(0.0, min(1.0, float(amount)))
    first_h, first_s, first_v = colorsys.rgb_to_hsv(*(channel / 255.0 for channel in first))
    second_h, second_s, second_v = colorsys.rgb_to_hsv(*(channel / 255.0 for channel in second))

    if first_s > 0.05 and second_s > 0.05 and first_v > 0.02 and second_v > 0.02:
        delta_hue = (second_h - first_h + 0.5) % 1.0 - 0.5
        hue = (first_h + delta_hue * t) % 1.0
        saturation = first_s + (second_s - first_s) * t
        value = first_v + (second_v - first_v) * t
        red, green, blue = colorsys.hsv_to_rgb(hue, saturation, value)
    else:
        red = (first[0] + (second[0] - first[0]) * t) / 255.0
        green = (first[1] + (second[1] - first[1]) * t) / 255.0
        blue = (first[2] + (second[2] - first[2]) * t) / 255.0
    return (
        round(max(0.0, min(1.0, red)) * 255),
        round(max(0.0, min(1.0, green)) * 255),
        round(max(0.0, min(1.0, blue)) * 255),
    )


def kelvin_from_temp(percent: int) -> int:
    """Map Tuya temp 0..100 (warm..cool) to an approximate Kelvin value."""
    return int(round(2700 + (max(0, min(100, percent)) / 100.0) * 3800))


def kelvin_to_rgb(kelvin: int) -> tuple[int, int, int]:
    """Approximate black-body colour (Tanner Helland algorithm)."""
    temperature = max(1000, min(40000, kelvin)) / 100.0
    if temperature <= 66:
        red = 255.0
        green = 99.4708025861 * _safe_log(temperature) - 161.1195681661
        blue = 0.0 if temperature <= 19 else 138.5177312231 * _safe_log(temperature - 10) - 305.0447927307
    else:
        red = 329.698727446 * ((temperature - 60) ** -0.1332047592)
        green = 288.1221695283 * ((temperature - 60) ** -0.0755148492)
        blue = 255.0
    return tuple(round(max(0.0, min(255.0, channel))) for channel in (red, green, blue))  # type: ignore[return-value]


def _safe_log(value: float) -> float:
    import math

    return math.log(value) if value > 0 else 0.0


def temp_preview_hex(percent: int, brightness: int = 100) -> str:
    """Colour for the white-mode preview swatch (slightly dimmed by brightness)."""
    rgb = kelvin_to_rgb(kelvin_from_temp(percent))
    factor = 0.35 + 0.65 * (max(1, min(100, brightness)) / 100.0)
    return rgb_to_hex(tuple(round(channel * factor) for channel in rgb))  # type: ignore[arg-type]


def format_ms(milliseconds: int | float) -> str:
    value = int(round(milliseconds))
    return f"{value} ms" if value < 1000 else f"{value / 1000:.1f} s"
