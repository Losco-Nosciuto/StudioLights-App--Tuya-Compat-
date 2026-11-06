"""Main Studio Lights window."""

from __future__ import annotations

import logging
import tkinter as tk
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import customtkinter as ctk
from PIL import Image

from ..config import ConfigError, LightStore, SceneStore, project_root
from ..controller import LightController
from ..flow import FlowRunner
from ..models import (
    ERROR_AUTH,
    ERROR_OFFLINE,
    SCENE_FLOW,
    SCENE_GLOBAL,
    SCENE_SNAPSHOT,
    FlowConfig,
    LightDevice,
    LightState,
    OperationReport,
    Scene,
    utc_now_iso,
)
from ..theme import COLORS, font, mono, setup_appearance
from ..util import format_ms, hex_to_rgb, kelvin_from_temp, rgb_to_hex, temp_preview_hex
from .colorpicker import ColorPicker
from .dialogs import (
    ColorPickerDialog,
    ConfirmDialog,
    SceneDialog,
    SettingsWindow,
)
from .widgets import LightRow, SceneCard

LOGGER = logging.getLogger("studiolights.ui.app")

STATUS_COLORS = {
    "muted": COLORS["muted"],
    "success": COLORS["success"],
    "warning": COLORS["warning"],
    "danger": COLORS["danger"],
}

MODE_LABELS = {
    "Bianco": ("APPLICA BIANCO", "white"),
    "Colore": ("APPLICA COLORE", "colour"),
    "Scena HW": ("ATTIVA SCENA HW", "scene"),
    "Flow": ("AVVIA FLOW", "flow"),
}

FLOW_PRESETS: dict[str, list[str]] = {
    "Cyberpunk": [
        "#00e5ff", "#7b2cff", "#ff2bd6", "#2200ff",
        "#00ffd5", "#ff00a8", "#4d00ff", "#00b3ff",
    ],
    "Tramonto": [
        "#ff3b30", "#ff7a18", "#ffb347", "#ffd166",
        "#ff8fb1", "#d94f8a", "#7b2cbf", "#3a0ca3",
    ],
    "Foresta": [
        "#0b3d2e", "#1f7a4d", "#3ddc97", "#a7f3d0",
        "#7cb342", "#2e7d32", "#134e4a", "#0f766e",
    ],
    "Neon": [
        "#ff00ff", "#00ffff", "#ffff00", "#ff0000",
        "#00ff00", "#0000ff", "#ff8000", "#8000ff",
    ],
}

PRESETS: list[tuple[str, str]] = [
    ("Rosso", "#ff3b30"),
    ("Ambra", "#ff8a3d"),
    ("Caldo", "#ffd166"),
    ("Lime", "#7cff6b"),
    ("Ciano", "#35e0c8"),
    ("Ghiaccio", "#3da5ff"),
    ("Indaco", "#6c5ce7"),
    ("Viola", "#b06cff"),
    ("Magenta", "#ff4fd8"),
    ("Bianco", "#ffffff"),
]


