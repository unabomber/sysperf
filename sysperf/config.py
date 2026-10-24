"""Persistent user defaults stored as JSON (no extra dependency needed).

Location follows the XDG convention: $XDG_CONFIG_HOME/sysperf/config.json,
falling back to ~/.config/sysperf/config.json.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional


def default_config_path() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "sysperf", "config.json")


def load_config(path: Optional[str] = None) -> Dict[str, Any]:
    path = path or default_config_path()
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_config(data: Dict[str, Any], path: Optional[str] = None) -> str:
    path = path or default_config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return path
