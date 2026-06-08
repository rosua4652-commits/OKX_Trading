from pathlib import Path

import pytest

pytest.importorskip("pydantic")

from ollama_agent_server.agent import run_agent
from ollama_agent_server.schemas import OllamaMessage
from ollama_agent_server.settings import Settings


class FakeOllama:
    def __init__(self) -> None:
        self.actions = [
            {"type": "command", "thought": "check cwd", "command": "pwd"},
            {"type": "final", "answer": "done"},
        ]

    def chat_json(
        self,
        model: str,
        messages: list[OllamaMessage],
        temperature: float,
        timeout_seconds: int,
    ) -> dict:
        return self.actions.pop(0)


def test_run_agent_reports_each_step_to_callback(tmp_path: Path) -> None:
    seen = []
    settings = Settings(workspace_root=tmp_path, command_timeout_seconds=5)

    response = run_agent(
        prompt="test",
        model="fake",
        workspace="",
        settings=settings,
        ollama=FakeOllama(),  # type: ignore[arg-type]
        max_steps=4,
        temperature=0.0,
        on_step=seen.append,
    )

    assert response.answer == "done"
    assert [step.index for step in seen] == [1, 2]
    assert seen[0].result is not None
    assert seen[0].result.exit_code == 0
