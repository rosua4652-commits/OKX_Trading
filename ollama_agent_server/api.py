<<<<<<< ours
<<<<<<< ours
<<<<<<< ours
from fastapi import Depends, FastAPI, Header, HTTPException, status
from requests import RequestException

from .agent import run_agent
from .ollama import OllamaClient, OllamaError
from .runner import WorkspaceError, resolve_workspace
from .schemas import HealthResponse, RunRequest, RunResponse
=======
=======
>>>>>>> theirs
=======
>>>>>>> theirs
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from requests import RequestException

from .agent import run_agent
from .jobs import JobNotFoundError, job_store
from .ollama import OllamaClient, OllamaError
from .runner import WorkspaceError, resolve_workspace
from .schemas import HealthResponse, JobResponse, JobStartResponse, RunRequest, RunResponse
<<<<<<< ours
<<<<<<< ours
>>>>>>> theirs
=======
>>>>>>> theirs
=======
>>>>>>> theirs
from .settings import Settings, get_settings

app = FastAPI(
    title="Ollama Agent Server",
<<<<<<< ours
<<<<<<< ours
<<<<<<< ours
    version="0.1.0",
    description="API server for running Ollama as a remote coding/debugging agent on a Linux host.",
)

=======
=======
>>>>>>> theirs
=======
>>>>>>> theirs
    version="0.2.0",
    description="API and Codex-like web UI for running Ollama as a remote coding/debugging agent on a Linux host.",
)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def web_ui() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/app", include_in_schema=False)
def web_ui_alias() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")

<<<<<<< ours
<<<<<<< ours
>>>>>>> theirs
=======
>>>>>>> theirs
=======
>>>>>>> theirs

def require_api_key(
    x_api_key: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    if settings.require_api_key and x_api_key != settings.api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid API key")


def get_ollama(settings: Settings = Depends(get_settings)) -> OllamaClient:
    return OllamaClient(settings.ollama_base_url)


@app.get("/health", response_model=HealthResponse)
def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    return HealthResponse(
        ok=True,
        ollama_base_url=settings.ollama_base_url,
        default_model=settings.default_model,
        workspace_root=str(settings.resolved_workspace_root),
    )


@app.get("/v1/models", dependencies=[Depends(require_api_key)])
def list_models(ollama: OllamaClient = Depends(get_ollama)) -> dict:
    try:
        return ollama.tags()
    except RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Ollama request failed: {exc}") from exc


@app.post("/v1/run", response_model=RunResponse, dependencies=[Depends(require_api_key)])
def run(request: RunRequest, settings: Settings = Depends(get_settings), ollama: OllamaClient = Depends(get_ollama)) -> RunResponse:
    try:
        workspace_path = resolve_workspace(settings.resolved_workspace_root, request.workspace)
        workspace_name = str(workspace_path.relative_to(settings.resolved_workspace_root))
        if workspace_name == ".":
            workspace_name = ""
        return run_agent(
            prompt=request.prompt,
            model=request.model or settings.default_model,
            workspace=workspace_name,
            settings=settings,
            ollama=ollama,
            max_steps=request.max_steps or settings.max_steps,
            temperature=request.temperature,
        )
    except WorkspaceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OllamaError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Ollama request failed: {exc}") from exc
<<<<<<< ours
<<<<<<< ours
<<<<<<< ours
=======
=======
>>>>>>> theirs
=======
>>>>>>> theirs


@app.post("/v1/jobs", response_model=JobStartResponse, dependencies=[Depends(require_api_key)])
def start_job(request: RunRequest, settings: Settings = Depends(get_settings)) -> JobStartResponse:
    try:
        workspace_path = resolve_workspace(settings.resolved_workspace_root, request.workspace)
        workspace_name = str(workspace_path.relative_to(settings.resolved_workspace_root))
        if workspace_name == ".":
            workspace_name = ""
        return job_store.submit(
            request,
            model=request.model or settings.default_model,
            workspace=workspace_name,
            settings=settings,
        )
    except WorkspaceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/v1/jobs/{job_id}", response_model=JobResponse, dependencies=[Depends(require_api_key)])
def get_job(job_id: str) -> JobResponse:
    try:
        return job_store.get(job_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc
<<<<<<< ours
<<<<<<< ours
>>>>>>> theirs
=======
>>>>>>> theirs
=======
>>>>>>> theirs
