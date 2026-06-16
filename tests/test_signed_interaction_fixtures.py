from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from nacl.signing import SigningKey

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_SIGNING_KEY = SigningKey(bytes(range(32)))
_TIMESTAMP = "1710000000"


def _component_payload(custom_id: str, *, user_id: str = "user-1", role_ids: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": 3,
        "id": f"signed-{custom_id.replace(':', '-')}",
        "channel_id": "channel-1",
        "guild_id": "guild-1",
        "message": {"id": "message-1"},
        "member": {
            "roles": list(role_ids or []),
            "user": {"id": user_id, "username": "tester", "global_name": "Test Operator"},
        },
        "data": {"custom_id": custom_id},
    }


def _signed_request(client, payload: dict[str, Any], *, signing_key: SigningKey = _SIGNING_KEY):
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    signature = signing_key.sign(_TIMESTAMP.encode("utf-8") + body).signature.hex()
    return client.post(
        "/discord/interactions",
        content=body,
        headers={
            "X-Signature-Ed25519": signature,
            "X-Signature-Timestamp": _TIMESTAMP,
            "Content-Type": "application/json",
        },
    )


def _configure_public_key(monkeypatch):
    monkeypatch.setenv("APHRODITE_DISCORD_PUBLIC_KEY", _SIGNING_KEY.verify_key.encode().hex())


def test_signed_native_skillopt_status_returns_ephemeral_success(monkeypatch, tmp_path):
    monkeypatch.setenv("APHRODITE_SKILLOPT_DATA_ROOT", str(tmp_path))
    _configure_public_key(monkeypatch)

    from fastapi.testclient import TestClient
    from aphrodite.app import create_app

    client = TestClient(create_app())
    response = _signed_request(client, _component_payload("skillopt:v1:status"))

    assert response.status_code == 200
    body = response.json()
    assert body["type"] == 4
    assert body["data"]["flags"] == 64
    assert body["aphrodite"]["result"]["ok"] is True
    assert body["aphrodite"]["action"] == "status"

def test_production_interaction_route_rejects_missing_and_bad_signatures(monkeypatch):
    _configure_public_key(monkeypatch)

    from fastapi.testclient import TestClient
    from aphrodite.app import create_app

    client = TestClient(create_app())
    body = json.dumps(_component_payload("skillopt:v1:status"), separators=(",", ":")).encode("utf-8")

    missing = client.post(
        "/discord/interactions",
        content=body,
        headers={"X-Signature-Timestamp": _TIMESTAMP, "Content-Type": "application/json"},
    )
    assert missing.status_code == 401
    assert missing.json()["detail"] == "Invalid Discord interaction signature"

    bad_key = SigningKey(bytes(reversed(range(32))))
    bad_signature = bad_key.sign(_TIMESTAMP.encode("utf-8") + body).signature.hex()
    bad = client.post(
        "/discord/interactions",
        content=body,
        headers={
            "X-Signature-Ed25519": bad_signature,
            "X-Signature-Timestamp": _TIMESTAMP,
            "Content-Type": "application/json",
        },
    )
    assert bad.status_code == 401
    assert bad.json()["detail"] == "Invalid Discord interaction signature"
