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
    handle,
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


def test_turn_raises_on_empty_reply_and_does_not_record(tmp_path):
    async def empty(config, message, acp_session_id):
        return TurnResult(reply="   ", stop_reason="end_turn", acp_session_id="S1")

    relay = _relay(tmp_path, empty)
    cid = relay.create_conversation()["id"]
    with pytest.raises(AcpTransportError):
        asyncio.run(relay.turn(cid, "hi"))
    # An empty turn must not be persisted as a success: no messages recorded,
    # turn count unchanged, and the session id left unset so the next turn
    # starts fresh rather than resuming a dead session.
    stored = relay.get_conversation(cid)
    assert stored["turns"] == 0
    assert stored["acp_session_id"] is None
    assert stored["messages"] == []


# --------------------------------------------------------------------------- #
# Synchronous dispatch surface (read-only; turns stay HTTP-only)
# --------------------------------------------------------------------------- #


def test_dispatch_list_empty_conversations(tmp_path):
    relay = _relay(tmp_path)
    configure_relay(relay)
    try:
        result = handle("list", [], {})
        assert result == {"ok": True, "action": "list", "conversations": []}
    finally:
        reset_relay()


def test_dispatch_list_populated_conversations_orders_by_recent_update(tmp_path):
    fake = FakeTransport()
    relay = _relay(tmp_path, fake)
    configure_relay(relay)
    try:
        first = relay.create_conversation(title="first")
        second = relay.create_conversation(title="second")
        asyncio.run(relay.turn(first["id"], "bump first"))

        result = handle("list", [], {})

        assert result["ok"] is True
        assert [c["id"] for c in result["conversations"]] == [first["id"], second["id"]]
        assert result["conversations"][0]["turns"] == 1
        assert fake.calls[0]["message"] == "bump first"
    finally:
        reset_relay()


def test_dispatch_get_conversation_returns_messages(tmp_path):
    relay = _relay(tmp_path)
    configure_relay(relay)
    try:
        convo = relay.create_conversation(title="read me")
        asyncio.run(relay.turn(convo["id"], "hello"))

        result = handle("get", [convo["id"]], {})

        assert result["ok"] is True
        assert result["conversation"]["id"] == convo["id"]
        assert result["conversation"]["title"] == "read me"
        assert [m["role"] for m in result["conversation"]["messages"]] == ["user", "agent"]
    finally:
        reset_relay()


def test_dispatch_get_rejects_missing_conversation_id(tmp_path):
    relay = _relay(tmp_path)
    configure_relay(relay)
    try:
        for payload in ([], ["   "]):
            result = handle("get", payload, {})
            assert result["ok"] is False
            assert result["error_type"] == "invalid_argument"
            assert "conversation id" in result["error"]
    finally:
        reset_relay()


def test_dispatch_get_unknown_conversation_id_returns_not_found(tmp_path):
    relay = _relay(tmp_path)
    configure_relay(relay)
    try:
        result = handle("get", ["missing"], {})
        assert result["ok"] is False
        assert result["conversation_id"] == "missing"
        assert result["error_type"] == "not_found"
    finally:
        reset_relay()


def test_dispatch_unsupported_action_points_to_http_routes_without_turning(tmp_path):
    fake = FakeTransport()
    relay = _relay(tmp_path, fake)
    configure_relay(relay)
    try:
        result = handle("turn", ["ignored", "hello"], {})
        assert result["ok"] is False
        assert result["error"] == "unknown action: turn"
        assert result["supported_actions"] == ["get", "health", "list", "readiness", "status"]
        assert "aphrodite dispatch-test acp_relay:v1:status" in result["examples"]
        assert "POST /acp/conversations/{id}/turns" in result["examples"]
        assert fake.calls == []
    finally:
        reset_relay()


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


def test_http_empty_reply_maps_to_502(tmp_path):
    from fastapi.testclient import TestClient

    from aphrodite.app import create_app

    async def empty(config, message, acp_session_id):
        return TurnResult(reply="", stop_reason="end_turn", acp_session_id="S1")

    configure_relay(_relay(tmp_path, empty))
    try:
        with TestClient(create_app()) as client:
            cid = client.post("/acp/conversations", json={}).json()["id"]
            resp = client.post(f"/acp/conversations/{cid}/turns", json={"message": "hi"})
            assert resp.status_code == 502, resp.text
    finally:
        reset_relay()


