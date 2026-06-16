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

    monkeypatch.setattr(cli, "build_router", lambda: StubRouter())

    assert cli.main(["dispatch-test", "skillopt:v1:status"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "ok": True,
        "custom_id": "skillopt:v1:status",
        "context": {"source": "cli"},
    }
