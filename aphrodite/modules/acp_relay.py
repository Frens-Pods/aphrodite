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
import hmac
import json
import os
import shutil
import sqlite3
import threading
import time
import uuid
import weakref
from contextlib import closing
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from fastapi import APIRouter, Depends, Header, HTTPException

from ..paths import hermes_root

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

DEFAULT_PROFILE = "forge"
DEFAULT_MODEL = ""
DEFAULT_PROVIDER = ""
DEFAULT_TURN_TIMEOUT = 240.0
DEFAULT_PROTOCOL_VERSION = 1

LIST_DEFAULT_LIMIT = 50
LIST_MAX_LIMIT = 200


def _env(name: str, default: str) -> str:
    raw = os.environ.get(name)
    if raw is None:
        return default
    raw = raw.strip()
    return raw or default


def _flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


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

    auto_approve = _flag("APHRODITE_ACP_AUTO_APPROVE", True)
    accept_hooks = _flag("APHRODITE_ACP_ACCEPT_HOOKS", True)

    reply_chunks: list[str] = []
    thought_chunks: list[str] = []

    def _text_of(update: Any) -> Optional[str]:
        # TEXT-ONLY policy: only assistant text is surfaced. Non-text content
        # blocks (image/audio/resource) have no ``.text`` attribute, so this
        # returns None and they are ignored by design; thoughts are captured
        # separately in ``session_update``.
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
            if not auto_approve:
                # Approvals gated off: refuse instead of auto-allowing.
                return RequestPermissionResponse(outcome=DeniedOutcome(outcome="cancelled"))
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
            # Intentionally TEXT-ONLY: assistant message text accumulates into
            # the reply, agent thoughts are captured separately, and all other
            # update kinds (tool calls, plans, non-text content) are ignored.
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
    # Non-interactive by default: avoid blocking on approvals/hooks. Both gates
    # default ON (keeps the verified forge flow working); set the corresponding
    # env var to 0 to opt out. Opt-out MUST strip any value inherited from the
    # parent env, or a YOLO/accept-hooks setting there would defeat the gate.
    if auto_approve:
        env.setdefault("HERMES_YOLO_MODE", "1")
    else:
        env.pop("HERMES_YOLO_MODE", None)
    if accept_hooks:
        env.setdefault("HERMES_ACCEPT_HOOKS", "1")
    else:
        env.pop("HERMES_ACCEPT_HOOKS", None)

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
                try:
                    loaded = await conn.load_session(
                        cwd=config.cwd, session_id=acp_session_id
                    )
                    session_id = acp_session_id
                    session_models = getattr(loaded, "models", None)
                except Exception:
                    # Stale/lost upstream session: self-heal by starting fresh.
                    # Prior upstream context is lost (acceptable); the new id is
                    # persisted by record_turn so the conversation recovers. If
                    # new_session also fails, let it propagate (wrapped below).
                    new = await conn.new_session(cwd=config.cwd)
                    session_id = new.session_id
                    session_models = getattr(new, "models", None)
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
        raise AcpTransportError(f"ACP turn timed out after {config.turn_timeout}s") from exc
    except asyncio.CancelledError:
        # Propagate cancellation so the SDK's async context manager tears down
        # the subprocess on HTTP-client disconnect.
        raise
    except AcpTransportError:
        raise
    except Exception as exc:
        raise AcpTransportError(f"ACP turn failed: {exc!r}") from exc


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
CREATE TABLE IF NOT EXISTS turn_idempotency (
    conversation_id TEXT NOT NULL,
    key TEXT NOT NULL,
    response TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (conversation_id, key)
);
"""


class ConversationStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        # A single shared connection keeps an in-memory DB alive for tests; it is
        # safe under concurrency because ``self._db_lock`` serializes every
        # access to the connection across the FastAPI threadpool and the loop.
        self._db_lock = threading.RLock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        if db_path != ":memory:":
            # WAL + a busy timeout make a file DB robust under concurrent
            # readers/writers; neither is meaningful for an in-memory DB.
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA busy_timeout=5000;")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        with self._db_lock:
            self._conn.close()

    def create(self, *, profile: str, model: str, provider: str, cwd: str, title: str | None) -> dict[str, Any]:
        with self._db_lock:
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
        with self._db_lock:
            row = self._conn.execute(
                "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
            return dict(row) if row else None

    def list(self, *, limit: int, offset: int) -> list[dict[str, Any]]:
        with self._db_lock:
            rows = self._conn.execute(
                "SELECT * FROM conversations ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            return [dict(r) for r in rows]

    def messages(self, conversation_id: str) -> list[dict[str, Any]]:
        with self._db_lock:
            rows = self._conn.execute(
                "SELECT idx, role, text, stop_reason, created_at FROM messages"
                " WHERE conversation_id = ? ORDER BY idx ASC",
                (conversation_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def delete(self, conversation_id: str) -> bool:
        with self._db_lock:
            cur = self._conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
            self._conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
            self._conn.execute(
                "DELETE FROM turn_idempotency WHERE conversation_id = ?", (conversation_id,)
            )
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
        with self._db_lock:
            now = time.time()
            row = self._conn.execute(
                "SELECT turns FROM conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
            if row is None:
                # The conversation row is gone (e.g. deleted mid-turn). Do NOT
                # fall back to base=0 or insert orphan messages.
                raise KeyError(conversation_id)
            base = int(row["turns"])
            user_idx = base * 2
            agent_idx = base * 2 + 1
            try:
                self._conn.execute(
                    "INSERT INTO messages (conversation_id, idx, role, text, stop_reason, created_at) VALUES (?,?,?,?,?,?)",
                    (conversation_id, user_idx, "user", user_text, None, now),
                )
                self._conn.execute(
                    "INSERT INTO messages (conversation_id, idx, role, text, stop_reason, created_at) VALUES (?,?,?,?,?,?)",
                    (conversation_id, agent_idx, "agent", agent_text, stop_reason, now),
                )
                cur = self._conn.execute(
                    "UPDATE conversations SET turns = turns + 1, acp_session_id = ?, updated_at = ? WHERE id = ?",
                    (acp_session_id, now, conversation_id),
                )
                assert cur.rowcount == 1
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            return self.get(conversation_id)  # type: ignore[return-value]

    def get_idempotent(self, conversation_id: str, key: str) -> Optional[dict[str, Any]]:
        with self._db_lock:
            row = self._conn.execute(
                "SELECT response FROM turn_idempotency WHERE conversation_id = ? AND key = ?",
                (conversation_id, key),
            ).fetchone()
            if row is None:
                return None
            try:
                return json.loads(row["response"])
            except Exception:
                return None

    def put_idempotent(self, conversation_id: str, key: str, response: dict[str, Any]) -> None:
        with self._db_lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO turn_idempotency (conversation_id, key, response, created_at)"
                " VALUES (?,?,?,?)",
                (conversation_id, key, json.dumps(response), time.time()),
            )
            self._conn.commit()


# --------------------------------------------------------------------------- #
# Orchestrator
# --------------------------------------------------------------------------- #


class AcpRelay:
    def __init__(self, config: RelayConfig, *, transport: Transport | None = None) -> None:
        self.config = config
        self._transport: Transport = transport or acp_transport
        self._store = ConversationStore(config.db_path)
        self._locks: "weakref.WeakKeyDictionary[Any, dict[str, asyncio.Lock]]" = (
            weakref.WeakKeyDictionary()
        )

    @property
    def store(self) -> ConversationStore:
        return self._store

    def close(self) -> None:
        self._store.close()

    def _lock(self, conversation_id: str) -> asyncio.Lock:
        # Per (running loop, conversation) lock. The outer map is keyed by the
        # loop OBJECT in a WeakKeyDictionary so dead loops (test/TestClient
        # churn) are GC'd and growth stays bounded; production runs one loop.
        loop = asyncio.get_running_loop()
        per = self._locks.get(loop)
        if per is None:
            per = {}
            self._locks[loop] = per
        lock = per.get(conversation_id)
        if lock is None:
            lock = asyncio.Lock()
            per[conversation_id] = lock
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

    def list_conversations(self, *, limit: int, offset: int) -> list[dict[str, Any]]:
        return self._store.list(limit=limit, offset=offset)

    def delete_conversation(self, conversation_id: str) -> bool:
        deleted = self._store.delete(conversation_id)
        # Prune the conversation's lock from every per-loop map so it does not
        # linger after the conversation is gone.
        for per in list(self._locks.values()):
            per.pop(conversation_id, None)
        return deleted

    async def turn(
        self,
        conversation_id: str,
        message: str,
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        if not str(message or "").strip():
            raise ValueError("message must be a non-empty string")
        convo = self._store.get(conversation_id)
        if convo is None:
            raise KeyError(conversation_id)

        async with self._lock(conversation_id):
            # Idempotent replay: a previously-recorded turn with the same key
            # returns the stored response without re-running the transport.
            if idempotency_key:
                cached = self._store.get_idempotent(conversation_id, idempotency_key)
                if cached is not None:
                    return cached
            # Re-read inside the lock so the session id reflects any prior turn.
            convo = self._store.get(conversation_id)
            if convo is None:
                raise KeyError(conversation_id)
            turn_config = replace(
                self.config,
                profile=convo["profile"],
                model=convo["model"],
                provider=convo["provider"],
                cwd=convo["cwd"],
            )
            result = await self._transport(turn_config, message, convo["acp_session_id"])
            if not str(result.reply or "").strip():
                # A completed turn with no assistant text means the engine
                # produced nothing usable — typically an upstream provider error
                # that Hermes' ACP adapter swallowed into a silent ``end_turn``.
                # Surface it as a failure instead of recording an empty
                # "successful" turn (and leave the session id unset so the next
                # turn starts fresh).
                raise AcpTransportError(
                    f"ACP turn produced no assistant reply "
                    f"(stop_reason={result.stop_reason!r}); the upstream engine likely failed"
                )
            updated = self._store.record_turn(
                conversation_id,
                user_text=message,
                agent_text=result.reply,
                stop_reason=result.stop_reason,
                acp_session_id=result.acp_session_id,
            )
            response = {
                "conversation_id": conversation_id,
                "turn": int(updated["turns"]),
                "reply": result.reply,
                "thoughts": result.thoughts,
                "stop_reason": result.stop_reason,
                "acp_session_id": result.acp_session_id,
                # ``incomplete`` flags a non-terminal stop (refusal, cancelled,
                # max_tokens, …) so clients need not parse stop_reason. Only an
                # empty reply raises; a non-empty incomplete reply is still 200.
                "incomplete": result.stop_reason not in ("end_turn", ""),
            }
            if idempotency_key:
                self._store.put_idempotent(conversation_id, idempotency_key, response)
        return response


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


def _db_writable(db_path: str) -> bool:
    if db_path == ":memory:":
        return True
    parent = Path(db_path).parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        return False
    return os.access(str(parent), os.W_OK)


def readiness() -> dict[str, Any]:
    cfg = load_relay_config()
    hermes_bin = cfg.hermes_bin
    bin_found = bool(shutil.which(hermes_bin) or Path(hermes_bin).exists())
    # bin_runnable: for an absolute/existing path require the exec bit; for a
    # bare name (resolved via PATH) fall back to bin_found.
    bin_path = Path(hermes_bin)
    if bin_path.is_absolute() or bin_path.exists():
        bin_runnable = os.access(str(bin_path), os.X_OK)
    else:
        bin_runnable = bin_found
    cwd_ok = Path(cfg.cwd).is_dir()
    db_writable = _db_writable(cfg.db_path)
    try:
        import acp  # noqa: F401

        acp_ok = True
    except Exception:
        acp_ok = False
    return {
        "ok": bin_runnable and acp_ok and cwd_ok and db_writable,
        "profile": cfg.profile,
        "model": cfg.model,
        "provider": cfg.provider,
        "model_choice": cfg.model_choice_id(),
        "hermes_bin": hermes_bin,
        "hermes_bin_found": bin_found,
        "acp_library": acp_ok,
        "db_path": cfg.db_path,
        "checks": {
            "bin_runnable": bin_runnable,
            "cwd_ok": cwd_ok,
            "db_writable": db_writable,
            "acp_library": acp_ok,
        },
    }


def handle(action: str, payload: list[str], context: dict[str, Any]) -> dict[str, Any]:
    if action in {"health", "readiness", "status"}:
        return {"ok": True, "action": action, "readiness": readiness()}
    if action == "list":
        return {"ok": True, "action": action, "conversations": get_relay().list_conversations(limit=LIST_DEFAULT_LIMIT, offset=0)}
    if action == "get":
        conversation_id = payload[0].strip() if payload else ""
        if not conversation_id:
            return {
                "ok": False,
                "action": action,
                "error_type": "invalid_argument",
                "error": "conversation id is required",
            }
        convo = get_relay().get_conversation(conversation_id)
        if convo is None:
            return {
                "ok": False,
                "action": action,
                "conversation_id": conversation_id,
                "error_type": "not_found",
                "error": "conversation not found",
            }
        return {"ok": True, "action": action, "conversation": convo}
    return {
        "ok": False,
        "error": f"unknown action: {action}",
        "supported_actions": ["get", "health", "list", "readiness", "status"],
        "examples": [
            "aphrodite dispatch-test acp_relay:v1:status",
            "aphrodite dispatch-test acp_relay:v1:list",
            "POST /acp/conversations/{id}/turns",
        ],
    }


# --------------------------------------------------------------------------- #
# FastAPI router (owned by Aphrodite)
# --------------------------------------------------------------------------- #

def _validate_create_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate/normalize a POST /conversations body.

    Returns ``{profile, model, provider, cwd, title}`` with None where a value
    is absent or intentionally dropped. Raises ``HTTPException`` (422/403) on
    bad input.
    """
    allowed_keys = {"profile", "model", "provider", "cwd", "title"}
    unknown = sorted(set(payload) - allowed_keys)
    if unknown:
        raise HTTPException(status_code=422, detail=f"unknown keys: {unknown}")

    clean: dict[str, Any] = {}
    for field in allowed_keys:
        value = payload.get(field)
        if value is None:
            clean[field] = None
            continue
        if not isinstance(value, str):
            raise HTTPException(status_code=422, detail=f"{field} must be a string")
        value = value.strip()
        clean[field] = value or None

    # Profile allowlist (opt-in via APHRODITE_ACP_ALLOWED_PROFILES). Validate the
    # EFFECTIVE profile: when the request omits one, create_conversation() falls
    # back to the configured default, so the gate must cover that default too.
    allowed = [
        p.strip()
        for p in os.environ.get("APHRODITE_ACP_ALLOWED_PROFILES", "").split(",")
        if p.strip()
    ]
    effective_profile = clean["profile"] or _env("APHRODITE_ACP_PROFILE", DEFAULT_PROFILE)
    if allowed and effective_profile not in allowed:
        raise HTTPException(status_code=403, detail="profile not allowed")

    # cwd override gate: dropped by default; only honored when explicitly
    # enabled, and then only for an existing directory at/under the configured
    # default cwd.
    if clean["cwd"] is not None:
        if not _flag("APHRODITE_ACP_ALLOW_CWD_OVERRIDE", False):
            clean["cwd"] = None
        else:
            base = Path(_default_cwd()).resolve()
            candidate = Path(clean["cwd"]).resolve()
            if not candidate.is_dir():
                raise HTTPException(status_code=403, detail="cwd is not a directory")
            if candidate != base and base not in candidate.parents:
                raise HTTPException(status_code=403, detail="cwd outside allowed root")
            clean["cwd"] = str(candidate)

    return clean


