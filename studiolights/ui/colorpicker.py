"""A compact HSV colour picker (saturation/value square + hue bar)."""

from __future__ import annotations

import colorsys
import logging
import tkinter as tk
from collections.abc import Callable

import customtkinter as ctk
from PIL import Image, ImageTk

from ..theme import COLORS, font, mono
from ..util import hex_to_rgb, rgb_to_hex

LOGGER = logging.getLogger("studiolights.ui.colorpicker")


class ColorPicker(ctk.CTkFrame):
    """Visual picker rendered with Pillow, completely dependency-free at runtime
    beyond Pillow itself. Emits the selected RGB tuple on every change."""

    SQUARE_W = 232
    SQUARE_H = 164
    HUE_W = 18
    RASTER_W = 116
    RASTER_H = 82

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        *,
        command: Callable[[tuple[int, int, int]], None] | None = None,
        initial_rgb: tuple[int, int, int] = (0, 220, 255),
    ) -> None:
        super().__init__(master, fg_color="transparent")
        self._command = command
        self._hue = 0.5
        self._sat = 0.8
        self._val = 1.0
        self._square_photo: ImageTk.PhotoImage | None = None
        self._hue_photo: ImageTk.PhotoImage | None = None
        self._square_bg: int | None = None
        self._marker_outer: int | None = None
        self._marker_inner: int | None = None
        self._hue_marker_dark: int | None = None
        self._hue_marker_light: int | None = None
        self._emit_enabled = True

        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=0)

        self._square = tk.Canvas(
            self,
            width=self.SQUARE_W,
            height=self.SQUARE_H,
            highlightthickness=0,
            bd=0,
            bg=COLORS["panel_alt"],
            cursor="crosshair",
        )
        self._square.grid(row=0, column=0, sticky="nw")

        self._hue_bar = tk.Canvas(
            self,
            width=self.HUE_W,
            height=self.SQUARE_H,
            highlightthickness=0,
            bd=0,
            bg=COLORS["panel_alt"],
            cursor="hand2",
        )
        self._hue_bar.grid(row=0, column=1, sticky="nw", padx=(8, 0))

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        footer.grid_columnconfigure(1, weight=1)

        self._swatch = ctk.CTkFrame(
            footer,
            width=22,
            height=22,
            corner_radius=6,
            fg_color="#00dcff",
            border_width=1,
            border_color=COLORS["border_light"],
        )
        self._swatch.grid(row=0, column=0, padx=(0, 8))
        self._swatch.grid_propagate(False)

        self._hex_var = tk.StringVar(value="#00dcff")
        self._hex_entry = ctk.CTkEntry(
            footer,
            textvariable=self._hex_var,
            width=100,
            height=24,
            fg_color=COLORS["panel_alt"],
            border_color=COLORS["border"],
            font=mono(12),
            justify="center",
        )
        self._hex_entry.grid(row=0, column=1, sticky="w")
        self._hex_entry.bind("<Return>", self._on_hex_submit)
        self._hex_entry.bind("<FocusOut>", self._on_hex_submit)

        self._rgb_label = ctk.CTkLabel(
            footer,
            text="0, 220, 255",
            font=font(10),
            text_color=COLORS["muted"],
        )
        self._rgb_label.grid(row=0, column=2, sticky="e", padx=(8, 0))

        self._square.bind("<Button-1>", self._on_square)
        self._square.bind("<B1-Motion>", self._on_square)
        self._hue_bar.bind("<Button-1>", self._on_hue)
        self._hue_bar.bind("<B1-Motion>", self._on_hue)

        self._render_hue_bar()
        self._render_square(emit=False)
        self.set_rgb(initial_rgb, emit=False)

    # ------------------------------------------------------------------ public
    def get_rgb(self) -> tuple[int, int, int]:
        red, green, blue = colorsys.hsv_to_rgb(self._hue, self._sat, self._val)
        return (round(red * 255), round(green * 255), round(blue * 255))

    def get_hex(self) -> str:
        return rgb_to_hex(self.get_rgb())

    def set_rgb(self, rgb: tuple[int, int, int], *, emit: bool = False) -> None:
        red, green, blue = (max(0, min(255, int(channel))) for channel in rgb)
        hue, saturation, value = colorsys.rgb_to_hsv(red / 255, green / 255, blue / 255)
        if saturation > 0.001 and value > 0.001:
            self._hue = hue
        self._sat = saturation
        self._val = value
        self._render_square(emit=False)
        self._update_markers()
        self._update_texts()
        if emit:
            self._emit()

    # ----------------------------------------------------------------- events
    def _on_square(self, event: tk.Event) -> None:
        x = max(0, min(self.SQUARE_W - 1, int(event.x)))
        y = max(0, min(self.SQUARE_H - 1, int(event.y)))
        self._sat = x / (self.SQUARE_W - 1)
        self._val = 1.0 - y / (self.SQUARE_H - 1)
        self._update_markers()
        self._update_texts()
        self._emit()

    def _on_hue(self, event: tk.Event) -> None:
        y = max(0, min(self.SQUARE_H - 1, int(event.y)))
        self._hue = y / (self.SQUARE_H - 1)
        self._render_square(emit=False)
        self._update_markers()
        self._update_texts()
        self._emit()

    def _on_hex_submit(self, _event: tk.Event | None = None) -> None:
        if not self._emit_enabled:
            return
        rgb = hex_to_rgb(self._hex_var.get())
        if rgb is None:
            self._hex_entry.configure(border_color=COLORS["danger"])
            self.after(1200, lambda: self._hex_entry.configure(border_color=COLORS["border"]))
            return
        self._hex_entry.configure(border_color=COLORS["border"])
        self.set_rgb(rgb, emit=True)

    def _emit(self) -> None:
        if self._command:
            self._command(self.get_rgb())

    # ---------------------------------------------------------------- rendering
    def _render_square(self, *, emit: bool) -> None:
        image = Image.new("RGB", (self.RASTER_W, self.RASTER_H))
        pixels: list[tuple[int, int, int]] = []
        for row in range(self.RASTER_H):
            value = 1.0 - row / (self.RASTER_H - 1)
            for column in range(self.RASTER_W):
                saturation = column / (self.RASTER_W - 1)
                red, green, blue = colorsys.hsv_to_rgb(self._hue, saturation, value)
                pixels.append((round(red * 255), round(green * 255), round(blue * 255)))
        image.putdata(pixels)
        image = image.resize((self.SQUARE_W, self.SQUARE_H), Image.Resampling.BILINEAR)
        self._square_photo = ImageTk.PhotoImage(image)
        if self._square_bg is None:
            self._square_bg = self._square.create_image(
                0, 0, anchor="nw", image=self._square_photo
            )
        else:
            self._square.itemconfigure(self._square_bg, image=self._square_photo)
        if self._marker_outer is not None:
            self._square.tag_raise(self._marker_outer)
        if self._marker_inner is not None:
            self._square.tag_raise(self._marker_inner)
        self._update_markers()
        if emit:
            self._emit()

    def _render_hue_bar(self) -> None:
        image = Image.new("RGB", (self.HUE_W, self.SQUARE_H))
        pixels: list[tuple[int, int, int]] = []
        for row in range(self.SQUARE_H):
            hue = row / (self.SQUARE_H - 1)
            red, green, blue = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
            color = (round(red * 255), round(green * 255), round(blue * 255))
            pixels.extend([color] * self.HUE_W)
        image.putdata(pixels)
        self._hue_photo = ImageTk.PhotoImage(image)
        self._hue_bar.create_image(0, 0, anchor="nw", image=self._hue_photo)

    def _update_markers(self) -> None:
        x = self._sat * (self.SQUARE_W - 1)
        y = (1.0 - self._val) * (self.SQUARE_H - 1)
        radius = 7
        if self._marker_outer is None:
            self._marker_outer = self._square.create_oval(
                x - radius - 1,
                y - radius - 1,
                x + radius + 1,
                y + radius + 1,
                outline="#000000",
                width=3,
            )
            self._marker_inner = self._square.create_oval(
                x - radius,
                y - radius,
                x + radius,
                y + radius,
                outline="#ffffff",
                width=2,
            )
        else:
            self._square.coords(
                self._marker_outer,
                x - radius - 1,
                y - radius - 1,
                x + radius + 1,
                y + radius + 1,
            )
            self._square.coords(
                self._marker_inner,
                x - radius,
                y - radius,
                x + radius,
                y + radius,
            )

        hue_y = self._hue * (self.SQUARE_H - 1)
        if self._hue_marker_dark is None:
            self._hue_marker_dark = self._hue_bar.create_line(
                0, hue_y, self.HUE_W, hue_y, fill="#000000", width=4
            )
            self._hue_marker_light = self._hue_bar.create_line(
                0, hue_y, self.HUE_W, hue_y, fill="#ffffff", width=2
            )
        else:
            self._hue_bar.coords(self._hue_marker_dark, 0, hue_y, self.HUE_W, hue_y)
            self._hue_bar.coords(self._hue_marker_light, 0, hue_y, self.HUE_W, hue_y)

    def _update_texts(self) -> None:
        red, green, blue = self.get_rgb()
        hex_value = rgb_to_hex((red, green, blue))
        self._swatch.configure(fg_color=hex_value)
        self._rgb_label.configure(text=f"{red}, {green}, {blue}")
        self._emit_enabled = False
        self._hex_var.set(hex_value)
        self._emit_enabled = True
