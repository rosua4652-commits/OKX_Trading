import json
<<<<<<< ours
<<<<<<< ours
<<<<<<< ours
=======
from collections.abc import Callable

>>>>>>> theirs
=======
from collections.abc import Callable

>>>>>>> theirs
=======
from collections.abc import Callable

>>>>>>> theirs
from pydantic import ValidationError

from .ollama import OllamaClient, OllamaError
from .runner import run_command
from .schemas import AgentStep, CommandAction, FinalAction, OllamaMessage, RunResponse
from .settings import Settings

SYSTEM_PROMPT = """
You are an autonomous coding and debugging agent running inside a Linux server.
A remote user sends tasks through an API. You can inspect files, run tests, debug
errors, edit code with shell commands, and then return a concise final answer.

You MUST respond with exactly one JSON object and no markdown.
Use one of these shapes:
{"type":"command","thought":"why this command is needed","command":"bash command"}
{"type":"final","answer":"final response to the remote user"}

Rules:
- Prefer small, inspectable commands before editing.
- Include exact test/check results in the final answer when relevant.
- Do not claim success unless command output supports it.
- The shell already runs on the target Ollama host in the selected workspace.
""".strip()


def run_agent(
    *,
    prompt: str,
    model: str,
    workspace: str,
    settings: Settings,
    ollama: OllamaClient,
    max_steps: int,
    temperature: float,
<<<<<<< ours
<<<<<<< ours
<<<<<<< ours
=======
    on_step: Callable[[AgentStep], None] | None = None,
>>>>>>> theirs
=======
    on_step: Callable[[AgentStep], None] | None = None,
>>>>>>> theirs
=======
    on_step: Callable[[AgentStep], None] | None = None,
>>>>>>> theirs
) -> RunResponse:
    messages: list[OllamaMessage] = [
        OllamaMessage(role="system", content=SYSTEM_PROMPT),
        OllamaMessage(role="user", content=prompt),
    ]
    steps: list[AgentStep] = []

    for index in range(1, max_steps + 1):
        raw_action = ollama.chat_json(
            model=model,
            messages=messages,
            temperature=temperature,
            timeout_seconds=settings.command_timeout_seconds,
        )
        action = _parse_action(raw_action)

        if isinstance(action, FinalAction):
<<<<<<< ours
<<<<<<< ours
<<<<<<< ours
            steps.append(AgentStep(index=index, action=action))
=======
=======
>>>>>>> theirs
=======
>>>>>>> theirs
            step = AgentStep(index=index, action=action)
            steps.append(step)
            if on_step:
                on_step(step)
<<<<<<< ours
<<<<<<< ours
>>>>>>> theirs
=======
>>>>>>> theirs
=======
>>>>>>> theirs
            return RunResponse(answer=action.answer, model=model, workspace=workspace, steps=steps)

        result = run_command(
            action.command,
            cwd=settings.resolved_workspace_root / workspace if workspace else settings.resolved_workspace_root,
            timeout_seconds=settings.command_timeout_seconds,
            max_output_chars=settings.max_command_output_chars,
        )
        step = AgentStep(index=index, action=action, result=result)
        steps.append(step)
<<<<<<< ours
<<<<<<< ours
<<<<<<< ours
=======
        if on_step:
            on_step(step)
>>>>>>> theirs
=======
        if on_step:
            on_step(step)
>>>>>>> theirs
=======
        if on_step:
            on_step(step)
>>>>>>> theirs
        messages.append(OllamaMessage(role="assistant", content=json.dumps(raw_action, ensure_ascii=False)))
        messages.append(
            OllamaMessage(
                role="user",
                content="Command result JSON:\n" + result.model_dump_json(),
            )
        )

    fallback = "Reached the maximum number of agent steps before a final answer was produced."
<<<<<<< ours
<<<<<<< ours
<<<<<<< ours
    steps.append(AgentStep(index=max_steps + 1, action=FinalAction(answer=fallback)))
=======
=======
>>>>>>> theirs
=======
>>>>>>> theirs
    step = AgentStep(index=max_steps + 1, action=FinalAction(answer=fallback))
    steps.append(step)
    if on_step:
        on_step(step)
<<<<<<< ours
<<<<<<< ours
>>>>>>> theirs
=======
>>>>>>> theirs
=======
>>>>>>> theirs
    return RunResponse(answer=fallback, model=model, workspace=workspace, steps=steps)


def _parse_action(raw_action: dict) -> CommandAction | FinalAction:
    action_type = raw_action.get("type")
    try:
        if action_type == "command":
            return CommandAction.model_validate(raw_action)
        if action_type == "final":
            return FinalAction.model_validate(raw_action)
    except ValidationError as exc:
        raise OllamaError(f"Invalid action from Ollama: {exc}") from exc
    raise OllamaError(f"Unsupported action type from Ollama: {action_type!r}")
