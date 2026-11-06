"""User settings and where data lives (default ~/.building-code-assistant, override with BCA_HOME)."""
import json
import os

DEFAULTS = {"region": None, "backend": "auto", "pins": {}}


def home():
    path = os.environ.get("BCA_HOME") or os.path.join(os.path.expanduser("~"), ".building-code-assistant")
    os.makedirs(path, exist_ok=True)
    return path


def _config_path():
    return os.path.join(home(), "config.json")


def load():
    cfg = dict(DEFAULTS)
    try:
        with open(_config_path(), encoding="utf-8") as f:
            cfg.update(json.load(f))
    except FileNotFoundError:
        pass
    return cfg


def save(cfg):
    with open(_config_path(), "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def is_set_up():
    return os.path.exists(_config_path())
