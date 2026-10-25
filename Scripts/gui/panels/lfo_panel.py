"""LFO panel: waveform presets, editable waveform canvas, rate and depth."""

from tkinter import Canvas

import customtkinter as ctk

from synth.lfo_waveform import (
    LFO_PRESET_LABELS,
    LFO_PRESET_ORDER,
    LFO_WAVETABLE_SIZE,
    lfo_interp_from_label,
    lfo_interp_label,
    point_indices,
)
from synth.safety_limits import (
    LFO_MAX_DEPTH_PCT,
    LFO_MAX_RATE_HZ,
    LFO_MIN_RATE_HZ,
    clamp_lfo_depth_pct,
    clamp_lfo_rate,
)
from gui.synth_controller import SynthController
from gui.widgets import (
    add_labeled_slider,
    add_teensy_only_hint,
    set_entry_text,
    wire_slider_entry,
)


class LfoPanel:
    """Builds the LFO controls. The LFO only sounds on the Teensy.

    The waveform is edited by dragging 16 points on a canvas. The resulting table is
    sent to the Teensy shortly after the last movement.

    Args:
        parent: Widget the panel frame is created in.
        controller (SynthController): Application logic.

    Attributes:
        frame (ctk.CTkFrame): The panel frame. The caller places it in the layout.
    """

    def __init__(self, parent, controller: SynthController) -> None:
        self.controller = controller
        self.state = controller.state

        self._lfo_drag_index: int | None = None
        self._lfo_table_send_after: object | None = None
        self._lfo_gui_syncing = False
        self._lfo_preset_buttons: dict[str, ctk.CTkButton] = {}

        self.frame = ctk.CTkFrame(parent, fg_color="transparent")
        self._build()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build(self) -> None:
        lfo = self.frame
        lfo.grid_columnconfigure(0, weight=1)
        state = self.state

        header = ctk.CTkFrame(lfo, fg_color="transparent")
        header.grid(row=0, column=0, columnspan=2, pady=(4, 4), sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header,
            text="LFO",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=0, column=0, sticky="w")
        add_teensy_only_hint(header, "LFO", row=1)

        shape_row = ctk.CTkFrame(lfo, fg_color="transparent")
        shape_row.grid(row=1, column=0, columnspan=2, pady=(0, 6), sticky="ew")
        shape_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(shape_row, text="LFO shape").grid(
            row=0, column=0, padx=(0, 8), sticky="w"
        )

        preset_row = ctk.CTkFrame(shape_row, fg_color="transparent")
        preset_row.grid(row=0, column=1, sticky="w")
        self._lfo_preset_buttons = {}
        for column, name in enumerate(LFO_PRESET_ORDER):
            button = ctk.CTkButton(
                preset_row,
                text=LFO_PRESET_LABELS[name],
                width=64,
                command=lambda preset=name: self._on_preset_clicked(preset),
            )
            button.grid(row=0, column=column, padx=(0, 6), sticky="w")
            self._lfo_preset_buttons[name] = button

        self.lfo_interp_var = ctk.StringVar(value=lfo_interp_label(state.lfo_interp))
        self.lfo_interp_switch = ctk.CTkSegmentedButton(
            shape_row,
            values=["Linear", "Step"],
            variable=self.lfo_interp_var,
            command=self._on_interp_changed,
            width=140,
        )
        self.lfo_interp_switch.grid(row=0, column=2, padx=(8, 0), sticky="e")

        canvas_host = ctk.CTkFrame(lfo, fg_color="gray17", corner_radius=6)
        canvas_host.grid(row=2, column=0, columnspan=2, pady=(0, 4), sticky="ew")
        canvas_host.grid_columnconfigure(0, weight=1)
        self.lfo_canvas = Canvas(
            canvas_host,
            height=90,
            bg="#1a1a1a",
            highlightthickness=0,
            bd=0,
        )
        self.lfo_canvas.grid(row=0, column=0, padx=4, pady=4, sticky="ew")
        self.lfo_canvas.bind("<Configure>", self._on_canvas_configure)
        self.lfo_canvas.bind("<ButtonPress-1>", self._on_canvas_press)
        self.lfo_canvas.bind("<B1-Motion>", self._on_canvas_motion)
        self.lfo_canvas.bind("<ButtonRelease-1>", self._on_canvas_release)
        self.lfo_canvas.after(1, self._draw_canvas)
        self.sync_waveform()

        self.lfo_rate_label = ctk.CTkLabel(
            lfo, text=f"LFO rate: {state.lfo_rate_hz:.2f} Hz"
        )
        self.lfo_rate_slider = ctk.CTkSlider(
            lfo, from_=LFO_MIN_RATE_HZ, to=LFO_MAX_RATE_HZ
        )
        self.lfo_rate_slider.set(state.lfo_rate_hz)
        self.lfo_rate_entry = ctk.CTkEntry(lfo, width=70)

        self.lfo_depth_label = ctk.CTkLabel(
            lfo, text=f"LFO depth: {state.lfo_depth_pct} %"
        )
        self.lfo_depth_slider = ctk.CTkSlider(
            lfo, from_=0, to=LFO_MAX_DEPTH_PCT, number_of_steps=LFO_MAX_DEPTH_PCT
        )
        self.lfo_depth_slider.set(state.lfo_depth_pct)
        self.lfo_depth_entry = ctk.CTkEntry(lfo, width=70)

        add_labeled_slider(
            lfo, 1, self.lfo_rate_label, self.lfo_rate_slider, self.lfo_rate_entry
        )
        add_labeled_slider(
            lfo, 2, self.lfo_depth_label, self.lfo_depth_slider, self.lfo_depth_entry
        )

        wire_slider_entry(
            self.lfo_rate_slider,
            self.lfo_rate_entry,
            LFO_MIN_RATE_HZ,
            LFO_MAX_RATE_HZ,
            self._on_rate_changed,
            decimals=2,
        )
        wire_slider_entry(
            self.lfo_depth_slider,
            self.lfo_depth_entry,
            0,
            LFO_MAX_DEPTH_PCT,
            self._on_depth_changed,
            decimals=0,
        )

    # ------------------------------------------------------------------
    # Rate / depth / shape handlers
    # ------------------------------------------------------------------

    def _on_rate_changed(self, value: float) -> None:
        self.state.lfo_rate_hz = clamp_lfo_rate(value)
        self.controller.save_config()
        self.controller.send_lfo()

    def _on_depth_changed(self, value: float) -> None:
        self.state.lfo_depth_pct = clamp_lfo_depth_pct(value)
        self.controller.save_config()
        self.controller.send_lfo()

    def _on_preset_clicked(self, preset: str) -> None:
        self.state.set_lfo_preset(preset)
        self.sync_waveform()
        self.controller.save_config()
        self.controller.send_lfo_table()

    def _on_interp_changed(self, value: str) -> None:
        if self._lfo_gui_syncing:
            return
        self.state.lfo_interp = lfo_interp_from_label(value)
        self.state.rebuild_lfo_from_points(mark_custom=True)
        self.sync_waveform()
        self.controller.save_config()
        self.controller.send_lfo_table()

    # ------------------------------------------------------------------
    # Sync with the synth state
    # ------------------------------------------------------------------

    def sync_waveform(self) -> None:
        """Highlight the active preset / interpolation and redraw the canvas."""
        self._lfo_gui_syncing = True
        active = self.state.lfo_preset
        for name, button in self._lfo_preset_buttons.items():
            if name == active:
                button.configure(fg_color="#1f6aa5", hover_color="#144870")
            else:
                button.configure(fg_color="gray30", hover_color="gray40")
        self.lfo_interp_var.set(lfo_interp_label(self.state.lfo_interp))
        self._draw_canvas()
        self._lfo_gui_syncing = False

    def sync_controls(self) -> None:
        """Move sliders and the waveform view to the values of the synth state."""
        self.lfo_rate_slider.set(self.state.lfo_rate_hz)
        self.lfo_depth_slider.set(self.state.lfo_depth_pct)
        self.sync_waveform()

    def refresh(self) -> None:
        """Update labels and entries from the synth state."""
        state = self.state
        self.lfo_rate_label.configure(text=f"LFO rate: {state.lfo_rate_hz:.2f} Hz")
        self.lfo_depth_label.configure(text=f"LFO depth: {state.lfo_depth_pct} %")
        set_entry_text(self.lfo_rate_entry, float(state.lfo_rate_hz), 2)
        set_entry_text(self.lfo_depth_entry, float(state.lfo_depth_pct), 0)

    # ------------------------------------------------------------------
    # Waveform canvas
    # ------------------------------------------------------------------

    # Return the width, height, and padding of the LFO canvas
    def _canvas_metrics(self) -> tuple[int, int, int, int]:
        width = max(self.lfo_canvas.winfo_width(), 2)
        height = max(self.lfo_canvas.winfo_height(), 2)
        return width, height, 12, 10

    # Convert sample index and value to x, y coordinates in canvas
    def _canvas_xy(self, sample_index: float, value: float) -> tuple[float, float]:
        width, height, pad_x, pad_y = self._canvas_metrics()
        inner_w = max(1, width - 2 * pad_x)
        inner_h = max(1, height - 2 * pad_y)
        x = pad_x + (sample_index / LFO_WAVETABLE_SIZE) * inner_w
        y = pad_y + (1.0 - (value + 1.0) / 2.0) * inner_h
        return x, y

    # Convert y coordinate in canvas to value (-1.0 to 1.0)
    def _canvas_y_to_value(self, y: float) -> float:
        _width, height, _pad_x, pad_y = self._canvas_metrics()
        inner_h = max(1, height - 2 * pad_y)
        value = 1.0 - 2.0 * (y - pad_y) / inner_h
        return max(-1.0, min(1.0, value))

    def _draw_canvas(self) -> None:
        canvas = self.lfo_canvas
        canvas.delete("all")
        width, height, _pad_x, _pad_y = self._canvas_metrics()
        if width < 20 or height < 20:
            return

        zero_left = self._canvas_xy(0, 0.0)
        zero_right = self._canvas_xy(LFO_WAVETABLE_SIZE, 0.0)
        canvas.create_line(
            zero_left[0], zero_left[1], zero_right[0], zero_right[1], fill="#3a3a3a"
        )

        table = self.state.lfo_table
        polyline: list[float] = []
        for index, sample in enumerate(table):
            x, y = self._canvas_xy(index, sample)
            polyline.extend((x, y))
        end_x, end_y = self._canvas_xy(LFO_WAVETABLE_SIZE, table[0])
        polyline.extend((end_x, end_y))
        canvas.create_line(*polyline, fill="#3b8ed0", width=2)

        for i, sample_index in enumerate(point_indices()):
            x, y = self._canvas_xy(int(sample_index), self.state.lfo_points[i])
            radius = 5
            canvas.create_oval(
                x - radius,
                y - radius,
                x + radius,
                y + radius,
                fill="#ffffff",
                outline="#1f6aa5",
                width=1,
            )

    def _on_canvas_configure(self, _event) -> None:
        self._draw_canvas()

    def _hit_handle(self, x: float, y: float) -> int | None:
        best_index: int | None = None
        best_dist = 14.0**2
        for i, sample_index in enumerate(point_indices()):
            hx, hy = self._canvas_xy(int(sample_index), self.state.lfo_points[i])
            dist = (x - hx) ** 2 + (y - hy) ** 2
            if dist < best_dist:
                best_dist = dist
                best_index = i
        return best_index

    def _apply_point_drag(self, y: float) -> None:
        if self._lfo_drag_index is None:
            return
        points = list(self.state.lfo_points)
        points[self._lfo_drag_index] = self._canvas_y_to_value(y)
        self.state.lfo_points = points
        self.state.rebuild_lfo_from_points(mark_custom=True)
        self.sync_waveform()
        self._schedule_table_send()

    def _on_canvas_press(self, event) -> None:
        self._lfo_drag_index = self._hit_handle(event.x, event.y)
        if self._lfo_drag_index is not None:
            self._apply_point_drag(event.y)

    def _on_canvas_motion(self, event) -> None:
        if self._lfo_drag_index is None:
            return
        self._apply_point_drag(event.y)

    def _on_canvas_release(self, _event) -> None:
        if self._lfo_drag_index is None:
            return
        self._lfo_drag_index = None
        self._cancel_table_send()
        self.controller.save_config()
        self.controller.send_lfo_table()

    # ------------------------------------------------------------------
    # Delayed table transmission while dragging
    # ------------------------------------------------------------------

    def _schedule_table_send(self, delay_ms: int = 80) -> None:
        if self._lfo_table_send_after is not None:
            self.frame.after_cancel(self._lfo_table_send_after)
        self._lfo_table_send_after = self.frame.after(delay_ms, self._flush_table_send)

    def _flush_table_send(self) -> None:
        self._lfo_table_send_after = None
        self.controller.send_lfo_table()

    def _cancel_table_send(self) -> None:
        if self._lfo_table_send_after is not None:
            self.frame.after_cancel(self._lfo_table_send_after)
            self._lfo_table_send_after = None
