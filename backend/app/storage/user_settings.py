"""User settings persistence."""

from __future__ import annotations

import json
from pathlib import Path

from app.models import AppConfig

SETTINGS_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "settings.json"


def load_settings() -> AppConfig | None:
    if not SETTINGS_FILE.exists():
        return None
    try:
        data = json.loads(SETTINGS_FILE.read_text())
        return AppConfig(**data)
    except Exception:
        return None


def save_settings(config: AppConfig) -> None:
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(config.model_dump(), ensure_ascii=False, indent=2))
