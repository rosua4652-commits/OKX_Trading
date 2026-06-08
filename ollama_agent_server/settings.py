from functools import lru_cache
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    model_config = SettingsConfigDict(env_prefix="OLLAMA_AGENT_", env_file=".env", extra="ignore")

    ollama_base_url: str = "http://127.0.0.1:11434"
    default_model: str = "llama3.1"
    host: str = "0.0.0.0"
    port: int = 8080
    workspace_root: Path = Field(default_factory=lambda: Path.cwd())
    command_timeout_seconds: int = 60
    max_steps: int = 12
    max_command_output_chars: int = 12000
    require_api_key: bool = False
    api_key: str | None = None

    @property
    def resolved_workspace_root(self) -> Path:
        return self.workspace_root.expanduser().resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
