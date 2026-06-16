from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _component_payload(custom_id, *, user_id="user-1", role_ids=None):
    return {
        "type": 3,
        "id": f"interaction-{custom_id.replace(':', '-')}",
        "channel_id": "channel-1",
        "guild_id": "guild-1",
        "message": {"id": "message-1"},
        "member": {
            "roles": list(role_ids or []),
            "user": {"id": user_id, "username": "tester", "global_name": "Test Operator"},
        },
        "data": {"custom_id": custom_id},
    }


def test_native_skillopt_dry_run_pack(monkeypatch, tmp_path):
    monkeypatch.setenv("APHRODITE_SKILLOPT_DATA_ROOT", str(tmp_path))

    from fastapi.testclient import TestClient
    from aphrodite.app import create_app

    client = TestClient(create_app())
    response = client.post("/discord/interactions/dry-run", json=_component_payload("skillopt:v1:status"))

    assert response.status_code == 200
    body = response.json()
    assert body["type"] == 4
    assert body["aphrodite"]["result"]["ok"] is True
    assert body["aphrodite"]["action"] == "status"
