import json
from typing import Any

import requests

from .schemas import OllamaChatRequest, OllamaMessage


class OllamaError(RuntimeError):
    """Raised when Ollama cannot provide a usable response."""


class OllamaClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def chat_json(
        self,
        model: str,
        messages: list[OllamaMessage],
        temperature: float,
        timeout_seconds: int,
    ) -> dict[str, Any]:
        payload = OllamaChatRequest(
            model=model,
            messages=messages,
            stream=False,
            format="json",
            options={"temperature": temperature},
        ).model_dump(exclude_none=True)
        response = requests.post(f"{self.base_url}/api/chat", json=payload, timeout=timeout_seconds)
        response.raise_for_status()
        data = response.json()
        content = data.get("message", {}).get("content", "")
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise OllamaError(f"Ollama returned non-JSON content: {content[:500]}") from exc
        if not isinstance(parsed, dict):
            raise OllamaError("Ollama JSON response must be an object")
        return parsed

    def tags(self) -> dict[str, Any]:
        response = requests.get(f"{self.base_url}/api/tags", timeout=10)
        response.raise_for_status()
        return response.json()
