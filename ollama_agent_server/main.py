import uvicorn

from .settings import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run("ollama_agent_server.api:app", host=settings.host, port=settings.port, reload=False)


if __name__ == "__main__":
    main()
