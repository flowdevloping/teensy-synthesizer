"""
Contains functionality to save/load synth setups and export configurations defined by the user
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

SETUPS_DIR = Path(__file__).resolve().parent.parent / "setups"
EXPORTS_DIR = Path(__file__).resolve().parent.parent / "exports"


# Data class for a synth setup
@dataclass
class SynthSetup:
    name: str
    synth_mode: str
    params: dict
    notes: str = ""
    version: int = 1

# Safely converts a filename to a safe filename
def _safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^\w\-]+", "_", name.strip(), flags=re.UNICODE)
    return cleaned[:80] or "setup"

# Ensures that the setup and export directories exist
def ensure_dirs() -> None:
    SETUPS_DIR.mkdir(parents=True, exist_ok=True)
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

# Lists all setups in the setup directory
def list_setups() -> list[str]:
    ensure_dirs()
    return sorted(p.stem for p in SETUPS_DIR.glob("*.json"))

# Saves a setup to the setup directory
def save_setup(setup: SynthSetup) -> Path:
    ensure_dirs()
    path = SETUPS_DIR / f"{_safe_filename(setup.name)}.json"
    data = {
        "name": setup.name,
        "synth_mode": setup.synth_mode,
        "version": setup.version,
        "params": setup.params,
        "notes": setup.notes,
    }
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


# Loads a setup from the setup directory
def load_setup(name: str) -> SynthSetup | None:
    path = SETUPS_DIR / f"{_safe_filename(name)}.json"
    if not path.exists():
        # try exact stem match from list
        path = SETUPS_DIR / f"{name}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return SynthSetup(
        name=str(data.get("name", name)),
        synth_mode=str(data.get("synth_mode", "fm")),
        params=dict(data.get("params") or {}),
        notes=str(data.get("notes", "")),
        version=int(data.get("version", 1)),
    )

# Exports a setup to a User specification
def export_hiwi_spec(setup: SynthSetup) -> Path:
    ensure_dirs()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = f"{_safe_filename(setup.name)}_{stamp}"
    json_path = EXPORTS_DIR / f"{base}.json"
    md_path = EXPORTS_DIR / f"{base}.md"

    save_data = {
        "name": setup.name,
        "synth_mode": setup.synth_mode,
        "version": setup.version,
        "params": setup.params,
        "notes": setup.notes,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "teensy_status": "pending_manual_port",
    }
    json_path.write_text(
        json.dumps(save_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    lines = [
        f"# Synth Setup Spec: {setup.name}",
        "",
        f"- Mode: `{setup.synth_mode}`",
        f"- Exported: {save_data['exported_at']}",
        f"- Teensy: manual porting by assistant",
        "",
        "## Notes",
        setup.notes or "—",
        "",
        "## Parameters",
        "```json",
        json.dumps(setup.params, indent=2, ensure_ascii=False),
        "```",
        "",
    ]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path
