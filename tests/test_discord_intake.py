from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_discord_component_payload_dispatches_custom_id_to_router():
    from aphrodite.discord.intake import handle_interaction_payload
    from aphrodite.router import DispatchRouter

    router = DispatchRouter()
    router.register(
        "demo",
        lambda action, payload, context: {
            "action": action,
            "payload": payload,
            "context_channel": context.get("channel_id"),
            "context_user": context.get("user_id"),
        },
    )

    response = handle_interaction_payload(
        {
            "type": 3,
            "id": "interaction-1",
            "channel_id": "channel-1",
            "member": {"user": {"id": "user-1"}},
            "data": {"custom_id": "demo:v1:done:42"},
        },
        router,
    )

    assert response == {
        "type": 4,
        "data": {
            "flags": 64,
            "content": "Demo done: ok",
        },
        "aphrodite": {
            "ok": True,
            "system": "demo",
            "version": "v1",
            "action": "done",
            "payload": ["42"],
            "result": {
                "action": "done",
                "payload": ["42"],
                "context_channel": "channel-1",
                "context_user": "user-1",
            },
        },
    }


def test_discord_component_payload_extracts_full_context_for_component_auth():
    from aphrodite.discord.intake import handle_interaction_payload
    from aphrodite.router import DispatchRouter

    router = DispatchRouter()
    router.register(
        "demo",
        lambda action, payload, context: {
            "ok": True,
            "message": "captured",
            "action": action,
            "payload": payload,
            "user_id": context.get("user_id"),
            "user_name": context.get("user_name"),
            "role_ids": context.get("role_ids"),
            "message_id": context.get("message_id"),
            "channel_id": context.get("channel_id"),
            "guild_id": context.get("guild_id"),
        },
    )

    response = handle_interaction_payload(
        {
            "type": 3,
            "id": "interaction-1",
            "channel_id": "channel-1",
            "guild_id": "guild-1",
            "member": {
                "roles": ["role-1", "role-2"],
                "user": {"id": "user-1", "username": "operator", "global_name": "Operator"},
            },
            "message": {"id": "message-1"},
            "data": {"custom_id": "demo:v1:approve:default:t_123"},
        },
        router,
    )

    result = response["aphrodite"]["result"]
    assert result["user_id"] == "user-1"
    assert result["user_name"] == "Operator"
    assert result["role_ids"] == ["role-1", "role-2"]
    assert result["message_id"] == "message-1"
    assert result["channel_id"] == "channel-1"
    assert result["guild_id"] == "guild-1"
    assert response["data"]["content"] == "captured"


def test_discord_intake_surfaces_module_level_errors_ephemerally():
    from aphrodite.discord.intake import handle_interaction_payload
    from aphrodite.router import DispatchRouter

    router = DispatchRouter()
    router.register(
        "demo",
        lambda action, payload, context: {
            "ok": False,
            "handled": True,
            "ephemeral": True,
            "error": "unauthorized",
            "message": "You're not authorized to control component tasks~",
        },
    )

    response = handle_interaction_payload(
        {"type": 3, "data": {"custom_id": "demo:v1:approve:default:t_123"}},
        router,
    )

    assert response["type"] == 4
    assert response["data"]["flags"] == 64
    assert "You're not authorized to control component tasks~" in response["data"]["content"]
    assert response["data"]["allowed_mentions"] == {"parse": []}
    assert response["aphrodite"]["operator_guidance"]["category"] == "unauthorized_mutation"
    assert response["aphrodite"]["result"]["ok"] is False


def test_discord_intake_returns_ping_ack_without_dispatch():
    from aphrodite.discord.intake import handle_interaction_payload
    from aphrodite.router import DispatchRouter

    assert handle_interaction_payload({"type": 1}, DispatchRouter()) == {"type": 1}


def test_discord_intake_rejects_missing_custom_id_as_ephemeral_error():
    from aphrodite.discord.intake import handle_interaction_payload
    from aphrodite.router import DispatchRouter

    response = handle_interaction_payload({"type": 3, "data": {}}, DispatchRouter())

    assert response["type"] == 4
    assert response["data"]["flags"] == 64
    assert "missing custom_id" in response["data"]["content"]
    assert response["aphrodite"]["ok"] is False


def test_fastapi_discord_dry_run_route_uses_app_router(monkeypatch, tmp_path):
    monkeypatch.setenv("APHRODITE_SKILLOPT_DATA_ROOT", str(tmp_path))

    from fastapi.testclient import TestClient
    from aphrodite.app import create_app

    client = TestClient(create_app())
    response = client.post(
        "/discord/interactions/dry-run",
        json={
            "type": 3,
            "channel_id": "chan",
            "member": {"user": {"id": "user"}},
            "data": {"custom_id": "skillopt:v1:status"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["type"] == 4
    assert body["aphrodite"]["result"]["ok"] is True
    assert body["aphrodite"]["action"] == "status"


def test_discord_component_payload_preserves_select_menu_values():
    from aphrodite.discord.intake import handle_interaction_payload
    from aphrodite.router import DispatchRouter

    router = DispatchRouter()
    router.register(
        "demo",
        lambda action, payload, context: {
            "ok": True,
            "message": context.get("component_values", [""])[0],
            "raw_values": context.get("raw_interaction_data", {}).get("values"),
        },
    )

    response = handle_interaction_payload(
        {
            "type": 3,
            "channel_id": "channel-1",
            "data": {"custom_id": "demo:v1:select-token", "values": ["task:23"]},
        },
        router,
    )

    assert response["aphrodite"]["result"]["message"] == "task:23"
    assert response["aphrodite"]["result"]["raw_values"] == ["task:23"]
    assert response["data"]["content"] == "task:23"
