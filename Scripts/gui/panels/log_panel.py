"""Log panel: read-only event log."""

from datetime import datetime

import customtkinter as ctk


class LogPanel:
    """Builds the event log and appends timestamped lines.

    Args:
        parent: Widget the panel frame is created in.

    Attributes:
        frame (ctk.CTkFrame): The panel frame. The caller places it in the layout.
    """

    def __init__(self, parent) -> None:
        self.frame = ctk.CTkFrame(parent)
        self.frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self.frame, text="Event log", anchor="w").grid(
            row=0, column=0, padx=12, pady=(12, 4), sticky="w"
        )

        self.log_text = ctk.CTkTextbox(self.frame, height=90, state="disabled")
        self.log_text.grid(row=1, column=0, padx=12, pady=(0, 12), sticky="ew")

    def log(self, message: str) -> None:
        """Append a line with the current time."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] {message}\n"
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
