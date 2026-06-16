from __future__ import annotations

from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey


def verify_discord_signature(
    public_key_hex: str,
    signature_hex: str,
    timestamp: str,
    body: bytes,
) -> bool:
    """Verify Discord interaction request signature.

    Discord signs `timestamp + raw_body` with the application's Ed25519 public
    key. Return False for missing/malformed inputs rather than raising so the
    HTTP boundary can consistently produce 401/503 responses.
    """
    try:
        if not (public_key_hex and signature_hex and timestamp):
            return False
        key = VerifyKey(bytes.fromhex(str(public_key_hex)))
        signature = bytes.fromhex(str(signature_hex))
        message = str(timestamp).encode("utf-8") + bytes(body or b"")
        key.verify(message, signature)
        return True
    except (BadSignatureError, ValueError, TypeError):
        return False
