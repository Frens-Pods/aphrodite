from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi import APIRouter
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from aphrodite.app import create_app
from aphrodite.modules import AdapterSpec


def _ping_router() -> APIRouter:
    router = APIRouter()

    @router.get("/ping")
    def ping():
        return {"ok": True}

    return router


def _response_class_name(route: APIRoute) -> str:
    response_class = route.response_class
    default_value = getattr(response_class, "value", None)
    resolved = default_value if default_value is not None else response_class
    return getattr(resolved, "__name__", type(resolved).__name__)


def _mounted_route_contract(app) -> dict[tuple[str, str], str]:
    routes: dict[tuple[str, str], str] = {}
    for route in app.routes:
        if isinstance(route, APIRoute):
            routes[(route.path, next(iter(route.methods - {"HEAD", "OPTIONS"})))] = _response_class_name(route)
            continue
        original_router = getattr(route, "original_router", None)
        include_context = getattr(route, "include_context", None)
        if original_router is None or include_context is None:
            continue
        prefix = include_context.prefix
        for child in original_router.routes:
            if isinstance(child, APIRoute):
                routes[(f"{prefix}{child.path}", next(iter(child.methods - {"HEAD", "OPTIONS"})))] = _response_class_name(child)
    return routes


def test_discovered_adapter_router_requires_bearer_token(monkeypatch):
    spec = AdapterSpec(system="demo", handle=lambda *a: {}, router=_ping_router())
    monkeypatch.setattr("aphrodite.app.discover_adapter_specs", lambda: ({"demo": spec}, {}))
    monkeypatch.setenv("APHRODITE_ADAPTER_AUTH_TOKEN", "t")

    response = TestClient(create_app()).get("/demo/ping")

    assert response.status_code == 401


def test_discovered_adapter_router_accepts_valid_bearer_token(monkeypatch):
    spec = AdapterSpec(system="demo", handle=lambda *a: {}, router=_ping_router())
    monkeypatch.setattr("aphrodite.app.discover_adapter_specs", lambda: ({"demo": spec}, {}))
    monkeypatch.setenv("APHRODITE_ADAPTER_AUTH_TOKEN", "t")

    response = TestClient(create_app()).get("/demo/ping", headers={"Authorization": "Bearer t"})

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_discovered_public_adapter_router_skips_host_auth(monkeypatch):
    spec = AdapterSpec(
        system="demo",
        handle=lambda *a: {},
        router=_ping_router(),
        requires_auth=False,
    )
    monkeypatch.setattr("aphrodite.app.discover_adapter_specs", lambda: ({"demo": spec}, {}))

    response = TestClient(create_app()).get("/demo/ping")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_invalid_adapter_router_is_quarantined_at_mount_time(monkeypatch):
    spec = AdapterSpec(system="demo", handle=lambda *a: {}, router=object())
    monkeypatch.setattr("aphrodite.app.discover_adapter_specs", lambda: ({"demo": spec}, {}))

    app = create_app()

    assert "demo" in app.state.adapter_quarantine
    assert app.state.adapter_quarantine["demo"]["phase"] == "mount"


def test_adapter_without_router_is_not_mounted(monkeypatch):
    spec = AdapterSpec(system="demo", handle=lambda *a: {}, router=None)
    monkeypatch.setattr("aphrodite.app.discover_adapter_specs", lambda: ({"demo": spec}, {}))

    response = TestClient(create_app()).get("/demo/ping")

    assert response.status_code == 404


def test_builtin_skillopt_router_is_mounted_through_adapter_seam(monkeypatch, tmp_path):
    monkeypatch.setenv("APHRODITE_SKILLOPT_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("APHRODITE_TRUSTED_ADAPTERS", "some-third-party")
    app = create_app()
    route_contract = _mounted_route_contract(app)
    skillopt_routes = {
        (path, method)
        for path, method in route_contract
        if path.startswith("/skillopt/")
    }

    assert skillopt_routes == {
        ("/skillopt/runs", "POST"),
        ("/skillopt/runs/train", "POST"),
        ("/skillopt/ui", "GET"),
        ("/skillopt/evals", "POST"),
        ("/skillopt/evals", "GET"),
        ("/skillopt/evals/{eval_id}", "GET"),
        ("/skillopt/runs", "GET"),
        ("/skillopt/runs/{run_id}", "GET"),
        ("/skillopt/runs/{run_id}/diff", "GET"),
        ("/skillopt/runs/{run_id}/review", "GET"),
        ("/skillopt/runs/{run_id}/files/{filename}", "GET"),
        ("/skillopt/runs/{run_id}/evaluate", "POST"),
        ("/skillopt/runs/{run_id}/evaluation", "GET"),
        ("/skillopt/runs/{run_id}/bundle", "POST"),
        ("/skillopt/runs/{run_id}/import", "POST"),
    }
    assert route_contract[("/skillopt/ui", "GET")] == "HTMLResponse"
    assert route_contract[("/skillopt/runs/{run_id}/review", "GET")] == "HTMLResponse"
    response = TestClient(app).get("/skillopt/runs")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "runs": [], "count": 0}