class StudioLightsApp(ctk.CTk):
    def __init__(self, root_dir: Path | None = None) -> None:
        setup_appearance()
        super().__init__()

        self.root_dir = Path(root_dir) if root_dir else project_root()
        self.title("Studio Lights — Controllo luci LAN")
        self.geometry("1360x860")
        self.minsize(1140, 740)
        self.configure(fg_color=COLORS["bg"])

        self._closing = False
        self._busy = False
        self._refresh_running = False
        self._scan_running = False
        self._save_job: str | None = None
        self.settings_window: SettingsWindow | None = None
        self.rows: dict[str, LightRow] = {}
        self.health: dict[str, bool | None] = {}
        self._scene_cards: list[SceneCard] = []
        self._bulk_buttons: list[ctk.CTkButton] = []

        self._task_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="ui-task")
        self.controller = LightController()
        self.flow_runner = FlowRunner(self.controller)
        self.flow_config = FlowConfig()
        self._flow_running = False
        self._flow_devices: list[LightDevice] = []

        self.store = LightStore(self.root_dir)
        self.scene_store = SceneStore(self.root_dir)
        self.store.ensure_template()

        data = self.store.bootstrap()
        self.devices: list[LightDevice] = list(data.devices)
        self.states: dict[str, LightState] = dict(data.states)
        self.demo: bool = data.demo
        self._auto_import_devices_json()
        for device in self.devices:
            self.states.setdefault(device.id, LightState())
            self.health[device.id] = None
        self.scenes: list[Scene] = self.scene_store.load()
        self.controller.sync_devices(self.devices)

        # Manual control state (percentages are what the Tuya API expects from us).
        self.ui_brightness = 80.0
        self.ui_temp = 50.0
        self.ui_rgb: tuple[int, int, int] = (255, 200, 150)
        self._mode = "Bianco"
        self._syncing = False

        self._setup_window_icon()
        self._build_ui()
        self._rebuild_light_rows()
        self._rebuild_scenes()
        self._update_editor_labels()
        self._update_online_chip()
        self._update_selection_ui()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<F5>", lambda _event: self.refresh_states())
        self.bind("<Control-n>", lambda _event: self.new_scene())
        self.after(350, self._startup)

    # =================================================================== setup
    def _setup_window_icon(self) -> None:
        ico = self.root_dir / "assets" / "icon.ico"
        png = self.root_dir / "assets" / "icon.png"
        if ico.exists():
            try:
                self.iconbitmap(str(ico))
            except tk.TclError:
                LOGGER.debug("iconbitmap non supportato su questa piattaforma.")
        if png.exists():
            try:
                photo = tk.PhotoImage(file=str(png))
                self.iconphoto(True, photo)
                self._icon_photo = photo
            except tk.TclError:
                LOGGER.debug("Impossibile caricare l'icona PNG.")

    def _auto_import_devices_json(self) -> None:
        """While the untouched demo is active, honour a wizard devices.json."""
        if not self.demo:
            return
        if not (self.root_dir / "devices.json").exists():
            return
        try:
            imported, warnings = self.store.import_devices_json()
        except ConfigError as exc:
            LOGGER.warning("Import automatico devices.json saltato: %s", exc)
            return
        if not imported:
            for warning in warnings:
                LOGGER.warning("Import automatico: %s", warning)
            return

        self.devices = imported
        self.states = {device.id: LightState() for device in imported}
        self.health = {device.id: None for device in imported}
        self.demo = False
        try:
            self.store.save(self.devices, self.states, self.demo)
        except Exception:
            LOGGER.exception("Salvataggio dell'import automatico fallito")
        LOGGER.info("Import automatico da devices.json: %d luci.", len(imported))

    def _logo_image(self) -> ctk.CTkImage | None:
        png = self.root_dir / "assets" / "icon.png"
        if not png.exists():
            return None
        try:
            image = Image.open(png)
            return ctk.CTkImage(light_image=image, dark_image=image, size=(34, 34))
        except Exception:
            LOGGER.debug("Logo non caricabile.", exc_info=True)
            return None

    def _build_ui(self) -> None:
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=0, minsize=352)
        self.grid_columnconfigure(1, weight=4, minsize=430)
        self.grid_columnconfigure(2, weight=4, minsize=430)

        self._build_header()
        self._build_lights_panel()
        self._build_controls_panel()
        self._build_scenes_panel()
        self._build_statusbar()

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(
            row=0, column=0, columnspan=3, sticky="ew", padx=18, pady=(14, 6)
        )
        header.grid_columnconfigure(1, weight=1)

        logo = self._logo_image()
        if logo is not None:
            self._logo_ref = logo
            ctk.CTkLabel(header, text="", image=logo, width=34, height=34).grid(
                row=0, column=0, rowspan=2, sticky="w", padx=(0, 12)
            )
        else:
            badge = ctk.CTkFrame(
                header,
                width=34,
                height=34,
                corner_radius=10,
                fg_color=COLORS["accent_dark"],
            )
            badge.grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 12))
            badge.grid_propagate(False)
            ctk.CTkLabel(
                badge,
                text="◉",
                font=font(19, "bold"),
                text_color=COLORS["accent"],
            ).place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(
            header,
            text="STUDIO LIGHTS",
            font=font(21, "bold"),
            text_color=COLORS["text"],
            anchor="w",
        ).grid(row=0, column=1, sticky="sw")
        ctk.CTkLabel(
            header,
            text="CONTROLLO LUCI LAN  ·  TUYA / SMART LIFE  ·  NESSUN CLOUD",
            font=font(9),
            text_color=COLORS["dim"],
            anchor="w",
        ).grid(row=1, column=1, sticky="nw", pady=(1, 0))

        self.online_chip = ctk.CTkFrame(
            header,
            fg_color=COLORS["panel"],
            corner_radius=16,
            border_width=1,
            border_color=COLORS["border"],
            height=32,
        )
        self.online_chip.grid(row=0, column=2, rowspan=2, padx=(0, 8))
        self.online_chip.grid_propagate(False)
        self.online_dot = ctk.CTkFrame(
            self.online_chip,
            width=7,
            height=7,
            corner_radius=4,
            fg_color=COLORS["dim"],
        )
        self.online_dot.pack(side="left", padx=(12, 6), pady=12)
        self.online_dot.pack_propagate(False)
        self.online_label = ctk.CTkLabel(
            self.online_chip,
            text="ONLINE —",
            font=font(9, "bold"),
            text_color=COLORS["muted"],
        )
        self.online_label.pack(side="left", padx=(0, 12))

        self.refresh_button = ctk.CTkButton(
            header,
            text="Aggiorna",
            width=92,
            height=32,
            corner_radius=8,
            fg_color="transparent",
            border_width=1,
            border_color=COLORS["border_light"],
            hover_color=COLORS["card_hover"],
            text_color=COLORS["muted"],
            font=font(10, "bold"),
            command=self.refresh_states,
        )
        self.refresh_button.grid(row=0, column=3, rowspan=2, padx=(0, 8))

        self.settings_button = ctk.CTkButton(
            header,
            text="Impostazioni",
            width=112,
            height=32,
            corner_radius=8,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            text_color=COLORS["accent_text"],
            font=font(10, "bold"),
            command=self.open_settings,
        )
        self.settings_button.grid(row=0, column=4, rowspan=2)

        self._bulk_buttons.extend([self.refresh_button])

    # ------------------------------------------------------------------ lights
    def _build_lights_panel(self) -> None:
        panel = ctk.CTkFrame(
            self,
            fg_color=COLORS["panel"],
            corner_radius=14,
            border_width=1,
            border_color=COLORS["border"],
        )
        panel.grid(row=1, column=0, sticky="nsew", padx=(18, 7), pady=(2, 10))
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_rowconfigure(3, weight=1)

        head = ctk.CTkFrame(panel, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=14, pady=(13, 0))
        head.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            head,
            text="LUCI",
            font=font(11, "bold"),
            text_color=COLORS["text"],
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        self.lights_count_label = ctk.CTkLabel(
            head,
            text="0",
            font=font(9, "bold"),
            text_color=COLORS["accent"],
            fg_color=COLORS["accent_dark"],
            corner_radius=8,
            width=30,
            height=20,
        )
        self.lights_count_label.grid(row=0, column=1, sticky="e")

        ctk.CTkLabel(
            panel,
            text="Spunta le luci da controllare, oppure usa gli switch rapidi.",
            font=font(9),
            text_color=COLORS["dim"],
            anchor="w",
            justify="left",
            wraplength=300,
        ).grid(row=1, column=0, sticky="w", padx=14, pady=(2, 8))

        self.demo_banner = ctk.CTkFrame(
            panel,
            fg_color=COLORS["warning_dark"],
            corner_radius=9,
            border_width=1,
            border_color="#5a3d16",
        )
        self.demo_banner.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 8))
        self.demo_banner.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            self.demo_banner,
            text="Modalità DEMO: luci e IP finti.",
            font=font(9, "bold"),
            text_color=COLORS["warning"],
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=10, pady=(6, 0))
        ctk.CTkButton(
            self.demo_banner,
            text="Configura",
            width=76,
            height=22,
            corner_radius=6,
            fg_color="transparent",
            hover_color="#4a3616",
            text_color=COLORS["warning"],
            font=font(9, "bold"),
            command=self.open_settings,
        ).grid(row=0, column=1, sticky="e", padx=8, pady=(4, 0))
        ctk.CTkLabel(
            self.demo_banner,
            text="Importa devices.json nelle impostazioni.",
            font=font(8),
            text_color="#c99b55",
            anchor="w",
        ).grid(row=1, column=0, columnspan=2, sticky="w", padx=10, pady=(0, 6))

        self.lights_scroll = ctk.CTkScrollableFrame(
            panel,
            fg_color="transparent",
            scrollbar_fg_color="transparent",
            scrollbar_button_color=COLORS["border"],
            scrollbar_button_hover_color=COLORS["border_light"],
        )
        self.lights_scroll.grid(row=3, column=0, sticky="nsew", padx=(6, 2))
        self.lights_scroll.grid_columnconfigure(0, weight=1)

        footer = ctk.CTkFrame(panel, fg_color="transparent")
        footer.grid(row=4, column=0, sticky="ew", padx=12, pady=(6, 12))
        footer.grid_columnconfigure(0, weight=1)
        footer.grid_columnconfigure(1, weight=1)

        ctk.CTkButton(
            footer,
            text="Seleziona tutte",
            height=24,
            corner_radius=6,
            fg_color="transparent",
            hover_color=COLORS["card_hover"],
            text_color=COLORS["muted"],
            font=font(9),
            command=self.select_all,
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(
            footer,
            text="Nessuna",
            height=24,
            corner_radius=6,
            fg_color="transparent",
            hover_color=COLORS["card_hover"],
            text_color=COLORS["muted"],
            font=font(9),
            command=self.select_none,
        ).grid(row=0, column=1, sticky="e")

        self.master_on_button = ctk.CTkButton(
            footer,
            text="ACCENDI SELEZIONATE",
            height=36,
            corner_radius=8,
            fg_color=COLORS["success_dark"],
            hover_color="#174a35",
            text_color=COLORS["success"],
            font=font(10, "bold"),
            command=lambda: self.power_selected(True),
        )
        self.master_on_button.grid(row=1, column=0, sticky="ew", padx=(0, 4), pady=(6, 4))
        self.master_off_button = ctk.CTkButton(
            footer,
            text="SPEGNI SELEZIONATE",
            height=36,
            corner_radius=8,
            fg_color=COLORS["danger_dark"],
            hover_color="#4d1d29",
            text_color=COLORS["danger"],
            font=font(10, "bold"),
            command=lambda: self.power_selected(False),
        )
        self.master_off_button.grid(row=1, column=1, sticky="ew", padx=(4, 0), pady=(6, 4))

        self.scan_button = ctk.CTkButton(
            footer,
            text="Aggiorna stato",
            height=30,
            corner_radius=7,
            fg_color="transparent",
            border_width=1,
            border_color=COLORS["border"],
            hover_color=COLORS["card_hover"],
            text_color=COLORS["muted"],
            font=font(9, "bold"),
            command=self.refresh_states,
        )
        self.scan_button.grid(row=2, column=0, sticky="ew", padx=(0, 4), pady=(2, 0))
        self.lan_button = ctk.CTkButton(
            footer,
            text="Scansiona IP LAN",
            height=30,
            corner_radius=7,
            fg_color="transparent",
            border_width=1,
            border_color=COLORS["border"],
            hover_color=COLORS["card_hover"],
            text_color=COLORS["muted"],
            font=font(9, "bold"),
            command=self.scan_lan,
        )
        self.lan_button.grid(row=2, column=1, sticky="ew", padx=(4, 0), pady=(2, 0))

        self._bulk_buttons.extend(
            [
                self.scan_button,
                self.lan_button,
                self.master_on_button,
                self.master_off_button,
            ]
        )

    # ---------------------------------------------------------------- controls
    def _build_controls_panel(self) -> None:
        panel = ctk.CTkFrame(
            self,
            fg_color=COLORS["panel"],
            corner_radius=14,
            border_width=1,
            border_color=COLORS["border"],
        )
        panel.grid(row=1, column=1, sticky="nsew", padx=7, pady=(2, 10))
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_rowconfigure(3, weight=1)

        head = ctk.CTkFrame(panel, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=18, pady=(13, 0))
        head.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            head,
            text="CONTROLLO MANUALE",
            font=font(11, "bold"),
            text_color=COLORS["text"],
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            head,
            text="Solo sulle luci spuntate",
            font=font(9),
            text_color=COLORS["dim"],
            anchor="e",
        ).grid(row=0, column=1, sticky="e")
        ctk.CTkLabel(
            panel,
            text="Un unico comando atomico per luce, inviato in parallelo.",
            font=font(9),
            text_color=COLORS["dim"],
            anchor="w",
        ).grid(row=1, column=0, sticky="w", padx=18, pady=(2, 10))

        self.mode_switch = ctk.CTkSegmentedButton(
            panel,
            values=["Bianco", "Colore", "Scena HW", "Flow"],
            height=34,
            corner_radius=8,
            border_width=2,
            fg_color=COLORS["panel_alt"],
            selected_color=COLORS["accent"],
            selected_hover_color=COLORS["accent_hover"],
            unselected_color=COLORS["panel_alt"],
            unselected_hover_color=COLORS["card_hover"],
            text_color=COLORS["text"],
            font=font(10, "bold"),
            command=self._switch_mode,
        )
        self.mode_switch.grid(row=2, column=0, sticky="ew", padx=18, pady=(2, 10))
        self.mode_switch.set("Bianco")

        self.content = ctk.CTkFrame(panel, fg_color="transparent")
        self.content.grid(row=3, column=0, sticky="nsew", padx=18, pady=(0, 8))
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        self.tab_frames: dict[str, ctk.CTkFrame] = {}

        white = self._build_white_tab()
        colour = self._build_colour_tab()
        hardware = self._build_hardware_tab()
        flow = self._build_flow_tab()
        for name, frame in (
            ("Bianco", white),
            ("Colore", colour),
            ("Scena HW", hardware),
            ("Flow", flow),
        ):
            frame.grid(row=0, column=0, sticky="nsew")
            frame.grid_remove()
            self.tab_frames[name] = frame
        white.grid()

        footer = ctk.CTkFrame(panel, fg_color="transparent")
        footer.grid(row=4, column=0, sticky="ew", padx=18, pady=(2, 14))
        footer.grid_columnconfigure(0, weight=1)

        self.apply_selection_label = ctk.CTkLabel(
            footer,
            text="Nessuna luce selezionata",
            font=font(9),
            text_color=COLORS["dim"],
            anchor="w",
        )
        self.apply_selection_label.grid(row=0, column=0, sticky="w", pady=(0, 5))

        self.apply_button = ctk.CTkButton(
            footer,
            text="APPLICA BIANCO",
            height=46,
            corner_radius=9,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            text_color=COLORS["accent_text"],
            font=font(12, "bold"),
            command=self.apply_manual,
        )
        self.apply_button.grid(row=1, column=0, sticky="ew")
        self._bulk_buttons.append(self.apply_button)

    def _build_white_tab(self) -> ctk.CTkFrame:
        tab = ctk.CTkFrame(self.content, fg_color="transparent")
        tab.grid_columnconfigure(0, weight=1)

        card = ctk.CTkFrame(
            tab,
            fg_color=COLORS["card"],
            corner_radius=12,
            border_width=1,
            border_color=COLORS["border"],
        )
        card.grid(row=0, column=0, sticky="new")
        card.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(card, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 0))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header,
            text="LUMINOSITÀ",
            font=font(9, "bold"),
            text_color=COLORS["dim"],
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        self.white_brightness_value = ctk.CTkLabel(
            header,
            text="80%",
            font=font(30, "bold"),
            text_color=COLORS["text"],
            anchor="e",
        )
        self.white_brightness_value.grid(row=0, column=1, sticky="e")

        self.white_slider = ctk.CTkSlider(
            card,
            from_=1,
            to=100,
            number_of_steps=99,
            height=16,
            fg_color=COLORS["border_light"],
            progress_color=COLORS["accent"],
            button_color=COLORS["accent"],
            button_hover_color=COLORS["accent_hover"],
            command=lambda value: self._on_brightness_change(value, "white"),
        )
        self.white_slider.grid(row=1, column=0, sticky="ew", padx=16, pady=(4, 14))
        self.white_slider.set(self.ui_brightness)

        separator = ctk.CTkFrame(card, height=1, fg_color=COLORS["border"])
        separator.grid(row=2, column=0, sticky="ew", padx=16)

        temp_header = ctk.CTkFrame(card, fg_color="transparent")
        temp_header.grid(row=3, column=0, sticky="ew", padx=16, pady=(14, 0))
        temp_header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            temp_header,
            text="TEMPERATURA COLORE",
            font=font(9, "bold"),
            text_color=COLORS["dim"],
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        self.temp_value = ctk.CTkLabel(
            temp_header,
            text="4600 K",
            font=font(16, "bold"),
            text_color=COLORS["text"],
            anchor="e",
        )
        self.temp_value.grid(row=0, column=1, sticky="e")

        self.temp_slider = ctk.CTkSlider(
            card,
            from_=0,
            to=100,
            number_of_steps=100,
            height=16,
            fg_color=COLORS["border_light"],
            progress_color=COLORS["accent"],
            button_color=COLORS["accent"],
            button_hover_color=COLORS["accent_hover"],
            command=self._on_temp_change,
        )
        self.temp_slider.grid(row=4, column=0, sticky="ew", padx=16, pady=(4, 2))
        self.temp_slider.set(self.ui_temp)

        labels = ctk.CTkFrame(card, fg_color="transparent")
        labels.grid(row=5, column=0, sticky="ew", padx=16)
        labels.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            labels,
            text="CALDO · 2700K",
            font=font(8),
            text_color=COLORS["dim"],
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            labels,
            text="FREDDO · 6500K",
            font=font(8),
            text_color=COLORS["dim"],
        ).grid(row=0, column=1, sticky="e")

        self.white_preview = ctk.CTkLabel(
            card,
            text="",
            height=30,
            corner_radius=8,
            fg_color=temp_preview_hex(int(self.ui_temp), int(self.ui_brightness)),
        )
        self.white_preview.grid(row=6, column=0, sticky="ew", padx=16, pady=(12, 6))

        ctk.CTkLabel(
            card,
            text="Il bianco viene inviato con luminosità e temperatura nello stesso payload.",
            font=font(8),
            text_color=COLORS["dim"],
            anchor="w",
        ).grid(row=7, column=0, sticky="w", padx=16, pady=(0, 14))
        return tab

    def _build_colour_tab(self) -> ctk.CTkFrame:
        tab = ctk.CTkFrame(self.content, fg_color="transparent")
        tab.grid_columnconfigure(0, weight=1)

        picker_card = ctk.CTkFrame(
            tab,
            fg_color=COLORS["card"],
            corner_radius=12,
            border_width=1,
            border_color=COLORS["border"],
        )
        picker_card.grid(row=0, column=0, sticky="new")
        ctk.CTkLabel(
            picker_card,
            text="COLORE RGB",
            font=font(9, "bold"),
            text_color=COLORS["dim"],
            anchor="w",
        ).pack(fill="x", padx=16, pady=(12, 6))
        self.picker = ColorPicker(
            picker_card,
            command=self._on_picker_change,
            initial_rgb=self.ui_rgb,
        )
        self.picker.pack(padx=16, pady=(0, 14))

        preset_card = ctk.CTkFrame(
            tab,
            fg_color=COLORS["card"],
            corner_radius=12,
            border_width=1,
            border_color=COLORS["border"],
        )
        preset_card.grid(row=1, column=0, sticky="new", pady=(8, 0))
        preset_card.grid_columnconfigure(0, weight=1)

        preset_head = ctk.CTkFrame(preset_card, fg_color="transparent")
        preset_head.grid(row=0, column=0, sticky="ew", padx=16, pady=(10, 4))
        preset_head.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            preset_head,
            text="PRESET RAPIDI",
            font=font(9, "bold"),
            text_color=COLORS["dim"],
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        self.preset_hint = ctk.CTkLabel(
            preset_head,
            text="",
            font=font(8),
            text_color=COLORS["muted"],
            anchor="e",
        )
        self.preset_hint.grid(row=0, column=1, sticky="e")

        swatches = ctk.CTkFrame(preset_card, fg_color="transparent")
        swatches.grid(row=1, column=0, sticky="w", padx=16, pady=(0, 8))
        for index, (name, color) in enumerate(PRESETS):
            button = ctk.CTkButton(
                swatches,
                text="",
                width=25,
                height=25,
                corner_radius=7,
                fg_color=color,
                hover_color=color,
                border_width=1,
                border_color=COLORS["border_light"],
                command=lambda hex_value=color: self._apply_preset(hex_value),
            )
            button.grid(row=0, column=index, padx=(0, 4))
            button.bind(
                "<Enter>",
                lambda _event, preset=name: self.preset_hint.configure(text=preset),
                add=True,
            )
            button.bind(
                "<Leave>",
                lambda _event: self.preset_hint.configure(text=""),
                add=True,
            )

        bright_head = ctk.CTkFrame(preset_card, fg_color="transparent")
        bright_head.grid(row=2, column=0, sticky="ew", padx=16, pady=(4, 0))
        bright_head.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            bright_head,
            text="LUMINOSITÀ",
            font=font(9, "bold"),
            text_color=COLORS["dim"],
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        self.color_brightness_value = ctk.CTkLabel(
            bright_head,
            text="80%",
            font=font(15, "bold"),
            text_color=COLORS["text"],
            anchor="e",
        )
        self.color_brightness_value.grid(row=0, column=1, sticky="e")

        self.color_slider = ctk.CTkSlider(
            preset_card,
            from_=1,
            to=100,
            number_of_steps=99,
            height=16,
            fg_color=COLORS["border_light"],
            progress_color=COLORS["accent"],
            button_color=COLORS["accent"],
            button_hover_color=COLORS["accent_hover"],
            command=lambda value: self._on_brightness_change(value, "colour"),
        )
        self.color_slider.grid(row=3, column=0, sticky="ew", padx=16, pady=(4, 12))
        self.color_slider.set(self.ui_brightness)
        return tab

    def _build_hardware_tab(self) -> ctk.CTkFrame:
        tab = ctk.CTkFrame(self.content, fg_color="transparent")
        tab.grid_columnconfigure(0, weight=1)

        card = ctk.CTkFrame(
            tab,
            fg_color=COLORS["card"],
            corner_radius=12,
            border_width=1,
            border_color=COLORS["border"],
        )
        card.grid(row=0, column=0, sticky="new")
        card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            card,
            text="SCENE HARDWARE TUYA",
            font=font(9, "bold"),
            text_color=COLORS["dim"],
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(14, 4))
        ctk.CTkLabel(
            card,
            text=(
                "Attiva le scene native del firmware. L'indice 1–4 funziona sulla "
                "maggior parte delle lampadine Type A; per le Type B puoi inviare "
                "anche un payload esadecimale opzionale."
            ),
            font=font(9),
            text_color=COLORS["muted"],
            anchor="w",
            justify="left",
            wraplength=360,
        ).grid(row=1, column=0, sticky="w", padx=16)

        index_row = ctk.CTkFrame(card, fg_color="transparent")
        index_row.grid(row=2, column=0, sticky="ew", padx=16, pady=(14, 6))
        index_row.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            index_row,
            text="INDICE SCENA",
            font=font(9, "bold"),
            text_color=COLORS["dim"],
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        self.hw_scene_menu = ctk.CTkOptionMenu(
            index_row,
            values=[str(value) for value in range(1, 9)],
            width=92,
            height=30,
            corner_radius=8,
            fg_color=COLORS["panel_alt"],
            button_color=COLORS["border"],
            button_hover_color=COLORS["border_light"],
            dropdown_fg_color=COLORS["panel_alt"],
            dropdown_hover_color=COLORS["card_hover"],
            text_color=COLORS["text"],
            font=font(11),
            anchor="center",
        )
        self.hw_scene_menu.grid(row=0, column=1, sticky="e")
        self.hw_scene_menu.set("1")

        ctk.CTkLabel(
            card,
            text="PAYLOAD SCENA (OPZIONALE, TYPE B)",
            font=font(9, "bold"),
            text_color=COLORS["dim"],
            anchor="w",
        ).grid(row=3, column=0, sticky="w", padx=16, pady=(4, 0))
        self.hw_data_entry = ctk.CTkEntry(
            card,
            height=34,
            placeholder_text="solo hex, senza indice",
            fg_color=COLORS["panel_alt"],
            border_color=COLORS["border"],
            font=mono(10),
        )
        self.hw_data_entry.grid(row=4, column=0, sticky="ew", padx=16, pady=(4, 10))

        note = ctk.CTkFrame(
            card,
            fg_color=COLORS["violet_dark"],
            corner_radius=8,
        )
        note.grid(row=5, column=0, sticky="ew", padx=16, pady=(0, 14))
        ctk.CTkLabel(
            note,
            text=(
                "La disponibilità e il significato delle scene dipendono dal modello. "
                "Se una scena non esiste, la lampadina risponde con un errore."
            ),
            font=font(8),
            text_color=COLORS["violet"],
            anchor="w",
            justify="left",
            wraplength=350,
        ).pack(fill="x", padx=10, pady=8)
        return tab

    def _build_flow_tab(self) -> ctk.CTkFrame:
        tab = ctk.CTkFrame(self.content, fg_color="transparent")
        tab.grid_columnconfigure(0, weight=1)

        card = ctk.CTkFrame(
            tab,
            fg_color=COLORS["card"],
            corner_radius=12,
            border_width=1,
            border_color=COLORS["border"],
        )
        card.grid(row=0, column=0, sticky="new")
        card.grid_columnconfigure(0, weight=1)

        head = ctk.CTkFrame(card, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 0))
        head.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            head,
            text="FADE INFINITO",
            font=font(9, "bold"),
            text_color=COLORS["dim"],
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            head,
            text="8 COLORI · LOOP",
            font=font(8, "bold"),
            text_color=COLORS["accent"],
            fg_color=COLORS["accent_dark"],
            corner_radius=6,
            width=92,
            height=20,
        ).grid(row=0, column=1, sticky="e")

        ctk.CTkLabel(
            card,
            text=(
                "Il fade è generato dal PC e inviato in tempo reale. "
                "La fluidità dipende dal firmware della lampadina."
            ),
            font=font(9),
            text_color=COLORS["muted"],
            anchor="w",
            justify="left",
            wraplength=350,
        ).grid(row=1, column=0, sticky="w", padx=16, pady=(2, 10))

        palette_head = ctk.CTkFrame(card, fg_color="transparent")
        palette_head.grid(row=2, column=0, sticky="ew", padx=16)
        palette_head.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            palette_head,
            text="PALETTE",
            font=font(9, "bold"),
            text_color=COLORS["dim"],
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            palette_head,
            text="clicca un colore per modificarlo",
            font=font(8),
            text_color=COLORS["dim"],
            anchor="e",
        ).grid(row=0, column=1, sticky="e")

        swatch_frame = ctk.CTkFrame(card, fg_color="transparent")
        swatch_frame.grid(row=3, column=0, sticky="w", padx=16, pady=(5, 8))
        self.flow_swatches: list[ctk.CTkButton] = []
        for index in range(8):
            color = self.flow_config.palette[index]
            button = ctk.CTkButton(
                swatch_frame,
                text="",
                width=28,
                height=28,
                corner_radius=8,
                fg_color=color,
                hover_color=color,
                border_width=1,
                border_color=COLORS["border_light"],
                command=lambda selected=index: self._edit_palette_color(selected),
            )
            button.grid(row=0, column=index, padx=(0, 5))
            self.flow_swatches.append(button)

        presets = ctk.CTkFrame(card, fg_color="transparent")
        presets.grid(row=4, column=0, sticky="ew", padx=16)
        for index, name in enumerate(FLOW_PRESETS):
            ctk.CTkButton(
                presets,
                text=name,
                width=72,
                height=23,
                corner_radius=6,
                fg_color=COLORS["panel_alt"],
                border_width=1,
                border_color=COLORS["border"],
                hover_color=COLORS["card_hover"],
                text_color=COLORS["muted"],
                font=font(8),
                command=lambda value=name: self._apply_flow_preset(value),
            ).grid(row=0, column=index, padx=(0, 5))

        speed_head = ctk.CTkFrame(card, fg_color="transparent")
        speed_head.grid(row=5, column=0, sticky="ew", padx=16, pady=(12, 0))
        speed_head.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            speed_head,
            text="VELOCITÀ · SECONDI PER TRANSAZIONE",
            font=font(9, "bold"),
            text_color=COLORS["dim"],
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        self.flow_speed_label = ctk.CTkLabel(
            speed_head,
            text="2.5 s",
            font=font(15, "bold"),
            text_color=COLORS["text"],
            anchor="e",
        )
        self.flow_speed_label.grid(row=0, column=1, sticky="e")

        self.flow_speed_slider = ctk.CTkSlider(
            card,
            from_=0.5,
            to=5.0,
            number_of_steps=45,
            height=16,
            fg_color=COLORS["border_light"],
            progress_color=COLORS["accent"],
            button_color=COLORS["accent"],
            button_hover_color=COLORS["accent_hover"],
            command=self._on_flow_speed,
        )
        self.flow_speed_slider.grid(row=6, column=0, sticky="ew", padx=16, pady=(4, 10))
        self.flow_speed_slider.set(self.flow_config.segment_seconds)

        options = ctk.CTkFrame(card, fg_color="transparent")
        options.grid(row=7, column=0, sticky="ew", padx=16)
        options.grid_columnconfigure(0, weight=1)

        fps_box = ctk.CTkFrame(options, fg_color="transparent")
        fps_box.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            fps_box,
            text="FPS",
            font=font(8, "bold"),
            text_color=COLORS["dim"],
            anchor="w",
        ).pack(side="left", padx=(0, 6))
        self.flow_fps_switch = ctk.CTkSegmentedButton(
            fps_box,
            values=["6", "10", "15"],
            height=26,
            corner_radius=6,
            border_width=2,
            fg_color=COLORS["panel_alt"],
            selected_color=COLORS["accent"],
            selected_hover_color=COLORS["accent_hover"],
            unselected_color=COLORS["panel_alt"],
            unselected_hover_color=COLORS["card_hover"],
            text_color=COLORS["text"],
            font=font(9, "bold"),
            command=self._on_flow_option,
        )
        self.flow_fps_switch.pack(side="left")
        self.flow_fps_switch.set(str(self.flow_config.fps))

        self.flow_phase_var = tk.BooleanVar(value=self.flow_config.phase_offset)
        self.flow_phase_switch = ctk.CTkSwitch(
            options,
            text="Sfasamento luci",
            width=130,
            switch_width=32,
            switch_height=16,
            fg_color=COLORS["border_light"],
            progress_color=COLORS["accent"],
            button_color=COLORS["text"],
            button_hover_color=COLORS["text"],
            text_color=COLORS["muted"],
            font=font(8),
            variable=self.flow_phase_var,
            command=self._on_flow_option,
        )
        self.flow_phase_switch.grid(row=0, column=1, sticky="e")

        bright_head = ctk.CTkFrame(card, fg_color="transparent")
        bright_head.grid(row=8, column=0, sticky="ew", padx=16, pady=(10, 0))
        bright_head.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            bright_head,
            text="LUMINOSITÀ",
            font=font(9, "bold"),
            text_color=COLORS["dim"],
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        self.flow_brightness_value = ctk.CTkLabel(
            bright_head,
            text=f"{int(round(self.ui_brightness))}%",
            font=font(14, "bold"),
            text_color=COLORS["text"],
            anchor="e",
        )
        self.flow_brightness_value.grid(row=0, column=1, sticky="e")

        self.flow_slider = ctk.CTkSlider(
            card,
            from_=1,
            to=100,
            number_of_steps=99,
            height=16,
            fg_color=COLORS["border_light"],
            progress_color=COLORS["accent"],
            button_color=COLORS["accent"],
            button_hover_color=COLORS["accent_hover"],
            command=lambda value: self._on_brightness_change(value, "flow"),
        )
        self.flow_slider.grid(row=9, column=0, sticky="ew", padx=16, pady=(4, 8))
        self.flow_slider.set(self.ui_brightness)

        footer = ctk.CTkFrame(card, fg_color="transparent")
        footer.grid(row=10, column=0, sticky="ew", padx=16, pady=(0, 14))
        footer.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            footer,
            text="Usa AVVIA FLOW in basso. Lo stop è sempre in barra di stato.",
            font=font(8),
            text_color=COLORS["dim"],
            anchor="w",
            wraplength=230,
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(
            footer,
            text="Salva scena Flow",
            width=126,
            height=30,
            corner_radius=7,
            fg_color="transparent",
            border_width=1,
            border_color=COLORS["border_light"],
            hover_color=COLORS["card_hover"],
            text_color=COLORS["accent"],
            font=font(9, "bold"),
            command=lambda: self.new_scene(SCENE_FLOW),
        ).grid(row=0, column=1, sticky="e")
        return tab

    # ------------------------------------------------------------------ scenes
    def _build_scenes_panel(self) -> None:
        panel = ctk.CTkFrame(
            self,
            fg_color=COLORS["panel"],
            corner_radius=14,
            border_width=1,
            border_color=COLORS["border"],
        )
        panel.grid(row=1, column=2, sticky="nsew", padx=(7, 18), pady=(2, 10))
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_rowconfigure(2, weight=1)

        head = ctk.CTkFrame(panel, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=14, pady=(13, 0))
        head.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            head,
            text="SCENE STUDIO",
            font=font(11, "bold"),
            text_color=COLORS["text"],
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        self.scene_count_label = ctk.CTkLabel(
            head,
            text="0",
            font=font(9, "bold"),
            text_color=COLORS["violet"],
            fg_color=COLORS["violet_dark"],
            corner_radius=8,
            width=28,
            height=20,
        )
        self.scene_count_label.grid(row=0, column=1, padx=(0, 8))
        ctk.CTkButton(
            head,
            text="＋ Nuova",
            width=88,
            height=28,
            corner_radius=7,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            text_color=COLORS["accent_text"],
            font=font(9, "bold"),
            command=self.new_scene,
        ).grid(row=0, column=2, sticky="e")

        ctk.CTkLabel(
            panel,
            text="Un clic per accendere l'atmosfera. Scena globale o snapshot multi-luce.",
            font=font(9),
            text_color=COLORS["dim"],
            anchor="w",
            justify="left",
            wraplength=390,
        ).grid(row=1, column=0, sticky="w", padx=14, pady=(2, 8))

        self.scenes_scroll = ctk.CTkScrollableFrame(
            panel,
            fg_color="transparent",
            scrollbar_fg_color="transparent",
            scrollbar_button_color=COLORS["border"],
            scrollbar_button_hover_color=COLORS["border_light"],
        )
        self.scenes_scroll.grid(row=2, column=0, sticky="nsew", padx=(6, 2))
        self.scenes_scroll.grid_columnconfigure(0, weight=1)
        self.scenes_scroll.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            panel,
            text="Click sulla card per applicare  ·  ⋯ per sovrascrivere o eliminare",
            font=font(8),
            text_color=COLORS["dim"],
            anchor="w",
        ).grid(row=3, column=0, sticky="w", padx=14, pady=(4, 12))

    def _build_statusbar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=2, column=0, columnspan=3, sticky="ew", padx=20, pady=(0, 12))
        bar.grid_columnconfigure(1, weight=1)

        self.status_dot = ctk.CTkFrame(
            bar,
            width=7,
            height=7,
            corner_radius=4,
            fg_color=COLORS["muted"],
        )
        self.status_dot.grid(row=0, column=0, padx=(2, 8))
        self.status_dot.grid_propagate(False)

        self.status_label = ctk.CTkLabel(
            bar,
            text="Pronto.",
            font=font(9),
            text_color=COLORS["muted"],
            anchor="w",
            justify="left",
        )
        self.status_label.grid(row=0, column=1, sticky="w")

        self.flow_stop_button = ctk.CTkButton(
            bar,
            text="■ STOP FLOW",
            width=102,
            height=24,
            corner_radius=6,
            fg_color=COLORS["danger_dark"],
            hover_color="#4d1d29",
            text_color=COLORS["danger"],
            font=font(9, "bold"),
            command=self.stop_flow,
        )
        self.flow_stop_button.grid(row=0, column=2, sticky="e", padx=(8, 10))
        self.flow_stop_button.grid_remove()

        self.latency_label = ctk.CTkLabel(
            bar,
            text="",
            font=mono(9),
            text_color=COLORS["dim"],
            anchor="e",
        )
        self.latency_label.grid(row=0, column=3, sticky="e", padx=(0, 2))

    # ==================================================================== data
    def _startup(self) -> None:
        if self._closing:
            return
        if not self.devices:
            self._set_status("Nessuna luce configurata: apri Impostazioni.", "warning")
            return
        if self.demo:
            self._set_status(
                "Modalità demo: importa devices.json o configura le tue luci.", "warning"
            )
            self._update_online_chip()
            return
        self.refresh_states(silent=True)

    def _find_device(self, device_id: str) -> LightDevice | None:
        return next((device for device in self.devices if device.id == device_id), None)

    def _selected_ids(self) -> list[str]:
        return [
            device.id
            for device in self.devices
            if device.id in self.rows and self.rows[device.id].selected
        ]

    def _selected_names(self) -> list[str]:
        return [device.name for device in self.devices if device.id in self._selected_ids()]

    def _manual_state(self) -> LightState:
        brightness = max(1, min(100, int(round(self.ui_brightness))))
        if self._mode == "Colore":
            return LightState(
                power=True,
                mode="colour",
                brightness=brightness,
                colortemp=int(round(self.ui_temp)),
                rgb=self.ui_rgb,
            )
        if self._mode == "Scena HW":
            data = self.hw_data_entry.get().strip() or None
            try:
                scene_index = int(self.hw_scene_menu.get())
            except ValueError:
                scene_index = 1
            return LightState(
                power=True,
                mode="scene",
                brightness=brightness,
                colortemp=int(round(self.ui_temp)),
                rgb=self.ui_rgb,
                hw_scene=scene_index,
                hw_data=data,
            )
        return LightState(
            power=True,
            mode="white",
            brightness=brightness,
            colortemp=int(round(self.ui_temp)),
            rgb=self.ui_rgb,
        )

    def _apply_editor_state(self, state: LightState, *, switch_tab: bool = True) -> None:
        self._syncing = True
        self.ui_brightness = float(state.brightness)
        self.ui_temp = float(state.colortemp)
        self.ui_rgb = state.rgb
        self.white_slider.set(state.brightness)
        self.color_slider.set(state.brightness)
        self.temp_slider.set(state.colortemp)
        self.picker.set_rgb(state.rgb, emit=False)
        self._syncing = False
        self._update_editor_labels()

        if not switch_tab:
            return
        if state.hw_scene is not None:
            target = "Scena HW"
            self.hw_scene_menu.set(str(min(8, max(1, state.hw_scene))))
            self.hw_data_entry.delete(0, "end")
            if state.hw_data:
                self.hw_data_entry.insert(0, state.hw_data)
        elif state.mode == "colour":
            target = "Colore"
        else:
            target = "Bianco"
        self.mode_switch.set(target)
        self._switch_mode(target)

    # ================================================================= editor
    def _on_brightness_change(self, value: float, source: str) -> None:
        self.ui_brightness = max(1.0, min(100.0, float(value)))
        self._update_editor_labels()
        if self._syncing:
            return
        self._syncing = True
        for name, slider in (
            ("white", self.white_slider),
            ("colour", self.color_slider),
            ("flow", self.flow_slider),
        ):
            if name != source:
                slider.set(self.ui_brightness)
        self._syncing = False
        if self._flow_running:
            self.flow_runner.update_config(self._flow_config_from_ui())

    def _on_temp_change(self, value: float) -> None:
        self.ui_temp = max(0.0, min(100.0, float(value)))
        self._update_editor_labels()

    def _on_picker_change(self, rgb: tuple[int, int, int]) -> None:
        self.ui_rgb = rgb

    def _update_editor_labels(self) -> None:
        brightness = int(round(self.ui_brightness))
        temp = int(round(self.ui_temp))
        self.white_brightness_value.configure(text=f"{brightness}%")
        self.color_brightness_value.configure(text=f"{brightness}%")
        if hasattr(self, "flow_brightness_value"):
            self.flow_brightness_value.configure(text=f"{brightness}%")
        self.temp_value.configure(text=f"{kelvin_from_temp(temp)} K")
        self.white_preview.configure(fg_color=temp_preview_hex(temp, brightness))

    def _switch_mode(self, value: str) -> None:
        self._mode = value if value in self.tab_frames else "Bianco"
        for name, frame in self.tab_frames.items():
            if name == self._mode:
                frame.grid()
            else:
                frame.grid_remove()
        self._update_apply_button_label()
        self._update_selection_ui()

    def _update_apply_button_label(self) -> None:
        if not hasattr(self, "apply_button"):
            return
        if self._busy:
            text = "INVIO…"
        elif self._mode == "Flow":
            text = "FERMA FLOW" if self._flow_running else "AVVIA FLOW"
        else:
            text = MODE_LABELS.get(self._mode, MODE_LABELS["Bianco"])[0]
        self.apply_button.configure(text=text)

    def _apply_preset(self, hex_value: str) -> None:
        rgb = hex_to_rgb(hex_value)
        if rgb:
            self.picker.set_rgb(rgb, emit=True)

    # ================================================================== flow UI
    def _flow_config_from_ui(self) -> FlowConfig:
        try:
            fps = int(self.flow_fps_switch.get())
        except (ValueError, AttributeError):
            fps = self.flow_config.fps
        try:
            speed = float(self.flow_speed_slider.get())
        except (ValueError, AttributeError):
            speed = self.flow_config.segment_seconds
        return FlowConfig(
            palette=list(self.flow_config.palette),
            segment_seconds=speed,
            fps=fps,
            phase_offset=bool(self.flow_phase_var.get()),
            brightness=int(round(self.ui_brightness)),
        )

    def _push_flow_config(self) -> None:
        if self._flow_running:
            self.flow_runner.update_config(self._flow_config_from_ui())

    def _on_flow_speed(self, value: float) -> None:
        self.flow_speed_label.configure(text=f"{float(value):.1f} s")
        self.flow_config = self._flow_config_from_ui()
        self._push_flow_config()

    def _on_flow_option(self, *_args: Any) -> None:
        self.flow_config = self._flow_config_from_ui()
        self._push_flow_config()

    def _refresh_flow_swatches(self) -> None:
        for index, button in enumerate(self.flow_swatches):
            color = self.flow_config.palette[index]
            button.configure(fg_color=color, hover_color=color)

    def _edit_palette_color(self, index: int) -> None:
        current = hex_to_rgb(self.flow_config.palette[index]) or (255, 255, 255)
        result = ColorPickerDialog.ask(
            self, f"Colore {index + 1} della palette", current
        )
        if result is None:
            return
        base = self._flow_config_from_ui()
        palette = list(base.palette)
        palette[index] = rgb_to_hex(result)
        self.flow_config = FlowConfig(
            palette=palette,
            segment_seconds=base.segment_seconds,
            fps=base.fps,
            phase_offset=base.phase_offset,
            brightness=base.brightness,
        )
        self._refresh_flow_swatches()
        self._push_flow_config()

    def _apply_flow_preset(self, name: str) -> None:
        palette = FLOW_PRESETS.get(name)
        if palette is None:
            return
        base = self._flow_config_from_ui()
        self.flow_config = FlowConfig(
            palette=list(palette),
            segment_seconds=base.segment_seconds,
            fps=base.fps,
            phase_offset=base.phase_offset,
            brightness=base.brightness,
        )
        self._refresh_flow_swatches()
        self._push_flow_config()
        self._set_status(f"Palette «{name}» caricata.", "muted")

    def _sync_flow_ui_from_config(
        self, config: FlowConfig, *, sync_brightness: bool = True
    ) -> None:
        self.flow_config = config.copy()
        if sync_brightness:
            self.ui_brightness = float(self.flow_config.brightness)
        self._syncing = True
        self.flow_speed_slider.set(self.flow_config.segment_seconds)
        self.flow_speed_label.configure(text=f"{self.flow_config.segment_seconds:.1f} s")
        fps_value = str(self.flow_config.fps)
        if fps_value not in ("6", "10", "15"):
            fps_value = "10"
        self.flow_fps_switch.set(fps_value)
        self.flow_phase_var.set(self.flow_config.phase_offset)
        if sync_brightness:
            self.white_slider.set(self.ui_brightness)
            self.color_slider.set(self.ui_brightness)
            self.flow_slider.set(self.ui_brightness)
        self._syncing = False
        self._refresh_flow_swatches()
        self._update_editor_labels()
        self._push_flow_config()

    def _toggle_flow(self) -> None:
        if self._flow_running:
            self.stop_flow()
            return
        if self._busy:
            self._set_status("Attendi la fine del comando in corso.", "warning")
            return
        selected = [
            device for device in self.devices if device.id in set(self._selected_ids())
        ]
        if not selected:
            self._set_status("Seleziona almeno una luce per avviare il flow.", "warning")
            return

        config = self._flow_config_from_ui()
        self.flow_config = config
        targets: dict[str, LightState] = {}
        for index, device in enumerate(selected):
            position = 0.0
            if config.phase_offset and len(selected) > 1:
                position = index / len(selected)
            targets[device.id] = LightState(
                power=True,
                mode="colour",
                brightness=config.brightness,
                rgb=config.colour_at(position),
            )

        self._flow_devices = selected
        self._bulk_apply(
            targets,
            "Flow",
            after_success=lambda report: self._begin_flow(report, selected, config),
        )

    def _begin_flow(
        self,
        report: OperationReport,
        devices: list[LightDevice],
        config: FlowConfig,
    ) -> None:
        successful = {result.device_id for result in report.results if result.ok}
        active = [device for device in devices if device.id in successful]
        if not active:
            self._set_status("Flow non avviato: nessuna luce raggiungibile.", "danger")
            return

        self.flow_runner.start(active, config)
        self._flow_running = True
        self._flow_devices = active
        self._update_flow_ui_running()
        self._update_selection_ui()
        failures = len(devices) - len(active)
        message = f"FLOW attivo · {len(active)} luci · {config.summary}"
        if failures:
            message += f" · {failures} non raggiungibili"
        self._set_status(message, "success" if not failures else "warning")

    def stop_flow(self, announce: bool = True) -> None:
        if not self._flow_running:
            return
        last_colors = self.flow_runner.stop()
        failed = self.flow_runner.failed_ids
        self._flow_running = False
        self._flow_devices = []
        for device_id in failed:
            self.health[device_id] = False

        for device_id, rgb in last_colors.items():
            state = self.states.get(device_id)
            if state is None:
                continue
            self.states[device_id] = state.copy(
                power=True,
                mode="colour",
                rgb=rgb,
                brightness=int(round(self.ui_brightness)),
            )
            row = self.rows.get(device_id)
            if row is not None:
                row.set_state(self.states[device_id], self.health.get(device_id))

        self._update_flow_ui_running()
        self._update_selection_ui()
        self._schedule_save()
        if announce:
            message = "■ Flow fermato · ultima tinta mantenuta"
            if failed:
                message += f" · {len(failed)} luci offline"
            self._set_status(message, "warning" if failed else "muted")

    def _update_flow_ui_running(self) -> None:
        if self._flow_running:
            self.flow_stop_button.grid()
        else:
            self.flow_stop_button.grid_remove()
        self._update_apply_button_label()

    # ================================================================ commands
    def _set_status(self, text: str, level: str = "muted") -> None:
        color = STATUS_COLORS.get(level, COLORS["muted"])
        self.status_label.configure(text=text, text_color=color)
        self.status_dot.configure(fg_color=color)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        for button in self._bulk_buttons:
            try:
                button.configure(state=state)
            except tk.TclError:
                pass
        if busy:
            self.apply_button.configure(text="INVIO…")
        else:
            self._switch_mode(self._mode)
    def refresh_states(self, silent: bool = False) -> None:
        if self._busy or self._refresh_running or self._closing:
            return
        if not self.devices:
            self._set_status("Nessuna luce configurata: apri Impostazioni.", "warning")
            return

        self._refresh_running = True
        self.refresh_button.configure(state="disabled")
        self.scan_button.configure(state="disabled")
        if not silent:
            self._set_status("Lettura dello stato dalle luci…", "muted")

        def job() -> OperationReport:
            return self.controller.refresh(self.devices, self.states)

        def done(report: OperationReport) -> None:
            self._refresh_running = False
            if self._closing:
                return
            self.refresh_button.configure(state="normal")
            self.scan_button.configure(state="normal")
            self._finish_report(report, silent=silent)

        def failed(exc: Exception) -> None:
            self._refresh_running = False
            if self._closing:
                return
            self.refresh_button.configure(state="normal")
            self.scan_button.configure(state="normal")
            LOGGER.exception("Refresh fallito")
            self._set_status(f"Errore durante la lettura: {exc}", "danger")

        self.submit(job, done, failed)

    def _finish_report(self, report: OperationReport, *, silent: bool = False) -> None:
        for result in report.results:
            if result.ok:
                if result.state is not None:
                    self.states[result.device_id] = result.state
                self.health[result.device_id] = True
            elif result.kind in (ERROR_OFFLINE, ERROR_AUTH):
                self.health[result.device_id] = False
            row = self.rows.get(result.device_id)
            if row is not None:
                row.set_state(
                    self.states.get(result.device_id, LightState()),
                    self.health.get(result.device_id),
                )

        self._update_online_chip()
        self._schedule_save()
        self.latency_label.configure(text=format_ms(report.elapsed_ms) if report.results else "")

        if not report.results:
            self._set_status("Nessuna luce coinvolta.", "muted")
            return
        if report.total == 1:
            result = report.results[0]
            if result.ok:
                summary = f" · {result.state.summary()}" if result.state else ""
                self._set_status(
                    f"✓ {result.name}{summary} · {format_ms(report.elapsed_ms)}",
                    "success",
                )
            else:
                self._set_status(
                    f"✕ {result.name} · {result.error or 'nessuna risposta'}",
                    "danger",
                )
            return
        if report.all_ok:
            self._set_status(
                f"✓ {report.action} · {report.success_count} luci · {format_ms(report.elapsed_ms)}",
                "success",
            )
        elif report.success_count:
            self._set_status(
                f"⚠ {report.action} · {report.success_count}/{report.total} · "
                f"{report.failure_hint()}",
                "warning",
            )
        else:
            self._set_status(
                f"✕ {report.action} · {report.failure_hint() or 'nessuna risposta'}",
                "danger",
            )

    def _bulk_apply(
        self,
        targets: dict[str, LightState],
        action: str,
        *,
        after_success: Callable[[OperationReport], None] | None = None,
    ) -> bool:
        if self._closing:
            return False
        if self._busy:
            self._set_status("Operazione già in corso…", "warning")
            return False
        if not targets:
            self._set_status("Nessuna luce coinvolta.", "warning")
            return False

        self._set_busy(True)
        self._set_status(f"{action} · invio a {len(targets)} luci…", "muted")

        def job() -> OperationReport:
            return self.controller.apply_states(targets, action)

        def done(report: OperationReport) -> None:
            if self._closing:
                return
            self._set_busy(False)
            self._finish_report(report)
            if report.success_count and after_success:
                after_success(report)

        def failed(exc: Exception) -> None:
            if self._closing:
                return
            self._set_busy(False)
            LOGGER.exception("Comando fallito")
            self._set_status(f"Errore: {exc}", "danger")

        self.submit(job, done, failed)
        return True

    def apply_manual(self) -> None:
        if self._mode == "Flow":
            self._toggle_flow()
            return
        selected = self._selected_ids()
        if not selected:
            self._set_status("Seleziona almeno una luce con le checkbox.", "warning")
            return
        if self._flow_running:
            self.stop_flow(announce=False)
        state = self._manual_state()
        action = {
            "Bianco": "Bianco applicato",
            "Colore": "Colore applicato",
            "Scena HW": "Scena hardware",
        }.get(self._mode, "Comando")
        self._bulk_apply({device_id: state.copy() for device_id in selected}, action)

    def power_selected(self, power: bool) -> None:
        selected = self._selected_ids()
        if not selected:
            self._set_status("Seleziona almeno una luce.", "warning")
            return
        if self._flow_running:
            self.stop_flow(announce=False)
        targets = {
            device_id: self.states.get(device_id, LightState()).copy(power=power)
            for device_id in selected
        }
        self._bulk_apply(targets, "Accensione" if power else "Spegnimento")

    def _on_light_power(self, device_id: str, power: bool) -> None:
        device = self._find_device(device_id)
        if device is None:
            return
        if self._flow_running:
            self.stop_flow(announce=False)
        old_state = self.states.get(device_id, LightState())
        new_state = old_state.copy(power=power)
        self.states[device_id] = new_state
        row = self.rows.get(device_id)
        if row is not None:
            row.set_state(new_state, self.health.get(device_id))
        self._set_status(
            f"{'Accensione' if power else 'Spegnimento'} {device.name}…", "muted"
        )

        def job() -> OperationReport:
            return self.controller.apply_states(
                {device_id: new_state}, "Accensione" if power else "Spegnimento"
            )

        def done(report: OperationReport) -> None:
            if self._closing:
                return
            self._finish_report(report)
            if not report.success_count:
                self.states[device_id] = old_state
                if row is not None:
                    row.set_state(old_state, self.health.get(device_id))

        def failed(exc: Exception) -> None:
            if self._closing:
                return
            self.states[device_id] = old_state
            if row is not None:
                row.set_state(old_state, self.health.get(device_id))
            LOGGER.exception("Toggle luce fallito")
            self._set_status(f"Errore: {exc}", "danger")

        self.submit(job, done, failed)

    # ================================================================== scenes
    def new_scene(self, default_type: str = SCENE_GLOBAL) -> None:
        selected_names = self._selected_names()
        dialog = SceneDialog(
            self,
            selected_names=selected_names,
            existing_type=default_type,
            global_summary=self._manual_state().summary(),
            flow_summary=self._flow_config_from_ui().summary,
        )
        dialog.wait_window()
        if not dialog.result_name:
            return
        name = dialog.result_name
        scene_type = dialog.result_type or default_type
        existing = self._find_scene_by_name(name)
        if existing is not None:
            if not ConfirmDialog.ask(
                self,
                "Sovrascrivere la scena?",
                f"Esiste già una scena chiamata «{existing.name}». Vuoi sostituirla?",
                confirm="Sovrascrivi",
            ):
                return
        self._store_scene(name, scene_type, existing)

    def _store_scene(
        self, name: str, scene_type: str, existing: Scene | None
    ) -> None:
        selected = self._selected_ids()
        if scene_type == SCENE_SNAPSHOT and not selected:
            self._set_status("Uno snapshot richiede almeno una luce selezionata.", "warning")
            return

        scene = existing or Scene(name=name, type=scene_type)
        scene.name = name
        scene.type = scene_type
        scene.demo = False
        scene.updated_at = utc_now_iso()
        if scene_type == SCENE_FLOW:
            scene.flow = self._flow_config_from_ui().copy()
            scene.state = None
            scene.lights = {}
        elif scene_type == SCENE_GLOBAL:
            scene.flow = None
            scene.state = self._manual_state()
            scene.lights = {}
        else:
            scene.flow = None
            scene.lights = {
                device_id: self.states.get(device_id, LightState()).copy()
                for device_id in selected
            }
            scene.state = next(iter(scene.lights.values())).copy()

        if existing is None:
            self.scenes.append(scene)
        self._save_scenes()
        self._rebuild_scenes()
        self._set_status(f"✓ Scena «{scene.name}» salvata.", "success")

    def overwrite_scene(self, scene: Scene) -> None:
        if scene.is_flow:
            detail = "palette e velocità del tab Flow"
        elif scene.is_global:
            detail = "controlli manuali"
        else:
            detail = "luci selezionate"
        if not ConfirmDialog.ask(
            self,
            "Sovrascrivere la scena?",
            f"«{scene.name}» verrà aggiornata con {detail}.",
            confirm="Sovrascrivi",
        ):
            return
        self._store_scene(scene.name, scene.type, scene)

    def delete_scene(self, scene: Scene) -> None:
        if not ConfirmDialog.ask(
            self,
            "Eliminare la scena?",
            f"«{scene.name}» verrà rimossa definitivamente.",
            confirm="Elimina",
            danger=True,
        ):
            return
        self.scenes = [item for item in self.scenes if item.id != scene.id]
        self._save_scenes()
        self._rebuild_scenes()
        self._set_status(f"Scena «{scene.name}» eliminata.", "muted")

    def _find_scene_by_name(self, name: str) -> Scene | None:
        return next(
            (scene for scene in self.scenes if scene.name.casefold() == name.casefold()),
            None,
        )

    def _show_scene_menu(self, scene: Scene) -> None:
        menu = tk.Menu(
            self,
            tearoff=0,
            bg=COLORS["panel_alt"],
            fg=COLORS["text"],
            activebackground=COLORS["accent"],
            activeforeground=COLORS["accent_text"],
            bd=0,
            relief="flat",
            font=font(10),
        )
        menu.add_command(label="Applica scena", command=lambda: self.apply_scene(scene))
        menu.add_separator()
        menu.add_command(
            label="Sovrascrivi con lo stato attuale",
            command=lambda: self.overwrite_scene(scene),
        )
        menu.add_command(
            label="Elimina scena", foreground=COLORS["danger"], command=lambda: self.delete_scene(scene)
        )
        try:
            menu.tk_popup(self.winfo_pointerx(), self.winfo_pointery())
        finally:
            menu.grab_release()

    def apply_scene(self, scene: Scene) -> None:
        if self._closing:
            return
        if self._busy:
            self._set_status("Operazione già in corso…", "warning")
            return
        if not self.devices:
            self._set_status("Nessuna luce configurata.", "warning")
            return

        if scene.is_flow:
            selected = self._selected_ids()
            if not selected:
                self._set_status(
                    "Seleziona le luci su cui avviare il Flow.", "warning"
                )
                return
            if self._flow_running:
                self.stop_flow(announce=False)
            self.flow_config = (scene.flow or FlowConfig()).copy()
            self._sync_flow_ui_from_config(self.flow_config)
            self.mode_switch.set("Flow")
            self._switch_mode("Flow")
            self._toggle_flow()
            return

        if self._flow_running:
            self.stop_flow(announce=False)

        action = f"Scena «{scene.name}»"
        if scene.is_global:
            selected = self._selected_ids()
            if not selected:
                self._set_status("Seleziona le luci a cui applicare la scena.", "warning")
                return
            state = (scene.state or LightState()).copy()
            targets = {device_id: state.copy() for device_id in selected}
        else:
            available = {
                device_id: state.copy()
                for device_id, state in scene.lights.items()
                if any(device.id == device_id for device in self.devices)
            }
            if available:
                targets = available
                self._select_only(list(available))
            elif scene.demo and self._selected_ids():
                chosen = self._selected_ids()
                ordered = list(scene.lights.values())
                targets = {
                    device_id: ordered[index].copy()
                    for index, device_id in enumerate(chosen[: len(ordered)])
                }
                self._select_only(list(targets))
                action = f"Scena «{scene.name}» (demo)"
            else:
                self._set_status(
                    "Questa scena fa riferimento a luci non più configurate.", "danger"
                )
                return

        preview_state = next(iter(targets.values()))

        def after(report: OperationReport) -> None:
            if scene.is_global and scene.state is not None:
                self._apply_editor_state(scene.state)
            elif preview_state is not None:
                self._apply_editor_state(preview_state)

        self._bulk_apply(targets, action, after_success=after)

    # ================================================================ settings
    def open_settings(self) -> None:
        if self.settings_window is not None and self.settings_window.winfo_exists():
            self.settings_window.lift()
            self.settings_window.focus_force()
            return
        self.settings_window = SettingsWindow(self, self)

    def device_id_exists(self, device_id: str, exclude: str | None = None) -> bool:
        return any(
            device.id == device_id and device.id != exclude for device in self.devices
        )

    def upsert_light(self, device: LightDevice, original_id: str | None = None) -> None:
        old_id = original_id or device.id
        if original_id and original_id != device.id:
            if original_id in self.states:
                self.states[device.id] = self.states.pop(original_id)
            self.health.pop(original_id, None)
            self.health.setdefault(device.id, None)
            for scene in self.scenes:
                if original_id in scene.lights:
                    scene.lights[device.id] = scene.lights.pop(original_id)
            self._save_scenes()
        else:
            self.states.setdefault(device.id, LightState())
            self.health.setdefault(device.id, None)

        index = next(
            (position for position, item in enumerate(self.devices) if item.id == old_id),
            None,
        )
        if index is None:
            self.devices.append(device)
        else:
            self.devices[index] = device

        self.demo = False
        self._after_config_change()
        self._set_status(f"✓ Luce «{device.name}» salvata.", "success")

    def delete_light(self, device_id: str) -> None:
        self.devices = [device for device in self.devices if device.id != device_id]
        self.states.pop(device_id, None)
        self.health.pop(device_id, None)
        for scene in self.scenes:
            scene.lights.pop(device_id, None)
        self.demo = False
        if not self.devices:
            self.demo = False
        self._save_scenes()
        self._after_config_change()
        self._set_status("Luce eliminata dalla configurazione.", "muted")

    def clear_demo_lights(self) -> None:
        self.devices = []
        self.states = {}
        self.health = {}
        self.demo = False
        self._after_config_change()
        self._set_status("Configurazione demo rimossa: aggiungi le tue luci.", "muted")

    def import_devices(self) -> tuple[int, list[str]]:
        imported, warnings = self.store.import_devices_json()
        if not imported:
            return 0, warnings

        if self.demo:
            self.devices = []
            self.states = {}
            self.health = {}

        by_id = {device.id: device for device in self.devices}
        for new_device in imported:
            existing = by_id.get(new_device.id)
            if existing is not None:
                index = self.devices.index(existing)
                self.devices[index] = new_device
            else:
                self.devices.append(new_device)
            self.states.setdefault(new_device.id, LightState())
            self.health.setdefault(new_device.id, None)
            by_id[new_device.id] = new_device

        self.demo = False
        self._after_config_change()
        self._set_status(f"✓ Importate {len(imported)} luci da devices.json.", "success")
        return len(imported), warnings

    def _after_config_change(self) -> None:
        if self._flow_running:
            self.stop_flow(announce=False)
        self._save_now()
        self.controller.sync_devices(self.devices)
        self._rebuild_light_rows()
        self._rebuild_scenes()
        self._update_online_chip()
        self._update_selection_ui()
        if self.settings_window is not None and self.settings_window.winfo_exists():
            self.settings_window.refresh()

    def _select_only(self, device_ids: list[str]) -> None:
        wanted = set(device_ids)
        for device_id, row in self.rows.items():
            row.set_selected(device_id in wanted)
        self._update_selection_ui()

    def select_all(self) -> None:
        for row in self.rows.values():
            row.set_selected(True)
        self._update_selection_ui()

    def select_none(self) -> None:
        for row in self.rows.values():
            row.set_selected(False)
        self._update_selection_ui()

    # ================================================================ LAN scan
    def scan_lan(self, on_done: Callable[[str, bool], None] | None = None) -> None:
        if self._scan_running or self._closing:
            return
        if self._busy:
            self._set_status("Attendi la fine del comando in corso.", "warning")
            return

        self._scan_running = True
        self.lan_button.configure(state="disabled", text="Scansione…")
        self._set_status(
            "Scansione LAN in corso… (broadcast UDP, qualche secondo)", "muted"
        )

        def job() -> Any:
            return self.controller.scan_lan()

        def done(outcome: Any) -> None:
            self._scan_running = False
            if self._closing:
                return
            self.lan_button.configure(state="normal", text="Scansiona IP LAN")
            matches = self.controller.match_scan_ips(outcome.found, self.devices)
            changed = {
                device.id: matches[device.id]
                for device in self.devices
                if device.id in matches and matches[device.id] != device.ip
            }
            if changed:
                updated = [
                    device.copy(ip=changed[device.id]) if device.id in changed else device
                    for device in self.devices
                ]
                self.devices = updated
                self._after_config_change()
                message = (
                    f"✓ Scansione: {outcome.count} dispositivi trovati · "
                    f"{len(changed)} IP aggiornati · {format_ms(outcome.elapsed_ms)}"
                )
                level = "success"
            elif matches:
                message = (
                    f"Scansione: {outcome.count} dispositivi trovati, IP già allineati."
                )
                level = "success"
            elif outcome.count:
                message = (
                    f"Scansione: {outcome.count} dispositivi trovati, nessun IP da aggiornare."
                )
                level = "warning"
            else:
                message = (
                    "Scansione: nessun dispositivo Tuya ha risposto. "
                    "Verifica di essere sulla stessa rete."
                )
                level = "warning"
            self._set_status(message, level)
            if on_done:
                on_done(message, True)

        def failed(exc: Exception) -> None:
            self._scan_running = False
            if self._closing:
                return
            self.lan_button.configure(state="normal", text="Scansiona IP LAN")
            LOGGER.exception("Scansione LAN fallita")
            message = f"Scansione LAN fallita: {exc}"
            self._set_status(message, "danger")
            if on_done:
                on_done(message, False)

        self.submit(job, done, failed)

    # =================================================================== saving
    def _schedule_save(self) -> None:
        if self._save_job is not None:
            try:
                self.after_cancel(self._save_job)
            except tk.TclError:
                pass
        self._save_job = self.after(600, self._save_now)

    def _save_now(self) -> None:
        if self._save_job is not None:
            try:
                self.after_cancel(self._save_job)
            except tk.TclError:
                pass
            self._save_job = None
        try:
            self.store.save(self.devices, self.states, self.demo)
        except Exception as exc:
            LOGGER.exception("Salvataggio lights_config.json fallito")
            self._set_status(f"Impossibile salvare la configurazione: {exc}", "danger")

    def _save_scenes(self) -> None:
        try:
            self.scene_store.save(self.scenes)
        except Exception as exc:
            LOGGER.exception("Salvataggio scenes.json fallito")
            self._set_status(f"Impossibile salvare le scene: {exc}", "danger")

    # ==================================================================== async
    def submit(
        self,
        fn: Callable[[], Any],
        on_success: Callable[[Any], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
    ) -> None:
        if self._closing:
            return
        future = self._task_pool.submit(fn)

        def poll() -> None:
            if self._closing:
                return
            if not future.done():
                self.after(25, poll)
                return
            try:
                result = future.result()
            except Exception as exc:
                LOGGER.exception("Task in background fallito")
                if on_error:
                    on_error(exc)
                else:
                    self._set_status(f"Errore: {exc}", "danger")
                return
            if on_success:
                try:
                    on_success(result)
                except Exception as exc:
                    LOGGER.exception("Callback UI fallita")
                    self._set_status(f"Errore UI: {exc}", "danger")

        self.after(25, poll)

    # ================================================================ rebuild UI
    def _rebuild_light_rows(self) -> None:
        selected = set(self._selected_ids())
        for child in self.lights_scroll.winfo_children():
            child.destroy()
        self.rows = {}

        self.lights_count_label.configure(text=str(len(self.devices)))
        if self.demo:
            self.demo_banner.grid()
        else:
            self.demo_banner.grid_remove()

        if not self.devices:
            empty = ctk.CTkFrame(self.lights_scroll, fg_color="transparent")
            empty.grid(row=0, column=0, sticky="ew", padx=8, pady=16)
            ctk.CTkLabel(
                empty,
                text="Nessuna luce configurata.",
                font=font(12, "bold"),
                text_color=COLORS["muted"],
                anchor="w",
            ).pack(fill="x")
            ctk.CTkLabel(
                empty,
                text="Apri Impostazioni per aggiungere una luce o importare devices.json.",
                font=font(9),
                text_color=COLORS["dim"],
                anchor="w",
                justify="left",
                wraplength=280,
            ).pack(fill="x", pady=(2, 8))
            ctk.CTkButton(
                empty,
                text="Apri Impostazioni",
                height=30,
                corner_radius=7,
                fg_color=COLORS["panel_alt"],
                border_width=1,
                border_color=COLORS["border"],
                hover_color=COLORS["card_hover"],
                text_color=COLORS["text"],
                font=font(9, "bold"),
                command=self.open_settings,
            ).pack(anchor="w")
            self._update_selection_ui()
            return

        for index, device in enumerate(self.devices):
            row = LightRow(
                self.lights_scroll,
                device,
                self.states.get(device.id, LightState()),
                selected=device.id in selected,
                online=self.health.get(device.id),
                on_selection_change=self._update_selection_ui,
                on_power_toggle=self._on_light_power,
            )
            row.grid(row=index, column=0, sticky="ew", padx=6, pady=4)
            self.rows[device.id] = row
        self._update_selection_ui()

    def _rebuild_scenes(self) -> None:
        for child in self.scenes_scroll.winfo_children():
            child.destroy()
        self._scene_cards = []
        self.scene_count_label.configure(text=str(len(self.scenes)))

        if not self.scenes:
            empty = ctk.CTkFrame(self.scenes_scroll, fg_color="transparent")
            empty.grid(row=0, column=0, columnspan=2, sticky="ew", padx=8, pady=16)
            ctk.CTkLabel(
                empty,
                text="Nessuna scena salvata.",
                font=font(12, "bold"),
                text_color=COLORS["muted"],
                anchor="w",
            ).pack(fill="x")
            ctk.CTkLabel(
                empty,
                text="Crea una scena globale o uno snapshot multi-luce.",
                font=font(9),
                text_color=COLORS["dim"],
                anchor="w",
                justify="left",
                wraplength=300,
            ).pack(fill="x", pady=(2, 0))
            return

        known_names = {device.id: device.name for device in self.devices}
        for index, scene in enumerate(self.scenes):
            card = SceneCard(
                self.scenes_scroll,
                scene,
                scene.summary(known_names),
                on_apply=self.apply_scene,
                on_menu=self._show_scene_menu,
            )
            card.grid(
                row=index // 2,
                column=index % 2,
                sticky="nsew",
                padx=4,
                pady=4,
            )
            self._scene_cards.append(card)

    def _update_selection_ui(self) -> None:
        if not hasattr(self, "apply_selection_label"):
            return
        count = len(self._selected_ids())
        if self._mode == "Flow":
            if self._flow_running:
                text = "Flow attivo · usa STOP FLOW in basso a destra"
                color = COLORS["success"]
            elif count:
                text = f"Avvia il flow su {count} {'luce selezionata' if count == 1 else 'luci selezionate'}"
                color = COLORS["muted"]
            else:
                text = "Seleziona le luci per avviare il flow"
                color = COLORS["warning"]
        elif count:
            text = f"Applica a {count} {'luce selezionata' if count == 1 else 'luci selezionate'}"
            color = COLORS["muted"]
        else:
            text = "Nessuna luce selezionata: usa le checkbox a sinistra"
            color = COLORS["warning"]
        self.apply_selection_label.configure(text=text, text_color=color)

    def _update_online_chip(self) -> None:
        total = len(self.devices)
        if total == 0:
            text, color = "NESSUNA LUCE", COLORS["dim"]
        else:
            online = sum(
                1 for device in self.devices if self.health.get(device.id) is True
            )
            offline = sum(
                1 for device in self.devices if self.health.get(device.id) is False
            )
            if online == total:
                text, color = f"ONLINE {online}/{total}", COLORS["success"]
            elif online > 0:
                text, color = f"ONLINE {online}/{total}", COLORS["warning"]
            elif offline > 0:
                text, color = f"OFFLINE {offline}/{total}", COLORS["danger"]
            else:
                text, color = f"{total} LUCI", COLORS["dim"]
        self.online_label.configure(text=text, text_color=color)
        self.online_dot.configure(fg_color=color)

    # =================================================================== close
    def _on_close(self) -> None:
        if self._closing:
            return
        if self._flow_running:
            self.stop_flow(announce=False)
        self._closing = True
        self._save_now()
        try:
            self.controller.shutdown()
        except Exception:
            LOGGER.exception("Shutdown controller fallito")
        self._task_pool.shutdown(wait=False, cancel_futures=True)
        try:
            self.destroy()
        except tk.TclError:
            pass