def test_build_router_registers_acp_relay_and_dispatches_read_only_actions(tmp_path):
    from aphrodite.app import build_router

    relay = _relay(tmp_path)
    convo = relay.create_conversation(title="via router")
    configure_relay(relay)
    try:
        router = build_router()
        assert "acp_relay" in router.systems

        health = router.dispatch("acp_relay:v1:health", context={"source": "test"})
        assert health["ok"] is True
        readiness = health["result"]["readiness"]
        assert readiness["profile"]
        assert "model_choice" in readiness

        listed = router.dispatch("acp_relay:v1:list", context={"source": "test"})
        assert listed["ok"] is True
        assert [c["id"] for c in listed["result"]["conversations"]] == [convo["id"]]

        fetched = router.dispatch(f"acp_relay:v1:get:{convo['id']}", context={"source": "test"})
        assert fetched["ok"] is True
        assert fetched["result"]["conversation"]["id"] == convo["id"]
    finally:
        reset_relay()


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


# --------------------------------------------------------------------------- #
# Hardening: store atomicity, locks, validation, auth, transport robustness,
# idempotency, stop-reason surfacing, and the text-only chunk policy.
# --------------------------------------------------------------------------- #


def _cfg(tmp_path: Path, **kw) -> RelayConfig:
    base = dict(
        profile="forge",
        hermes_bin="hermes",
        cwd=str(tmp_path),
        db_path=str(tmp_path / "relay.sqlite3"),
    )
    base.update(kw)
    return RelayConfig(**base)


def _fake_acp(
    monkeypatch,
    *,
    new_session_id="S1",
    current_model_id=None,
    load_session_raises=False,
    prompt_raises=None,
    chunks=(),
    stop_reason="end_turn",
):
    """Install a fake ``acp``/``acp.schema`` for driving ``acp_transport``.

    Returns a ``captured`` dict exposing the subprocess env, the constructed
    client, set_session_model calls, loaded session ids, and counters. ``chunks``
    is a list of ``(kind, text)`` emitted via ``session_update`` during prompt;
    ``kind`` is "message"/"thought"/anything-else (a non-text update).
    """
    captured = {
        "env": None,
        "client": None,
        "set_model": [],
        "loaded": [],
        "new_sessions": 0,
        "prompts": 0,
    }

    class FakeBlock:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    AgentMessageChunk = type("AgentMessageChunk", (), {})
    AgentThoughtChunk = type("AgentThoughtChunk", (), {})

    def _build(kind, text):
        if kind == "message":
            upd = AgentMessageChunk()
        elif kind == "thought":
            upd = AgentThoughtChunk()
        else:
            return object()  # a non-text update kind the relay must ignore
        upd.content = SimpleNamespace(text=text) if text is not None else SimpleNamespace()
        return upd

    class FakeSpawn:
        def __init__(self, factory, binary, *args, env=None, cwd=None):
            captured["env"] = env
            captured["client"] = factory(object())

        async def __aenter__(self):
            client = captured["client"]

            class Conn:
                async def initialize(self, **kwargs):
                    return None

                async def new_session(self, cwd):
                    captured["new_sessions"] += 1
                    models = (
                        SimpleNamespace(current_model_id=current_model_id)
                        if current_model_id is not None
                        else None
                    )
                    return SimpleNamespace(session_id=new_session_id, models=models)

                async def load_session(self, cwd, session_id):
                    captured["loaded"].append(session_id)
                    if load_session_raises:
                        raise RuntimeError("stale session")
                    return SimpleNamespace(models=None)

                async def set_session_model(self, model_id, session_id):
                    captured["set_model"].append(
                        {"model_id": model_id, "session_id": session_id}
                    )

                async def prompt(self, prompt, session_id):
                    captured["prompts"] += 1
                    if prompt_raises is not None:
                        raise prompt_raises
                    for kind, text in chunks:
                        await client.session_update(session_id, _build(kind, text))
                    return SimpleNamespace(stop_reason=stop_reason)

            return Conn(), object()

        async def __aexit__(self, *a):
            return False

    acp_module = ModuleType("acp")
    acp_module.spawn_agent_process = FakeSpawn
    acp_module.RequestError = SimpleNamespace(
        method_not_found=lambda method: RuntimeError(method)
    )
    acp_schema = ModuleType("acp.schema")
    acp_schema.AgentMessageChunk = AgentMessageChunk
    acp_schema.AgentThoughtChunk = AgentThoughtChunk
    acp_schema.AllowedOutcome = FakeBlock
    acp_schema.ClientCapabilities = type("ClientCapabilities", (), {})
    acp_schema.DeniedOutcome = FakeBlock
    acp_schema.RequestPermissionResponse = FakeBlock
    acp_schema.TextContentBlock = FakeBlock
    acp_module.schema = acp_schema
    monkeypatch.setitem(sys.modules, "acp", acp_module)
    monkeypatch.setitem(sys.modules, "acp.schema", acp_schema)
    return captured


