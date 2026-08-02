"""Loads and validates configuration once, from config.json or the environment.

config.json (if present) wins over env vars, so a local instance key doesn't
require exporting shell variables. Fails fast with a clear message rather than
letting a missing key surface as a confusing error deep in the SDK.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_CONFIG_JSON_PATH = Path(__file__).parent / "config.json"


@dataclass(frozen=True)
class Config:
    synap_api_key: str
    instance_name: str
    openai_api_key: Optional[str]

    @property
    def has_openai(self) -> bool:
        return bool(self.openai_api_key)


def _load_config_json() -> dict:
    if not _CONFIG_JSON_PATH.exists():
        return {}
    raw = _CONFIG_JSON_PATH.read_text(encoding="utf-8").strip()
    if not raw:
        return {}
    return json.loads(raw)


def load_config() -> Config:
    file_values = _load_config_json()

    synap_api_key = file_values.get("MAXIMEM_API_KEY") or os.environ.get("SYNAP_API_KEY")
    # INSTANCE_NAME is a human-readable label, not the "inst_<hex16>" instance
    # id the SDK expects -- so it's kept only for display, and instance_id is
    # left empty for the SDK to auto-resolve from the API key at initialize().
    instance_name = file_values.get("INSTANCE_NAME", "")
    openai_api_key = os.environ.get("OPENAI_API_KEY")

    if not synap_api_key:
        raise RuntimeError(
            "Missing Synap API key. Set it in config.json as \"MAXIMEM_API_KEY\", "
            "or export SYNAP_API_KEY in your shell."
        )

    return Config(
        synap_api_key=synap_api_key,
        instance_name=instance_name,
        openai_api_key=openai_api_key,
    )
