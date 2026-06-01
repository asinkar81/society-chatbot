"""
Helper utilities
"""
import json
from pathlib import Path
from typing import Any, Dict


def save_json(data: Dict[str, Any], filepath: Path):
    """Save dictionary to JSON file"""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2, default=str)


def load_json(filepath: Path) -> Dict[str, Any]:
    """Load dictionary from JSON file"""
    if not filepath.exists():
        return {}
    with open(filepath, "r") as f:
        return json.load(f)


def safe_get(dictionary: Dict, key: str, default=None):
    """Safely get nested dictionary value"""
    keys = key.split(".")
    value = dictionary
    for k in keys:
        if isinstance(value, dict):
            value = value.get(k, default)
        else:
            return default
    return value
