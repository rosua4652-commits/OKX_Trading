from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Lock
from uuid import uuid4

from .agent import run_agent
from .ollama import OllamaClient
from .schemas import AgentStep, JobResponse, JobStartResponse, RunRequest
from .settings import Settings

JobStatus = str


class JobNotFoundError(KeyError):
    """Raised when a requested agent job does not exist."""


class AgentJobStore:
    """Small in-memory job runner for Codex-like asynchronous UI polling."""

    def __init__(self, max_workers: int = 2) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ollama-agent-job")
        self._jobs: dict[str, JobResponse] = {}
        self._lock = Lock()

    def submit(self, request: RunRequest, *, model: str, workspace: str, settings: Settings) -> JobStartResponse:
        job_id = uuid4().hex
        now = datetime.now(UTC)
        job = JobResponse(
            job_id=job_id,
            status="queued",
            created_at=now,
            updated_at=now,
            model=model,
            workspace=workspace,
            prompt=request.prompt,
        )
        with self._lock:
            self._jobs[job_id] = job
        self._executor.submit(self._run, job_id, request, model, workspace, settings)
        return JobStartResponse(job_id=job_id, status="queued")

    def get(self, job_id: str) -> JobResponse:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise JobNotFoundError(job_id)
            return job.model_copy(deep=True)

    def _run(self, job_id: str, request: RunRequest, model: str, workspace: str, settings: Settings) -> None:
        self._patch(job_id, status="running")
        ollama = OllamaClient(settings.ollama_base_url)

        def record_step(step: AgentStep) -> None:
            with self._lock:
                job = self._jobs[job_id]
                job.steps.append(step)
                job.updated_at = datetime.now(UTC)

        try:
            response = run_agent(
                prompt=request.prompt,
                model=model,
                workspace=workspace,
                settings=settings,
                ollama=ollama,
                max_steps=request.max_steps or settings.max_steps,
                temperature=request.temperature,
                on_step=record_step,
            )
        except Exception as exc:  # noqa: BLE001 - surface background failures to the API/UI.
            self._patch(job_id, status="failed", error=str(exc))
            return
        self._patch(job_id, status="succeeded", answer=response.answer)

    def _patch(self, job_id: str, **updates: object) -> None:
        with self._lock:
            job = self._jobs[job_id]
            for key, value in updates.items():
                setattr(job, key, value)
            job.updated_at = datetime.now(UTC)


job_store = AgentJobStore()
