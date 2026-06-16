from __future__ import annotations

from typing import Any

from aphrodite.discord.component_guidance import private_failure_guidance
from aphrodite.router import DispatchRouter

DISCORD_INTERACTION_PING = 1
DISCORD_INTERACTION_COMPONENT = 3
DISCORD_RESPONSE_PONG = 1
DISCORD_RESPONSE_CHANNEL_MESSAGE = 4
DISCORD_RESPONSE_DEFERRED_UPDATE = 6
DISCORD_FLAG_EPHEMERAL = 64


def handle_interaction_payload(
    payload: dict[str, Any], router: DispatchRouter
) -> dict[str, Any]:
    """Handle a Discord interaction payload in Aphrodite dry-run/runtime form.

    This does not verify Discord Ed25519 signatures. Production HTTP interaction
    mode must add signature verification at the ingress boundary before calling
    this function. The function is still useful for tests, local sidecar routing,
    and discord.py-style adapters that already received a trusted interaction.
    """
    interaction_type = payload.get("type")
    if interaction_type == DISCORD_INTERACTION_PING:
        return {"type": DISCORD_RESPONSE_PONG}

    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    custom_id = str(data.get("custom_id") or "").strip()
    if not custom_id:
        return _ephemeral_error("Aphrodite Discord intake: missing custom_id", {"ok": False, "error": "missing custom_id"})

    result = router.dispatch(custom_id, context=_context_from_payload(payload))
    if not result.get("ok"):
        return _ephemeral_error(
            f"Aphrodite could not handle `{custom_id}`: {result.get('error', 'unknown error')}",
            result,
        )
    module_result = result.get("result") if isinstance(result.get("result"), dict) else {}
    if module_result and module_result.get("ok") is False:
        return _ephemeral_error(
            str(module_result.get("message") or module_result.get("error") or "Aphrodite action failed"),
            result,
        )
    if module_result.get("discord_response") == "deferred_update":
        return {"type": DISCORD_RESPONSE_DEFERRED_UPDATE, "aphrodite": result}
    return {
        "type": DISCORD_RESPONSE_CHANNEL_MESSAGE,
        "data": {
            "flags": DISCORD_FLAG_EPHEMERAL,
            "content": _success_message(result),
        },
        "aphrodite": result,
    }


def _context_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    member = payload.get("member") if isinstance(payload.get("member"), dict) else {}
    user = member.get("user") if isinstance(member.get("user"), dict) else payload.get("user")
    if not isinstance(user, dict):
        user = {}
    message = payload.get("message") if isinstance(payload.get("message"), dict) else {}
    component_values = [str(value) for value in (data.get("values") or []) if str(value)]
    role_ids = [str(role) for role in (member.get("roles") or []) if str(role)]
    user_name = str(
        user.get("global_name")
        or user.get("display_name")
        or user.get("username")
        or user.get("name")
        or ""
    )
    return {
        "source": "discord",
        "interaction_id": str(payload.get("id") or ""),
        "channel_id": str(payload.get("channel_id") or ""),
        "guild_id": str(payload.get("guild_id") or ""),
        "message_id": str(message.get("id") or ""),
        "user_id": str(user.get("id") or ""),
        "user_name": user_name,
        "role_ids": role_ids,
        "component_values": component_values,
        "raw_interaction_data": data,
        "raw_interaction_type": payload.get("type"),
    }


def _success_message(result: dict[str, Any]) -> str:
    system = str(result.get("system") or "Aphrodite").capitalize()
    action = str(result.get("action") or "action")
    module_result = result.get("result") if isinstance(result.get("result"), dict) else {}
    if isinstance(module_result, dict) and module_result.get("message"):
        return str(module_result.get("message"))
    return f"{system} {action}: ok"


def _ephemeral_error(content: str, result: dict[str, Any]) -> dict[str, Any]:
    guided_content, guided_result = private_failure_guidance(content, result)
    return {
        "type": DISCORD_RESPONSE_CHANNEL_MESSAGE,
        "data": {
            "flags": DISCORD_FLAG_EPHEMERAL,
            "content": guided_content,
            "allowed_mentions": {"parse": []},
        },
        "aphrodite": guided_result,
    }
