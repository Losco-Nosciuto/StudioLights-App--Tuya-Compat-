"""Non-modal Screen Sync configuration window."""

from __future__ import annotations

import logging
import tkinter as tk
from tkinter import simpledialog
from typing import Any

import customtkinter as ctk
from PIL import Image, ImageTk

try:
    import mss as _mss
except Exception:
    _mss = None

from ..screen_sync import (
    SCREEN_PRESETS,
    MonitorInfo,
    ScreenAnalyzer,
    ScreenSyncConfig,
    SensorZone,
    default_sensor_zones,
    list_monitors,
)
from ..theme import COLORS, font, mono
from .layout import restore_geometry

LOGGER = logging.getLogger("studiolights.ui.screen_sync")


class ScreenSyncWindow(ctk.CTkToplevel):
    def __init__(
        self,
        master: ctk.CTkBaseClass,
        app: Any,
        *,
        geometry: str | None = None,
    ) -> None:
        super().__init__(master, fg_color=COLORS["bg"])
        self.app = app
        self._restore_geometry = geometry
        self.title("Screen Sync — Studio Lights")
        self.geometry("900x820")
        self.minsize(780, 640)
        self.transient(master)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self._monitors: list[MonitorInfo] = list_monitors()
        self._monitor_by_label: dict[str, MonitorInfo] = {}
        self._preview_boxes: list[ctk.CTkFrame] = []
        self._preview_labels: list[ctk.CTkLabel] = []
        self._zone_assignment_buttons: list[ctk.CTkButton] = []
        self._zone_menu_vars: list[tk.BooleanVar] = []
        self._preset_store = getattr(app, "screen_preset_store", None)
        self._presets: dict[str, dict[str, Any]] = (
            self._preset_store.load() if self._preset_store is not None else {}
        )
        self._preset_loading = False
        self._preview_job: str | None = None
        self._save_job: str | None = None
        self._running = False
        self._config = app.screen_config.copy()
        self._zones: list[SensorZone] = [zone.copy() for zone in self._config.sensor_zones]
        self._selected_zone: int | None = 0 if self._zones else None
        self._zone_area: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
        self._drag: dict[str, Any] | None = None
        self._sensor_thumb: Image.Image | None = None
        self._thumb_photo: ImageTk.PhotoImage | None = None
        self._thumb_job: str | None = None
        self._editor_frame: Any = None
        self._build()
        self._apply_config(self._config)
        self._refresh_monitors()
        self._update_preview()
        self._thumb_job = self.after(500, self._capture_thumb_main)
        self.after(70, self._present)

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=24, pady=(18, 6))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header,
            text="Screen Sync",
            font=font(22, "bold"),
            text_color=COLORS["text"],
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            header,
            text="Le luci seguono monitor, zone e luminosità del gioco.",
            font=font(10),
            text_color=COLORS["muted"],
            anchor="w",
        ).grid(row=1, column=0, sticky="w", pady=(1, 0))
        self.preset_menu = ctk.CTkOptionMenu(
            header,
            values=["Default"],
            width=156,
            height=30,
            corner_radius=8,
            fg_color=COLORS["panel_alt"],
            button_color=COLORS["border"],
            button_hover_color=COLORS["border_light"],
            dropdown_fg_color=COLORS["panel_alt"],
            dropdown_hover_color=COLORS["card_hover"],
            text_color=COLORS["text"],
            font=font(9),
            anchor="w",
            command=self._on_preset_selected,
        )
        self.preset_menu.grid(row=0, column=1, rowspan=2, sticky="e", padx=(0, 6))
        ctk.CTkButton(
            header,
            text="+ Preset",
            width=78,
            height=30,
            corner_radius=8,
            fg_color="transparent",
            border_width=1,
            border_color=COLORS["border_light"],
            hover_color=COLORS["card_hover"],
            text_color=COLORS["muted"],
            font=font(9, "bold"),
            command=self._save_preset_dialog,
        ).grid(row=0, column=2, rowspan=2, sticky="e", padx=(0, 8))
        ctk.CTkButton(
            header,
            text="Salva",
            width=82,
            height=30,
            corner_radius=8,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            text_color=COLORS["accent_text"],
            font=font(10, "bold"),
            command=self._save_now,
        ).grid(row=0, column=3, rowspan=2, sticky="e", padx=(0, 8))
        ctk.CTkButton(
            header,
            text="Chiudi",
            width=76,
            height=30,
            corner_radius=8,
            fg_color="transparent",
            border_width=1,
            border_color=COLORS["border_light"],
            hover_color=COLORS["card_hover"],
            text_color=COLORS["muted"],
            font=font(10, "bold"),
            command=self.close,
        ).grid(row=0, column=4, rowspan=2, sticky="e")

        self.scroll = ctk.CTkScrollableFrame(
            self,
            fg_color="transparent",
            scrollbar_fg_color="transparent",
            scrollbar_button_color=COLORS["border"],
            scrollbar_button_hover_color=COLORS["border_light"],
        )
        self.scroll.grid(row=1, column=0, sticky="nsew", padx=18, pady=4)
        self.scroll.grid_columnconfigure(0, weight=1)

        self._build_monitor_card()
        self._build_zone_map_card()
        self._build_preview_card()
        self._build_settings_card()
        self._fix_mouse_wheel()

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=2, column=0, sticky="ew", padx=24, pady=(8, 18))
        footer.grid_columnconfigure(0, weight=1)
        self.footer_status = ctk.CTkLabel(
            footer,
            text="Configura e premi Avvia.",
            font=font(9),
            text_color=COLORS["muted"],
            anchor="w",
        )
        self.footer_status.grid(row=0, column=0, sticky="w")
        self.select_button = ctk.CTkButton(
            footer,
            text="Seleziona tutte le luci",
            width=150,
            height=34,
            corner_radius=8,
            fg_color="transparent",
            border_width=1,
            border_color=COLORS["border_light"],
            hover_color=COLORS["card_hover"],
            text_color=COLORS["muted"],
            font=font(9, "bold"),
            command=self._select_all_lights,
        )
        self.select_button.grid(row=0, column=1, sticky="e", padx=(8, 0))
        self.start_button = ctk.CTkButton(
            footer,
            text="AVVIA SYNC",
            width=150,
            height=40,
            corner_radius=9,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            text_color=COLORS["accent_text"],
            font=font(11, "bold"),
            command=self._toggle,
        )
        self.start_button.grid(row=0, column=2, sticky="e", padx=(8, 0))

    def _card(self) -> ctk.CTkFrame:
        card = ctk.CTkFrame(
            self.scroll,
            fg_color=COLORS["panel"],
            corner_radius=12,
            border_width=1,
            border_color=COLORS["border"],
        )
        card.grid(sticky="ew", padx=4, pady=5)
        card.grid_columnconfigure(0, weight=1)
        return card

    def _build_monitor_card(self) -> None:
        card = self._card()
        ctk.CTkLabel(
            card,
            text="MONITOR DA CATTURARE",
            font=font(9, "bold"),
            text_color=COLORS["dim"],
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=14, pady=(10, 0))
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.grid(row=1, column=0, sticky="ew", padx=14, pady=(4, 12))
        row.grid_columnconfigure(0, weight=1)
        self.monitor_menu = ctk.CTkOptionMenu(
            row,
            values=["Schermo principale"],
            height=32,
            corner_radius=8,
            fg_color=COLORS["panel_alt"],
            button_color=COLORS["border"],
            button_hover_color=COLORS["border_light"],
            dropdown_fg_color=COLORS["panel_alt"],
            dropdown_hover_color=COLORS["card_hover"],
            text_color=COLORS["text"],
            font=font(10),
            anchor="w",
            command=lambda _value: self._schedule_save(),
        )
        self.monitor_menu.grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(
            row,
            text="Aggiorna",
            width=86,
            height=32,
            corner_radius=8,
            fg_color=COLORS["panel_alt"],
            border_width=1,
            border_color=COLORS["border"],
            hover_color=COLORS["card_hover"],
            text_color=COLORS["muted"],
            font=font(9, "bold"),
            command=self._refresh_monitors,
        ).grid(row=0, column=1, padx=(8, 0))
        ctk.CTkLabel(
            card,
            text=(
                "Per i giochi usa il monitor giusto e, se il frame è nero, "
                "passa a borderless windowed e disattiva HDR."
            ),
            font=font(8),
            text_color=COLORS["dim"],
            anchor="w",
            justify="left",
            wraplength=700,
        ).grid(row=2, column=0, sticky="w", padx=14, pady=(0, 10))

    def _build_zone_map_card(self) -> None:
        card = self._card()
        head = ctk.CTkFrame(card, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=14, pady=(10, 0))
        head.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            head,
            text="SENSORI SCHERMO · ANTEPRIMA 16:9",
            font=font(9, "bold"),
            text_color=COLORS["dim"],
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        self.zone_caption = ctk.CTkLabel(
            head,
            text="",
            font=font(8),
            text_color=COLORS["muted"],
            anchor="e",
        )
        self.zone_caption.grid(row=0, column=1, sticky="e")

        body = ctk.CTkFrame(card, fg_color="transparent")
        body.grid(row=1, column=0, sticky="ew", padx=14, pady=(5, 2))
        body.grid_columnconfigure(0, weight=1)

        self.zone_canvas = tk.Canvas(
            body,
            height=240,
            bg=COLORS["panel_alt"],
            highlightthickness=0,
            bd=0,
            cursor="crosshair",
        )
        self.zone_canvas.grid(row=0, column=0, sticky="ew")
        self.zone_canvas.bind("<Configure>", self._on_zone_canvas_configure)
        self.zone_canvas.bind("<ButtonPress-1>", self._on_zone_press)
        self.zone_canvas.bind("<B1-Motion>", self._on_zone_drag)
        self.zone_canvas.bind("<ButtonRelease-1>", self._on_zone_release)
        self.zone_canvas.bind("<Double-Button-1>", self._on_zone_double_click)
        self.zone_canvas.bind("<ButtonPress-3>", self._on_zone_right_click)
        self.zone_canvas.bind("<Motion>", self._on_zone_hover)

        side = ctk.CTkFrame(body, fg_color="transparent", width=158)
        side.grid(row=0, column=1, sticky="n", padx=(10, 0))
        side.grid_propagate(False)
        ctk.CTkLabel(
            side,
            text="MODALITÀ",
            font=font(8, "bold"),
            text_color=COLORS["dim"],
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        self.mode_menu = ctk.CTkOptionMenu(
            side,
            values=["Sensori liberi", "Fasce automatiche"],
            width=150,
            height=27,
            fg_color=COLORS["panel_alt"],
            button_color=COLORS["border"],
            button_hover_color=COLORS["border_light"],
            dropdown_fg_color=COLORS["panel_alt"],
            dropdown_hover_color=COLORS["card_hover"],
            text_color=COLORS["text"],
            font=font(9),
            command=lambda _value: self._on_sampling_mode_changed(),
        )
        self.mode_menu.grid(row=1, column=0, sticky="ew", pady=(3, 6))
        ctk.CTkButton(
            side,
            text="+ Sensore",
            width=150,
            height=27,
            corner_radius=6,
            fg_color=COLORS["panel_alt"],
            border_width=1,
            border_color=COLORS["border"],
            hover_color=COLORS["card_hover"],
            text_color=COLORS["muted"],
            font=font(8, "bold"),
            command=self._add_sensor_zone,
        ).grid(row=2, column=0, sticky="ew", pady=(0, 5))
        ctk.CTkButton(
            side,
            text="Rimuovi",
            width=150,
            height=27,
            corner_radius=6,
            fg_color=COLORS["panel_alt"],
            border_width=1,
            border_color=COLORS["border"],
            hover_color=COLORS["card_hover"],
            text_color=COLORS["muted"],
            font=font(8, "bold"),
            command=self._remove_sensor_zone,
        ).grid(row=3, column=0, sticky="ew", pady=(0, 5))
        ctk.CTkButton(
            side,
            text="Rigenera fasce",
            width=150,
            height=27,
            corner_radius=6,
            fg_color="transparent",
            border_width=1,
            border_color=COLORS["border"],
            hover_color=COLORS["card_hover"],
            text_color=COLORS["dim"],
            font=font(8),
            command=self._regenerate_bands,
        ).grid(row=4, column=0, sticky="ew")

        ctk.CTkLabel(
            card,
            text=(
                "Trascina un sensore per spostarlo, quadratino in basso a destra "
                "per ridimensionarlo. Doppio clic sul vuoto aggiunge, clic destro "
                "rimuove. La cattura resta una sola."
            ),
            font=font(8),
            text_color=COLORS["dim"],
            anchor="w",
            justify="left",
            wraplength=760,
        ).grid(row=2, column=0, sticky="w", padx=14, pady=(0, 9))

    # --------------------------------------------------------- zone geometry
    def _sampling_mode(self) -> str:
        if not hasattr(self, "mode_menu"):
            return "bands"
        return "zones" if self.mode_menu.get() == "Sensori liberi" else "bands"

    def _zone_count(self) -> int:
        if self._sampling_mode() == "zones":
            return len(self._zones)
        return int(self.zones_menu.get()) if hasattr(self, "zones_menu") else 3

    def _on_zone_canvas_configure(self, _event: tk.Event) -> None:
        self._rebuild_zone_map()

    def _zone_pixel_rect(self, zone: SensorZone) -> tuple[float, float, float, float]:
        left, top, right, bottom = self._zone_area
        width = right - left
        height = bottom - top
        return (
            left + zone.x * width,
            top + zone.y * height,
            left + (zone.x + zone.w) * width,
            top + (zone.y + zone.h) * height,
        )

    def _zone_at(self, x: float, y: float) -> int | None:
        for index in range(len(self._zones) - 1, -1, -1):
            x0, y0, x1, y1 = self._zone_pixel_rect(self._zones[index])
            if x0 <= x <= x1 and y0 <= y <= y1:
                return index
        return None

    def _near_handle(self, index: int, x: float, y: float) -> bool:
        _x0, _y0, x1, y1 = self._zone_pixel_rect(self._zones[index])
        return abs(x - x1) <= 14 and abs(y - y1) <= 14

    def _rebuild_zone_map(self) -> None:
        if not hasattr(self, "zone_canvas"):
            return
        canvas = self.zone_canvas
        canvas.delete("all")
        width = max(320, canvas.winfo_width() or 760)
        height = max(140, int(canvas.cget("height")))
        pad = 8
        avail_w = max(1, width - pad * 2)
        avail_h = max(1, height - pad * 2)
        content_w = min(avail_w, avail_h * 16 / 9)
        content_h = content_w * 9 / 16
        left = (width - content_w) / 2
        top = (height - content_h) / 2
        right = left + content_w
        bottom = top + content_h
        self._zone_area = (left, top, right, bottom)
        if self._sensor_thumb is not None:
            try:
                thumb = self._sensor_thumb.resize(
                    (max(1, int(right - left)), max(1, int(bottom - top))),
                    Image.Resampling.BILINEAR,
                )
                self._thumb_photo = ImageTk.PhotoImage(thumb)
                canvas.create_image(left, top, image=self._thumb_photo, anchor="nw")
            except Exception:
                pass
        canvas.create_rectangle(
            left,
            top,
            right,
            bottom,
            fill="",
            outline=COLORS["border_light"],
            width=1,
        )
        for step in (1, 2):
            x = left + (right - left) * step / 3
            y = top + (bottom - top) * step / 3
            canvas.create_line(x, top, x, bottom, fill=COLORS["border"], dash=(2, 5))
            canvas.create_line(left, y, right, y, fill=COLORS["border"], dash=(2, 5))
        canvas.create_text(
            left + 6,
            top + 5,
            text=f"16:9 · {self.monitor_menu.get() if hasattr(self, 'monitor_menu') else 'Monitor'}",
            anchor="nw",
            fill=COLORS["dim"],
            font=font(8),
        )

        mode = self._sampling_mode()
        if mode == "bands":
            bands = int(self.zones_menu.get()) if hasattr(self, "zones_menu") else 3
            for index in range(bands):
                x0 = left + (right - left) * index / bands
                x1 = left + (right - left) * (index + 1) / bands
                canvas.create_rectangle(
                    x0 + 2,
                    top + 20,
                    x1 - 2,
                    bottom - 2,
                    fill=COLORS["panel_alt"],
                    stipple="gray50",
                    outline=COLORS["border_light"],
                )
                canvas.create_text(
                    x0 + 8,
                    top + 26,
                    text=f"Z{index + 1}",
                    anchor="nw",
                    fill=COLORS["accent"],
                    font=font(9, "bold"),
                )
            canvas.create_text(
                left + 6,
                bottom - 6,
                text="Fasce automatiche · non modificabili",
                anchor="sw",
                fill=COLORS["dim"],
                font=font(8),
            )
            self.zone_caption.configure(text=f"{bands} fasce · modalità automatica")
            return

        if not self._zones:
            self.zone_caption.configure(text="nessun sensore")
            return
        for index, zone in enumerate(self._zones):
            x0, y0, x1, y1 = self._zone_pixel_rect(zone)
            selected = index == self._selected_zone
            canvas.create_rectangle(
                x0,
                y0,
                x1,
                y1,
                fill=COLORS["accent_dark"] if selected else COLORS["panel_alt"],
                stipple="gray50",
                outline=COLORS["accent"] if selected else COLORS["border_light"],
                width=2 if selected else 1,
            )
            canvas.create_text(
                x0 + 5,
                y0 + 4,
                text=f"Z{index + 1}",
                anchor="nw",
                fill=COLORS["accent"] if selected else COLORS["muted"],
                font=font(9, "bold"),
            )
            canvas.create_text(
                x0 + 5,
                y0 + 20,
                text=f"{round(zone.x * 100)}%,{round(zone.y * 100)}% · "
                f"{round(zone.w * 100)}×{round(zone.h * 100)}%",
                anchor="nw",
                fill=COLORS["dim"],
                font=font(7),
            )
            names = [
                device.name
                for device in self.app.devices
                if self._config.zone_map.get(device.id) == index
            ]
            canvas.create_text(
                x0 + 5,
                y1 - 5,
                text=", ".join(names)[:34] if names else "—",
                anchor="sw",
                fill=COLORS["text"] if names else COLORS["dim"],
                font=font(8, "bold") if names else font(8),
            )
            if selected:
                canvas.create_rectangle(
                    x1 - 11,
                    y1 - 11,
                    x1,
                    y1,
                    fill=COLORS["accent"],
                    outline=COLORS["accent"],
                )
        self.zone_caption.configure(
            text=(
                f"{len(self._zones)} sensori · "
                f"Z{self._selected_zone + 1} selezionata"
                if self._selected_zone is not None
                else f"{len(self._zones)} sensori · nessuna selezionata"
            )
        )

    # -------------------------------------------------------- zone interaction
    def _on_zone_press(self, event: tk.Event) -> None:
        if self._sampling_mode() != "zones":
            return
        index = self._zone_at(event.x, event.y)
        self._selected_zone = index
        if index is not None:
            mode = "resize" if self._near_handle(index, event.x, event.y) else "move"
            self._drag = {
                "mode": mode,
                "index": index,
                "x": event.x,
                "y": event.y,
                "zone": self._zones[index].copy(),
            }
        self._rebuild_zone_map()

    def _on_zone_drag(self, event: tk.Event) -> None:
        if self._drag is None:
            return
        left, top, right, bottom = self._zone_area
        area_w = max(1.0, right - left)
        area_h = max(1.0, bottom - top)
        dx = (event.x - self._drag["x"]) / area_w
        dy = (event.y - self._drag["y"]) / area_h
        start: SensorZone = self._drag["zone"]
        zone = self._zones[self._drag["index"]]
        if self._drag["mode"] == "move":
            zone.x = max(0.0, min(1.0 - zone.w, start.x + dx))
            zone.y = max(0.0, min(1.0 - zone.h, start.y + dy))
        else:
            zone.w = max(0.04, min(1.0 - zone.x, start.w + dx))
            zone.h = max(0.04, min(1.0 - zone.y, start.h + dy))
        self._rebuild_zone_map()

    def _on_zone_release(self, _event: tk.Event) -> None:
        if self._drag is None:
            return
        self._drag = None
        self._config.sensor_zones = [zone.copy() for zone in self._zones]
        self._schedule_save()
        self._refresh_editor_preview()
        self._push_live_config()

    def _on_zone_double_click(self, event: tk.Event) -> None:
        if self._sampling_mode() != "zones":
            return
        if self._zone_at(event.x, event.y) is not None:
            return
        left, top, right, bottom = self._zone_area
        if right <= left or bottom <= top:
            return
        x = (event.x - left) / (right - left)
        y = (event.y - top) / (bottom - top)
        self._add_sensor_zone(x, y)

    def _on_zone_right_click(self, event: tk.Event) -> None:
        if self._sampling_mode() != "zones":
            return
        index = self._zone_at(event.x, event.y)
        if index is None:
            return
        self._selected_zone = index
        self._remove_sensor_zone()

    def _on_zone_hover(self, event: tk.Event) -> None:
        if self._drag is not None:
            return
        if self._sampling_mode() != "zones":
            self.zone_canvas.configure(cursor="")
            return
        index = self._zone_at(event.x, event.y)
        if index is None:
            cursor = "crosshair"
        elif self._near_handle(index, event.x, event.y):
            cursor = "size_nw_se"
        else:
            cursor = "fleur"
        self.zone_canvas.configure(cursor=cursor)

    def _add_sensor_zone(self, x: float = 0.5, y: float = 0.5) -> None:
        if self._sampling_mode() != "zones":
            self.mode_menu.set("Sensori liberi")
        if len(self._zones) >= 8:
            return
        self._config.zone_map = self._zone_map_snapshot()
        zone_w, zone_h = 0.26, 0.30
        zone = SensorZone(
            x=max(0.0, min(1.0 - zone_w, x - zone_w / 2)),
            y=max(0.0, min(1.0 - zone_h, y - zone_h / 2)),
            w=zone_w,
            h=zone_h,
        )
        self._zones.append(zone)
        self._selected_zone = len(self._zones) - 1
        self._after_zones_changed()

    def _remove_sensor_zone(self) -> None:
        if self._sampling_mode() != "zones" or len(self._zones) <= 1:
            return
        self._config.zone_map = self._zone_map_snapshot()
        index = self._selected_zone
        if index is None or not (0 <= index < len(self._zones)):
            index = len(self._zones) - 1
        self._zones.pop(index)
        remapped: dict[str, int] = {}
        for device_id, zone_index in self._config.zone_map.items():
            if zone_index == index:
                remapped[device_id] = -1
            elif zone_index > index:
                remapped[device_id] = zone_index - 1
            else:
                remapped[device_id] = zone_index
        self._config.zone_map = remapped
        self._selected_zone = min(index, len(self._zones) - 1)
        self._after_zones_changed()

    def _regenerate_bands(self) -> None:
        count = int(self.zones_menu.get()) if hasattr(self, "zones_menu") else 3
        self._config.zone_map = self._zone_map_snapshot()
        self._zones = default_sensor_zones(count)
        self._selected_zone = 0
        self.mode_menu.set("Sensori liberi")
        self._after_zones_changed()

    def _on_sampling_mode_changed(self) -> None:
        self._config.zone_map = self._zone_map_snapshot()
        self._config.sampling_mode = self._sampling_mode()
        self._sync_mode_widgets()
        self._rebuild_preview()
        self._schedule_save()
        self._refresh_editor_preview()
        self._push_live_config()

    def _sync_mode_widgets(self) -> None:
        state = "normal" if self._sampling_mode() == "bands" else "disabled"
        try:
            self.zones_menu.configure(state=state)
        except Exception:
            pass

    def _after_zones_changed(self) -> None:
        self._config.sampling_mode = "zones"
        self._config.sensor_zones = [zone.copy() for zone in self._zones]
        self._sync_mode_widgets()
        count = max(1, len(self._zones))
        for device_id, zone_index in list(self._config.zone_map.items()):
            if zone_index >= count:
                remapped = zone_index % count if count > 1 else -1
                self._config.zone_map[device_id] = remapped
        self._rebuild_preview()
        self._schedule_save()
        self._refresh_editor_preview()
        self._push_live_config()

    def _refresh_selection_footer(self) -> None:
        if self.app.screen_running:
            return
        selected = len(self.app._selected_ids())
        if selected:
            self.footer_status.configure(
                text=f"{selected} luci selezionate · premi Avvia.",
                text_color=COLORS["muted"],
            )
            self.start_button.configure(state="normal")
            self.select_button.configure(state="normal")
        else:
            self.footer_status.configure(
                text="Seleziona almeno una luce (qui o nella finestra principale).",
                text_color=COLORS["warning"],
            )
            self.start_button.configure(state="disabled")
            self.select_button.configure(state="normal")

    def _select_all_lights(self) -> None:
        self.app.select_all()
        self._refresh_selection_footer()
        self._rebuild_zone_map()

    def _build_preview_card(self) -> None:
        card = self._card()
        head = ctk.CTkFrame(card, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=14, pady=(10, 0))
        head.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            head,
            text="ANTEPRIMA ZONE",
            font=font(9, "bold"),
            text_color=COLORS["dim"],
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        self.preview_status = ctk.CTkLabel(
            head,
            text="",
            font=mono(9),
            text_color=COLORS["muted"],
            anchor="e",
        )
        self.preview_status.grid(row=0, column=1, sticky="e")
        self.preview_row = ctk.CTkFrame(card, fg_color="transparent")
        self.preview_row.grid(row=1, column=0, sticky="ew", padx=14, pady=(6, 3))
        self.preview_map_caption = ctk.CTkLabel(
            card,
            text="Clicca sotto una zona per assegnare le luci.",
            font=font(8),
            text_color=COLORS["dim"],
            anchor="w",
            justify="left",
        )
        self.preview_map_caption.grid(row=2, column=0, sticky="w", padx=14, pady=(0, 10))

    def _build_settings_card(self) -> None:
        card = self._card()
        ctk.CTkLabel(
            card,
            text="ANALISI E REAZIONE",
            font=font(9, "bold"),
            text_color=COLORS["dim"],
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=14, pady=(10, 0))

        options = ctk.CTkFrame(card, fg_color="transparent")
        options.grid(row=2, column=0, sticky="ew", padx=14, pady=(4, 6))
        options.grid_columnconfigure(5, weight=1)
        ctk.CTkLabel(
            options,
            text="FASCE",
            font=font(8, "bold"),
            text_color=COLORS["dim"],
        ).grid(row=0, column=0, sticky="w")
        self.zones_menu = ctk.CTkOptionMenu(
            options,
            values=["3", "5", "7"],
            width=64,
            height=27,
            fg_color=COLORS["panel_alt"],
            button_color=COLORS["border"],
            button_hover_color=COLORS["border_light"],
            dropdown_fg_color=COLORS["panel_alt"],
            dropdown_hover_color=COLORS["card_hover"],
            text_color=COLORS["text"],
            font=font(9),
            command=lambda _value: self._on_zones_changed(),
        )
        self.zones_menu.grid(row=0, column=1, padx=(6, 14))
        ctk.CTkLabel(
            options,
            text="PUNTI/ZONA",
            font=font(8, "bold"),
            text_color=COLORS["dim"],
        ).grid(row=0, column=2, sticky="w")
        self.sample_menu = ctk.CTkOptionMenu(
            options,
            values=["1", "4", "9"],
            width=64,
            height=27,
            fg_color=COLORS["panel_alt"],
            button_color=COLORS["border"],
            button_hover_color=COLORS["border_light"],
            dropdown_fg_color=COLORS["panel_alt"],
            dropdown_hover_color=COLORS["card_hover"],
            text_color=COLORS["text"],
            font=font(9),
            command=lambda _value: self._schedule_save(),
        )
        self.sample_menu.grid(row=0, column=3, padx=(6, 14))
        ctk.CTkLabel(
            options,
            text="FPS",
            font=font(8, "bold"),
            text_color=COLORS["dim"],
        ).grid(row=0, column=4, sticky="w")
        self.fps_menu = ctk.CTkOptionMenu(
            options,
            values=["5", "8", "10", "15", "30", "60"],
            width=64,
            height=27,
            fg_color=COLORS["panel_alt"],
            button_color=COLORS["border"],
            button_hover_color=COLORS["border_light"],
            dropdown_fg_color=COLORS["panel_alt"],
            dropdown_hover_color=COLORS["card_hover"],
            text_color=COLORS["text"],
            font=font(9),
            command=lambda _value: self._schedule_save(),
        )
        self.fps_menu.grid(row=0, column=5, sticky="w", padx=(6, 0))

        self.smooth_slider, self.smooth_label = self._slider_row(
            card, 3, "INSEGUIMENTO", 0.1, 3.0, 29, "1.2 s"
        )
        self.saturation_slider, self.saturation_label = self._slider_row(
            card, 4, "SATURAZIONE", 0.5, 2.0, 30, "1.25×"
        )
        self.max_slider, self.max_label = self._slider_row(
            card, 5, "LUMINOSITÀ MASSIMA", 20, 100, 80, "80%"
        )
        self.min_slider, self.min_label = self._slider_row(
            card, 6, "LUMINOSITÀ MINIMA", 0, 40, 8, "10%"
        )
        self.gamma_slider, self.gamma_label = self._slider_row(
            card, 7, "CURVA BUIO (più alta = scuri più cupi)", 0.6, 1.8, 12, "1.15"
        )

        toggles = ctk.CTkFrame(card, fg_color="transparent")
        toggles.grid(row=8, column=0, sticky="ew", padx=14, pady=(4, 2))
        self.hud_var = tk.BooleanVar(value=True)
        ctk.CTkSwitch(
            toggles,
            text="Escludi HUD/barre",
            width=130,
            variable=self.hud_var,
            switch_width=30,
            switch_height=16,
            fg_color=COLORS["border_light"],
            progress_color=COLORS["accent"],
            button_color=COLORS["text"],
            text_color=COLORS["muted"],
            font=font(8),
            command=self._schedule_save,
        ).pack(side="left")
        self.black_var = tk.BooleanVar(value=True)
        ctk.CTkSwitch(
            toggles,
            text="Mantieni colore su schermo nero",
            width=220,
            variable=self.black_var,
            switch_width=30,
            switch_height=16,
            fg_color=COLORS["border_light"],
            progress_color=COLORS["accent"],
            button_color=COLORS["text"],
            text_color=COLORS["muted"],
            font=font(8),
            command=self._schedule_save,
        ).pack(side="left", padx=(24, 0))

        toggles2 = ctk.CTkFrame(card, fg_color="transparent")
        toggles2.grid(row=9, column=0, sticky="ew", padx=14, pady=(2, 4))
        self.neutral_white_var = tk.BooleanVar(value=True)
        ctk.CTkSwitch(
            toggles2,
            text="Bianco dedicato per colori neutri",
            width=220,
            variable=self.neutral_white_var,
            switch_width=30,
            switch_height=16,
            fg_color=COLORS["border_light"],
            progress_color=COLORS["accent"],
            button_color=COLORS["text"],
            text_color=COLORS["muted"],
            font=font(8),
            command=self._schedule_save,
        ).pack(side="left")
        self.turbo_var = tk.BooleanVar(value=False)
        ctk.CTkSwitch(
            toggles2,
            text="Turbo music (sperimentale)",
            width=200,
            variable=self.turbo_var,
            switch_width=30,
            switch_height=16,
            fg_color=COLORS["border_light"],
            progress_color=COLORS["warning"],
            button_color=COLORS["text"],
            text_color=COLORS["muted"],
            font=font(8),
            command=self._schedule_save,
        ).pack(side="left", padx=(20, 0))

        toggles3 = ctk.CTkFrame(card, fg_color="transparent")
        toggles3.grid(row=10, column=0, sticky="ew", padx=14, pady=(2, 4))
        self.dark_off_var = tk.BooleanVar(value=True)
        ctk.CTkSwitch(
            toggles3,
            text="Nero = spento (sotto il 5%)",
            width=190,
            variable=self.dark_off_var,
            switch_width=30,
            switch_height=16,
            fg_color=COLORS["border_light"],
            progress_color=COLORS["accent"],
            button_color=COLORS["text"],
            text_color=COLORS["muted"],
            font=font(8),
            command=self._schedule_save,
        ).pack(side="left")
        ctk.CTkLabel(
            toggles3,
            text="evita il minimo acceso delle lampadine",
            font=font(8),
            text_color=COLORS["dim"],
            anchor="w",
        ).pack(side="left", padx=(10, 0))

        ctk.CTkLabel(
            card,
            text=(
                "Oltre ~85% di luminosità i LED bianchi si mescolano ai colori e "
                "li sbiadiscono: per verdi/blu pieni tieni il massimo più basso."
            ),
            font=font(8),
            text_color=COLORS["dim"],
            anchor="w",
            justify="left",
            wraplength=760,
        ).grid(row=11, column=0, sticky="w", padx=14, pady=(0, 10))

    def _slider_row(
        self,
        master: ctk.CTkFrame,
        row: int,
        label: str,
        minimum: float,
        maximum: float,
        steps: int,
        initial_text: str,
    ) -> tuple[ctk.CTkSlider, ctk.CTkLabel]:
        frame = ctk.CTkFrame(master, fg_color="transparent")
        frame.grid(row=row, column=0, sticky="ew", padx=14, pady=(2, 3))
        frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            frame,
            text=label,
            font=font(8, "bold"),
            text_color=COLORS["dim"],
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        label_widget = ctk.CTkLabel(
            frame,
            text=initial_text,
            font=font(9, "bold"),
            text_color=COLORS["text"],
            anchor="e",
        )
        label_widget.grid(row=0, column=1, sticky="e")
        slider = ctk.CTkSlider(
            frame,
            from_=minimum,
            to=maximum,
            number_of_steps=steps,
            height=14,
            fg_color=COLORS["border_light"],
            progress_color=COLORS["accent"],
            button_color=COLORS["accent"],
            button_hover_color=COLORS["accent_hover"],
            command=self._schedule_save,
        )
        slider.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(1, 0))
        return slider, label_widget

    # ------------------------------------------------------------- mouse wheel
    def _walk_widgets(self, widget: tk.Misc):
        yield widget
        for child in widget.winfo_children():
            yield from self._walk_widgets(child)

    def _scroll_page(self, event: tk.Event) -> str:
        canvas = getattr(self.scroll, "_parent_canvas", None)
        if canvas is None:
            return "break"
        if getattr(event, "num", None) == 4:
            delta = -1
        elif getattr(event, "num", None) == 5:
            delta = 1
        else:
            delta = -1 if event.delta > 0 else 1
        canvas.yview_scroll(delta, "units")
        return "break"

    def _fix_mouse_wheel(self) -> None:
        """Keep the wheel for scrolling the page, never for changing sliders."""
        scrollers = (ctk.CTkSlider, ctk.CTkOptionMenu)
        roots = [self.scroll]
        if hasattr(self, "preset_menu"):
            roots.append(self.preset_menu)
        for root in roots:
            for widget in self._walk_widgets(root):
                if not isinstance(widget, scrollers):
                    continue
                for target in self._walk_widgets(widget):
                    for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                        try:
                            target.unbind(sequence)
                        except tk.TclError:
                            pass
                        target.bind(sequence, self._scroll_page)
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            try:
                self.scroll.unbind(sequence)
            except tk.TclError:
                pass
            self.scroll.bind(sequence, self._scroll_page)

    # ------------------------------------------------------------------ state
    def _apply_config(self, config: ScreenSyncConfig) -> None:
        self._config = config.copy()
        self._config.assign_default_zones(self.app.devices)
        self._zones = [zone.copy() for zone in self._config.sensor_zones]
        self._selected_zone = 0 if self._zones else None
        self.mode_menu.set(
            "Sensori liberi" if self._config.sampling_mode == "zones" else "Fasce automatiche"
        )
        self.zones_menu.set(str(self._config.zones))
        self.sample_menu.set(str(self._config.sample_points))
        self.fps_menu.set(str(self._config.fps))
        self.smooth_slider.set(self._config.smoothing)
        self.saturation_slider.set(self._config.saturation)
        self.max_slider.set(self._config.brightness_max)
        self.min_slider.set(self._config.brightness_min)
        self.gamma_slider.set(self._config.brightness_gamma)
        self.hud_var.set(self._config.ignore_hud)
        self.black_var.set(self._config.hold_on_black)
        self.turbo_var.set(self._config.turbo)
        self.neutral_white_var.set(self._config.neutral_white)
        self.dark_off_var.set(self._config.dark_off)
        self._update_slider_labels()
        self._sync_mode_widgets()
        self._refresh_preset_menu()
        self._rebuild_zone_map()
        self._rebuild_preview()

    def _update_slider_labels(self) -> None:
        self.smooth_label.configure(text=f"{self.smooth_slider.get():.1f} s")
        self.saturation_label.configure(text=f"{self.saturation_slider.get():.2f}×")
        self.max_label.configure(text=f"{int(round(self.max_slider.get()))}%")
        self.min_label.configure(text=f"{int(round(self.min_slider.get()))}%")
        self.gamma_label.configure(text=f"{self.gamma_slider.get():.2f}")

    def _zone_map_snapshot(self) -> dict[str, int]:
        count = max(1, self._zone_count())
        zone_map: dict[str, int] = {}
        for index, device in enumerate(self.app.devices):
            zone = self._config.zone_map.get(device.id)
            if zone is None:
                zone = index % count if count > 1 else -1
            zone_map[device.id] = zone
        return zone_map

    def _read_config(self) -> ScreenSyncConfig:
        monitor = self._monitor_by_label.get(self.monitor_menu.get())
        zone_map = self._zone_map_snapshot()
        return ScreenSyncConfig(
            monitor_index=monitor.index if monitor else self._config.monitor_index,
            monitor_label=monitor.label if monitor else self._config.monitor_label,
            sampling_mode=self._sampling_mode(),
            sensor_zones=[zone.copy() for zone in self._zones],
            zones=int(self.zones_menu.get()),
            sample_grid={1: 1, 4: 2, 9: 3}.get(
                int(self.sample_menu.get()), self._config.sample_grid
            ),
            smoothing=float(self.smooth_slider.get()),
            saturation=float(self.saturation_slider.get()),
            brightness_min=int(round(self.min_slider.get())),
            brightness_max=int(round(self.max_slider.get())),
            brightness_gamma=float(self.gamma_slider.get()),
            fps=int(self.fps_menu.get()),
            turbo=bool(self.turbo_var.get()),
            neutral_white=bool(self.neutral_white_var.get()),
            neutral_threshold=self._config.neutral_threshold,
            dark_off=bool(self.dark_off_var.get()),
            dark_off_threshold=self._config.dark_off_threshold,
            ignore_hud=bool(self.hud_var.get()),
            hold_on_black=bool(self.black_var.get()),
            preset=self._config.preset,
            zone_map=zone_map,
        )

    def get_config(self) -> ScreenSyncConfig:
        config = self._read_config()
        config.assign_default_zones(self.app.devices)
        self._config = config
        self.app.screen_config = config
        self.app.screen_store.save(config)
        return config

    def _schedule_save(self, *_args: Any) -> None:
        self._update_slider_labels()
        if self._save_job is not None:
            try:
                self.after_cancel(self._save_job)
            except tk.TclError:
                pass
        self._save_job = self.after(400, self._save_now)

    def _save_now(self) -> None:
        self._save_job = None
        try:
            self.get_config()
        except Exception:
            LOGGER.exception("Salvataggio screen_sync.json fallito")
        self._push_live_config()

    def _push_live_config(self) -> None:
        if not getattr(self.app, "screen_running", False):
            return
        try:
            self.app.update_screen_sync_config(self)
        except Exception:
            LOGGER.exception("Aggiornamento live Screen Sync fallito")

    def _refresh_editor_preview(self) -> None:
        if getattr(self.app, "screen_running", False):
            return
        if self._sensor_thumb is None:
            return
        try:
            self._editor_frame = ScreenAnalyzer().update(
                self._sensor_thumb, self._read_config(), 0.1
            )
        except Exception:
            LOGGER.debug("Anteprima editor Screen Sync fallita.", exc_info=True)
            self._editor_frame = None
        self._update_preview()

    def _preset_names(self) -> list[str]:
        names = ["Default", *sorted(self._presets)]
        for name in SCREEN_PRESETS:
            if name not in names:
                names.append(name)
        return names

    def _refresh_preset_menu(self) -> None:
        if not hasattr(self, "preset_menu"):
            return
        values = self._preset_names()
        self.preset_menu.configure(values=values)
        if self._config.preset not in values:
            self._config.preset = "Default"
        self.preset_menu.set(self._config.preset)

    def _on_preset_selected(self, name: str) -> None:
        if self._preset_loading:
            return
        base = self._read_config()
        if name == "Default":
            data = ScreenSyncConfig().to_dict()
        elif name in self._presets:
            data = self._presets[name]
        elif name in SCREEN_PRESETS:
            data = SCREEN_PRESETS[name]
        else:
            return
        merged = base.to_dict()
        for key, value in data.items():
            if key in ("monitor_index", "monitor_label", "zone_map"):
                continue
            merged[key] = value
        merged["preset"] = name
        self._preset_loading = True
        try:
            self._apply_config(ScreenSyncConfig.from_dict(merged))
            self._config.preset = name
        finally:
            self._preset_loading = False
        self._schedule_save()
        self._push_live_config()
        self.footer_status.configure(
            text=f"Preset «{name}» applicato.",
            text_color=COLORS["muted"],
        )

    def _save_preset_dialog(self) -> None:
        name = simpledialog.askstring("Salva preset", "Nome del preset:", parent=self)
        if not name:
            return
        name = name.strip()
        if not name:
            return
        if name == "Default":
            self.footer_status.configure(
                text="«Default» è riservato: scegli un altro nome.",
                text_color=COLORS["warning"],
            )
            return
        data = self._read_config().to_dict()
        for key in ("monitor_index", "monitor_label", "zone_map", "preset"):
            data.pop(key, None)
        self._presets[name] = data
        if self._preset_store is not None:
            try:
                self._preset_store.save(self._presets)
            except Exception:
                LOGGER.exception("Salvataggio preset Screen Sync fallito")
                self.footer_status.configure(
                    text="Preset non salvato: errore di scrittura.",
                    text_color=COLORS["danger"],
                )
                return
        self._config.preset = name
        self._refresh_preset_menu()
        self._save_now()
        self.footer_status.configure(
            text=f"Preset «{name}» salvato.",
            text_color=COLORS["success"],
        )

    def _on_zones_changed(self) -> None:
        self._config.zones = int(self.zones_menu.get())
        if self._sampling_mode() == "bands":
            self._rebuild_preview()
        self._rebuild_zone_map()
        self._schedule_save()
        self._refresh_editor_preview()
        self._push_live_config()

    def _refresh_monitors(self) -> None:
        self._monitors = list_monitors()
        self._monitor_by_label = {monitor.label: monitor for monitor in self._monitors}
        values = list(self._monitor_by_label) or ["Schermo principale"]
        self.monitor_menu.configure(values=values)
        current_label = self._config.monitor_label
        if current_label in self._monitor_by_label:
            self.monitor_menu.set(current_label)
        else:
            primary = next((m for m in self._monitors if m.primary), self._monitors[0])
            self.monitor_menu.set(primary.label)
            self._config.monitor_index = primary.index
            self._config.monitor_label = primary.label

    def _rebuild_preview(self) -> None:
        for child in self.preview_row.winfo_children():
            child.destroy()
        self._preview_boxes = []
        self._preview_labels = []
        self._zone_assignment_buttons = []
        zones = max(1, self._zone_count())
        for index in range(zones):
            column = ctk.CTkFrame(self.preview_row, fg_color="transparent")
            column.grid(row=0, column=index, sticky="ew", padx=(0, 5))
            self.preview_row.grid_columnconfigure(index, weight=1)
            box = ctk.CTkFrame(
                column,
                height=42,
                corner_radius=8,
                fg_color=COLORS["panel_alt"],
            )
            box.pack(fill="x")
            box.pack_propagate(False)
            label = ctk.CTkLabel(
                box,
                text=f"Z{index + 1}",
                font=font(8, "bold"),
                text_color=COLORS["text"],
            )
            label.place(relx=0.5, rely=0.5, anchor="center")
            button = ctk.CTkButton(
                column,
                text="Nessuna luce",
                height=25,
                corner_radius=6,
                fg_color=COLORS["panel_alt"],
                border_width=1,
                border_color=COLORS["border"],
                hover_color=COLORS["card_hover"],
                text_color=COLORS["muted"],
                font=font(8),
                anchor="w",
                command=lambda value=index: self._open_zone_menu(value),
            )
            button.pack(fill="x", pady=(3, 0))
            self._preview_boxes.append(box)
            self._preview_labels.append(label)
            self._zone_assignment_buttons.append(button)
        self._refresh_zone_assignments()
        self._rebuild_zone_map()

    def _refresh_zone_assignments(self) -> None:
        for index, button in enumerate(self._zone_assignment_buttons):
            names = [
                device.name
                for device in self.app.devices
                if self._config.zone_map.get(device.id) == index
            ]
            if not names:
                text = "Nessuna luce"
            elif len(names) <= 2:
                text = ", ".join(names)
            else:
                text = f"{names[0]}, {names[1]} +{len(names) - 2}"
            try:
                button.configure(text=f"{text[:27]} ▾")
            except tk.TclError:
                pass
        globals_ = [
            device.name
            for device in self.app.devices
            if self._config.zone_map.get(device.id, -1) < 0
        ]
        if not self.app.devices:
            caption = "Nessuna luce configurata."
        elif globals_:
            caption = "Globali (media schermo): " + ", ".join(globals_)
        else:
            caption = "Clicca sotto una zona per assegnare le luci."
        self.preview_map_caption.configure(text=caption)

    def _open_zone_menu(self, zone_index: int) -> None:
        if not self.app.devices:
            self.footer_status.configure(
                text="Nessuna luce configurata: aggiungila dalle Impostazioni.",
                text_color=COLORS["warning"],
            )
            return
        if not (0 <= zone_index < len(self._zone_assignment_buttons)):
            return
        button = self._zone_assignment_buttons[zone_index]
        menu = tk.Menu(
            self,
            tearoff=0,
            bg=COLORS["panel_alt"],
            fg=COLORS["text"],
            activebackground=COLORS["accent_dark"],
            activeforeground=COLORS["text"],
            selectcolor=COLORS["accent"],
            bd=0,
            relief="flat",
        )
        self._zone_menu_vars = []
        for device in self.app.devices:
            variable = tk.BooleanVar(
                value=self._config.zone_map.get(device.id) == zone_index
            )
            self._zone_menu_vars.append(variable)
            menu.add_checkbutton(
                label=device.name,
                variable=variable,
                command=lambda device_id=device.id, var=variable, index=zone_index: (
                    self._toggle_zone_light(device_id, index, var)
                ),
            )
        menu.add_separator()
        menu.add_command(
            label="Nessuna (Globale)",
            command=lambda index=zone_index: self._clear_zone(index),
        )
        try:
            menu.tk_popup(
                button.winfo_rootx(),
                button.winfo_rooty() + button.winfo_height(),
            )
        finally:
            menu.grab_release()

    def _toggle_zone_light(
        self,
        device_id: str,
        zone_index: int,
        variable: tk.BooleanVar,
    ) -> None:
        if variable.get():
            self._config.zone_map[device_id] = zone_index
        elif self._config.zone_map.get(device_id) == zone_index:
            self._config.zone_map[device_id] = -1
        self._refresh_zone_assignments()
        self._rebuild_zone_map()
        self._schedule_save()
        self._refresh_editor_preview()
        self._push_live_config()

    def _clear_zone(self, zone_index: int) -> None:
        for device in self.app.devices:
            if self._config.zone_map.get(device.id) == zone_index:
                self._config.zone_map[device.id] = -1
        self._refresh_zone_assignments()
        self._rebuild_zone_map()
        self._schedule_save()
        self._refresh_editor_preview()
        self._push_live_config()

    def _capture_thumb_main(self) -> None:
        if not self.winfo_exists():
            return
        monitor_index = self._config.monitor_index
        try:
            monitor = self._monitor_by_label.get(self.monitor_menu.get())
            if monitor is not None:
                monitor_index = monitor.index
        except Exception:
            pass
        if _mss is not None:
            try:
                with _mss.MSS() as sct:
                    monitors = sct.monitors
                    index = (
                        monitor_index
                        if 1 <= monitor_index < len(monitors)
                        else 1
                    )
                    shot = sct.grab(monitors[index])
                    self._sensor_thumb = Image.frombytes(
                        "RGB", shot.size, shot.bgra, "raw", "BGRX"
                    )
            except Exception:
                LOGGER.debug("Sensor thumbnail capture failed.", exc_info=True)
        try:
            if self._sensor_thumb is not None:
                analyzer = ScreenAnalyzer()
                config = self._read_config()
                self._editor_frame = analyzer.update(self._sensor_thumb, config, 0.1)
        except Exception:
            LOGGER.debug("Editor analysis failed.", exc_info=True)
            self._editor_frame = None
        self._rebuild_zone_map()
        self._update_preview()
        self._thumb_job = self.after(2000, self._capture_thumb_main)

    def _stop_thumb(self) -> None:
        if self._thumb_job is not None:
            try:
                self.after_cancel(self._thumb_job)
            except tk.TclError:
                pass
            self._thumb_job = None

    # --------------------------------------------------------------- lifecycle
    def _present(self) -> None:
        if not self.winfo_exists():
            return
        self.update_idletasks()
        if not restore_geometry(self, self._restore_geometry):
            parent = self.app
            x = parent.winfo_rootx() + max(
                0, (parent.winfo_width() - self.winfo_width()) // 2
            )
            y = parent.winfo_rooty() + max(
                0, (parent.winfo_height() - self.winfo_height()) // 2
            )
            self.geometry(f"+{max(10, x)}+{max(10, y)}")
        self.lift()
        self.focus_force()
        self._preview_job = self.after(250, self._update_preview)

    def _update_preview(self) -> None:
        self._preview_job = None
        if not self.winfo_exists():
            return
        runner = getattr(self.app, "screen_runner", None)
        if runner is not None and getattr(self.app, "screen_running", False):
            frame = runner.last_frame
        else:
            frame = self._editor_frame
        if frame is not None:
            for index, box in enumerate(self._preview_boxes):
                target = frame.zones[index % len(frame.zones)] if frame.zones else frame.global_target
                is_off = (
                    self._config.dark_off
                    and target.brightness <= self._config.dark_off_threshold
                )
                sample = target.sample_rgb
                if sample == (0, 0, 0):
                    sample = (8, 8, 10)
                color = f"#{sample[0]:02x}{sample[1]:02x}{sample[2]:02x}"
                box.configure(fg_color=color)
                if index < len(self._preview_labels):
                    raw_pct = round(
                        (target.sample_luma if target.sample_luma > 0 else target.luma) * 100
                    )
                    self._preview_labels[index].configure(
                        text=(
                            f"Z{index + 1} · {raw_pct}% → "
                            f"{'OFF' if is_off else str(target.brightness) + '%'}"
                        ),
                        text_color=(
                            "#101418"
                            if target.sample_luma > 0.45
                            else COLORS["text"]
                        ),
                    )
            self.preview_status.configure(
                text=(
                    f"{frame.capture_ms} ms · {frame.analysis_ms} ms · "
                    f"{self.app.screen_runner.effective_fps:.1f} fps · "
                    f"scena {frame.frame_luma:.0%}/{frame.frame_median:.0%} · "
                    f"sat {frame.frame_saturation:.0%} · ×{frame.dark_factor:.2f}"
                )
            )
            if frame.warning:
                self.footer_status.configure(text=frame.warning, text_color=COLORS["warning"])
            elif self.app.screen_running:
                self.footer_status.configure(
                    text=(
                        f"Sync attivo · {len(frame.zones)} zone · "
                        f"{self.app.screen_runner.frame_count} frame · "
                        f"{self.app.screen_runner.effective_fps:.1f} fps"
                    ),
                    text_color=COLORS["success"],
                )
        else:
            for box in self._preview_boxes:
                box.configure(fg_color=COLORS["panel_alt"])
            self.preview_status.configure(text="nessun frame")
        if not self.app.screen_running:
            self._refresh_selection_footer()
        self._preview_job = self.after(300, self._update_preview)

    def set_running(self, running: bool) -> None:
        self._running = running
        if running:
            self.start_button.configure(
                text="FERMA SYNC",
                fg_color=COLORS["danger_dark"],
                hover_color="#4d1d29",
                text_color=COLORS["danger"],
                state="normal",
            )
            self.select_button.configure(state="disabled")
            self.footer_status.configure(
                text="Screen Sync attivo.", text_color=COLORS["success"]
            )
        else:
            self.start_button.configure(
                text="AVVIA SYNC",
                fg_color=COLORS["accent"],
                hover_color=COLORS["accent_hover"],
                text_color=COLORS["accent_text"],
                state="normal",
            )
            self.select_button.configure(state="normal")
            self._refresh_selection_footer()

    def _toggle(self) -> None:
        if self.app.screen_running:
            self.app.stop_screen_sync()
            return
        if not self.app._selected_ids():
            self.footer_status.configure(
                text="Nessuna luce selezionata: premi «Seleziona tutte le luci».",
                text_color=COLORS["warning"],
            )
            return
        started = self.app.start_screen_sync(self)
        if not started and not self.app.screen_running:
            self.footer_status.configure(
                text="Sync non avviato: controlla le luci selezionate e riprova.",
                text_color=COLORS["warning"],
            )

    def refresh_devices(self) -> None:
        count = max(1, self._zone_count())
        for index, device in enumerate(self.app.devices):
            if device.id not in self._config.zone_map:
                self._config.zone_map[device.id] = (
                    index % count if count > 1 else -1
                )
        self._rebuild_preview()

    def close(self) -> None:
        self._stop_thumb()
        if self.app.screen_running:
            self.app.stop_screen_sync(announce=False)
        if self._preview_job is not None:
            try:
                self.after_cancel(self._preview_job)
            except tk.TclError:
                pass
            self._preview_job = None
        if self._save_job is not None:
            try:
                self.after_cancel(self._save_job)
            except tk.TclError:
                pass
            self._save_job = None
        try:
            self.get_config()
        except Exception:
            LOGGER.exception("Salvataggio finale Screen Sync fallito")
        self.app.screen_window = None
        self.destroy()
