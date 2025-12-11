import json
from pathlib import Path

CONFIG_PATH = Path("debug_config.json")

DEFAULT_CONFIG = {
    "frontend_debug": False,
    "backend_debug": False,
    "inventory_debug": False,
    "network_debug": False,
}


def load_debug_config():
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text())
    return DEFAULT_CONFIG


def save_debug_config(config: dict):
    CONFIG_PATH.write_text(json.dumps(config, indent=2))
