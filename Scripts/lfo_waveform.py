"""
LFO cycle tables for the GUI editor and the Teensy RAM upload.

The firmware plays one 256-sample cycle (power of two). The PC owns the shape:
presets generate an exact cycle, the 8-point editor rebuilds a cycle, and both
are uploaded as int16 chunks. This module does not talk to serial itself.
"""

from __future__ import annotations

import numpy as np

LFO_WAVETABLE_SIZE = 256
LFO_POINT_COUNT = 16
LFO_TABLE_CHUNK_SIZE = 32

LFO_INTERP_LINEAR = "linear"
LFO_INTERP_STEP = "step"
DEFAULT_LFO_INTERP = LFO_INTERP_LINEAR
DEFAULT_LFO_PRESET = "sine"

LFO_PRESET_ORDER: list[str] = ["sine", "saw", "square", "triangle", "snh"]
LFO_PRESET_LABELS: dict[str, str] = {
    "sine": "Sine",
    "saw": "Saw",
    "square": "Square",
    "triangle": "Triangle",
    "snh": "S&H",
    "custom": "Custom",
}
LFO_INTERP_LABELS: dict[str, str] = {
    LFO_INTERP_LINEAR: "Linear",
    LFO_INTERP_STEP: "Step",
}

_FORMULA_PRESETS = {"sine", "triangle", "saw", "square"}
_KNOWN_PRESETS = _FORMULA_PRESETS | {"snh", "custom"}
_LEGACY_SHAPE_TO_PRESET = {
    "sine": "sine",
    "triangle": "triangle",
    "saw": "saw",
    "square": "square",
    "ramp": "saw",
}


def _phase() -> np.ndarray:
    return np.linspace(0.0, 1.0, LFO_WAVETABLE_SIZE, endpoint=False)


def point_indices() -> np.ndarray:
    step = LFO_WAVETABLE_SIZE // LFO_POINT_COUNT
    return np.arange(LFO_POINT_COUNT, dtype=np.int32) * step


def clamp_lfo_preset(value: object) -> str:
    name = str(value).strip().lower()
    return name if name in _KNOWN_PRESETS else DEFAULT_LFO_PRESET


def clamp_lfo_interp(value: object) -> str:
    name = str(value).strip().lower()
    return name if name in (LFO_INTERP_LINEAR, LFO_INTERP_STEP) else DEFAULT_LFO_INTERP


def lfo_preset_label(value: object) -> str:
    return LFO_PRESET_LABELS[clamp_lfo_preset(value)]


def lfo_interp_label(value: object) -> str:
    return LFO_INTERP_LABELS[clamp_lfo_interp(value)]


def lfo_interp_from_label(label: str) -> str:
    for name, text in LFO_INTERP_LABELS.items():
        if text == label:
            return name
    return DEFAULT_LFO_INTERP

# Clamps points in visual editor to -1.0 to 1.0
def clamp_lfo_points(value: object) -> list[float]:
    try:
        vals = [float(v) for v in value]  # type: ignore[union-attr]
    except (TypeError, ValueError):
        return sample_points_from_table(generate_preset_table(DEFAULT_LFO_PRESET))
    if len(vals) < LFO_POINT_COUNT:
        vals = vals + [0.0] * (LFO_POINT_COUNT - len(vals))
    elif len(vals) > LFO_POINT_COUNT:
        vals = vals[:LFO_POINT_COUNT]
    return [max(-1.0, min(1.0, v)) for v in vals]


def clamp_lfo_table(value: object) -> list[float]:
    try:
        arr = np.asarray(list(value), dtype=np.float64)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return generate_preset_table(DEFAULT_LFO_PRESET)
    if arr.size != LFO_WAVETABLE_SIZE:
        if arr.size < 2:
            return generate_preset_table(DEFAULT_LFO_PRESET)
        t_old = np.linspace(0.0, 1.0, arr.size, endpoint=False)
        t_new = np.linspace(0.0, 1.0, LFO_WAVETABLE_SIZE, endpoint=False)
        arr = np.interp(t_new, t_old, arr)
    return [float(x) for x in np.clip(arr, -1.0, 1.0)]


def sample_points_from_table(table: object) -> list[float]:
    arr = np.asarray(clamp_lfo_table(table), dtype=np.float64)
    return [float(arr[i]) for i in point_indices()]

