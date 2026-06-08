<<<<<<< ours
<<<<<<< ours
<<<<<<< ours
=======
from datetime import datetime
>>>>>>> theirs
=======
from datetime import datetime
>>>>>>> theirs
=======
from datetime import datetime
>>>>>>> theirs
from typing import Any, Literal
from pydantic import BaseModel, Field

from .runner import CommandResult


class RunRequest(BaseModel):
    prompt: str = Field(..., min_length=1, description="User request to solve on the Ollama host.")
    model: str | None = Field(None, description="Ollama model name. Defaults to server config.")
    workspace: str | None = Field(None, description="Workspace path relative to the configured workspace root.")
    max_steps: int | None = Field(None, ge=1, le=50)
    temperature: float = Field(0.2, ge=0.0, le=2.0)


class CommandAction(BaseModel):
    type: Literal["command"] = "command"
    thought: str = Field(..., description="Short reason for running this command.")
    command: str = Field(..., description="Shell command to run on the Linux host.")


class FinalAction(BaseModel):
    type: Literal["final"] = "final"
    answer: str = Field(..., description="Final answer returned to the remote API caller.")


class AgentStep(BaseModel):
    index: int
    action: CommandAction | FinalAction
    result: CommandResult | None = None


class RunResponse(BaseModel):
    answer: str
    model: str
    workspace: str
    steps: list[AgentStep]


class HealthResponse(BaseModel):
    ok: bool
    ollama_base_url: str
    default_model: str
    workspace_root: str


class OllamaMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class OllamaChatRequest(BaseModel):
    model: str
    messages: list[OllamaMessage]
    stream: bool = False
    format: str | dict[str, Any] | None = None
    options: dict[str, Any] | None = None
<<<<<<< ours
<<<<<<< ours
<<<<<<< ours
=======
=======
>>>>>>> theirs
=======
>>>>>>> theirs


class JobStartResponse(BaseModel):
    job_id: str
    status: Literal["queued", "running", "succeeded", "failed"]


class JobResponse(BaseModel):
    job_id: str
    status: Literal["queued", "running", "succeeded", "failed"]
    created_at: datetime
    updated_at: datetime
    model: str
    workspace: str
    prompt: str
    steps: list[AgentStep] = Field(default_factory=list)
    answer: str | None = None
    error: str | None = None
<<<<<<< ours
<<<<<<< ours
>>>>>>> theirs
=======
>>>>>>> theirs
=======
>>>>>>> theirs
