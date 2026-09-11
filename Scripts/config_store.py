"""
Contains functionality to save latest configuration
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"

from safety_limits import (
    DEFAULT_VOLUME_PCT,
    FILTER_DEFAULT_CUTOFF_HZ,
    FILTER_DEFAULT_Q,
    LFO_DEFAULT_DEPTH_PCT,
    LFO_DEFAULT_RATE_HZ,
    clamp_filter_cutoff,
    clamp_filter_q,
    clamp_lfo_depth_pct,
    clamp_lfo_rate,
    clamp_mod_depth_pct,
    clamp_modulator_hz,
    clamp_modulator_ratio,
    clamp_volume_pct,
)
from lfo_waveform import (
    DEFAULT_LFO_INTERP,
    DEFAULT_LFO_PRESET,
    default_lfo_points,
    default_lfo_table,
    lfo_state_from_mapping,
)
from waveforms import (
    DEFAULT_CARRIER_WAVEFORM,
    clamp_carrier_waveform,
)
@dataclass
class AppConfig:
    last_port: str | None = None
    last_midi_port: str | None = None
    auto_reconnect: bool = True
    key_frequencies: dict[str, float] = field(default_factory=dict)
    carrier_waveform: str = DEFAULT_CARRIER_WAVEFORM
    modulator_hz: float = 20.0
    modulator_mode: str = "fixed"
    modulator_ratio: float = 1.0
    volume_pct: int = DEFAULT_VOLUME_PCT
    mod_depth_pct: int = 20
    lfo_rate_hz: float = LFO_DEFAULT_RATE_HZ
    lfo_depth_pct: int = LFO_DEFAULT_DEPTH_PCT
    lfo_preset: str = DEFAULT_LFO_PRESET
    lfo_interp: str = DEFAULT_LFO_INTERP
    lfo_points: list[float] = field(default_factory=default_lfo_points)
    lfo_table: list[float] = field(default_factory=default_lfo_table)
    filter_cutoff_hz: float = FILTER_DEFAULT_CUTOFF_HZ
    filter_resonance: float = FILTER_DEFAULT_Q
    active_preset: str = "Standard"
    local_audio_enabled: bool = True
    last_setup_name: str = ""


# Function to load the config from the config file defined in CONFIG_PATH
def load_config() -> AppConfig:
    if not CONFIG_PATH.exists():
        return AppConfig()

    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return AppConfig()

    _lfo_preset, _lfo_interp, _lfo_points, _lfo_table = lfo_state_from_mapping(data)

    return AppConfig(
        last_port=data.get("last_port"),
        last_midi_port=data.get("last_midi_port"),
        auto_reconnect=bool(data.get("auto_reconnect", True)),
        key_frequencies={
            str(k): float(v)
            for k, v in (data.get("key_frequencies") or {}).items()
        },
        carrier_waveform=clamp_carrier_waveform(
            data.get("carrier_waveform", DEFAULT_CARRIER_WAVEFORM)
        ),
        modulator_hz=clamp_modulator_hz(float(data.get("modulator_hz", 20.0))),
        modulator_mode=str(data.get("modulator_mode", "fixed")),
        modulator_ratio=clamp_modulator_ratio(float(data.get("modulator_ratio", 1.0))),
        volume_pct=clamp_volume_pct(int(data.get("volume_pct", DEFAULT_VOLUME_PCT))),
        mod_depth_pct=clamp_mod_depth_pct(int(data.get("mod_depth_pct", 20))),
        lfo_rate_hz=clamp_lfo_rate(float(data.get("lfo_rate_hz", LFO_DEFAULT_RATE_HZ))),
        lfo_depth_pct=clamp_lfo_depth_pct(int(data.get("lfo_depth_pct", LFO_DEFAULT_DEPTH_PCT))),
        lfo_preset=_lfo_preset,
        lfo_interp=_lfo_interp,
        lfo_points=_lfo_points,
        lfo_table=_lfo_table,
        filter_cutoff_hz=clamp_filter_cutoff(float(data.get("filter_cutoff_hz", FILTER_DEFAULT_CUTOFF_HZ))),
        filter_resonance=clamp_filter_q(float(data.get("filter_resonance", FILTER_DEFAULT_Q))),
        active_preset=str(data.get("active_preset", "Standard")),
        local_audio_enabled=bool(data.get("local_audio_enabled", True)),
        last_setup_name=str(data.get("last_setup_name", "")),
    )


# Function to save the config to the config file defined in CONFIG_PATH
def save_config(config: AppConfig) -> None:
    data = {
        "last_port": config.last_port,
        "last_midi_port": config.last_midi_port,
        "auto_reconnect": config.auto_reconnect,
        "key_frequencies": config.key_frequencies,
        "carrier_waveform": config.carrier_waveform,
        "modulator_hz": config.modulator_hz,
        "modulator_mode": config.modulator_mode,
        "modulator_ratio": config.modulator_ratio,
        "volume_pct": config.volume_pct,
        "mod_depth_pct": config.mod_depth_pct,
        "lfo_rate_hz": config.lfo_rate_hz,
        "lfo_depth_pct": config.lfo_depth_pct,
        "lfo_preset": config.lfo_preset,
        "lfo_interp": config.lfo_interp,
        "lfo_points": list(config.lfo_points),
        "lfo_table": list(config.lfo_table),
        "filter_cutoff_hz": config.filter_cutoff_hz,
        "filter_resonance": config.filter_resonance,
        "active_preset": config.active_preset,
        "local_audio_enabled": config.local_audio_enabled,
        "last_setup_name": config.last_setup_name,
    }
    CONFIG_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
