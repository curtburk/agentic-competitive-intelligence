"""
competitive_intel/config.py
Configuration loading from YAML.
"""

import yaml
from pathlib import Path


def load_config(path: str = "/config/competitors.yml") -> dict:
    """Load pipeline configuration from YAML file."""
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(config_path) as f:
        config = yaml.safe_load(f)

    required_keys = ["competitors", "hp_positioning"]
    for key in required_keys:
        if key not in config:
            raise ValueError(f"Config missing required key: {key}")

    # Validate competitor structure
    for comp in config["competitors"]:
        if "name" not in comp:
            raise ValueError(f"Competitor missing 'name': {comp}")

    return config
