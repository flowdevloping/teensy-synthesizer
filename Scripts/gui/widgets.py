"""Shared customtkinter helpers used by several GUI panels."""

import customtkinter as ctk


def format_param_value(value: float, decimals: int) -> str:
    """Format a parameter value for an entry field."""
    if decimals <= 0:
        return str(int(round(value)))
    return f"{value:.{decimals}f}"


def set_entry_text(entry: ctk.CTkEntry, value: float, decimals: int) -> None:
    """Show a value in an entry, only touching the widget if the text changed."""
    text = format_param_value(value, decimals)
    if entry.get() != text:
        entry.delete(0, "end")
        entry.insert(0, text)


def add_labeled_slider(
    parent: ctk.CTkFrame,
    row: int,
    label: ctk.CTkLabel,
    slider: ctk.CTkSlider,
    entry: ctk.CTkEntry | None = None,
) -> None:
    """Grid a label above a slider (and an optional entry next to the slider)."""
    label_row = row * 2 + 1
    control_row = row * 2 + 2
    label.grid(row=label_row, column=0, columnspan=2, padx=0, pady=(6, 2), sticky="w")
    parent.grid_columnconfigure(0, weight=1)
    slider.grid(row=control_row, column=0, padx=0, pady=(0, 4), sticky="ew")
    if entry is not None:
        entry.grid(row=control_row, column=1, padx=(8, 0), pady=(0, 4), sticky="e")


def wire_slider_entry(
    slider: ctk.CTkSlider,
    entry: ctk.CTkEntry,
    minimum: float,
    maximum: float,
    on_value,
    decimals: int = 2,
) -> None:
    """Keep a slider and a numeric entry in sync and call `on_value` on every change."""
    set_entry_text(entry, float(slider.get()), decimals)

    def on_slider(value: float) -> None:
        set_entry_text(entry, float(value), decimals)
        on_value(float(value))

    def commit(_event: object = None) -> str | None:
        raw = entry.get().strip().replace(",", ".")
        try:
            parsed = float(raw)
        except ValueError:
            set_entry_text(entry, float(slider.get()), decimals)
            return None
        clamped = max(minimum, min(maximum, parsed))
        slider.set(clamped)
        actual = float(slider.get())
        set_entry_text(entry, actual, decimals)
        on_value(actual)
        return "break"

    slider.configure(command=on_slider)
    internal = getattr(entry, "_entry", None)
    for sequence in ("<Return>", "<Key-Return>", "<FocusOut>"):
        entry.bind(sequence, commit)
        if internal is not None:
            internal.bind(sequence, commit, add="+")
    entry._numeric_commit = commit  # type: ignore[attr-defined]


def disable_all_slider_scrolling(root) -> None:
    """Disable mouse wheel changes on every slider below `root`.

    Otherwise scrolling the page would accidentally change slider values.
    """

    def disable(slider: ctk.CTkSlider) -> None:
        canvas = getattr(slider, "_canvas", None)
        if canvas is None:
            return
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            canvas.bind(sequence, lambda _event: "break")

    def walk(widget) -> None:
        for child in widget.winfo_children():
            if isinstance(child, ctk.CTkSlider):
                disable(child)
            walk(child)

    walk(root)


def create_value_block(
    parent: ctk.CTkFrame, column: int, title: str, initial_value: str
) -> ctk.CTkLabel:
    """Create a titled value box and return the label showing the value."""
    block = ctk.CTkFrame(parent)
    block.grid(row=0, column=column, padx=8, pady=12, sticky="nsew")

    ctk.CTkLabel(block, text=title, font=ctk.CTkFont(size=14)).pack(
        padx=12, pady=(12, 4)
    )
    value_label = ctk.CTkLabel(
        block,
        text=initial_value,
        font=ctk.CTkFont(size=22, weight="bold"),
    )
    value_label.pack(padx=12, pady=(0, 12))
    return value_label


def add_teensy_only_hint(parent: ctk.CTkFrame, feature: str, row: int) -> None:
    """Show the hint that a feature only works with a connected Teensy."""
    ctk.CTkLabel(
        parent,
        text=(
            f"{feature} only works while connected to Teensy and through "
            "the audio modules speaker. Without connection to the audio module "
            "a fallback option with pythons sounddevice library is used as synth, "
            "to enable playing around with sounds on the local device."
        ),
        text_color="gray70",
        anchor="w",
        justify="left",
        wraplength=720,
    ).grid(row=row, column=0, pady=(3, 0), sticky="ew")
