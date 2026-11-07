"""Saved window geometry helpers."""

from __future__ import annotations

import re
import tkinter as tk

_GEOMETRY_RE = re.compile(r"^(\d+)x(\d+)([+-]\d+)([+-]\d+)$")


def window_geometry(window: tk.Misc) -> str:
    try:
        return window.geometry()
    except tk.TclError:
        return ""


def restore_geometry(
    window: tk.Misc,
    geometry: object,
    *,
    min_width: int = 200,
    min_height: int = 120,
) -> bool:
    """Apply a saved 'WxH+X+Y' geometry, clamped to the visible desktop."""
    if not isinstance(geometry, str):
        return False
    match = _GEOMETRY_RE.match(geometry.strip())
    if not match:
        return False
    width, height, x, y = (int(part) for part in match.groups())
    try:
        left = window.winfo_vrootx()
        top = window.winfo_vrooty()
        screen_width = window.winfo_vrootwidth() or window.winfo_screenwidth()
        screen_height = window.winfo_vrootheight() or window.winfo_screenheight()
        width = max(min_width, min(width, screen_width))
        height = max(min_height, min(height, screen_height))
        x = max(left, min(x, left + screen_width - 80))
        y = max(top, min(y, top + screen_height - 60))
        window.geometry(f"{width}x{height}{x:+d}{y:+d}")
    except tk.TclError:
        return False
    return True
