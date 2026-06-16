from pathlib import Path
import sys

from nacl.signing import SigningKey

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_verify_discord_signature_accepts_valid_signature():
    from aphrodite.discord.signature import verify_discord_signature

    signing_key = SigningKey.generate()
    body = b'{"type":1}'
    timestamp = "1710000000"
    signature = signing_key.sign(timestamp.encode("utf-8") + body).signature.hex()

    assert verify_discord_signature(
        public_key_hex=signing_key.verify_key.encode().hex(),
        signature_hex=signature,
        timestamp=timestamp,
        body=body,
    ) is True


def test_verify_discord_signature_rejects_tampered_body():
    from aphrodite.discord.signature import verify_discord_signature

    signing_key = SigningKey.generate()
    timestamp = "1710000000"
    signature = signing_key.sign(timestamp.encode("utf-8") + b'{"type":1}').signature.hex()

    assert verify_discord_signature(
        public_key_hex=signing_key.verify_key.encode().hex(),
        signature_hex=signature,
        timestamp=timestamp,
        body=b'{"type":3}',
    ) is False


def test_verify_discord_signature_rejects_missing_or_invalid_inputs():
    from aphrodite.discord.signature import verify_discord_signature

    assert verify_discord_signature("", "", "", b"") is False
    assert verify_discord_signature("not-hex", "also-not-hex", "1", b"{}") is False


def test_production_discord_route_requires_configured_public_key(monkeypatch):
    monkeypatch.delenv("APHRODITE_DISCORD_PUBLIC_KEY", raising=False)

    from fastapi.testclient import TestClient
    from aphrodite.app import create_app

    client = TestClient(create_app())
    response = client.post(
        "/discord/interactions",
        content=b'{"type":1}',
        headers={
            "X-Signature-Ed25519": "00",
            "X-Signature-Timestamp": "1710000000",
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Discord public key is not configured"


def test_production_discord_route_verifies_signature_and_handles_ping(monkeypatch):
    signing_key = SigningKey.generate()
    body = b'{"type":1}'
    timestamp = "1710000000"
    signature = signing_key.sign(timestamp.encode("utf-8") + body).signature.hex()
    monkeypatch.setenv("APHRODITE_DISCORD_PUBLIC_KEY", signing_key.verify_key.encode().hex())

    from fastapi.testclient import TestClient
    from aphrodite.app import create_app

    client = TestClient(create_app())
    response = client.post(
        "/discord/interactions",
        content=body,
        headers={
            "X-Signature-Ed25519": signature,
            "X-Signature-Timestamp": timestamp,
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"type": 1}


def test_production_discord_route_rejects_bad_signature(monkeypatch):
    signing_key = SigningKey.generate()
    other_key = SigningKey.generate()
    body = b'{"type":1}'
    timestamp = "1710000000"
    bad_signature = other_key.sign(timestamp.encode("utf-8") + body).signature.hex()
    monkeypatch.setenv("APHRODITE_DISCORD_PUBLIC_KEY", signing_key.verify_key.encode().hex())

    from fastapi.testclient import TestClient
    from aphrodite.app import create_app

    client = TestClient(create_app())
    response = client.post(
        "/discord/interactions",
        content=body,
        headers={
            "X-Signature-Ed25519": bad_signature,
            "X-Signature-Timestamp": timestamp,
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid Discord interaction signature"
