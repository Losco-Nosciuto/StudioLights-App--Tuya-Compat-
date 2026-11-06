"""Reusable UI widgets: light rows and scene cards."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable

import customtkinter as ctk

from ..models import LightDevice, LightState, Scene
from ..theme import COLORS, font


class LightRow(ctk.CTkFrame):
    """One bulb: selection checkbox, live state summary and quick ON/OFF switch."""

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        device: LightDevice,
        state: LightState,
        *,
        selected: bool,
        online: bool | None,
        on_selection_change: Callable[[], None],
        on_power_toggle: Callable[[str, bool], None],
    ) -> None:
        super().__init__(
            master,
            fg_color=COLORS["card"],
            corner_radius=10,
            border_width=1,
            border_color=COLORS["border"],
        )
        self.device = device
        self.state = state
        self.online = online
        self._on_selection_change = on_selection_change
        self._on_power_toggle = on_power_toggle
        self._updating = False

        self.grid_columnconfigure(1, weight=1)

        self.selected_var = tk.BooleanVar(value=selected)
        self.checkbox = ctk.CTkCheckBox(
            self,
            text="",
            variable=self.selected_var,
            width=22,
            checkbox_width=19,
            checkbox_height=19,
            corner_radius=5,
            border_width=2,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            border_color=COLORS["border_light"],
            checkmark_color=COLORS["accent_text"],
            command=self._selection_changed,
        )
        self.checkbox.grid(row=0, column=0, rowspan=2, padx=(10, 6), pady=10)

        self.dot = ctk.CTkFrame(
            self, width=8, height=8, corner_radius=4, fg_color=COLORS["dim"]
        )
        self.dot.grid(row=0, column=1, sticky="w", padx=(0, 6))
        self.dot.grid_propagate(False)

        self.name_label = ctk.CTkLabel(
            self,
            text=device.name,
            font=font(13, "bold"),
            text_color=COLORS["text"],
            anchor="w",
        )
        self.name_label.grid(row=0, column=1, sticky="w", padx=(14, 4))

        self.version_label = ctk.CTkLabel(
            self,
            text=f"v{device.version}",
            font=font(9),
            text_color=COLORS["dim"],
            anchor="e",
        )
        self.version_label.grid(row=0, column=2, sticky="e", padx=(0, 8))

        self.detail_label = ctk.CTkLabel(
            self,
            text="",
            font=font(9),
            text_color=COLORS["muted"],
            anchor="w",
            justify="left",
            wraplength=200,
        )
        self.detail_label.grid(
            row=1, column=1, columnspan=2, sticky="w", padx=(14, 8), pady=(0, 8)
        )

        self.switch_var = tk.IntVar(value=1 if state.power else 0)
        self.power_switch = ctk.CTkSwitch(
            self,
            text="",
            width=40,
            switch_width=36,
            switch_height=18,
            variable=self.switch_var,
            onvalue=1,
            offvalue=0,
            fg_color=COLORS["border_light"],
            progress_color=COLORS["success"],
            button_color=COLORS["text"],
            button_hover_color=COLORS["text"],
            command=self._power_changed,
        )
        self.power_switch.grid(row=0, column=3, rowspan=2, padx=(0, 10))

        self.name_label.bind("<Button-1>", lambda _event: self._toggle_selection())
        self.version_label.bind("<Button-1>", lambda _event: self._toggle_selection())
        self.detail_label.bind("<Button-1>", lambda _event: self._toggle_selection())

        self.set_state(state, online)

    # ------------------------------------------------------------------ helpers
    def _selection_changed(self) -> None:
        if not self._updating:
            self._on_selection_change()

    def _toggle_selection(self) -> None:
        if self._updating:
            return
        self.selected_var.set(not self.selected_var.get())
        self._on_selection_change()

    def _power_changed(self) -> None:
        if self._updating:
            return
        self._on_power_toggle(self.device.id, bool(self.switch_var.get()))

    @property
    def selected(self) -> bool:
        return bool(self.selected_var.get())

    def set_selected(self, selected: bool) -> None:
        self._updating = True
        self.selected_var.set(bool(selected))
        self._updating = False

    def set_state(self, state: LightState, online: bool | None = None) -> None:
        self.state = state
        if online is None:
            online = self.online
        self.online = online

        self._updating = True
        if state.power:
            self.power_switch.select()
        else:
            self.power_switch.deselect()
        self._updating = False

        detail = f"{self.device.display_ip}\n{state.summary()}"
        if online is False:
            detail += "\noffline"
        self.detail_label.configure(
            text=detail,
            text_color=COLORS["danger"] if online is False else COLORS["muted"],
        )
        if online is True:
            dot_color = COLORS["success"] if state.power else COLORS["off"]
        elif online is False:
            dot_color = COLORS["danger"]
        else:
            dot_color = COLORS["dim"]
        self.dot.configure(fg_color=dot_color)
        self.name_label.configure(text_color=COLORS["dim"] if online is False else COLORS["text"])


class SceneCard(ctk.CTkFrame):
    """Clickable scene tile with a per-card context menu."""

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        scene: Scene,
        summary: str,
        *,
        on_apply: Callable[[Scene], None],
        on_menu: Callable[[Scene], None],
    ) -> None:
        super().__init__(
            master,
            fg_color=COLORS["card"],
            corner_radius=12,
            border_width=1,
            border_color=COLORS["border"],
        )
        self.grid_columnconfigure(1, weight=1)
        self.scene = scene
        self._on_apply = on_apply
        self._on_menu = on_menu
        self._bound_widgets: list[tk.Misc] = []

        accent = ctk.CTkFrame(
            self,
            width=4,
            height=1,
            corner_radius=2,
            fg_color=scene.accent_hex,
        )
        accent.grid(row=0, column=0, rowspan=3, sticky="ns", padx=(7, 4), pady=9)
        accent.grid_propagate(False)

        badge_color = COLORS["violet"] if scene.is_snapshot else COLORS["accent"]
        badge_text = scene.type_label + (" · DEMO" if scene.demo else "")
        self.badge = ctk.CTkLabel(
            self,
            text=badge_text,
            font=font(9, "bold"),
            text_color=badge_color,
            anchor="w",
        )
        self.badge.grid(row=0, column=1, sticky="w", padx=(4, 0), pady=(9, 0))

        self.menu_button = ctk.CTkButton(
            self,
            text="⋯",
            width=26,
            height=22,
            corner_radius=6,
            fg_color="transparent",
            hover_color=COLORS["card_hover"],
            text_color=COLORS["muted"],
            font=font(17, "bold"),
            command=lambda: self._on_menu(self.scene),
        )
        self.menu_button.grid(row=0, column=2, sticky="ne", padx=(0, 6), pady=(6, 0))

        self.name_label = ctk.CTkLabel(
            self,
            text=scene.name,
            font=font(13, "bold"),
            text_color=COLORS["text"],
            anchor="w",
            justify="left",
            wraplength=164,
        )
        self.name_label.grid(row=1, column=1, columnspan=2, sticky="w", padx=(4, 8))

        self.summary_label = ctk.CTkLabel(
            self,
            text=summary,
            font=font(10),
            text_color=COLORS["muted"],
            anchor="w",
            justify="left",
            wraplength=164,
        )
        self.summary_label.grid(
            row=2, column=1, columnspan=2, sticky="w", padx=(4, 8), pady=(0, 8)
        )

        for widget in (self, accent, self.name_label, self.summary_label, self.badge):
            self._bind_widget(widget)
        self.menu_button.bind("<Button-1>", lambda _event: None, add=True)

    def _bind_widget(self, widget: tk.Misc) -> None:
        widget.bind("<Button-1>", self._apply, add=True)
        widget.bind("<Enter>", self._hover_in, add=True)
        widget.bind("<Leave>", self._hover_out, add=True)
        try:
            widget.configure(cursor="hand2")
        except Exception:
            pass
        self._bound_widgets.append(widget)
        # CTkFrame draws on an internal canvas that swallows clicks.
        # CTkLabel.bind() already forwards to its canvas, so avoid double firing.
        if isinstance(widget, ctk.CTkFrame):
            canvas = getattr(widget, "_canvas", None)
            if canvas is not None:
                canvas.bind("<Button-1>", self._apply, add=True)
                canvas.bind("<Enter>", self._hover_in, add=True)
                canvas.bind("<Leave>", self._hover_out, add=True)
                canvas.configure(cursor="hand2")

    def _apply(self, _event: tk.Event | None = None) -> None:
        self._on_apply(self.scene)

    def _hover_in(self, _event: tk.Event | None = None) -> None:
        self.configure(border_color=COLORS["accent"])

    def _hover_out(self, _event: tk.Event | None = None) -> None:
        self.configure(border_color=COLORS["border"])
