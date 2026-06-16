# ACP relay

`aphrodite/modules/acp_relay.py` lets Aphrodite bridge HTTP or dispatch calls to an external ACP agent runtime while keeping conversation state in Aphrodite-owned SQLite.

## Public surfaces

The module exposes three integration points.

### FastAPI router

```python
router = APIRouter(prefix="/acp", tags=["acp_relay"])
```

`aphrodite.app.create_app()` includes this router. Routes include:

- `GET /acp/health` — relay readiness/configuration summary.
- `POST /acp/conversations` — create a conversation record.
- `GET /acp/conversations` — list conversations.
- `GET /acp/conversations/{conversation_id}` — read one conversation.
- `DELETE /acp/conversations/{conversation_id}` — delete one conversation.
- `POST /acp/conversations/{conversation_id}/turns` — send one user message through the ACP transport.

### Dispatch handler

```python
def handle(action: str, payload: list[str], context: dict[str, Any]) -> dict[str, Any]:
    ...
```

Registering `acp_relay` in `APHRODITE_MODULES` makes this callable available through `DispatchRouter`. Actions `health`, `readiness`, and `status` return the readiness payload. Other dispatch actions currently return a handled-false response that points callers to the `/acp` HTTP routes.

### Relay classes

- `RelayConfig` stores profile, model, provider, binary, working directory, timeout, database path, and protocol version.
- `ConversationStore` persists conversations and turns in SQLite.
- `AcpRelay` orchestrates conversation creation, lookup, deletion, and turn execution.
- `configure_relay()` and `reset_relay()` let tests or embedding code replace the process-wide relay singleton.

## Runtime model

For a real turn, `acp_transport()` spawns:

```text
hermes -p <profile> acp
```

It then uses the ACP client protocol to create or resume a session, set the requested model, send the user message, and collect assistant reply chunks and thought chunks.

The `acp` Python client is imported lazily inside `acp_transport()`. This keeps the module importable when the optional ACP client is not installed. In that case, real turns fail with an `AcpTransportError`, while tests and fake transports can still use the rest of the module.

The subprocess environment sets these defaults if they are not already present:

- `HERMES_YOLO_MODE=1`
- `HERMES_ACCEPT_HOOKS=1`

Those defaults prevent non-interactive ACP turns from blocking on approval prompts.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `APHRODITE_ACP_PROFILE` | `forge` | Profile passed to `hermes -p <profile> acp`. |
| `APHRODITE_ACP_MODEL` | `openai/gpt-4o-mini` | Model name used in the ACP model choice id. |
| `APHRODITE_ACP_PROVIDER` | `openrouter` | Provider name used in the ACP model choice id. |
| `APHRODITE_ACP_HERMES_BIN` | discovered `hermes` binary | Explicit executable path or command name for the external runtime. |
| `APHRODITE_ACP_DB` | `<hermes_root>/aphrodite/acp_relay.sqlite3` | SQLite database path. |
| `APHRODITE_ACP_CWD` | shared Hermes root | Working directory for the subprocess. |
| `APHRODITE_ACP_TURN_TIMEOUT` | `240.0` | Maximum seconds for one ACP turn. |

`RelayConfig.model_choice_id()` combines provider and model as:

```text
<provider>:<model>
```

## Minimal local smoke

1. Install the optional ACP client in the environment if you want real turns.
2. Set any needed `APHRODITE_ACP_*` overrides.
3. Start Aphrodite.
4. Check readiness:

```sh
curl http://127.0.0.1:9079/acp/health
```

5. Create a conversation, then post turns to `/acp/conversations/{conversation_id}/turns`.

Keep hostnames, tokens, profile homes, and deployment paths in private configuration, not in tracked docs.
