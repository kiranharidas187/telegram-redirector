"""
Plain JSON config storage for the web portal — no database. config.json
holds which channels to listen to, their assigned voices, and tuning
settings. The portal frontend holds the full config client-side and PUTs
the whole thing back on any change, so this module only needs load/save.
"""

import json
from pathlib import Path
from typing import Any

CONFIG_PATH = Path(__file__).resolve().parent / "config.json"

DEFAULTS: dict[str, Any] = {
    "channels": [],
    "forward_targets": [],
    "speech_rate": 175,
    "volume": 1.0,
}


def load() -> dict:
    """Reads config.json from disk, filling in any missing keys with
    defaults. If the file doesn't exist yet, returns defaults without
    creating it — save() is what creates it, on first write."""
    if not CONFIG_PATH.exists():
        return {**DEFAULTS, "channels": []}
    with CONFIG_PATH.open() as f:
        data = json.load(f)
    return {**DEFAULTS, **data}


def save(config: dict) -> None:
    with CONFIG_PATH.open("w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")
