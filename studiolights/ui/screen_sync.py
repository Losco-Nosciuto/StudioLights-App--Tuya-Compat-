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
    list_monitors,
)
from ..theme import COLORS, font, mono

LOGGER = logging.getLogger("studiolights.ui.screen_sync")


class ScreenSyncWindow(ctk.CTkToplevel):
    def __init__(self, master: ctk.CTkBaseClass, app: Any) -> None:
        super().__init__(master, fg_color=COLORS["bg"])
        self.app = app
        self.title("Screen Sync — Studio Lights")
        self.geometry("820x740")
        self.minsize(740, 620)
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
            text="MAPPA SCHERMO → ZONE",
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
        self.zone_canvas = tk.Canvas(
            card,
            height=118,
            bg=COLORS["panel_alt"],
            highlightthickness=0,
            bd=0,
        )
        self.zone_canvas.grid(row=1, column=0, sticky="ew", padx=14, pady=(5, 12))
        self.zone_canvas.bind("<Configure>", lambda _event: self._rebuild_zone_map())
        ctk.CTkLabel(
            card,
            text=(
                "Le zone sono fasce verticali uguali del monitor. "
                "I punti/zona sono campioni dentro ogni fascia; HUD e barre nere "
                "vengono esclusi se attivo."
            ),
            font=font(8),
            text_color=COLORS["dim"],
            anchor="w",
            justify="left",
            wraplength=700,
        ).grid(row=2, column=0, sticky="w", padx=14, pady=(0, 10))

    def _rebuild_zone_map(self) -> None:
        if not hasattr(self, "zone_canvas"):
            return
        canvas = self.zone_canvas
        canvas.delete("all")
        width = max(300, canvas.winfo_width() or 700)
        height = 118
        zones = int(self.zones_menu.get()) if hasattr(self, "zones_menu") else 3
        left, right = 12, width - 12
        top, bottom = 26, height - 12
        monitor = self.monitor_menu.get() if hasattr(self, "monitor_menu") else "Monitor"
        canvas.create_text(
            left,
            8,
            text=monitor,
            anchor="nw",
            fill=COLORS["dim"],
            font=font(8),
        )
        global_names: list[str] = []
        for index in range(zones):
            x0 = left + (right - left) * index // zones
            x1 = left + (right - left) * (index + 1) // zones
            canvas.create_rectangle(
                x0,
                top,
                x1,
                bottom,
                fill=COLORS["panel"],
                outline=COLORS["border_light"],
                width=1,
            )
            canvas.create_text(
                x0 + 7,
                top + 6,
                text=f"Z{index + 1}",
                anchor="nw",
                fill=COLORS["accent"],
                font=font(9, "bold"),
            )
            start_pct = round(100 * index / zones)
            end_pct = round(100 * (index + 1) / zones)
            canvas.create_text(
                x0 + 7,
                top + 23,
                text=f"{start_pct}–{end_pct}%",
                anchor="nw",
                fill=COLORS["dim"],
                font=font(8),
            )
            names = []
            for device in self.app.devices:
                menu = self._light_menus.get(device.id)
                value = menu.get() if menu is not None else "Globale"
                if value == f"Zona {index + 1}":
                    names.append(device.name)
                elif value == "Globale":
                    global_names.append(device.name)
            canvas.create_text(
                x0 + 7,
                bottom - 7,
                text=", ".join(names)[:38] if names else "—",
                anchor="sw",
                fill=COLORS["text"] if names else COLORS["dim"],
                font=font(8, "bold") if names else font(8),
            )
        unique_global = list(dict.fromkeys(global_names))
        self.zone_caption.configure(
            text=(
                "Globale: " + ", ".join(unique_global)[:40]
                if unique_global
                else "Nessuna luce globale"
            )
        )

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
            text="ZONE",
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
            values=["5", "8", "10", "15"],
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
            card, 3, "INSEGUIMENTO", 0.3, 3.0, 27, "1.2 s"
        )
        self.saturation_slider, self.saturation_label = self._slider_row(
            card, 4, "SATURAZIONE", 0.5, 2.0, 30, "1.25×"
        )
        self.max_slider, self.max_label = self._slider_row(
            card, 5, "LUMINOSITÀ MASSIMA", 20, 100, 80, "80%"
        )
        self.min_slider, self.min_label = self._slider_row(
            card, 6, "LUMINOSITÀ MINIMA", 0, 40, 8, "8%"
        )

        toggles = ctk.CTkFrame(card, fg_color="transparent")
        toggles.grid(row=7, column=0, sticky="ew", padx=14, pady=(4, 12))
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
        self.zones_menu.set(str(self._config.zones))
        self.sample_menu.set(str(self._config.sample_points))
        self.fps_menu.set(str(self._config.fps))
        self.smooth_slider.set(self._config.smoothing)
        self.saturation_slider.set(self._config.saturation)
        self.max_slider.set(self._config.brightness_max)
        self.min_slider.set(self._config.brightness_min)
        self.hud_var.set(self._config.ignore_hud)
        self.black_var.set(self._config.hold_on_black)
        self._update_slider_labels()
        self._rebuild_preview()

    def _update_slider_labels(self) -> None:
        self.smooth_label.configure(text=f"{self.smooth_slider.get():.1f} s")
        self.saturation_label.configure(text=f"{self.saturation_slider.get():.2f}×")
        self.max_label.configure(text=f"{int(round(self.max_slider.get()))}%")
        self.min_label.configure(text=f"{int(round(self.min_slider.get()))}%")

    def _read_config(self) -> ScreenSyncConfig:
        monitor = self._monitor_by_label.get(self.monitor_menu.get())
        zone_map: dict[str, int] = {}
        for device in self.app.devices:
            menu = self._light_menus.get(device.id)
            if menu is None:
                continue
            value = menu.get()
            if value == "Globale":
                zone_map[device.id] = -1
            else:
                try:
                    zone_map[device.id] = int(value.split()[-1]) - 1
                except (ValueError, IndexError):
                    zone_map[device.id] = -1
        return ScreenSyncConfig(
            monitor_index=monitor.index if monitor else self._config.monitor_index,
            monitor_label=monitor.label if monitor else self._config.monitor_label,
            zones=int(self.zones_menu.get()),
            sample_grid={1: 1, 4: 2, 9: 3}.get(
                int(self.sample_menu.get()), self._config.sample_grid
            ),
            smoothing=float(self.smooth_slider.get()),
            saturation=float(self.saturation_slider.get()),
            brightness_min=int(round(self.min_slider.get())),
            brightness_max=int(round(self.max_slider.get())),
            fps=int(self.fps_menu.get()),
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
        self.smooth_slider.set(preset["smoothing"])
        self.saturation_slider.set(preset["saturation"])
        self.max_slider.set(preset["brightness_max"])
        self._update_slider_labels()
        self._schedule_save()

    def _on_zones_changed(self) -> None:
        self._config.zones = int(self.zones_menu.get())
        self._rebuild_preview()
        self._rebuild_light_map()
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
        zones = int(self.zones_menu.get()) if hasattr(self, "zones_menu") else 3
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
        zones = int(self.zones_menu.get()) if hasattr(self, "zones_menu") else 3
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
                color = f"#{target.rgb[0]:02x}{target.rgb[1]:02x}{target.rgb[2]:02x}"
                box.configure(fg_color=color)
                if index < len(self._preview_labels):
                    self._preview_labels[index].configure(
                        text=f"Z{index + 1} · {target.brightness}%",
                        text_color="#101418" if target.luma > 0.45 else COLORS["text"],
                    )
            self.preview_status.configure(
                text=f"{frame.capture_ms} ms capture · {frame.analysis_ms} ms analisi"
            )
            if frame.warning:
                self.footer_status.configure(text=frame.warning, text_color=COLORS["warning"])
            elif self.app.screen_running:
                self.footer_status.configure(
                    text=f"Sync attivo · {len(frame.zones)} zone · "
                    f"{self.app.screen_runner.frame_count} frame",
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
