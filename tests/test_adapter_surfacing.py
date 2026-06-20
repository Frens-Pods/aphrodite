from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from aphrodite.modules import AdapterSpec


def _handle(action, payload, context):
    return {"ok": True}


def _fake_adapter_specs():
    return (
        {
            "demo": AdapterSpec(
                system="demo",
                handle=_handle,
                source="test",
                requires_auth=False,
                api_version=1,
            )
        },
        {"broken": {"name": "broken", "phase": "load", "error": "boom"}},
    )


def test_status_surfaces_adapter_runtime_errors(monkeypatch):
    import aphrodite.app as app_module

    monkeypatch.setattr(app_module, "discover_adapter_specs", _fake_adapter_specs)

    payload = TestClient(app_module.create_app()).get("/status").json()

    assert "broken" in payload["adapters"]["load_errors"]
    assert "quarantined" in payload["adapters"]
    assert "lifespan_errors" in payload["adapters"]
    assert "lifespan_started" in payload["adapters"]


def test_modules_payload_surfaces_adapter_errors_and_sources(monkeypatch):
    import aphrodite.inventory as inventory

    monkeypatch.setattr(inventory, "discover_adapter_specs", _fake_adapter_specs)

    payload = inventory.modules_payload()

    assert "broken" in payload["errors"]
    assert payload["sources"] == {"demo": "test"}


def test_doctor_payload_adds_informational_adapter_lint(monkeypatch):
    import aphrodite.doctor as doctor

    monkeypatch.setattr(doctor, "discover_adapter_specs", _fake_adapter_specs)

    payload = doctor.doctor_payload(root=ROOT)

    assert payload["adapters"]["ok"] is False
    assert "broken" in payload["adapters"]["errors"]