# Converts points in visual editor to table for firmware
def points_to_table(points: object, interp: object) -> list[float]:
    pts = clamp_lfo_points(points)
    mode = clamp_lfo_interp(interp)
    step = LFO_WAVETABLE_SIZE // LFO_POINT_COUNT
    if mode == LFO_INTERP_STEP:
        table = np.empty(LFO_WAVETABLE_SIZE, dtype=np.float64)
        for i, level in enumerate(pts):
            table[i * step : (i + 1) * step] = level
        return [float(x) for x in table]
    xs = np.arange(LFO_POINT_COUNT + 1, dtype=np.float64) * step
    ys = np.array(pts + [pts[0]], dtype=np.float64)
    t = np.arange(LFO_WAVETABLE_SIZE, dtype=np.float64)
    return [float(x) for x in np.clip(np.interp(t, xs, ys), -1.0, 1.0)]


def generate_preset_table(preset: object, rng: np.random.Generator | None = None) -> list[float]:
    t = _phase()
    name = clamp_lfo_preset(preset)
    if name == "triangle":
        return (2.0 * np.abs(2.0 * t - 1.0) - 1.0).tolist()
    if name == "saw":
        return (2.0 * t - 1.0).tolist()
    if name == "square":
        return np.where(t < 0.5, 1.0, -1.0).astype(float).tolist()
    if name == "snh":
        engine = rng if rng is not None else np.random.default_rng()
        levels = engine.uniform(-1.0, 1.0, LFO_POINT_COUNT)
        return points_to_table(levels.tolist(), LFO_INTERP_STEP)
    return np.sin(2.0 * np.pi * t).tolist()


def apply_lfo_preset(preset: object, rng: np.random.Generator | None = None) -> tuple[str, str, list[float], list[float]]:
    name = clamp_lfo_preset(preset)
    if name == "custom":
        name = DEFAULT_LFO_PRESET
    if name == "snh":
        table = generate_preset_table("snh", rng=rng)
        return "snh", LFO_INTERP_STEP, sample_points_from_table(table), table
    table = generate_preset_table(name)
    return name, LFO_INTERP_LINEAR, sample_points_from_table(table), table


def default_lfo_table() -> list[float]:
    return generate_preset_table(DEFAULT_LFO_PRESET)


def default_lfo_points() -> list[float]:
    return sample_points_from_table(default_lfo_table())


def table_to_int16(samples: object) -> list[int]:
    arr = np.asarray(clamp_lfo_table(samples), dtype=np.float64)
    clipped = np.clip(np.round(arr * 32767.0), -32767, 32767).astype(np.int16)
    return [int(v) for v in clipped]


def lfo_state_from_mapping(data: dict | None) -> tuple[str, str, list[float], list[float]]:
    """Load preset/interp/points/table from config or setup JSON, including legacy lfo_shape."""
    payload = data or {}
    table_raw = payload.get("lfo_table")
    points_raw = payload.get("lfo_points")
    preset_raw = payload.get("lfo_preset")
    interp_raw = payload.get("lfo_interp")

    if table_raw is not None:
        table = clamp_lfo_table(table_raw)
        points = clamp_lfo_points(points_raw) if points_raw is not None else sample_points_from_table(table)
        preset = clamp_lfo_preset(preset_raw) if preset_raw is not None else "custom"
        interp = clamp_lfo_interp(interp_raw) if interp_raw is not None else DEFAULT_LFO_INTERP
        return preset, interp, points, table

    if points_raw is not None:
        points = clamp_lfo_points(points_raw)
        interp = clamp_lfo_interp(interp_raw) if interp_raw is not None else DEFAULT_LFO_INTERP
        preset = clamp_lfo_preset(preset_raw) if preset_raw is not None else "custom"
        return preset, interp, points, points_to_table(points, interp)

    if preset_raw is not None:
        preset = clamp_lfo_preset(preset_raw)
        if preset != "custom":
            return apply_lfo_preset(preset)

    legacy = payload.get("lfo_shape")
    if legacy is not None:
        mapped = _LEGACY_SHAPE_TO_PRESET.get(str(legacy).strip().lower(), DEFAULT_LFO_PRESET)
        return apply_lfo_preset(mapped)

    return apply_lfo_preset(DEFAULT_LFO_PRESET)
