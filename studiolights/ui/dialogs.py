"""Dark modal dialogs and the settings window."""

from __future__ import annotations

import logging
import sys
import tkinter as tk
from pathlib import Path
from typing import Any

import customtkinter as ctk

from ..models import SUPPORTED_VERSIONS, LightDevice
from ..theme import COLORS, font, mono
from .colorpicker import ColorPicker

LOGGER = logging.getLogger("studiolights.ui.dialogs")

WIZARD_COMMAND = "python -m tinytuya wizard"


def wizard_command_full() -> str:
    """Copy-paste command using the same Python that runs the app (venv)."""
    executable = Path(sys.executable)
    if executable.name.lower() == "pythonw.exe":
        executable = executable.with_name("python.exe")
    if " " in str(executable):
        return f'"{executable}" -m tinytuya wizard'
    return f"{executable} -m tinytuya wizard"


class BaseDialog(ctk.CTkToplevel):
    def __init__(
        self,
        master: ctk.CTkBaseClass,
        title: str,
        width: int,
        height: int,
        *,
        modal: bool = True,
    ) -> None:
        super().__init__(master, fg_color=COLORS["bg"])
        self._parent = master
        self._modal = modal
        self._width = width
        self._height = height
        self._closed = False
        self.title(title)
        try:
            icon = Path(__file__).resolve().parents[2] / "assets" / "icon.ico"
            if icon.exists():
                self.iconbitmap(str(icon))
        except tk.TclError:
            pass
        self.transient(master)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Escape>", lambda _event: self.close())
        self.withdraw()
        self.after(20, self._present)

    def _present(self) -> None:
        if self._closed or not self.winfo_exists():
            return
        self.update_idletasks()
        try:
            parent = self._parent.winfo_toplevel()
            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
            pw = parent.winfo_width()
            ph = parent.winfo_height()
        except tk.TclError:
            px = py = 0
            pw = self.winfo_screenwidth()
            ph = self.winfo_screenheight()

        x = px + max(0, (pw - self._width) // 2)
        y = py + max(0, (ph - self._height) // 2)
        x = max(10, min(self.winfo_screenwidth() - self._width - 10, x))
        y = max(10, min(self.winfo_screenheight() - self._height - 40, y))
        self.geometry(f"{self._width}x{self._height}+{x}+{y}")
        self.deiconify()
        # CTk redraws the Windows titlebar by temporarily hiding the window.
        # Calling resizable() only after mapping avoids the window staying hidden.
        self.resizable(False, False)
        self.lift()
        if self._modal:
            try:
                self.grab_set()
            except tk.TclError:
                pass
        self.focus_force()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()
        if self._modal and isinstance(self._parent, BaseDialog):
            try:
                if self._parent.winfo_exists():
                    self._parent.grab_set()
            except tk.TclError:
                pass


class ConfirmDialog(BaseDialog):
    def __init__(
        self,
        master: ctk.CTkBaseClass,
        title: str,
        message: str,
        *,
        confirm: str = "Conferma",
        cancel: str = "Annulla",
        danger: bool = False,
    ) -> None:
        super().__init__(master, title, 480, 250)
        self.result = False

        ctk.CTkLabel(
            self,
            text=title,
            font=font(18, "bold"),
            text_color=COLORS["text"],
            anchor="w",
        ).pack(fill="x", padx=26, pady=(24, 10))
        ctk.CTkLabel(
            self,
            text=message,
            font=font(12),
            text_color=COLORS["muted"],
            anchor="w",
            justify="left",
            wraplength=420,
        ).pack(fill="x", padx=26)

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(side="bottom", fill="x", padx=26, pady=22)
        ctk.CTkButton(
            footer,
            text=cancel,
            width=110,
            height=34,
            corner_radius=8,
            fg_color="transparent",
            border_width=1,
            border_color=COLORS["border_light"],
            hover_color=COLORS["card_hover"],
            text_color=COLORS["muted"],
            command=self.close,
        ).pack(side="right", padx=(8, 0))
        ctk.CTkButton(
            footer,
            text=confirm,
            width=130,
            height=34,
            corner_radius=8,
            fg_color=COLORS["danger"] if danger else COLORS["accent"],
            hover_color="#ff7d90" if danger else COLORS["accent_hover"],
            text_color="#180206" if danger else COLORS["accent_text"],
            font=font(12, "bold"),
            command=self._confirm,
        ).pack(side="right")

    def _confirm(self) -> None:
        self.result = True
        self.close()

    @classmethod
    def ask(
        cls,
        master: ctk.CTkBaseClass,
        title: str,
        message: str,
        *,
        confirm: str = "Conferma",
        cancel: str = "Annulla",
        danger: bool = False,
    ) -> bool:
        dialog = cls(
            master,
            title,
            message,
            confirm=confirm,
            cancel=cancel,
            danger=danger,
        )
        dialog.wait_window()
        return dialog.result


class AlertDialog(BaseDialog):
    def __init__(self, master: ctk.CTkBaseClass, title: str, message: str) -> None:
        super().__init__(master, title, 500, 300)
        ctk.CTkLabel(
            self,
            text=title,
            font=font(18, "bold"),
            text_color=COLORS["text"],
            anchor="w",
        ).pack(fill="x", padx=26, pady=(24, 10))
        ctk.CTkLabel(
            self,
            text=message,
            font=font(12),
            text_color=COLORS["muted"],
            anchor="w",
            justify="left",
            wraplength=440,
        ).pack(fill="x", padx=26)
        ctk.CTkButton(
            self,
            text="OK",
            width=120,
            height=34,
            corner_radius=8,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            text_color=COLORS["accent_text"],
            font=font(12, "bold"),
            command=self.close,
        ).pack(side="bottom", pady=22)

    @classmethod
    def show(cls, master: ctk.CTkBaseClass, title: str, message: str) -> None:
        dialog = cls(master, title, message)
        dialog.wait_window()


class ColorPickerDialog(BaseDialog):
    """Small modal wrapper around the HSV picker used by the Flow palette."""

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        title: str,
        initial_rgb: tuple[int, int, int],
    ) -> None:
        super().__init__(master, title, 380, 400)
        self.result: tuple[int, int, int] | None = None

        ctk.CTkLabel(
            self,
            text=title,
            font=font(18, "bold"),
            text_color=COLORS["text"],
            anchor="w",
        ).pack(fill="x", padx=24, pady=(20, 10))
        self.picker = ColorPicker(self, initial_rgb=initial_rgb)
        self.picker.pack(padx=22, pady=(0, 8))

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(side="bottom", fill="x", padx=24, pady=18)
        ctk.CTkButton(
            footer,
            text="Annulla",
            width=96,
            height=34,
            corner_radius=8,
            fg_color="transparent",
            border_width=1,
            border_color=COLORS["border_light"],
            hover_color=COLORS["card_hover"],
            text_color=COLORS["muted"],
            command=self.close,
        ).pack(side="right", padx=(8, 0))
        ctk.CTkButton(
            footer,
            text="Salva colore",
            width=130,
            height=34,
            corner_radius=8,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            text_color=COLORS["accent_text"],
            font=font(11, "bold"),
            command=self._save,
        ).pack(side="right")

    def _save(self) -> None:
        self.result = self.picker.get_rgb()
        self.close()

    @classmethod
    def ask(
        cls,
        master: ctk.CTkBaseClass,
        title: str,
        initial_rgb: tuple[int, int, int],
    ) -> tuple[int, int, int] | None:
        dialog = cls(master, title, initial_rgb)
        dialog.wait_window()
        return dialog.result


class SceneDialog(BaseDialog):
    """Create / overwrite dialog. Read result_name and result_type afterwards."""

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        *,
        selected_names: list[str],
        existing_name: str = "",
        existing_type: str = "global",
        overwrite: bool = False,
        global_summary: str = "",
        flow_summary: str = "",
    ) -> None:
        super().__init__(master, "Scena Studio", 570, 550)
        self.result_name: str | None = None
        self.result_type: str | None = None
        self._selected_names = selected_names
        self._global_summary = global_summary
        self._flow_summary = flow_summary

        ctk.CTkLabel(
            self,
            text="Sovrascrivi scena" if overwrite else "Nuova scena",
            font=font(21, "bold"),
            text_color=COLORS["text"],
            anchor="w",
        ).pack(fill="x", padx=26, pady=(22, 2))
        ctk.CTkLabel(
            self,
            text="Salva l'atmosfera dello studio e richiamala con un clic.",
            font=font(11),
            text_color=COLORS["muted"],
            anchor="w",
        ).pack(fill="x", padx=26, pady=(0, 18))

        ctk.CTkLabel(
            self,
            text="NOME SCENA",
            font=font(9, "bold"),
            text_color=COLORS["dim"],
            anchor="w",
        ).pack(fill="x", padx=26)
        self.name_entry = ctk.CTkEntry(
            self,
            height=36,
            fg_color=COLORS["panel_alt"],
            border_color=COLORS["border"],
            font=font(13),
        )
        self.name_entry.pack(fill="x", padx=26, pady=(5, 16))
        self.name_entry.insert(0, existing_name)
        self.name_entry.bind("<Return>", lambda _event: self._save())

        ctk.CTkLabel(
            self,
            text="TIPO DI SCENA",
            font=font(9, "bold"),
            text_color=COLORS["dim"],
            anchor="w",
        ).pack(fill="x", padx=26)
        self.type_switch = ctk.CTkSegmentedButton(
            self,
            values=["Globale", "Snapshot Studio", "Flow"],
            height=34,
            corner_radius=8,
            fg_color=COLORS["panel_alt"],
            selected_color=COLORS["accent"],
            selected_hover_color=COLORS["accent_hover"],
            unselected_color=COLORS["panel_alt"],
            unselected_hover_color=COLORS["card_hover"],
            text_color=COLORS["text"],
            font=font(11, "bold"),
            command=lambda _value: self._update_description(),
        )
        self.type_switch.pack(fill="x", padx=26, pady=(5, 14))
        if existing_type == "snapshot":
            self.type_switch.set("Snapshot Studio")
        elif existing_type == "flow":
            self.type_switch.set("Flow")
        else:
            self.type_switch.set("Globale")

        self.description = ctk.CTkLabel(
            self,
            text="",
            font=font(11),
            text_color=COLORS["muted"],
            justify="left",
            anchor="w",
            wraplength=500,
        )
        self.description.pack(fill="x", padx=26)

        self.selection_info = ctk.CTkLabel(
            self,
            text="",
            font=font(10),
            text_color=COLORS["dim"],
            justify="left",
            anchor="w",
            wraplength=500,
        )
        self.selection_info.pack(fill="x", padx=26, pady=(8, 0))

        preview_box = ctk.CTkFrame(
            self,
            fg_color=COLORS["panel_alt"],
            corner_radius=10,
            border_width=1,
            border_color=COLORS["border"],
        )
        preview_box.pack(fill="x", padx=26, pady=(14, 0))
        ctk.CTkLabel(
            preview_box,
            text="ANTEPRIMA",
            font=font(8, "bold"),
            text_color=COLORS["dim"],
            anchor="w",
        ).pack(fill="x", padx=12, pady=(8, 0))
        self.preview_label = ctk.CTkLabel(
            preview_box,
            text="",
            font=font(11),
            text_color=COLORS["muted"],
            anchor="w",
            justify="left",
            wraplength=480,
        )
        self.preview_label.pack(fill="x", padx=12, pady=(1, 8))

        self.error_label = ctk.CTkLabel(
            self,
            text="",
            font=font(10),
            text_color=COLORS["danger"],
            anchor="w",
        )
        self.error_label.pack(fill="x", padx=26, pady=(6, 0))

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(side="bottom", fill="x", padx=26, pady=20)
        ctk.CTkButton(
            footer,
            text="Annulla",
            width=100,
            height=36,
            corner_radius=8,
            fg_color="transparent",
            border_width=1,
            border_color=COLORS["border_light"],
            hover_color=COLORS["card_hover"],
            text_color=COLORS["muted"],
            command=self.close,
        ).pack(side="right", padx=(8, 0))
        ctk.CTkButton(
            footer,
            text="Salva scena",
            width=140,
            height=36,
            corner_radius=8,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            text_color=COLORS["accent_text"],
            font=font(12, "bold"),
            command=self._save,
        ).pack(side="right")

        self._update_description()
        self.name_entry.focus_set()

    def _selected_type(self) -> str:
        selected = self.type_switch.get()
        if selected == "Snapshot Studio":
            return "snapshot"
        if selected == "Flow":
            return "flow"
        return "global"

    def _update_description(self) -> None:
        scene_type = self._selected_type()
        if scene_type == "flow":
            self.description.configure(
                text=(
                    "Scena FLOW: salva la palette, la velocità e lo sfasamento attuali "
                    "del tab Flow. Al richiamo avvia il fade infinito sulle luci "
                    "selezionate in quel momento."
                )
            )
            self.selection_info.configure(text="La palette viene letta dal tab Flow.")
            self.preview_label.configure(text=self._flow_summary or "Flow · 8 colori")
            return
        if scene_type == "global":
            self.description.configure(
                text=(
                    "Scena GLOBALE: salva i valori attuali dei controlli manuali "
                    "(bianco o colore + luminosità). Al richiamo viene applicata alle luci "
                    "selezionate in quel momento."
                )
            )
            self.selection_info.configure(text="")
            self.preview_label.configure(
                text=self._global_summary or "Stato attuale dei controlli manuali"
            )
        else:
            count = len(self._selected_names)
            self.description.configure(
                text=(
                    "SNAPSHOT STUDIO: salva lo stato individuale di ogni luce selezionata "
                    "(colore, bianco, luminosità). Al richiamo ogni luce riceve esattamente "
                    "il proprio stato."
                )
            )
            if count:
                preview = ", ".join(self._selected_names[:5])
                if count > 5:
                    preview += f", +{count - 5}"
                self.selection_info.configure(text=f"Luci incluse ({count}): {preview}")
                self.preview_label.configure(text=f"Snapshot di {count} luci.")
            else:
                self.selection_info.configure(
                    text="Nessuna luce selezionata: seleziona le luci prima di salvare uno snapshot."
                )
                self.preview_label.configure(text="Nessuna luce inclusa.")

    def _save(self) -> None:
        name = self.name_entry.get().strip()
        if not name:
            self.error_label.configure(text="Inserisci un nome per la scena.")
            return
        if len(name) > 48:
            self.error_label.configure(text="Il nome non può superare 48 caratteri.")
            return
        scene_type = self._selected_type()
        if scene_type == "snapshot" and not self._selected_names:
            self.error_label.configure(
                text="Uno snapshot richiede almeno una luce selezionata."
            )
            return
        self.result_name = name
        self.result_type = scene_type
        self.close()


