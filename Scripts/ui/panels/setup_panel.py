"""Setup panel: save, load and export synth setups."""

from typing import Callable

import customtkinter as ctk

from storage.config_store import AppConfig
from storage.setup_store import (
    SynthSetup,
    export_user_spec,
    list_setups,
    load_setup,
    save_setup,
)
from ui.synth_controller import SynthController


class SetupPanel:
    """Builds the 'Save/Load Setups' area and handles the file operations.

    Args:
        parent: Widget the panel frame is created in.
        controller (SynthController): Application logic.
        on_stop (Callable[[], None]): Stops all sounds. Called before a setup is applied.

    Attributes:
        frame (ctk.CTkFrame): The panel frame. The caller places it in the layout.
    """

    def __init__(
        self,
        parent,
        controller: SynthController,
        on_stop: Callable[[], None],
    ) -> None:
        self.controller = controller
        self.state = controller.state
        self.config = controller.config
        self._on_stop = on_stop

        self.frame = ctk.CTkFrame(parent)
        self._build()
        controller.add_config_contributor(self._contribute_config)

    def _build(self) -> None:
        setup_frame = self.frame
        setup_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            setup_frame,
            text="Save/Load Setups",
            font=ctk.CTkFont(size=15, weight="bold"),
        ).grid(row=0, column=0, columnspan=3, padx=12, pady=(12, 6), sticky="w")
        ctk.CTkLabel(setup_frame, text="Load").grid(
            row=1, column=0, padx=12, pady=6, sticky="w"
        )
        self.setup_load_var = ctk.StringVar(value="")
        self.setup_load_menu = ctk.CTkOptionMenu(
            setup_frame, variable=self.setup_load_var, values=["No setups"]
        )
        self.setup_load_menu.grid(row=1, column=1, padx=6, pady=6, sticky="ew")
        ctk.CTkButton(
            setup_frame, text="Load", width=90, command=self._load_setup
        ).grid(row=1, column=2, padx=(6, 12), pady=6)
        ctk.CTkLabel(setup_frame, text="Name").grid(
            row=2, column=0, padx=12, pady=6, sticky="w"
        )
        self.setup_name_var = ctk.StringVar(value=self.config.last_setup_name)
        self.setup_name_entry = ctk.CTkEntry(
            setup_frame, textvariable=self.setup_name_var, placeholder_text="Setup name"
        )
        self.setup_name_entry.grid(row=2, column=1, padx=6, pady=6, sticky="ew")
        ctk.CTkButton(
            setup_frame, text="Save", width=90, command=self._save_setup
        ).grid(row=2, column=2, padx=(6, 12), pady=6)
        ctk.CTkLabel(setup_frame, text="Notes").grid(
            row=3, column=0, padx=12, pady=(6, 12), sticky="nw"
        )
        self.setup_notes_entry = ctk.CTkEntry(
            setup_frame, placeholder_text="Optional notes"
        )
        self.setup_notes_entry.grid(row=3, column=1, padx=6, pady=(6, 12), sticky="ew")
        ctk.CTkButton(
            setup_frame, text="Export spec", width=110, command=self._export_setup_spec
        ).grid(row=3, column=2, padx=(6, 12), pady=(6, 12))
        self._refresh_setup_list()

    def _contribute_config(self, config: AppConfig) -> None:
        config.last_setup_name = self.setup_name_var.get().strip()

    def _refresh_setup_list(self) -> None:
        setups = list_setups()
        values = setups or ["No setups"]
        self.setup_load_menu.configure(values=values)
        preferred = self.config.last_setup_name
        self.setup_load_var.set(preferred if preferred in setups else values[0])

    def _current_setup(self) -> SynthSetup:
        name = (
            self.setup_name_var.get().strip()
            or self.config.last_setup_name
            or "Untitled"
        )
        return SynthSetup(
            name=name,
            params=self.state.setup_params_dict(),
            notes=self.setup_notes_entry.get().strip(),
        )

    def _save_setup(self) -> None:
        setup = self._current_setup()
        path = save_setup(setup)
        self.setup_name_var.set(setup.name)
        self.config.last_setup_name = setup.name
        self.controller.save_config()
        self._refresh_setup_list()
        self.controller.log(f"Setup saved: {path.name}")

    def _load_setup(self) -> None:
        name = self.setup_load_var.get()
        setup = load_setup(name)
        if setup is None:
            self.controller.log(f"Setup not found: {name}")
            return
        self._on_stop()
        self.setup_name_var.set(setup.name)
        self.setup_notes_entry.delete(0, "end")
        self.setup_notes_entry.insert(0, setup.notes)
        self.controller.apply_setup(setup)

    def _export_setup_spec(self) -> None:
        setup = self._current_setup()
        path = export_user_spec(setup)
        self.controller.log(f"Spec exported: {path.name}")