def test_record_turn_raises_keyerror_when_row_gone_no_orphans(tmp_path):
    relay = _relay(tmp_path)
    store = relay.store
    with pytest.raises(KeyError):
        store.record_turn(
            "ghost",
            user_text="u",
            agent_text="a",
            stop_reason="end_turn",
            acp_session_id="S1",
        )
    # A missing conversation row must abort before any message is inserted.
    assert store.messages("ghost") == []


def test_delete_during_turn_raises_keyerror_and_no_orphans(tmp_path):
    class BlockingTransport:
        def __init__(self):
            self.started = None
            self.release = None
            self.calls = 0

        async def __call__(self, config, message, acp_session_id):
            self.calls += 1
            self.started.set()
            await self.release.wait()
            return TurnResult(reply="late", stop_reason="end_turn", acp_session_id="S1")

    transport = BlockingTransport()
    relay = _relay(tmp_path, transport)
    cid = relay.create_conversation()["id"]

    async def scenario():
        transport.started = asyncio.Event()
        transport.release = asyncio.Event()
        task = asyncio.create_task(relay.turn(cid, "hi"))
        await transport.started.wait()
        # Delete while the turn is parked inside the transport (lock held). The
        # atomic record_turn then finds the row gone and raises KeyError.
        assert relay.delete_conversation(cid) is True
        transport.release.set()
        with pytest.raises(KeyError):
            await task

    asyncio.run(scenario())
    # No orphan messages survive for the deleted conversation.
    assert relay.store.messages(cid) == []


def test_list_pagination_caps_and_offsets(tmp_path):
    from fastapi.testclient import TestClient

    from aphrodite.app import create_app

    configure_relay(_relay(tmp_path))
    try:
        with TestClient(create_app()) as client:
            for i in range(5):
                client.post("/acp/conversations", json={"title": f"c{i}"})
            page1 = client.get("/acp/conversations?limit=2&offset=0").json()
            assert len(page1["conversations"]) == 2
            assert page1["limit"] == 2
            assert page1["offset"] == 0
            page2 = client.get("/acp/conversations?limit=2&offset=2").json()
            assert len(page2["conversations"]) == 2
            ids1 = {c["id"] for c in page1["conversations"]}
            ids2 = {c["id"] for c in page2["conversations"]}
            assert ids1.isdisjoint(ids2)
            # limit clamps to the module max.
            clamped = client.get("/acp/conversations?limit=9999").json()
            assert clamped["limit"] == 200
    finally:
        reset_relay()


def test_create_rejects_unknown_key(tmp_path):
    from fastapi.testclient import TestClient

    from aphrodite.app import create_app

    configure_relay(_relay(tmp_path))
    try:
        with TestClient(create_app()) as client:
            resp = client.post("/acp/conversations", json={"bogus": "x"})
            assert resp.status_code == 422
    finally:
        reset_relay()


def test_create_rejects_non_string_profile(tmp_path):
    from fastapi.testclient import TestClient

    from aphrodite.app import create_app

    configure_relay(_relay(tmp_path))
    try:
        with TestClient(create_app()) as client:
            resp = client.post("/acp/conversations", json={"profile": 123})
            assert resp.status_code == 422
    finally:
        reset_relay()


def test_create_drops_cwd_by_default(tmp_path):
    from fastapi.testclient import TestClient

    from aphrodite.app import create_app

    configure_relay(_relay(tmp_path))
    try:
        with TestClient(create_app()) as client:
            created = client.post("/acp/conversations", json={"cwd": "/etc"})
            assert created.status_code == 200
            # The override is silently dropped; the relay keeps its own cwd.
            assert created.json()["cwd"] == str(tmp_path)
    finally:
        reset_relay()


