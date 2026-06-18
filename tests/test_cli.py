from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_dispatch_test_cli_uses_real_configured_router(monkeypatch, capsys):
    import aphrodite.cli as cli

    class StubRouter:
        def dispatch(self, custom_id, context=None):
            return {"ok": True, "custom_id": custom_id, "context": context}

    monkeypatch.setattr(cli, "maybe_notify_update", lambda command: None)
    monkeypatch.setattr(cli, "build_router", lambda: StubRouter())

    assert cli.main(["dispatch-test", "skillopt:v1:status"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "ok": True,
        "custom_id": "skillopt:v1:status",
        "context": {"source": "cli"},
    }


def test_serve_uses_config_defaults_and_overrides(monkeypatch, capsys):
    import aphrodite.cli as cli

    calls = []

    def capture_run_server(host, port, reload=False):
        calls.append((host, port, reload))

    monkeypatch.setattr(cli, "maybe_notify_update", lambda command: None)
    monkeypatch.setattr(cli, "run_server", capture_run_server)
    monkeypatch.setenv("APHRODITE_HOST", "127.0.0.9")
    monkeypatch.setenv("APHRODITE_PORT", "9876")

    assert cli.main(["serve"]) == 0
    assert calls == [("127.0.0.9", 9876, False)]
    assert "Starting Aphrodite on http://127.0.0.9:9876" in capsys.readouterr().out

    assert cli.main(["serve", "--host", "0.0.0.0", "--port", "1234", "--reload"]) == 0
    assert calls[-1] == ("0.0.0.0", 1234, True)
    assert "Starting Aphrodite on http://0.0.0.0:1234" in capsys.readouterr().out


def test_modules_cli_prints_inventory_payload(monkeypatch, capsys):
    import aphrodite.cli as cli

    monkeypatch.setattr(cli, "maybe_notify_update", lambda command: None)
    monkeypatch.setattr(
        cli,
        "modules_payload",
        lambda: {
            "ok": True,
            "configured": ["skillopt", "missing_one"],
            "discovered": ["skillopt"],
            "active": ["skillopt"],
            "missing": ["missing_one"],
            "available": [],
            "hint": "pip install -e <your-module-dir>; set APHRODITE_MODULES",
        },
    )

    assert cli.main(["modules"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["configured"] == ["skillopt", "missing_one"]
    assert payload["discovered"] == ["skillopt"]
    assert payload["missing"] == ["missing_one"]


def test_dispatch_test_exit_reflects_router_and_handler_success(monkeypatch, capsys):
    import aphrodite.cli as cli

    monkeypatch.setattr(cli, "maybe_notify_update", lambda command: None)

    assert cli.main(["dispatch-test", "skillopt:v1:status"]) == 0
    ok_payload = json.loads(capsys.readouterr().out)
    assert ok_payload["ok"] is True

    assert cli.main(["dispatch-test", "unknown:v1:ping"]) == 1
    failing_payload = json.loads(capsys.readouterr().out)
    assert failing_payload["ok"] is False
