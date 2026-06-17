from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aphrodite.modules.acp_relay import (  # noqa: E402
    AcpRelay,
    AcpTransportError,
    RelayConfig,
    TurnResult,
    acp_transport,
    configure_relay,
    readiness,
    reset_relay,
)


class FakeTransport:
    """Simulates a stateful ACP agent.

    Records every call and keeps per-session message history so tests can prove
    the relay (a) creates a session on the first turn and (b) forwards the same
    session id on later turns — i.e. maintained-session continuity plumbing.
    """

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.sessions: dict[str, list[str]] = {}

    async def __call__(self, config: RelayConfig, message: str, acp_session_id):
        self.calls.append(
            {
                "profile": config.profile,
                "model": config.model,
                "provider": config.provider,
                "message": message,
                "acp_session_id": acp_session_id,
            }
        )
        if acp_session_id is None:
            sid = f"S{len(self.sessions) + 1}"
            self.sessions[sid] = []
        else:
            sid = acp_session_id
        history = self.sessions.setdefault(sid, [])
        history.append(message)
        reply = f"[{sid}] turns={len(history)} first={history[0]!r}"
        return TurnResult(reply=reply, stop_reason="end_turn", acp_session_id=sid)


def _relay(tmp_path: Path, transport=None) -> AcpRelay:
    cfg = RelayConfig(
        profile="forge",
        hermes_bin="hermes",
        cwd=str(tmp_path),
        db_path=str(tmp_path / "acp.sqlite3"),
    )
    return AcpRelay(cfg, transport=transport or FakeTransport())


def test_command_uses_profile_and_acp_subcommand():
    cfg = RelayConfig(profile="forge", hermes_bin="hermes")
    binary, args = cfg.command()
    assert binary == "hermes"
    # ACP ignores -m/--provider; explicit overrides switch via set_session_model.
    assert args == ["-p", "forge", "acp"]
    assert cfg.model_choice_id() is None
    explicit = RelayConfig(
        profile="forge",
        model="openai/gpt-4o-mini",
        provider="openrouter",
        hermes_bin="hermes",
    )
    assert explicit.model_choice_id() == "openrouter:openai/gpt-4o-mini"


def test_model_choice_id_requires_both_provider_and_model():
    assert (
        RelayConfig(
            profile="forge",
            provider="openrouter",
            model="",
        ).model_choice_id()
        is None
    )
    assert (
        RelayConfig(
            profile="forge",
            provider="",
            model="openai/gpt-4o-mini",
        ).model_choice_id()
        is None
    )
    assert (
        RelayConfig(
            profile="forge",
            provider="",
            model="",
        ).model_choice_id()
        is None
    )
    assert (
        RelayConfig(
            profile="forge",
            provider="openrouter",
            model="openai/gpt-4o-mini",
        ).model_choice_id()
        == "openrouter:openai/gpt-4o-mini"
    )


def test_readiness_reports_profile_default_model_choice(monkeypatch):
    monkeypatch.delenv("APHRODITE_ACP_MODEL", raising=False)
    monkeypatch.delenv("APHRODITE_ACP_PROVIDER", raising=False)

    payload = readiness()

    assert payload["model"] == ""
    assert payload["provider"] == ""
    assert payload["model_choice"] is None


def test_acp_transport_resolves_engine_override_or_profile(monkeypatch, tmp_path):
    class FakeBlock:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    def run(cfg, *, current_model_id):
        calls: list[dict] = []

        class FakeSpawn:
            def __init__(self, factory, binary, *args, env=None, cwd=None):
                factory(object())

            async def __aenter__(self):
                class Conn:
                    async def initialize(self, **kwargs):
                        return None

                    async def new_session(self, cwd):
                        models = (
                            SimpleNamespace(current_model_id=current_model_id)
                            if current_model_id is not None
                            else None
                        )
                        return SimpleNamespace(session_id="S1", models=models)

                    async def load_session(self, cwd, session_id):
                        return None

                    async def set_session_model(self, model_id, session_id):
                        calls.append({"model_id": model_id, "session_id": session_id})

                    async def prompt(self, prompt, session_id):
                        return SimpleNamespace(stop_reason="end_turn")

                return Conn(), object()

            async def __aexit__(self, *a):
                return False

        acp_module = ModuleType("acp")
        acp_module.spawn_agent_process = FakeSpawn
        acp_module.RequestError = SimpleNamespace(
            method_not_found=lambda method: RuntimeError(method)
        )
        acp_schema = ModuleType("acp.schema")
        acp_schema.AgentMessageChunk = type("AgentMessageChunk", (), {})
        acp_schema.AgentThoughtChunk = type("AgentThoughtChunk", (), {})
        acp_schema.AllowedOutcome = FakeBlock
        acp_schema.ClientCapabilities = type("ClientCapabilities", (), {})
        acp_schema.DeniedOutcome = FakeBlock
        acp_schema.RequestPermissionResponse = FakeBlock
        acp_schema.TextContentBlock = FakeBlock
        acp_module.schema = acp_schema
        monkeypatch.setitem(sys.modules, "acp", acp_module)
        monkeypatch.setitem(sys.modules, "acp.schema", acp_schema)
        asyncio.run(acp_transport(cfg, "hi", None))
        return calls

    base = dict(cwd=str(tmp_path), db_path=str(tmp_path / "relay.sqlite3"))

    # No override: the relay drives the profile's own current model.
    assert run(RelayConfig(**base), current_model_id="openai-codex:gpt-5.5") == [
        {"model_id": "openai-codex:gpt-5.5", "session_id": "S1"}
    ]
    # Explicit override wins over the profile default.
    assert run(
        RelayConfig(model="openai/gpt-4o-mini", provider="openrouter", **base),
        current_model_id="openai-codex:gpt-5.5",
    ) == [{"model_id": "openrouter:openai/gpt-4o-mini", "session_id": "S1"}]
    # Neither an override nor an advertised profile model: nothing to set.
    assert run(RelayConfig(**base), current_model_id=None) == []


