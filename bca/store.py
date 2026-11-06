"""Local law storage. Each amendment is kept as its own snapshot so you can pin an older version.

    <home>/laws/<law id>/<amended YYYYMMDD>.json
"""
import json
import os

from . import config


def _dir(law_id):
    return os.path.join(config.home(), "laws", law_id)


def save(law):
    """Write a snapshot. Returns True if it is new, False if that version was already stored."""
    d = _dir(law["id"])
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, law["amended"] + ".json")
    if os.path.exists(path):
        return False
    with open(path, "w", encoding="utf-8") as f:
        json.dump(law, f, ensure_ascii=False)
    return True


def versions(law_id):
    try:
        return sorted(n[:-5] for n in os.listdir(_dir(law_id)) if n.endswith(".json"))
    except FileNotFoundError:
        return []


def load(law_id, pin=None):
    """Load the pinned version, or the latest one. None if nothing is stored."""
    have = versions(law_id)
    if not have:
        return None
    version = pin if pin in have else have[-1]
    with open(os.path.join(_dir(law_id), version + ".json"), encoding="utf-8") as f:
        return json.load(f)


def load_all(entries, pins=None):
    pins = pins or {}
    laws = []
    for e in entries:
        law = load(e["id"], pins.get(e["id"]))
        if law:
            laws.append(law)
    return laws
