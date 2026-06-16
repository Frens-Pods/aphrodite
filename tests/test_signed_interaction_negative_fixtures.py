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
        "id": f"negative-{custom_id.replace(':', '-')}",
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


def _assert_ephemeral_failure(response, *, error_fragment: str):
    assert response.status_code == 200
    body = response.json()
    assert body["type"] == 4
    assert body["data"]["flags"] == 64
    assert error_fragment in body["data"]["content"]
    aphrodite = body["aphrodite"]
    module_result = aphrodite.get("result") if isinstance(aphrodite.get("result"), dict) else {}
    assert aphrodite.get("ok") is False or module_result.get("ok") is False
    assert "discord_response" not in aphrodite
    return body


def test_signed_route_rejects_stale_component_versions_before_side_effects(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from aphrodite.app import create_app

    _configure_public_key(monkeypatch)
    monkeypatch.setenv("APHRODITE_SKILLOPT_DATA_ROOT", str(tmp_path))

    client = TestClient(create_app())
    stale_status = _signed_request(
        client,
        _component_payload("skillopt:v0:status", user_id="user-allowed"),
    )

    body = _assert_ephemeral_failure(stale_status, error_fragment="unsupported custom_id version")
    assert body["aphrodite"]["error"] == "unsupported custom_id version"
    assert body["aphrodite"]["version"] == "v0"


def test_signed_route_rejects_malformed_and_unknown_component_payloads_without_public_side_effects(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from aphrodite.app import create_app

    _configure_public_key(monkeypatch)
    monkeypatch.setenv("APHRODITE_SKILLOPT_DATA_ROOT", str(tmp_path))

    client = TestClient(create_app())
    cases = [
        (_component_payload("skillopt"), "custom_id must be"),
        (_component_payload("unknown:v1:approve:default:t_123"), "unknown system"),
        (_component_payload("skillopt:v1:archive:default:t_123", user_id="user-allowed"), "unsupported skillopt action"),
        ({**_component_payload("skillopt:v1:status", user_id="user-allowed"), "data": {}}, "missing custom_id"),
    ]

    for payload, expected_error in cases:
        response = _signed_request(client, payload)
        _assert_ephemeral_failure(response, error_fragment=expected_error)


def test_signed_negative_fixture_doc_and_verify_are_wired_without_activation_commands():
    doc = ROOT / "docs" / "signed-interaction-negative-fixtures.md"
    verify = ROOT / "scripts" / "verify.sh"
    doc_text = doc.read_text(encoding="utf-8")
    verify_text = verify.read_text(encoding="utf-8")

    assert "stale component custom-id versions" in doc_text
    assert "skillopt:v0:status" in doc_text
    assert "data.flags: 64" in doc_text
    assert "tests/test_signed_interaction_negative_fixtures.py" in verify_text
    forbidden = [
        "systemctl restart",
        "systemctl reload",
        "systemctl start",
        "hermes gateway run --replace",
        "dry_run=False",
        "curl -X POST https://discord.com",
        "discord endpoint",
        "crontab",
    ]
    lowered = verify_text.lower()
    for token in forbidden:
        assert token.lower() not in lowered


def test_signed_route_bad_json_fails_at_http_boundary_before_dispatch(monkeypatch):
    from fastapi.testclient import TestClient
    from aphrodite.app import create_app

    _configure_public_key(monkeypatch)
    client = TestClient(create_app())
    body = b'{"type":3,"data":{"custom_id":"skillopt:v1:status"}'
    signature = _SIGNING_KEY.sign(_TIMESTAMP.encode("utf-8") + body).signature.hex()

    response = client.post(
        "/discord/interactions",
        content=body,
        headers={
            "X-Signature-Ed25519": signature,
            "X-Signature-Timestamp": _TIMESTAMP,
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid JSON payload"
