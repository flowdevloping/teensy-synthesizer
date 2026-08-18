"""
Contains functionality to save latest configuration
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"

from safety_limits import (
    DEFAULT_VOLUME_PCT,
    clamp_mod_depth_pct,
    clamp_modulator_hz,
    clamp_modulator_ratio,
    clamp_volume_pct,
)
@dataclass
class AppConfig:
    last_port: str | None = None
    last_midi_port: str | None = None
    auto_reconnect: bool = True
    key_frequencies: dict[str, float] = field(default_factory=dict)
    modulator_hz: float = 20.0
    modulator_mode: str = "fixed"
    modulator_ratio: float = 1.0
    volume_pct: int = DEFAULT_VOLUME_PCT
    mod_depth_pct: int = 20
    active_preset: str = "Standard"
    local_audio_enabled: bool = True
    last_setup_name: str = ""


# Loads the config from the config file defined in CONFIG_PATH
def load_config() -> AppConfig:
    if not CONFIG_PATH.exists():
        return AppConfig()

    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return AppConfig()

    return AppConfig(
        last_port=data.get("last_port"),
        last_midi_port=data.get("last_midi_port"),
        auto_reconnect=bool(data.get("auto_reconnect", True)),
        key_frequencies={
            str(k): float(v)
            for k, v in (data.get("key_frequencies") or {}).items()
        },
        modulator_hz=clamp_modulator_hz(float(data.get("modulator_hz", 20.0))),
        modulator_mode=str(data.get("modulator_mode", "fixed")),
        modulator_ratio=clamp_modulator_ratio(float(data.get("modulator_ratio", 1.0))),
        volume_pct=clamp_volume_pct(int(data.get("volume_pct", DEFAULT_VOLUME_PCT))),
        mod_depth_pct=clamp_mod_depth_pct(int(data.get("mod_depth_pct", 20))),
        active_preset=str(data.get("active_preset", "Standard")),
        local_audio_enabled=bool(data.get("local_audio_enabled", True)),
        last_setup_name=str(data.get("last_setup_name", "")),
    )


# Saves the config to the config file defined in CONFIG_PATH
def save_config(config: AppConfig) -> None:
    data = {
        "last_port": config.last_port,
        "last_midi_port": config.last_midi_port,
        "auto_reconnect": config.auto_reconnect,
        "key_frequencies": config.key_frequencies,
        "modulator_hz": config.modulator_hz,
        "modulator_mode": config.modulator_mode,
        "modulator_ratio": config.modulator_ratio,
        "volume_pct": config.volume_pct,
        "mod_depth_pct": config.mod_depth_pct,
        "active_preset": config.active_preset,
        "local_audio_enabled": config.local_audio_enabled,
        "last_setup_name": config.last_setup_name,
    }
    CONFIG_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
