from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_configured_missing_module_dispatches_to_placeholder(monkeypatch):
    from fastapi.testclient import TestClient

    from aphrodite.app import create_app

    monkeypatch.setenv("APHRODITE_MODULES", "missing")
    with TestClient(create_app()) as client:
        result = client.post("/dispatch/missing:v1:ping").json()

    assert result["ok"] is True
    assert result["system"] == "missing"
    assert result["result"] == {
        "ok": False,
        "error": "module adapter 'missing' is configured but not installed",
        "hint": "pip install -e <your-module-dir> into this environment, then set APHRODITE_MODULES to include 'missing' (run: aphrodite modules)",
    }


def test_unknown_system_reports_known_systems_and_fix():
    from aphrodite.router import DispatchRouter

    router = DispatchRouter()
    router.register("beta", lambda action, payload, context: {"ok": True})
    router.register("alpha", lambda action, payload, context: {"ok": True})

    result = router.dispatch("missing:v1:ping")

    assert result["ok"] is False
    assert result["error"] == "unknown system"
    assert result["system"] == "missing"
    assert result["known_systems"] == ["alpha", "beta"]
    assert result["fix"] == "Set APHRODITE_MODULES to include this system, or install its adapter package; run `aphrodite modules` to see what is discovered."


def test_unsupported_version_includes_dispatch_example():
    from aphrodite.router import DispatchRouter

    router = DispatchRouter()
    router.register("demo", lambda action, payload, context: {"ok": True})

    result = router.dispatch("demo:v9:approve:42")

    assert result["ok"] is False
    assert result["error"] == "unsupported custom_id version"
    assert result["supported_versions"] == ["v1"]
    assert result["example"] == "demo:v1:approve"


def test_handler_exception_includes_adapter_hint():
    from aphrodite.router import DispatchRouter

    def boom(action, payload, context):
        raise RuntimeError("adapter exploded")

    router = DispatchRouter()
    router.register("demo", boom)

    result = router.dispatch("demo:v1:approve:42")

    assert result["ok"] is False
    assert result["error"] == "adapter exploded"
    assert result["hint"] == "adapter 'demo' raised while handling 'approve'; check that handler's code and re-run aphrodite dispatch-test."