class LightEditorDialog(BaseDialog):
    """Add or edit a bulb. Read `.result` (LightDevice | None) afterwards."""

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        app: Any,
        device: LightDevice | None = None,
    ) -> None:
        super().__init__(
            master, "Modifica luce" if device else "Aggiungi luce", 640, 620
        )
        self.app = app
        self.device = device
        self.result: LightDevice | None = None
        self._test_running = False

        ctk.CTkLabel(
            self,
            text="Modifica luce" if device else "Aggiungi luce",
            font=font(21, "bold"),
            text_color=COLORS["text"],
            anchor="w",
        ).pack(fill="x", padx=26, pady=(22, 2))
        header_actions = ctk.CTkFrame(self, fg_color="transparent")
        header_actions.pack(fill="x", padx=26, pady=(0, 2))
        header_actions.grid_columnconfigure(0, weight=1)
        ctk.CTkButton(
            header_actions,
            text="Salva",
            width=84,
            height=30,
            corner_radius=8,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            text_color=COLORS["accent_text"],
            font=font(11, "bold"),
            command=self._save,
        ).grid(row=0, column=1, sticky="e")
        ctk.CTkButton(
            header_actions,
            text="Annulla",
            width=80,
            height=30,
            corner_radius=8,
            fg_color="transparent",
            border_width=1,
            border_color=COLORS["border_light"],
            hover_color=COLORS["card_hover"],
            text_color=COLORS["muted"],
            font=font(10, "bold"),
            command=self.close,
        ).grid(row=0, column=2, sticky="e", padx=(8, 0))
        ctk.CTkLabel(
            header_actions,
            text="Invio o Ctrl+S per salvare",
            font=font(8),
            text_color=COLORS["dim"],
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            self,
            text="I dati sono disponibili nel devices.json del wizard tinytuya "
            "oppure nell'app Smart Life (Device ID / Local Key).",
            font=font(10),
            text_color=COLORS["muted"],
            anchor="w",
            justify="left",
            wraplength=580,
        ).pack(fill="x", padx=26, pady=(0, 16))

        self.name_entry = self._field("NOME", "es. Luce SX")
        self.id_entry = self._field("DEVICE ID", "es. bf1234abcd5678efgh90")
        if device:
            self.name_entry.insert(0, device.name)
            self.id_entry.insert(0, device.device_id)

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=26)
        row.grid_columnconfigure(0, weight=3)
        row.grid_columnconfigure(1, weight=2)

        ip_box = ctk.CTkFrame(row, fg_color="transparent")
        ip_box.grid(row=0, column=0, sticky="ew", padx=(0, 12))
        ctk.CTkLabel(
            ip_box,
            text="IP LOCALE",
            font=font(9, "bold"),
            text_color=COLORS["dim"],
            anchor="w",
        ).pack(fill="x")
        self.ip_entry = ctk.CTkEntry(
            ip_box,
            height=36,
            placeholder_text="192.168.1.50",
            fg_color=COLORS["panel_alt"],
            border_color=COLORS["border"],
            font=font(12),
        )
        self.ip_entry.pack(fill="x", pady=(5, 12))

        version_box = ctk.CTkFrame(row, fg_color="transparent")
        version_box.grid(row=0, column=1, sticky="ew")
        ctk.CTkLabel(
            version_box,
            text="PROTOCOLLO",
            font=font(9, "bold"),
            text_color=COLORS["dim"],
            anchor="w",
        ).pack(fill="x")
        self.version_menu = ctk.CTkOptionMenu(
            version_box,
            values=list(SUPPORTED_VERSIONS),
            height=36,
            corner_radius=8,
            fg_color=COLORS["panel_alt"],
            button_color=COLORS["border"],
            button_hover_color=COLORS["border_light"],
            dropdown_fg_color=COLORS["panel_alt"],
            dropdown_hover_color=COLORS["card_hover"],
            text_color=COLORS["text"],
            font=font(12),
            anchor="w",
        )
        self.version_menu.pack(fill="x", pady=(5, 12))
        self.version_menu.set(device.version if device else "3.3")

        if device:
            self.ip_entry.insert(0, device.ip)

        key_header = ctk.CTkFrame(self, fg_color="transparent")
        key_header.pack(fill="x", padx=26)
        ctk.CTkLabel(
            key_header,
            text="LOCAL KEY",
            font=font(9, "bold"),
            text_color=COLORS["dim"],
            anchor="w",
        ).pack(side="left")
        self.show_key = ctk.CTkCheckBox(
            key_header,
            text="Mostra",
            font=font(9),
            checkbox_width=14,
            checkbox_height=14,
            corner_radius=4,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            border_color=COLORS["border_light"],
            checkmark_color=COLORS["accent_text"],
            text_color=COLORS["muted"],
            command=self._toggle_key,
        )
        self.show_key.pack(side="right")

        self.key_entry = ctk.CTkEntry(
            self,
            height=36,
            show="•",
            placeholder_text="16 caratteri",
            fg_color=COLORS["panel_alt"],
            border_color=COLORS["border"],
            font=mono(12),
        )
        self.key_entry.pack(fill="x", padx=26, pady=(5, 4))
        if device:
            self.key_entry.insert(0, device.local_key)

        ctk.CTkLabel(
            self,
            text="Suggerimento: dopo un cambio IP usa «Scansiona LAN»; "
            "la Local Key non cambia mai.",
            font=font(9),
            text_color=COLORS["dim"],
            anchor="w",
        ).pack(fill="x", padx=26)

        self.error_label = ctk.CTkLabel(
            self,
            text="",
            font=font(10),
            text_color=COLORS["danger"],
            anchor="w",
            justify="left",
            wraplength=570,
        )
        self.error_label.pack(fill="x", padx=26, pady=(8, 0))

        test_row = ctk.CTkFrame(self, fg_color="transparent")
        test_row.pack(fill="x", padx=26, pady=(12, 0))
        self.test_button = ctk.CTkButton(
            test_row,
            text="Test connessione",
            width=130,
            height=32,
            corner_radius=8,
            fg_color="transparent",
            border_width=1,
            border_color=COLORS["border_light"],
            hover_color=COLORS["card_hover"],
            text_color=COLORS["accent"],
            font=font(11, "bold"),
            command=self._test_connection,
        )
        self.test_button.pack(side="left")
        self.test_result = ctk.CTkLabel(
            test_row,
            text="",
            font=font(10),
            text_color=COLORS["muted"],
            anchor="w",
            justify="left",
            wraplength=380,
        )
        self.test_result.pack(side="left", fill="x", expand=True, padx=(10, 0))

        info_box = ctk.CTkFrame(
            self,
            fg_color=COLORS["panel_alt"],
            corner_radius=8,
            border_width=1,
            border_color=COLORS["border"],
        )
        info_box.pack(fill="x", padx=26, pady=(16, 0))
        ctk.CTkLabel(
            info_box,
            text=(
                "La Local Key non esce mai da questo computer e viene usata solo in LAN. "
                "Non condividerla e non committare devices.json su Git."
            ),
            font=font(9),
            text_color=COLORS["muted"],
            anchor="w",
            justify="left",
            wraplength=550,
        ).pack(fill="x", padx=10, pady=8)

        self.name_entry.focus_set()
        self.bind("<Control-Return>", lambda _event: self._save())
        self.bind("<Control-s>", lambda _event: self._save())
        self.bind("<Control-S>", lambda _event: self._save())
        for entry in (self.name_entry, self.id_entry, self.ip_entry, self.key_entry):
            entry.bind("<Return>", lambda _event: self._save())
            entry.bind("<KP_Enter>", lambda _event: self._save())

    def _field(self, label: str, placeholder: str) -> ctk.CTkEntry:
        ctk.CTkLabel(
            self,
            text=label,
            font=font(9, "bold"),
            text_color=COLORS["dim"],
            anchor="w",
        ).pack(fill="x", padx=26)
        entry = ctk.CTkEntry(
            self,
            height=36,
            placeholder_text=placeholder,
            fg_color=COLORS["panel_alt"],
            border_color=COLORS["border"],
            font=font(12),
        )
        entry.pack(fill="x", padx=26, pady=(5, 12))
        return entry

    def _toggle_key(self) -> None:
        self.key_entry.configure(show="" if self.show_key.get() else "•")

    def _build_device(self) -> LightDevice:
        return LightDevice(
            name=self.name_entry.get().strip(),
            device_id=self.id_entry.get().strip(),
            ip=self.ip_entry.get().strip(),
            local_key=self.key_entry.get().strip(),
            version=self.version_menu.get(),
        )

    def _validate(self, *, for_test: bool = False) -> LightDevice | None:
        device = self._build_device()
        errors = device.validation_errors()
        if for_test:
            errors = [error for error in errors if "nome" not in error.lower()]
        if device.device_id and self.app.device_id_exists(
            device.device_id, exclude=self.device.id if self.device else None
        ):
            errors.append("Esiste già una luce con questo Device ID.")
        if device.ip:
            exclude_id = self.device.id if self.device else None
            conflict = next(
                (
                    item
                    for item in self.app.devices
                    if item.ip == device.ip and item.id != exclude_id
                ),
                None,
            )
            if conflict is not None:
                errors.append(
                    f"L'IP {device.ip} è già usato da «{conflict.name}». "
                    "Ogni lampadina deve avere un IP univoco."
                )
        if errors:
            self.error_label.configure(text="\n".join(errors))
            return None
        warnings = device.validation_warnings()
        self.error_label.configure(
            text="\n".join(warnings),
            text_color=COLORS["warning"] if warnings else COLORS["danger"],
        )
        return device

    def _test_connection(self) -> None:
        if self._test_running:
            return
        device = self._validate(for_test=True)
        if device is None:
            return
        if not device.ip:
            self.test_result.configure(
                text="Inserisci un IP per eseguire il test.",
                text_color=COLORS["warning"],
            )
            return

        self._test_running = True
        self.test_button.configure(state="disabled", text="Test…")
        self.test_result.configure(text="Connessione in corso…", text_color=COLORS["muted"])

        def done(result: tuple[bool, str]) -> None:
            if not self.winfo_exists():
                return
            self._test_running = False
            self.test_button.configure(state="normal", text="Test connessione")
            ok, message = result
            self.test_result.configure(
                text=message,
                text_color=COLORS["success"] if ok else COLORS["danger"],
            )

        def failed(exc: Exception) -> None:
            if not self.winfo_exists():
                return
            self._test_running = False
            self.test_button.configure(state="normal", text="Test connessione")
            self.test_result.configure(text=str(exc), text_color=COLORS["danger"])

        self.app.submit(
            lambda: self.app.controller.test_connection(device),
            on_success=done,
            on_error=failed,
        )

    def _save(self) -> None:
        device = self._validate()
        if device is None:
            return
        self.result = device
        self.close()


