from pathlib import Path

import pytest

from ollama_agent_server.runner import WorkspaceError, resolve_workspace, run_command


def test_resolve_workspace_stays_under_root(tmp_path: Path) -> None:
    workspace = resolve_workspace(tmp_path, "project-a")
    assert workspace == tmp_path / "project-a"
    assert workspace.exists()


def test_resolve_workspace_rejects_escape(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceError):
        resolve_workspace(tmp_path, "../outside")


def test_run_command_captures_stdout(tmp_path: Path) -> None:
    result = run_command("printf hello", tmp_path, timeout_seconds=5, max_output_chars=100)
    assert result.exit_code == 0
    assert result.stdout == "hello"
    assert result.stderr == ""
    assert not result.timed_out
