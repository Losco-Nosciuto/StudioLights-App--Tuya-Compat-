"""Non-modal Screen Sync configuration window."""

from __future__ import annotations

import logging
import tkinter as tk
from typing import Any

import customtkinter as ctk

from ..screen_sync import (
    SCREEN_PRESETS,
    MonitorInfo,
    ScreenSyncConfig,
    SensorZone,
    default_sensor_zones,
    list_monitors,
)
from ..theme import COLORS, font, mono

LOGGER = logging.getLogger("studiolights.ui.screen_sync")


class ScreenSyncWindow(ctk.CTkToplevel):
    def __init__(self, master: ctk.CTkBaseClass, app: Any) -> None:
        super().__init__(master, fg_color=COLORS["bg"])
        self.app = app
        self.title("Screen Sync — Studio Lights")
        self.geometry("900x820")
        self.minsize(780, 640)
        self.transient(master)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self._monitors: list[MonitorInfo] = list_monitors()
        self._monitor_by_label: dict[str, MonitorInfo] = {}
        self._light_menus: dict[str, ctk.CTkOptionMenu] = {}
        self._preview_boxes: list[ctk.CTkFrame] = []
        self._preview_labels: list[ctk.CTkLabel] = []
        self._preview_job: str | None = None
        self._save_job: str | None = None
        self._running = False
        self._config = app.screen_config.copy()
        self._zones: list[SensorZone] = [zone.copy() for zone in self._config.sensor_zones]
        self._selected_zone: int | None = 0 if self._zones else None
        self._zone_area: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
        self._drag: dict[str, Any] | None = None
        self._build()
        self._apply_config(self._config)
        self._refresh_monitors()
        self._rebuild_light_map()
        self._update_preview()
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
        ).grid(row=0, column=2, rowspan=2, sticky="e")
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
        ).grid(row=0, column=1, rowspan=2, sticky="e", padx=(0, 8))

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
        self._build_light_map_card()

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

        toolbar = ctk.CTkFrame(card, fg_color="transparent")
        toolbar.grid(row=1, column=0, sticky="ew", padx=14, pady=(5, 4))
        toolbar.grid_columnconfigure(4, weight=1)
        ctk.CTkLabel(
            toolbar,
            text="MODALITÀ",
            font=font(8, "bold"),
            text_color=COLORS["dim"],
        ).grid(row=0, column=0, sticky="w")
        self.mode_menu = ctk.CTkOptionMenu(
            toolbar,
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
        self.mode_menu.grid(row=0, column=1, padx=(6, 14))
        ctk.CTkButton(
            toolbar,
            text="+ Sensore",
            width=86,
            height=27,
            corner_radius=6,
            fg_color=COLORS["panel_alt"],
            border_width=1,
            border_color=COLORS["border"],
            hover_color=COLORS["card_hover"],
            text_color=COLORS["muted"],
            font=font(8, "bold"),
            command=self._add_sensor_zone,
        ).grid(row=0, column=2, padx=(0, 5))
        ctk.CTkButton(
            toolbar,
            text="Rimuovi",
            width=74,
            height=27,
            corner_radius=6,
            fg_color=COLORS["panel_alt"],
            border_width=1,
            border_color=COLORS["border"],
            hover_color=COLORS["card_hover"],
            text_color=COLORS["muted"],
            font=font(8, "bold"),
            command=self._remove_sensor_zone,
        ).grid(row=0, column=3, padx=(0, 5))
        ctk.CTkButton(
            toolbar,
            text="Rigenera fasce",
            width=106,
            height=27,
            corner_radius=6,
            fg_color="transparent",
            border_width=1,
            border_color=COLORS["border"],
            hover_color=COLORS["card_hover"],
            text_color=COLORS["dim"],
            font=font(8),
            command=self._regenerate_bands,
        ).grid(row=0, column=4, sticky="e")

        self.zone_canvas = tk.Canvas(
            card,
            height=300,
            bg=COLORS["panel_alt"],
            highlightthickness=0,
            bd=0,
            cursor="crosshair",
        )
        self.zone_canvas.grid(row=2, column=0, sticky="ew", padx=14, pady=(2, 4))
        self.zone_canvas.bind("<Configure>", self._on_zone_canvas_configure)
        self.zone_canvas.bind("<ButtonPress-1>", self._on_zone_press)
        self.zone_canvas.bind("<B1-Motion>", self._on_zone_drag)
        self.zone_canvas.bind("<ButtonRelease-1>", self._on_zone_release)
        self.zone_canvas.bind("<Double-Button-1>", self._on_zone_double_click)
        self.zone_canvas.bind("<ButtonPress-3>", self._on_zone_right_click)
        self.zone_canvas.bind("<Motion>", self._on_zone_hover)

        ctk.CTkLabel(
            card,
            text=(
                "Trascina un sensore per spostarlo, usa il quadratino in basso a "
                "destra per ridimensionarlo. Doppio clic sul vuoto aggiunge un "
                "sensore, clic destro lo rimuove. La cattura resta una sola: le "
                "zone scelgono solo cosa campionare."
            ),
            font=font(8),
            text_color=COLORS["dim"],
            anchor="w",
            justify="left",
            wraplength=760,
        ).grid(row=3, column=0, sticky="w", padx=14, pady=(0, 10))

    # --------------------------------------------------------- zone geometry
    def _sampling_mode(self) -> str:
        return "zones" if self.mode_menu.get() == "Sensori liberi" else "bands"

    def _zone_count(self) -> int:
        if self._sampling_mode() == "zones":
            return len(self._zones)
        return int(self.zones_menu.get()) if hasattr(self, "zones_menu") else 3

    def _on_zone_canvas_configure(self, event: tk.Event) -> None:
        target = int(min(480, max(180, event.width * 9 / 16)))
        current = int(self.zone_canvas.cget("height"))
        if abs(current - target) > 2:
            self.zone_canvas.configure(height=target)
            return
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
        height = max(180, int(canvas.cget("height")))
        pad = 10
        left, top, right, bottom = pad, pad, width - pad, height - pad
        self._zone_area = (left, top, right, bottom)
        canvas.create_rectangle(
            left,
            top,
            right,
            bottom,
            fill=COLORS["panel"],
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
            names = []
            for device in self.app.devices:
                menu = self._light_menus.get(device.id)
                if menu is not None and menu.get() == f"Zona {index + 1}":
                    names.append(device.name)
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
        self._config.zone_map = self._collect_zone_map()
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
        self._config.zone_map = self._collect_zone_map()
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
        self._config.zone_map = self._collect_zone_map()
        self._zones = default_sensor_zones(count)
        self._selected_zone = 0
        self.mode_menu.set("Sensori liberi")
        self._after_zones_changed()

    def _on_sampling_mode_changed(self) -> None:
        self._config.zone_map = self._collect_zone_map()
        self._config.sampling_mode = self._sampling_mode()
        self._sync_mode_widgets()
        self._rebuild_light_map()
        self._rebuild_preview()
        self._schedule_save()

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
        self._rebuild_light_map()
        self._rebuild_preview()
        self._schedule_save()

    def _on_light_map_changed(self) -> None:
        self._schedule_save()
        self._rebuild_zone_map()

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
        self.preview_row.grid(row=1, column=0, sticky="ew", padx=14, pady=(6, 14))

    def _build_settings_card(self) -> None:
        card = self._card()
        ctk.CTkLabel(
            card,
            text="ANALISI E REAZIONE",
            font=font(9, "bold"),
            text_color=COLORS["dim"],
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=14, pady=(10, 0))

        preset_row = ctk.CTkFrame(card, fg_color="transparent")
        preset_row.grid(row=1, column=0, sticky="w", padx=14, pady=(5, 4))
        for index, name in enumerate(SCREEN_PRESETS):
            ctk.CTkButton(
                preset_row,
                text=name,
                width=86,
                height=25,
                corner_radius=6,
                fg_color=COLORS["panel_alt"],
                border_width=1,
                border_color=COLORS["border"],
                hover_color=COLORS["card_hover"],
                text_color=COLORS["muted"],
                font=font(8),
                command=lambda value=name: self._apply_preset(value),
            ).grid(row=0, column=index, padx=(0, 5))

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

    def _build_light_map_card(self) -> None:
        card = self._card()
        head = ctk.CTkFrame(card, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=14, pady=(10, 2))
        head.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            head,
            text="MAPPA LUCI → ZONE",
            font=font(9, "bold"),
            text_color=COLORS["dim"],
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            head,
            text="Globale = media schermo intero",
            font=font(8),
            text_color=COLORS["dim"],
            anchor="e",
        ).grid(row=0, column=1, sticky="e")
        self.light_map_frame = ctk.CTkFrame(card, fg_color="transparent")
        self.light_map_frame.grid(row=1, column=0, sticky="ew", padx=14, pady=(4, 10))
        self.light_map_frame.grid_columnconfigure(0, weight=1)

    # ------------------------------------------------------------------ state
    def _apply_config(self, config: ScreenSyncConfig) -> None:
        self._config = config.copy()
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
        self._rebuild_zone_map()
        self._rebuild_preview()

    def _update_slider_labels(self) -> None:
        self.smooth_label.configure(text=f"{self.smooth_slider.get():.1f} s")
        self.saturation_label.configure(text=f"{self.saturation_slider.get():.2f}×")
        self.max_label.configure(text=f"{int(round(self.max_slider.get()))}%")
        self.min_label.configure(text=f"{int(round(self.min_slider.get()))}%")
        self.gamma_label.configure(text=f"{self.gamma_slider.get():.2f}")

    def _collect_zone_map(self) -> dict[str, int]:
        zone_map: dict[str, int] = {}
        for device in self.app.devices:
            menu = self._light_menus.get(device.id)
            if menu is None:
                if device.id in self._config.zone_map:
                    zone_map[device.id] = self._config.zone_map[device.id]
                continue
            value = menu.get()
            if value == "Globale":
                zone_map[device.id] = -1
            else:
                try:
                    zone_map[device.id] = int(value.split()[-1]) - 1
                except (ValueError, IndexError):
                    zone_map[device.id] = -1
        return zone_map

    def _read_config(self) -> ScreenSyncConfig:
        monitor = self._monitor_by_label.get(self.monitor_menu.get())
        zone_map = self._collect_zone_map()
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

    def _apply_preset(self, name: str) -> None:
        preset = SCREEN_PRESETS.get(name)
        if not preset:
            return
        self._config.preset = name
        if "smoothing" in preset:
            self.smooth_slider.set(preset["smoothing"])
        if "saturation" in preset:
            self.saturation_slider.set(preset["saturation"])
        if "brightness_max" in preset:
            self.max_slider.set(preset["brightness_max"])
        if "fps" in preset:
            self.fps_menu.set(str(int(preset["fps"])))
        if "turbo" in preset:
            self.turbo_var.set(bool(preset["turbo"]))
        self._update_slider_labels()
        self._schedule_save()

    def _on_zones_changed(self) -> None:
        self._config.zones = int(self.zones_menu.get())
        if self._sampling_mode() == "bands":
            self._rebuild_light_map()
            self._rebuild_preview()
        self._rebuild_zone_map()
        self._schedule_save()

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
        zones = self._zone_count()
        for index in range(zones):
            box = ctk.CTkFrame(
                self.preview_row,
                height=42,
                corner_radius=8,
                fg_color=COLORS["panel_alt"],
            )
            box.grid(row=0, column=index, sticky="ew", padx=(0, 5))
            self.preview_row.grid_columnconfigure(index, weight=1)
            box.grid_propagate(False)
            label = ctk.CTkLabel(
                box,
                text=f"Z{index + 1}",
                font=font(8, "bold"),
                text_color=COLORS["text"],
            )
            label.place(relx=0.5, rely=0.5, anchor="center")
            self._preview_boxes.append(box)
            self._preview_labels.append(label)

    def _rebuild_light_map(self) -> None:
        for child in self.light_map_frame.winfo_children():
            child.destroy()
        self._light_menus = {}
        zones = self._zone_count()
        values = ["Globale"] + [f"Zona {index + 1}" for index in range(zones)]
        for row_index, device in enumerate(self.app.devices):
            row = ctk.CTkFrame(self.light_map_frame, fg_color="transparent")
            row.grid(row=row_index, column=0, sticky="ew", pady=2)
            row.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(
                row,
                text=device.name,
                font=font(9, "bold"),
                text_color=COLORS["text"],
                anchor="w",
            ).grid(row=0, column=0, sticky="w", padx=(0, 8))
            default_zone = self._config.zone_map.get(
                device.id, row_index % zones if zones > 1 else -1
            )
            value = (
                "Globale"
                if default_zone < 0
                else f"Zona {min(default_zone, zones - 1) + 1}"
            )
            menu = ctk.CTkOptionMenu(
                row,
                values=values,
                width=100,
                height=25,
                fg_color=COLORS["panel_alt"],
                button_color=COLORS["border"],
                button_hover_color=COLORS["border_light"],
                dropdown_fg_color=COLORS["panel_alt"],
                dropdown_hover_color=COLORS["card_hover"],
                text_color=COLORS["text"],
                font=font(9),
                command=lambda _value: self._on_light_map_changed(),
            )
            menu.grid(row=0, column=1, sticky="e")
            menu.set(value)
            self._light_menus[device.id] = menu
        if not self.app.devices:
            ctk.CTkLabel(
                self.light_map_frame,
                text="Nessuna luce configurata.",
                font=font(9),
                text_color=COLORS["muted"],
                anchor="w",
            ).grid(row=0, column=0, sticky="w")
        self._rebuild_zone_map()

    # --------------------------------------------------------------- lifecycle
    def _present(self) -> None:
        if not self.winfo_exists():
            return
        self.update_idletasks()
        parent = self.app
        x = parent.winfo_rootx() + max(0, (parent.winfo_width() - self.winfo_width()) // 2)
        y = parent.winfo_rooty() + max(0, (parent.winfo_height() - self.winfo_height()) // 2)
        self.geometry(f"+{max(10, x)}+{max(10, y)}")
        self.lift()
        self.focus_force()
        self._preview_job = self.after(250, self._update_preview)

    def _update_preview(self) -> None:
        self._preview_job = None
        if not self.winfo_exists():
            return
        frame = self.app.screen_runner.last_frame
        if frame is not None:
            for index, box in enumerate(self._preview_boxes):
                target = frame.zones[index % len(frame.zones)] if frame.zones else frame.global_target
                is_off = (
                    self._config.dark_off
                    and target.brightness <= self._config.dark_off_threshold
                )
                sample = target.sample_rgb if target.sample_rgb != (0, 0, 0) else target.rgb
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
        self._config.zone_map = {
            device.id: self._config.zone_map.get(device.id, -1)
            for device in self.app.devices
        }
        self._rebuild_light_map()

    def close(self) -> None:
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
