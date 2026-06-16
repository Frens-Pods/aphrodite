from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_health_payload_names_aphrodite_and_no_core_policy():
    from aphrodite.app import health_payload

    payload = health_payload()

    assert payload["ok"] is True
    assert payload["service"] == "aphrodite"
    assert payload["policy"] == "no-hermes-core"
    assert payload["modules"] == ["image_gen", "skillopt", "acp_relay"]


def test_custom_id_router_dispatches_registered_module_action():
    from aphrodite.router import DispatchRouter

    router = DispatchRouter()

    def handler(action, payload, context):
        return {"handled": True, "action": action, "payload": payload, "context": context}

    router.register("demo", handler)
    result = router.dispatch("demo:v1:done:42", context={"source": "test"})

    assert result == {
        "ok": True,
        "system": "demo",
        "version": "v1",
        "action": "done",
        "payload": ["42"],
        "result": {"handled": True, "action": "done", "payload": ["42"], "context": {"source": "test"}},
    }


def test_custom_id_router_rejects_unknown_system_without_throwing():
    from aphrodite.router import DispatchRouter

    result = DispatchRouter().dispatch("unknown:v1:do:x")

    assert result["ok"] is False
    assert result["error"] == "unknown system"
    assert result["system"] == "unknown"


def test_doctor_reports_paths_and_core_repo_without_modifying_core():
    from aphrodite.doctor import doctor_payload

    payload = doctor_payload(root=ROOT)

    assert payload["ok"] is True
    assert payload["service"] == "aphrodite"
    assert payload["root"] == str(ROOT)
    assert payload["hermes_core_policy"] == "read-only / untouched"
    assert "aphrodite/app.py" in payload["required_files_present"]