def test_first_turn_creates_session_and_records(tmp_path):
    fake = FakeTransport()
    relay = _relay(tmp_path, fake)
    convo = relay.create_conversation()
    cid = convo["id"]
    assert convo["acp_session_id"] is None
    assert convo["turns"] == 0

    out = asyncio.run(relay.turn(cid, "hello forge"))
    assert out["turn"] == 1
    assert out["acp_session_id"] == "S1"
    assert "hello forge" in out["reply"]
    # The first transport call must request a NEW session (acp_session_id None).
    assert fake.calls[0]["acp_session_id"] is None

    stored = relay.get_conversation(cid)
    assert stored["acp_session_id"] == "S1"
    assert stored["turns"] == 1
    assert [m["role"] for m in stored["messages"]] == ["user", "agent"]
    assert stored["messages"][0]["text"] == "hello forge"


def test_second_turn_resumes_same_session(tmp_path):
    fake = FakeTransport()
    relay = _relay(tmp_path, fake)
    cid = relay.create_conversation()["id"]

    async def two_turns():
        a = await relay.turn(cid, "remember the number 42")
        b = await relay.turn(cid, "what number did I say?")
        return a, b

    first, second = asyncio.run(two_turns())
    # Continuity: the second turn must reuse the session id from the first.
    assert fake.calls[0]["acp_session_id"] is None
    assert fake.calls[1]["acp_session_id"] == "S1"
    assert second["acp_session_id"] == "S1"
    assert second["turn"] == 2
    # The agent "remembers" the first message (proves session memory plumbing).
    assert "remember the number 42" in second["reply"]

    stored = relay.get_conversation(cid)
    assert stored["turns"] == 2
    assert len(stored["messages"]) == 4


def test_turn_rejects_empty_message(tmp_path):
    relay = _relay(tmp_path)
    cid = relay.create_conversation()["id"]
    with pytest.raises(ValueError):
        asyncio.run(relay.turn(cid, "   "))


def test_turn_unknown_conversation_raises(tmp_path):
    relay = _relay(tmp_path)
    with pytest.raises(KeyError):
        asyncio.run(relay.turn("does-not-exist", "hi"))


def test_per_conversation_overrides_are_persisted_and_used(tmp_path):
    fake = FakeTransport()
    relay = _relay(tmp_path, fake)
    cid = relay.create_conversation(model="anthropic/claude-3.5-sonnet", provider="openrouter")["id"]
    asyncio.run(relay.turn(cid, "hi"))
    assert fake.calls[0]["model"] == "anthropic/claude-3.5-sonnet"


def test_delete_conversation(tmp_path):
    relay = _relay(tmp_path)
    cid = relay.create_conversation()["id"]
    asyncio.run(relay.turn(cid, "hi"))
    assert relay.delete_conversation(cid) is True
    assert relay.get_conversation(cid) is None
    assert relay.delete_conversation(cid) is False


def test_transport_error_propagates(tmp_path):
    async def boom(config, message, acp_session_id):
        raise AcpTransportError("spawn failed")

    relay = _relay(tmp_path, boom)
    cid = relay.create_conversation()["id"]
    with pytest.raises(AcpTransportError):
        asyncio.run(relay.turn(cid, "hi"))


# --------------------------------------------------------------------------- #
# HTTP route wiring (FastAPI TestClient against the real app factory)
# --------------------------------------------------------------------------- #


