import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class CommandResult:
    command: str
    cwd: str
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool = False

    def model_dump_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


class WorkspaceError(ValueError):
    """Raised when a requested workspace escapes the configured root."""


def resolve_workspace(root: Path, requested: str | None) -> Path:
    root = root.expanduser().resolve()
    workspace = root if not requested else (root / requested).expanduser().resolve()
    if workspace != root and root not in workspace.parents:
        raise WorkspaceError(f"workspace must stay under {root}")
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def run_command(command: str, cwd: Path, timeout_seconds: int, max_output_chars: int) -> CommandResult:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            shell=True,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            executable="/bin/bash",
        )
        return CommandResult(
            command=command,
            cwd=str(cwd),
            exit_code=completed.returncode,
            stdout=_trim(completed.stdout, max_output_chars),
            stderr=_trim(completed.stderr, max_output_chars),
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            command=command,
            cwd=str(cwd),
            exit_code=None,
            stdout=_trim(exc.stdout or "", max_output_chars),
            stderr=_trim(exc.stderr or "", max_output_chars),
            timed_out=True,
        )


def _trim(value: str | bytes, max_chars: int) -> str:
    if isinstance(value, bytes):
        value = value.decode(errors="replace")
    if len(value) <= max_chars:
        return value
    omitted = len(value) - max_chars
    return value[:max_chars] + f"\n...[trimmed {omitted} chars]"