def _require_auth(authorization: str | None = Header(default=None)) -> None:
    token = os.environ.get("APHRODITE_ACP_AUTH_TOKEN", "").strip()
    if not token:
        return
    if not authorization or not hmac.compare_digest(authorization, f"Bearer {token}"):
        raise HTTPException(status_code=401, detail="unauthorized")


router = APIRouter(
    prefix="/acp",
    tags=["acp_relay"],
    dependencies=[Depends(_require_auth)],
)


@router.get("/health")
def acp_health() -> dict[str, Any]:
    return readiness()


@router.post("/conversations")
def acp_create_conversation(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    validated = _validate_create_payload(payload or {})
    return get_relay().create_conversation(**validated)


@router.get("/conversations")
def acp_list_conversations(limit: int = LIST_DEFAULT_LIMIT, offset: int = 0) -> dict[str, Any]:
    limit = max(1, min(limit, LIST_MAX_LIMIT))
    offset = max(0, offset)
    return {
        "conversations": get_relay().list_conversations(limit=limit, offset=offset),
        "limit": limit,
        "offset": offset,
    }


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
async def acp_turn(
    conversation_id: str,
    payload: dict[str, Any],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    message = str((payload or {}).get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required")
    # Idempotency key: the ``Idempotency-Key`` header wins over a payload key.
    payload_key = (payload or {}).get("idempotency_key")
    key = idempotency_key or (payload_key if isinstance(payload_key, str) else None)
    relay = get_relay()
    try:
        return await relay.turn(conversation_id, message, idempotency_key=key)
    except KeyError:
        raise HTTPException(status_code=404, detail="conversation not found")
    except AcpTransportError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