def test_create_cwd_override_bad_dir_403(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from aphrodite.app import create_app

    monkeypatch.setenv("APHRODITE_ACP_ALLOW_CWD_OVERRIDE", "1")
    configure_relay(_relay(tmp_path))
    try:
        with TestClient(create_app()) as client:
            resp = client.post(
                "/acp/conversations", json={"cwd": str(tmp_path / "does-not-exist")}
            )
            assert resp.status_code == 403
    finally:
        reset_relay()


def test_create_profile_allowlist_403(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from aphrodite.app import create_app

    monkeypatch.setenv("APHRODITE_ACP_ALLOWED_PROFILES", "alpha,beta")
    configure_relay(_relay(tmp_path))
    try:
        with TestClient(create_app()) as client:
            denied = client.post("/acp/conversations", json={"profile": "forge"})
            assert denied.status_code == 403
            allowed = client.post("/acp/conversations", json={"profile": "alpha"})
            assert allowed.status_code == 200
    finally:
        reset_relay()


def test_create_profile_allowlist_gates_default_profile(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from aphrodite.app import create_app

    # Default profile is "forge"; an allowlist that omits it must reject a
    # profile-less POST that would otherwise fall back to the default profile.
    monkeypatch.setenv("APHRODITE_ACP_ALLOWED_PROFILES", "alpha,beta")
    monkeypatch.delenv("APHRODITE_ACP_PROFILE", raising=False)
    configure_relay(_relay(tmp_path))
    try:
        with TestClient(create_app()) as client:
            denied = client.post("/acp/conversations", json={})
            assert denied.status_code == 403
            allowed = client.post("/acp/conversations", json={"profile": "alpha"})
            assert allowed.status_code == 200
    finally:
        reset_relay()


def test_auth_enforced_when_token_set(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from aphrodite.app import create_app

    monkeypatch.setenv("APHRODITE_ACP_AUTH_TOKEN", "sekret")
    configure_relay(_relay(tmp_path))
    try:
        with TestClient(create_app()) as client:
            assert client.get("/acp/conversations").status_code == 401
            assert (
                client.get(
                    "/acp/conversations", headers={"Authorization": "Bearer wrong"}
                ).status_code
                == 401
            )
            ok = client.get(
                "/acp/conversations", headers={"Authorization": "Bearer sekret"}
            )
            assert ok.status_code == 200
    finally:
        reset_relay()


def test_auth_open_when_token_unset(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from aphrodite.app import create_app

    monkeypatch.delenv("APHRODITE_ACP_AUTH_TOKEN", raising=False)
    configure_relay(_relay(tmp_path))
    try:
        with TestClient(create_app()) as client:
            assert client.get("/acp/conversations").status_code == 200
    finally:
        reset_relay()


def test_auto_approve_off_denies_and_omits_yolo_env(monkeypatch, tmp_path):
    monkeypatch.setenv("APHRODITE_ACP_AUTO_APPROVE", "0")
    monkeypatch.delenv("HERMES_YOLO_MODE", raising=False)
    captured = _fake_acp(monkeypatch)
    asyncio.run(acp_transport(_cfg(tmp_path), "hi", None))
    # Subprocess env must NOT enable YOLO when auto-approve is gated off.
    assert "HERMES_YOLO_MODE" not in captured["env"]
    # The client refuses permission requests outright, even when options exist.
    resp = asyncio.run(
        captured["client"].request_permission(
            [SimpleNamespace(kind="allow_once", option_id="x")], "S1", None
        )
    )
    assert resp.outcome.outcome == "cancelled"


def test_auto_approve_off_strips_inherited_yolo_env(monkeypatch, tmp_path):
    # Even when the parent process already exports YOLO / accept-hooks, opting
    # out MUST strip them so an inherited value can't defeat the gate.
    monkeypatch.setenv("APHRODITE_ACP_AUTO_APPROVE", "0")
    monkeypatch.setenv("APHRODITE_ACP_ACCEPT_HOOKS", "0")
    monkeypatch.setenv("HERMES_YOLO_MODE", "1")
    monkeypatch.setenv("HERMES_ACCEPT_HOOKS", "1")
    captured = _fake_acp(monkeypatch)
    asyncio.run(acp_transport(_cfg(tmp_path), "hi", None))
    assert "HERMES_YOLO_MODE" not in captured["env"]
    assert "HERMES_ACCEPT_HOOKS" not in captured["env"]


def test_auto_approve_default_sets_env_and_allows(monkeypatch, tmp_path):
    monkeypatch.delenv("APHRODITE_ACP_AUTO_APPROVE", raising=False)
    monkeypatch.delenv("APHRODITE_ACP_ACCEPT_HOOKS", raising=False)
    monkeypatch.delenv("HERMES_YOLO_MODE", raising=False)
    monkeypatch.delenv("HERMES_ACCEPT_HOOKS", raising=False)
    captured = _fake_acp(monkeypatch)
    asyncio.run(acp_transport(_cfg(tmp_path), "hi", None))
    assert captured["env"]["HERMES_YOLO_MODE"] == "1"
    assert captured["env"]["HERMES_ACCEPT_HOOKS"] == "1"
    resp = asyncio.run(
        captured["client"].request_permission(
            [SimpleNamespace(kind="allow_once", option_id="opt-1")], "S1", None
        )
    )
    assert resp.outcome.outcome == "selected"
    assert resp.outcome.option_id == "opt-1"


def test_transport_normalizes_unexpected_exception(monkeypatch, tmp_path):
    _fake_acp(monkeypatch, prompt_raises=RuntimeError("kaboom"))
    # An arbitrary transport failure is normalized to AcpTransportError (-> 502).
    with pytest.raises(AcpTransportError):
        asyncio.run(acp_transport(_cfg(tmp_path), "hi", None))


def test_transport_self_heals_stale_session(monkeypatch, tmp_path):
    captured = _fake_acp(
        monkeypatch,
        load_session_raises=True,
        new_session_id="S2",
        chunks=[("message", "healed reply")],
    )
    result = asyncio.run(acp_transport(_cfg(tmp_path), "hi", "OLD-SESSION"))
    # A failed load_session falls back to a fresh session and still completes.
    assert captured["loaded"] == ["OLD-SESSION"]
    assert captured["new_sessions"] == 1
    assert result.acp_session_id == "S2"
    assert result.reply == "healed reply"


def test_transport_ignores_non_text_chunks(monkeypatch, tmp_path):
    _fake_acp(
        monkeypatch,
        chunks=[("message", None), ("other", None), ("message", "real text")],
    )
    result = asyncio.run(acp_transport(_cfg(tmp_path), "hi", None))
    # Text-less and non-text updates are ignored without error; only real
    # assistant text is surfaced.
    assert result.reply == "real text"


def test_incomplete_true_for_non_end_stop_reason(tmp_path):
    async def maxed(config, message, acp_session_id):
        return TurnResult(
            reply="partial answer", stop_reason="max_tokens", acp_session_id="S1"
        )

    relay = _relay(tmp_path, maxed)
    cid = relay.create_conversation()["id"]
    out = asyncio.run(relay.turn(cid, "hi"))
    assert out["incomplete"] is True
    assert out["reply"] == "partial answer"
    assert out["stop_reason"] == "max_tokens"


def test_incomplete_false_for_end_turn(tmp_path):
    relay = _relay(tmp_path)  # FakeTransport returns stop_reason="end_turn"
    cid = relay.create_conversation()["id"]
    out = asyncio.run(relay.turn(cid, "hi"))
    assert out["incomplete"] is False


def test_idempotent_turn_returns_cached_and_skips_transport(tmp_path):
    class CountingTransport:
        def __init__(self):
            self.count = 0

        async def __call__(self, config, message, acp_session_id):
            self.count += 1
            return TurnResult(
                reply=f"reply {self.count}", stop_reason="end_turn", acp_session_id="S1"
            )

    counting = CountingTransport()
    relay = _relay(tmp_path, counting)
    cid = relay.create_conversation()["id"]
    first = asyncio.run(relay.turn(cid, "hi", idempotency_key="k1"))
    second = asyncio.run(relay.turn(cid, "hi again", idempotency_key="k1"))
    # Same key -> identical stored response and the transport is not re-invoked.
    assert counting.count == 1
    assert second == first
    # A different key runs the transport again.
    third = asyncio.run(relay.turn(cid, "new", idempotency_key="k2"))
    assert counting.count == 2
    assert third["reply"] == "reply 2"


def test_http_idempotency_key_header_dedupes(tmp_path):
    from fastapi.testclient import TestClient

    from aphrodite.app import create_app

    class CountingTransport:
        def __init__(self):
            self.count = 0

        async def __call__(self, config, message, acp_session_id):
            self.count += 1
            return TurnResult(
                reply=f"r{self.count}", stop_reason="end_turn", acp_session_id="S1"
            )

    counting = CountingTransport()
    configure_relay(_relay(tmp_path, counting))
    try:
        with TestClient(create_app()) as client:
            cid = client.post("/acp/conversations", json={}).json()["id"]
            headers = {"Idempotency-Key": "abc"}
            r1 = client.post(
                f"/acp/conversations/{cid}/turns", json={"message": "hi"}, headers=headers
            )
            r2 = client.post(
                f"/acp/conversations/{cid}/turns", json={"message": "hi"}, headers=headers
            )
            assert r1.status_code == 200, r1.text
            assert r2.json() == r1.json()
            assert counting.count == 1
    finally:
        reset_relay()
