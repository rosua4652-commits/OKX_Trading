"""Client-safe config serialization and merge on save."""

from __future__ import annotations

from app.models import AppConfig

_SENSITIVE = ("okx_api_key", "okx_api_secret", "okx_passphrase")


def api_keys_configured(config: AppConfig) -> bool:
    return bool(
        config.okx_api_key.strip()
        and config.okx_api_secret.strip()
        and config.okx_passphrase.strip()
    )


def merge_config_update(incoming: AppConfig, current: AppConfig) -> AppConfig:
    data = incoming.model_dump()
    for key in _SENSITIVE:
        if not str(data.get(key) or "").strip():
            data[key] = getattr(current, key)
    return AppConfig(**data)


def config_for_client(config: AppConfig) -> dict:
    data = config.model_dump()
    data["api_keys_configured"] = api_keys_configured(config)
    for key in _SENSITIVE:
        data[key] = ""
    return data
