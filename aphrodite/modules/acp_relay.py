"""Aphrodite ACP relay module.

Bridges an external HTTP caller to a Hermes profile (default ``forge``) over the
Agent Client Protocol (ACP), so a caller can hold a **maintained-session,
multi-turn** conversation with the agent. Each HTTP turn is incremental: the
caller sends only the new message and the agent recalls prior turns, because the
ACP session is persisted by Hermes in ``state.db`` and restored via
``session/load`` on the next turn.

NO-CORE policy: this module never imports Hermes core. It talks to Hermes purely
as an external process — ``hermes -p <profile> ... acp`` — driven through the
standalone ``acp`` client library. The only Aphrodite-owned surfaces are the
FastAPI routes and a local SQLite conversation store, both explicitly allowed by
``NO_CORE_POLICY.md``.

Transport is pluggable (``AcpRelay(transport=...)``) so the orchestration logic
is unit-testable without a live Hermes; the real transport spawns the subprocess
and drives the ACP handshake.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sqlite3
import time
import uuid
from contextlib import closing
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from fastapi import APIRouter, HTTPException

from ..paths import hermes_root

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

DEFAULT_PROFILE = "forge"
DEFAULT_MODEL = ""
DEFAULT_PROVIDER = ""
DEFAULT_TURN_TIMEOUT = 240.0
DEFAULT_PROTOCOL_VERSION = 1


def _env(name: str, default: str) -> str:
    raw = os.environ.get(name)
    if raw is None:
        return default
    raw = raw.strip()
    return raw or default


def _resolve_hermes_bin() -> str:
    explicit = os.environ.get("APHRODITE_ACP_HERMES_BIN", "").strip()
    if explicit:
        return explicit
    found = shutil.which("hermes")
    if found:
        return found
    home = os.environ.get("HOME") or str(Path.home())
    candidate = Path(home) / ".local" / "bin" / "hermes"
    if candidate.exists():
        return str(candidate)
    return "hermes"


def _default_db_path() -> str:
    explicit = os.environ.get("APHRODITE_ACP_DB", "").strip()
    if explicit:
        return explicit
    return str(hermes_root() / "aphrodite" / "acp_relay.sqlite3")


def _default_cwd() -> str:
    explicit = os.environ.get("APHRODITE_ACP_CWD", "").strip()
    if explicit:
        return explicit
    return str(hermes_root())


@dataclass(frozen=True)
class RelayConfig:
    profile: str = DEFAULT_PROFILE
    model: str = DEFAULT_MODEL
    provider: str = DEFAULT_PROVIDER
    hermes_bin: str = "hermes"
    cwd: str = "."
    turn_timeout: float = DEFAULT_TURN_TIMEOUT
    db_path: str = "acp_relay.sqlite3"
    protocol_version: int = DEFAULT_PROTOCOL_VERSION

    def command(self) -> tuple[str, list[str]]:
        """Return (binary, args) for spawning the agent subprocess.

        Only ``-p <profile> acp`` is passed: Hermes' ACP adapter ignores the
        top-level ``-m``/``--provider`` flags (it builds the per-session agent
        from the profile/auth defaults). A runtime ``session/set_model`` switch
        happens only when an explicit provider/model override is configured;
        otherwise the profile's own engine drives the turn.
        """
        return self.hermes_bin, ["-p", self.profile, "acp"]

    def model_choice_id(self) -> str | None:
        """ACP model id for Hermes, or None to keep the profile default engine."""
        if self.provider and self.model:
            return f"{self.provider}:{self.model}"
        return None


def load_relay_config(**overrides: Any) -> RelayConfig:
    cfg = RelayConfig(
        profile=_env("APHRODITE_ACP_PROFILE", DEFAULT_PROFILE),
        model=_env("APHRODITE_ACP_MODEL", DEFAULT_MODEL),
        provider=_env("APHRODITE_ACP_PROVIDER", DEFAULT_PROVIDER),
        hermes_bin=_resolve_hermes_bin(),
        cwd=_default_cwd(),
        turn_timeout=float(_env("APHRODITE_ACP_TURN_TIMEOUT", str(DEFAULT_TURN_TIMEOUT))),
        db_path=_default_db_path(),
    )
    clean = {k: v for k, v in overrides.items() if v is not None}
    if clean:
        cfg = replace(cfg, **clean)
    return cfg


# --------------------------------------------------------------------------- #
# Turn transport
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class TurnResult:
    reply: str
    stop_reason: str
    acp_session_id: str
    thoughts: str = ""


# A transport runs exactly one conversational turn. When ``acp_session_id`` is
# None it MUST create a fresh ACP session; otherwise it MUST resume the named
# session so prior context is restored. It returns the assistant reply plus the
# (possibly newly created) session id.
Transport = Callable[[RelayConfig, str, Optional[str]], Awaitable[TurnResult]]


class AcpTransportError(RuntimeError):
    """Raised when the ACP turn cannot be completed."""


async def acp_transport(
    config: RelayConfig,
    message: str,
    acp_session_id: Optional[str],
) -> TurnResult:
    """Real transport: spawn ``hermes ... acp`` and drive one turn over ACP."""
    try:
        import acp
        from acp.schema import (
            AgentMessageChunk,
            AgentThoughtChunk,
            AllowedOutcome,
            ClientCapabilities,
            DeniedOutcome,
            RequestPermissionResponse,
            TextContentBlock,
        )
    except Exception as exc:  # pragma: no cover - environment guard
        raise AcpTransportError(f"acp client library unavailable: {exc!r}") from exc

    reply_chunks: list[str] = []
    thought_chunks: list[str] = []

    def _text_of(update: Any) -> Optional[str]:
        content = getattr(update, "content", None)
        return getattr(content, "text", None)

    class RelayClient:
        """ACP client that auto-approves and collects the agent's reply.

        Capabilities are advertised as minimal (no client fs/terminal), so the
        agent runs its own tools and never delegates file/terminal work to us.
        """

        def __init__(self, _agent: Any) -> None:
            self._agent = _agent

        async def request_permission(self, options, session_id, tool_call, **_kwargs):
            chosen = None
            for kind in ("allow_always", "allow_once"):
                for opt in options:
                    if getattr(opt, "kind", None) == kind:
                        chosen = opt
                        break
                if chosen is not None:
                    break
            if chosen is None and options:
                chosen = options[0]
            if chosen is None:
                return RequestPermissionResponse(outcome=DeniedOutcome(outcome="cancelled"))
            return RequestPermissionResponse(
                outcome=AllowedOutcome(outcome="selected", option_id=chosen.option_id)
            )

        async def session_update(self, session_id, update, **_kwargs):
            if isinstance(update, AgentMessageChunk):
                text = _text_of(update)
                if text:
                    reply_chunks.append(text)
            elif isinstance(update, AgentThoughtChunk):
                text = _text_of(update)
                if text:
                    thought_chunks.append(text)

        async def read_text_file(self, path, session_id, limit=None, line=None, **_kwargs):
            raise acp.RequestError.method_not_found("fs/read_text_file")

        async def write_text_file(self, content, path, session_id, **_kwargs):
            return None

        async def ext_method(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
            return {}

        async def ext_notification(self, method: str, params: dict[str, Any]) -> None:
            return None

        def on_connect(self, _conn: Any) -> None:
            return None

    binary, args = config.command()
    env = dict(os.environ)
    # Non-interactive: never block waiting on approvals/hooks.
    env.setdefault("HERMES_YOLO_MODE", "1")
    env.setdefault("HERMES_ACCEPT_HOOKS", "1")

    async def _drive() -> TurnResult:
        async with acp.spawn_agent_process(
            lambda agent: RelayClient(agent),
            binary,
            *args,
            env=env,
            cwd=config.cwd,
        ) as (conn, _process):
            await conn.initialize(
                protocol_version=config.protocol_version,
                client_capabilities=ClientCapabilities(),
            )
            if acp_session_id is None:
                new = await conn.new_session(cwd=config.cwd)
                session_id = new.session_id
                session_models = getattr(new, "models", None)
            else:
                session_id = acp_session_id
                loaded = await conn.load_session(cwd=config.cwd, session_id=session_id)
                session_models = getattr(loaded, "models", None)
            # Resolve the engine: an explicit relay override (provider+model)
            # wins; otherwise use the profile's own current model. Some engines
            # (e.g. openai-codex) reject an empty model, and the ACP session does
            # not auto-apply its current model, so the relay sets it explicitly.
            profile_model = getattr(session_models, "current_model_id", None)
            model_choice = config.model_choice_id() or profile_model
            if model_choice:
                await conn.set_session_model(
                    model_id=model_choice,
                    session_id=session_id,
                )
            resp = await conn.prompt(
                prompt=[TextContentBlock(type="text", text=message)],
                session_id=session_id,
            )
            stop_reason = getattr(resp, "stop_reason", "") or ""
            stop_reason = str(getattr(stop_reason, "value", stop_reason))
            return TurnResult(
                reply="".join(reply_chunks).strip(),
                stop_reason=stop_reason,
                acp_session_id=session_id,
                thoughts="".join(thought_chunks).strip(),
            )

    try:
        return await asyncio.wait_for(_drive(), timeout=config.turn_timeout)
    except asyncio.TimeoutError as exc:
        raise AcpTransportError(
            f"ACP turn timed out after {config.turn_timeout}s"
        ) from exc


# --------------------------------------------------------------------------- #
# Conversation store (SQLite, owned by Aphrodite)
# --------------------------------------------------------------------------- #

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    title TEXT,
    profile TEXT NOT NULL,
    model TEXT NOT NULL,
    provider TEXT NOT NULL,
    cwd TEXT NOT NULL,
    acp_session_id TEXT,
    turns INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    conversation_id TEXT NOT NULL,
    idx INTEGER NOT NULL,
    role TEXT NOT NULL,
    text TEXT NOT NULL,
    stop_reason TEXT,
    created_at REAL NOT NULL,
    PRIMARY KEY (conversation_id, idx)
);
"""


class ConversationStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        # A single shared connection keeps an in-memory DB alive for tests and is
        # safe here because the relay serializes writes per conversation and the
        # service runs as a single uvicorn process.
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def create(self, *, profile: str, model: str, provider: str, cwd: str, title: str | None) -> dict[str, Any]:
        cid = uuid.uuid4().hex
        now = time.time()
        self._conn.execute(
            "INSERT INTO conversations (id, title, profile, model, provider, cwd, acp_session_id, turns, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (cid, title, profile, model, provider, cwd, None, 0, now, now),
        )
        self._conn.commit()
        return self.get(cid)  # type: ignore[return-value]

    def get(self, conversation_id: str) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        return dict(row) if row else None

    def list(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM conversations ORDER BY updated_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def messages(self, conversation_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT idx, role, text, stop_reason, created_at FROM messages"
            " WHERE conversation_id = ? ORDER BY idx ASC",
            (conversation_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def delete(self, conversation_id: str) -> bool:
        cur = self._conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        self._conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def record_turn(
        self,
        conversation_id: str,
        *,
        user_text: str,
        agent_text: str,
        stop_reason: str,
        acp_session_id: str,
    ) -> dict[str, Any]:
        now = time.time()
        row = self._conn.execute(
            "SELECT turns FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        base = int(row["turns"]) if row else 0
        user_idx = base * 2
        agent_idx = base * 2 + 1
        self._conn.execute(
            "INSERT INTO messages (conversation_id, idx, role, text, stop_reason, created_at) VALUES (?,?,?,?,?,?)",
            (conversation_id, user_idx, "user", user_text, None, now),
        )
        self._conn.execute(
            "INSERT INTO messages (conversation_id, idx, role, text, stop_reason, created_at) VALUES (?,?,?,?,?,?)",
            (conversation_id, agent_idx, "agent", agent_text, stop_reason, now),
        )
        self._conn.execute(
            "UPDATE conversations SET turns = turns + 1, acp_session_id = ?, updated_at = ? WHERE id = ?",
            (acp_session_id, now, conversation_id),
        )
        self._conn.commit()
        return self.get(conversation_id)  # type: ignore[return-value]


# --------------------------------------------------------------------------- #
# Orchestrator
# --------------------------------------------------------------------------- #


class AcpRelay:
    def __init__(self, config: RelayConfig, *, transport: Transport | None = None) -> None:
        self.config = config
        self._transport: Transport = transport or acp_transport
        self._store = ConversationStore(config.db_path)
        self._locks: dict[tuple[int, str], asyncio.Lock] = {}

    @property
    def store(self) -> ConversationStore:
        return self._store

    def close(self) -> None:
        self._store.close()

    def _lock(self, conversation_id: str) -> asyncio.Lock:
        # Key by running loop so a cached Lock is never reused across event
        # loops (production runs one loop; tests/TestClient may use several).
        key = (id(asyncio.get_running_loop()), conversation_id)
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    def create_conversation(
        self,
        *,
        profile: str | None = None,
        model: str | None = None,
        provider: str | None = None,
        cwd: str | None = None,
        title: str | None = None,
    ) -> dict[str, Any]:
        return self._store.create(
            profile=profile or self.config.profile,
            model=model or self.config.model,
            provider=provider or self.config.provider,
            cwd=cwd or self.config.cwd,
            title=title,
        )

    def get_conversation(self, conversation_id: str) -> Optional[dict[str, Any]]:
        convo = self._store.get(conversation_id)
        if convo is None:
            return None
        convo = dict(convo)
        convo["messages"] = self._store.messages(conversation_id)
        return convo

    def list_conversations(self) -> list[dict[str, Any]]:
        return self._store.list()

    def delete_conversation(self, conversation_id: str) -> bool:
        return self._store.delete(conversation_id)

    async def turn(self, conversation_id: str, message: str) -> dict[str, Any]:
        if not str(message or "").strip():
            raise ValueError("message must be a non-empty string")
        convo = self._store.get(conversation_id)
        if convo is None:
            raise KeyError(conversation_id)

        async with self._lock(conversation_id):
            # Re-read inside the lock so the session id reflects any prior turn.
            convo = self._store.get(conversation_id)
            assert convo is not None
            turn_config = replace(
                self.config,
                profile=convo["profile"],
                model=convo["model"],
                provider=convo["provider"],
                cwd=convo["cwd"],
            )
            result = await self._transport(turn_config, message, convo["acp_session_id"])
            updated = self._store.record_turn(
                conversation_id,
                user_text=message,
                agent_text=result.reply,
                stop_reason=result.stop_reason,
                acp_session_id=result.acp_session_id,
            )
        return {
            "conversation_id": conversation_id,
            "turn": int(updated["turns"]),
            "reply": result.reply,
            "thoughts": result.thoughts,
            "stop_reason": result.stop_reason,
            "acp_session_id": result.acp_session_id,
        }


# --------------------------------------------------------------------------- #
# Process-wide singleton (overridable for tests)
# --------------------------------------------------------------------------- #

_RELAY: AcpRelay | None = None


def get_relay() -> AcpRelay:
    global _RELAY
    if _RELAY is None:
        _RELAY = AcpRelay(load_relay_config())
    return _RELAY


def configure_relay(relay: AcpRelay) -> None:
    """Install a relay instance (used by tests)."""
    global _RELAY
    _RELAY = relay


def reset_relay() -> None:
    global _RELAY
    if _RELAY is not None:
        _RELAY.close()
    _RELAY = None


# --------------------------------------------------------------------------- #
# Dispatch handler (for DispatchRouter registration)
# --------------------------------------------------------------------------- #


def readiness() -> dict[str, Any]:
    cfg = load_relay_config()
    hermes_bin = cfg.hermes_bin
    bin_ok = bool(shutil.which(hermes_bin) or Path(hermes_bin).exists())
    try:
        import acp  # noqa: F401

        acp_ok = True
    except Exception:
        acp_ok = False
    return {
        "ok": bin_ok and acp_ok,
        "profile": cfg.profile,
        "model": cfg.model,
        "provider": cfg.provider,
        "model_choice": cfg.model_choice_id(),
        "hermes_bin": hermes_bin,
        "hermes_bin_found": bin_ok,
        "acp_library": acp_ok,
        "db_path": cfg.db_path,
    }


def handle(action: str, payload: list[str], context: dict[str, Any]) -> dict[str, Any]:
    if action in {"health", "readiness", "status"}:
        return {"ok": True, "action": action, "readiness": readiness()}
    return {
        "handled": False,
        "system": "acp_relay",
        "action": action,
        "payload": payload,
        "message": "acp_relay dispatch supports only health/readiness; use the /acp HTTP routes",
    }


# --------------------------------------------------------------------------- #
# FastAPI router (owned by Aphrodite)
# --------------------------------------------------------------------------- #

router = APIRouter(prefix="/acp", tags=["acp_relay"])


@router.get("/health")
def acp_health() -> dict[str, Any]:
    return readiness()


@router.post("/conversations")
def acp_create_conversation(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    convo = get_relay().create_conversation(
        profile=payload.get("profile"),
        model=payload.get("model"),
        provider=payload.get("provider"),
        cwd=payload.get("cwd"),
        title=payload.get("title"),
    )
    return convo


@router.get("/conversations")
def acp_list_conversations() -> dict[str, Any]:
    return {"conversations": get_relay().list_conversations()}


@router.get("/conversations/{conversation_id}")
def acp_get_conversation(conversation_id: str) -> dict[str, Any]:
    convo = get_relay().get_conversation(conversation_id)
    if convo is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return convo


@router.delete("/conversations/{conversation_id}")
def acp_delete_conversation(conversation_id: str) -> dict[str, Any]:
    deleted = get_relay().delete_conversation(conversation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="conversation not found")
    return {"deleted": True, "conversation_id": conversation_id}


@router.post("/conversations/{conversation_id}/turns")
async def acp_turn(conversation_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    message = str((payload or {}).get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required")
    relay = get_relay()
    try:
        return await relay.turn(conversation_id, message)
    except KeyError:
        raise HTTPException(status_code=404, detail="conversation not found")
    except AcpTransportError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
