from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import contextlib

from fastapi.testclient import TestClient

from aphrodite.app import create_app
from aphrodite.modules import AdapterSpec


def _handle(*_args):
    return {}


def test_adapter_lifespan_starts_and_shuts_down(monkeypatch):
    events: list[str] = []

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        events.append("enter")
        try:
            yield
        finally:
            events.append("exit")

    spec = AdapterSpec(system="demo", handle=_handle, lifespan=lifespan)
    monkeypatch.setattr("aphrodite.app.discover_adapter_specs", lambda: ({"demo": spec}, {}))

    with TestClient(create_app()) as client:
        assert client.app.state.adapter_lifespan_started == ["demo"]
        assert client.app.state.adapter_lifespan_errors == {}
        assert events == ["enter"]

    assert events == ["enter", "exit"]


def test_adapter_lifespan_startup_failure_is_isolated(monkeypatch):
    @contextlib.asynccontextmanager
    async def lifespan(_app):
        raise RuntimeError("boom")
        yield

    spec = AdapterSpec(system="broken", handle=_handle, lifespan=lifespan)
    monkeypatch.setattr("aphrodite.app.discover_adapter_specs", lambda: ({"broken": spec}, {}))

    with TestClient(create_app()) as client:
        assert client.app.state.adapter_lifespan_started == []
        assert "broken" in client.app.state.adapter_lifespan_errors
        assert client.app.state.adapter_lifespan_errors["broken"]["phase"] == "startup"


def test_adapter_without_lifespan_is_skipped(monkeypatch):
    spec = AdapterSpec(system="plain", handle=_handle, lifespan=None)
    monkeypatch.setattr("aphrodite.app.discover_adapter_specs", lambda: ({"plain": spec}, {}))

    with TestClient(create_app()) as client:
        assert client.app.state.adapter_lifespan_started == []
        assert client.app.state.adapter_lifespan_errors == {}
