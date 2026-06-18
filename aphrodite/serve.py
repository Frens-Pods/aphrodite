"""Serve the Aphrodite FastAPI application."""

from __future__ import annotations


def run_server(host: str, port: int, reload: bool = False) -> None:
    """Run Aphrodite with uvicorn."""
    import uvicorn

    uvicorn.run(
        "aphrodite.app:create_app",
        factory=True,
        host=host,
        port=port,
        reload=reload,
    )