class SettingsWindow(ctk.CTkToplevel):
    """Non-modal device manager with wizard import and LAN scan."""

    def __init__(self, master: ctk.CTkBaseClass, app: Any) -> None:
        super().__init__(master, fg_color=COLORS["bg"])
        self.app = app
        self.title("Impostazioni — Studio Lights")
        self.geometry("780x700")
        self.minsize(720, 620)
        self.transient(master)
        try:
            icon = Path(__file__).resolve().parents[2] / "assets" / "icon.ico"
            if icon.exists():
                self.iconbitmap(str(icon))
        except tk.TclError:
            pass
        self.protocol("WM_DELETE_WINDOW", self.close)
        self._rows_frame: ctk.CTkScrollableFrame | None = None
        self._action_label: ctk.CTkLabel | None = None

        self._build()
        self.refresh()
        self.after(80, self._present)

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

    def _build(self) -> None:
        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=24, pady=(20, 4))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header,
            text="Impostazioni luci",
            font=font(22, "bold"),
            text_color=COLORS["text"],
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            header,
            text="Gestisci dispositivi, importa il wizard e aggiorna gli IP.",
            font=font(11),
            text_color=COLORS["muted"],
            anchor="w",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))
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
            command=self.close,
        ).grid(row=0, column=1, rowspan=2, sticky="e")

        self.demo_banner = ctk.CTkFrame(
            self,
            fg_color=COLORS["warning_dark"],
            corner_radius=10,
            border_width=1,
            border_color="#6b4a1a",
        )
        self.demo_banner.grid(row=1, column=0, sticky="ew", padx=24, pady=(10, 4))
        self.demo_banner.grid_columnconfigure(0, weight=1)
        self.demo_label = ctk.CTkLabel(
            self.demo_banner,
            text="",
            font=font(10),
            text_color=COLORS["warning"],
            anchor="w",
            justify="left",
            wraplength=560,
        )
        self.demo_label.grid(row=0, column=0, sticky="w", padx=12, pady=8)
        self.demo_clear = ctk.CTkButton(
            self.demo_banner,
            text="Svuota demo",
            width=96,
            height=26,
            corner_radius=7,
            fg_color="transparent",
            border_width=1,
            border_color="#6b4a1a",
            hover_color="#4a3616",
            text_color=COLORS["warning"],
            font=font(10, "bold"),
            command=self._clear_demo,
        )
        self.demo_clear.grid(row=0, column=1, sticky="e", padx=10)

        self.rows_frame = ctk.CTkScrollableFrame(
            self,
            fg_color=COLORS["panel"],
            corner_radius=12,
            border_width=1,
            border_color=COLORS["border"],
            scrollbar_fg_color="transparent",
            scrollbar_button_color=COLORS["border"],
            scrollbar_button_hover_color=COLORS["border_light"],
        )
        self.rows_frame.grid(row=2, column=0, sticky="nsew", padx=24, pady=10)
        self.rows_frame.grid_columnconfigure(0, weight=1)

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=3, column=0, sticky="ew", padx=24, pady=(0, 6))
        actions.grid_columnconfigure(0, weight=1)
        actions.grid_columnconfigure(1, weight=1)
        self._action_button(actions, "＋ Aggiungi luce", self._add_device, 0, 0)
        self._action_button(actions, "Importa devices.json", self._import_devices, 0, 1)
        self.scan_button = self._action_button(
            actions, "Scansiona IP LAN", self._scan, 1, 0
        )
        self._action_button(actions, "Copia comando wizard", self._copy_wizard, 1, 1)

        self._action_label = ctk.CTkLabel(
            self,
            text="",
            font=font(10),
            text_color=COLORS["muted"],
            anchor="w",
            justify="left",
            wraplength=700,
        )
        self._action_label.grid(row=4, column=0, sticky="ew", padx=26)

        help_box = ctk.CTkFrame(
            self,
            fg_color=COLORS["panel_alt"],
            corner_radius=10,
            border_width=1,
            border_color=COLORS["border"],
        )
        help_box.grid(row=5, column=0, sticky="ew", padx=24, pady=(8, 18))
        help_box.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            help_box,
            text="GUIDA RAPIDA",
            font=font(9, "bold"),
            text_color=COLORS["dim"],
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=12, pady=(8, 0))
        ctk.CTkLabel(
            help_box,
            text=(
                f"1.  {WIZARD_COMMAND}   (usa il Python del .venv)\n"
                "2.  Metti devices.json accanto a main.py\n"
                "3.  Importa qui: le luci vengono lette automaticamente\n"
                "4.  Se il router cambia IP, usa «Scansiona IP LAN»"
            ),
            font=font(9),
            text_color=COLORS["muted"],
            anchor="w",
            justify="left",
        ).grid(row=1, column=0, sticky="w", padx=12, pady=(2, 8))

    def _action_button(
        self,
        master: ctk.CTkFrame,
        text: str,
        command: Any,
        row: int,
        column: int,
    ) -> ctk.CTkButton:
        button = ctk.CTkButton(
            master,
            text=text,
            height=34,
            corner_radius=8,
            fg_color=COLORS["panel_alt"],
            border_width=1,
            border_color=COLORS["border"],
            hover_color=COLORS["card_hover"],
            text_color=COLORS["text"],
            font=font(10, "bold"),
            command=command,
        )
        button.grid(
            row=row,
            column=column,
            sticky="ew",
            padx=(0 if column == 0 else 6, 6 if column == 0 else 0),
            pady=4,
        )
        return button

    # ------------------------------------------------------------------ state
    def refresh(self) -> None:
        if not self.winfo_exists():
            return
        self.demo_banner.grid() if self.app.demo else self.demo_banner.grid_remove()
        if self.app.demo:
            self.demo_label.configure(
                text=(
                    "Configurazione DEMO attiva: le luci hanno ID e IP finti. "
                    "Importa devices.json o aggiungi le tue luci, poi svuota la demo."
                )
            )

        frame = self.rows_frame
        assert frame is not None
        for child in frame.winfo_children():
            child.destroy()

        if not self.app.devices:
            ctk.CTkLabel(
                frame,
                text="Nessuna luce configurata.\nAggiungi una luce o importa devices.json.",
                font=font(12),
                text_color=COLORS["muted"],
                justify="left",
                anchor="w",
            ).grid(row=0, column=0, sticky="w", padx=14, pady=16)
            return

        for index, device in enumerate(self.app.devices):
            row = ctk.CTkFrame(
                frame,
                fg_color=COLORS["card"],
                corner_radius=9,
                border_width=1,
                border_color=COLORS["border"],
            )
            row.grid(row=index, column=0, sticky="ew", padx=8, pady=4)
            row.grid_columnconfigure(0, weight=1)

            name_row = ctk.CTkFrame(row, fg_color="transparent")
            name_row.grid(row=0, column=0, sticky="w", padx=12, pady=(8, 0))
            ctk.CTkLabel(
                name_row,
                text=device.name,
                font=font(12, "bold"),
                text_color=COLORS["text"],
                anchor="w",
            ).pack(side="left")
            if self.app.demo:
                ctk.CTkLabel(
                    name_row,
                    text="DEMO",
                    font=font(8, "bold"),
                    text_color=COLORS["warning"],
                    fg_color=COLORS["warning_dark"],
                    corner_radius=4,
                    width=38,
                    height=16,
                ).pack(side="left", padx=(8, 0))
            ctk.CTkLabel(
                row,
                text=f"{device.display_ip}  ·  protocollo {device.version}  ·  key {device.masked_key}",
                font=font(9),
                text_color=COLORS["muted"],
                anchor="w",
            ).grid(row=1, column=0, sticky="w", padx=12, pady=(1, 8))

            buttons = ctk.CTkFrame(row, fg_color="transparent")
            buttons.grid(row=0, column=1, rowspan=2, sticky="e", padx=10)
            ctk.CTkButton(
                buttons,
                text="Modifica",
                width=72,
                height=26,
                corner_radius=7,
                fg_color="transparent",
                border_width=1,
                border_color=COLORS["border_light"],
                hover_color=COLORS["card_hover"],
                text_color=COLORS["muted"],
                font=font(9),
                command=lambda item=device: self._edit_device(item),
            ).pack(side="left", padx=3)
            ctk.CTkButton(
                buttons,
                text="Elimina",
                width=66,
                height=26,
                corner_radius=7,
                fg_color="transparent",
                hover_color=COLORS["danger_dark"],
                text_color=COLORS["danger"],
                font=font(9),
                command=lambda item=device: self._delete_device(item),
            ).pack(side="left", padx=3)

    def _set_action(self, text: str, color: str = COLORS["muted"]) -> None:
        if self._action_label is not None and self._action_label.winfo_exists():
            self._action_label.configure(text=text, text_color=color)

    # ---------------------------------------------------------------- actions
    def _add_device(self) -> None:
        dialog = LightEditorDialog(self, self.app, None)
        dialog.wait_window()
        if dialog.result is not None:
            self.app.upsert_light(dialog.result)
            self.refresh()
            self._set_action(f"Luce «{dialog.result.name}» aggiunta.", COLORS["success"])

    def _edit_device(self, device: LightDevice) -> None:
        dialog = LightEditorDialog(self, self.app, device)
        dialog.wait_window()
        if dialog.result is not None:
            self.app.upsert_light(dialog.result, original_id=device.id)
            self.refresh()
            self._set_action(f"Luce «{dialog.result.name}» aggiornata.", COLORS["success"])

    def _delete_device(self, device: LightDevice) -> None:
        if not ConfirmDialog.ask(
            self,
            "Eliminare la luce?",
            f"«{device.name}» verrà rimossa dalla configurazione e dalle scene snapshot.",
            confirm="Elimina",
            danger=True,
        ):
            return
        self.app.delete_light(device.id)
        self.refresh()
        self._set_action(f"Luce «{device.name}» eliminata.", COLORS["muted"])

    def _import_devices(self) -> None:
        try:
            count, warnings = self.app.import_devices()
        except Exception as exc:
            AlertDialog.show(self, "Import non riuscito", str(exc))
            return
        self.refresh()
        if count:
            displayed_warnings = list(warnings[:6])
            if len(warnings) > 6:
                displayed_warnings.append(f"… e altre {len(warnings) - 6} note (vedi il log).")
            message = f"Importate {count} luci da devices.json."
            if displayed_warnings:
                message += "\n\n" + "\n".join(displayed_warnings)
            self._set_action(message.replace("\n", " "), COLORS["success"])
            AlertDialog.show(self, "Import completato", message)
        else:
            AlertDialog.show(
                self,
                "Nessuna luce importata",
                "\n".join(warnings) or "devices.json non contiene dispositivi validi.",
            )

    def _scan(self) -> None:
        self.scan_button.configure(state="disabled", text="Scansione…")
        self._set_action("Scansione LAN in corso…", COLORS["muted"])

        def finished(message: str, ok: bool) -> None:
            if not self.winfo_exists():
                return
            self.scan_button.configure(state="normal", text="Scansiona IP LAN")
            self._set_action(message, COLORS["success"] if ok else COLORS["warning"])
            self.refresh()

        self.app.scan_lan(on_done=finished)

    def _copy_wizard(self) -> None:
        command = wizard_command_full()
        self.clipboard_clear()
        self.clipboard_append(command)
        self._set_action(f"Comando copiato: {command}", COLORS["success"])

    def _clear_demo(self) -> None:
        if not ConfirmDialog.ask(
            self,
            "Rimuovere la configurazione demo?",
            "Tutte le luci finte verranno eliminate. Le scene demo restano disponibili.",
            confirm="Svuota demo",
            danger=True,
        ):
            return
        self.app.clear_demo_lights()
        self.refresh()
        self._set_action("Configurazione demo rimossa.", COLORS["success"])

    def close(self) -> None:
        self.app.settings_window = None
        self.destroy()
