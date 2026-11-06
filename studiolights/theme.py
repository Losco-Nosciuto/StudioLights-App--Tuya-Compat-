"""Dark studio palette and small style helpers."""

from __future__ import annotations

import customtkinter as ctk

COLORS = {
    "bg": "#070A0F",
    "panel": "#0D131B",
    "panel_alt": "#111923",
    "card": "#141D29",
    "card_hover": "#1A2533",
    "border": "#1F2C3B",
    "border_light": "#2B3B4F",
    "text": "#E8F0F8",
    "muted": "#8B9DB2",
    "dim": "#5B6B7F",
    "accent": "#4FD1C5",
    "accent_hover": "#6EE7DB",
    "accent_dark": "#123A37",
    "accent_text": "#06120F",
    "violet": "#B08CFF",
    "violet_dark": "#241B3C",
    "success": "#3DDC97",
    "success_dark": "#0F3326",
    "warning": "#FFB454",
    "warning_dark": "#3A2A12",
    "danger": "#FF6178",
    "danger_dark": "#3A1620",
    "off": "#39485A",
}

FONT = "Roboto"
MONO = "Consolas"


def setup_appearance() -> None:
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")


def font(size: int = 13, weight: str = "normal") -> tuple[str, int, str]:
    return (FONT, size, weight)


def mono(size: int = 12) -> tuple[str, int, str]:
    return (MONO, size, "normal")