def test_http_routes_drive_a_conversation(tmp_path):
    from fastapi.testclient import TestClient

    from aphrodite.app import create_app

    fake = FakeTransport()
    configure_relay(_relay(tmp_path, fake))
    try:
        with TestClient(create_app()) as client:
            health = client.get("/acp/health")
            assert health.status_code == 200

            created = client.post("/acp/conversations", json={"title": "omp<->forge"})
            assert created.status_code == 200
            cid = created.json()["id"]

            t1 = client.post(f"/acp/conversations/{cid}/turns", json={"message": "remember 42"})
            assert t1.status_code == 200, t1.text
            assert t1.json()["acp_session_id"] == "S1"

            t2 = client.post(f"/acp/conversations/{cid}/turns", json={"message": "recall?"})
            assert t2.status_code == 200
            body = t2.json()
            assert body["turn"] == 2
            assert "remember 42" in body["reply"]

            got = client.get(f"/acp/conversations/{cid}")
            assert got.status_code == 200
            assert len(got.json()["messages"]) == 4

            listed = client.get("/acp/conversations")
            assert any(c["id"] == cid for c in listed.json()["conversations"])

            deleted = client.delete(f"/acp/conversations/{cid}")
            assert deleted.status_code == 200
            assert client.get(f"/acp/conversations/{cid}").status_code == 404
    finally:
        reset_relay()


def test_http_turn_requires_message(tmp_path):
    from fastapi.testclient import TestClient

    from aphrodite.app import create_app

    configure_relay(_relay(tmp_path))
    try:
        with TestClient(create_app()) as client:
            cid = client.post("/acp/conversations", json={}).json()["id"]
            resp = client.post(f"/acp/conversations/{cid}/turns", json={"message": "  "})
            assert resp.status_code == 400
    finally:
        reset_relay()


def test_http_turn_unknown_conversation_404(tmp_path):
    from fastapi.testclient import TestClient

    from aphrodite.app import create_app

    configure_relay(_relay(tmp_path))
    try:
        with TestClient(create_app()) as client:
            resp = client.post("/acp/conversations/nope/turns", json={"message": "hi"})
            assert resp.status_code == 404
    finally:
        reset_relay()


def test_http_transport_error_maps_to_502(tmp_path):
    from fastapi.testclient import TestClient

    from aphrodite.app import create_app

    async def boom(config, message, acp_session_id):
        raise AcpTransportError("hermes acp crashed")

    configure_relay(_relay(tmp_path, boom))
    try:
        with TestClient(create_app()) as client:
            cid = client.post("/acp/conversations", json={}).json()["id"]
            resp = client.post(f"/acp/conversations/{cid}/turns", json={"message": "hi"})
            assert resp.status_code == 502
    finally:
        reset_relay()


def test_build_router_registers_acp_relay():
    from aphrodite.app import build_router

    router = build_router()
    assert "acp_relay" in router.systems
    result = router.dispatch("acp_relay:v1:health", context={"source": "test"})
    assert result["ok"] is True
    readiness = result["result"]["readiness"]
    assert readiness["profile"]
    assert "model_choice" in readiness


# --------------------------------------------------------------------------- #
# Live end-to-end against the real Hermes forge ACP server.
# Gated behind APHRODITE_ACP_E2E=1 so it only runs where Hermes is reachable.
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(
    os.environ.get("APHRODITE_ACP_E2E") != "1",
    reason="requires a live Hermes forge ACP server; set APHRODITE_ACP_E2E=1",
)
def test_e2e_live_forge_maintains_context(tmp_path):
    from aphrodite.modules.acp_relay import AcpRelay, load_relay_config

    relay = AcpRelay(load_relay_config(db_path=str(tmp_path / "e2e.sqlite3")))
    try:
        cid = relay.create_conversation()["id"]

        async def convo():
            a = await relay.turn(cid, "Remember the codeword BANANA-7. Reply with exactly: ok")
            b = await relay.turn(
                cid,
                "What was the codeword I asked you to remember? Reply with just the codeword.",
            )
            return a, b

        first, second = asyncio.run(convo())
        # Turn 1 produced real text on the profile's configured engine.
        assert first["reply"], "turn 1 produced no reply"
        assert first["acp_session_id"]
        # Maintained session: turn 2 reuses the same ACP session.
        assert second["acp_session_id"] == first["acp_session_id"]
        assert second["turn"] == 2
        # Maintained context: the agent recalls the codeword from turn 1
        # without the caller re-pasting it.
        assert "BANANA" in second["reply"].upper(), f"agent did not recall context: {second['reply']!r}"
    finally:
        relay.close()
