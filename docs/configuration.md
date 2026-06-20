# Configuration

Aphrodite reads runtime configuration from environment variables. You do not
need an env file for a local `/health` trial; the defaults bind to
`127.0.0.1:9079` with the public module set.

Copy the example file only when you need non-default host/port, module
selection, CORS, production Discord verification, or ACP auth:

```sh
cp config/aphrodite.env.example config/aphrodite.env
```

`config/aphrodite.env` is local operator configuration and must not be committed.

## Core service settings

| Variable | Default | Used by | Purpose |
| --- | --- | --- | --- |
| `APHRODITE_HOST` | `127.0.0.1` | `aphrodite.config.load_config` | Bind host used by CLI/service configuration. |
| `APHRODITE_PORT` | `9079` | `aphrodite.config.load_config` | Bind port. Invalid values fall back to `9079`. |
| `APHRODITE_MODULES` | `image_gen,skillopt,acp_relay` | `aphrodite.config.load_config`, `aphrodite.app.build_router` | Module selection for the dispatch router: unset/empty uses the default trio; `+name` appends to the built-in modules; a bare comma-separated list replaces them — use bare only to intentionally reduce the set. Unknown names register a placeholder handler. |
| APHRODITE_CORS_ORIGINS | none (CORS disabled) | aphrodite.config.load_config, aphrodite.app.create_app | Comma-separated browser origins allowed to call HTTP routes cross-origin. Unset → no CORS middleware (loopback-only). Use * to allow any origin (credentials are then disabled per the CORS spec). |
| `HERMES_HOME` | `~/.hermes` | `aphrodite.config`, `aphrodite.paths` | Locates the external Hermes home. If it points at `<root>/profiles/<name>`, `hermes_root()` collapses to `<root>` for shared plugin discovery. |
| `APHRODITE_PUBLIC_BASE_URL` | none | readiness/preflight helpers | Public HTTPS origin for endpoint preflight. Do not include `/discord/interactions`; Aphrodite appends that path when checking the Discord endpoint. |

## Discord interaction and authorization settings

| Variable | Default | Used by | Purpose |
| --- | --- | --- | --- |
| `APHRODITE_DISCORD_PUBLIC_KEY` | none | `aphrodite.app`, `aphrodite.discord.signature` | Discord application Ed25519 public key for inbound `/discord/interactions` signature verification. Production interactions fail closed with `503` when unset. |
| `APHRODITE_DISCORD_BOT_TOKEN` | none | preflight helpers | Outbound Discord bot token used by read-only deployment preflight checks. |
| `APHRODITE_DISCORD_EXPECTED_BOT_ID` | none | endpoint/preflight helpers | Optional expected bot id checked by live-publish preflight. |
| `APHRODITE_DISCORD_EXPECTED_BOT_USERNAME` | none | endpoint/preflight helpers | Optional expected bot username checked by live-publish preflight. |

## Module runtime overrides

### Image generation

| Variable | Default | Purpose |
| --- | --- | --- |
| `APHRODITE_IMAGE_GEN_MODEL` | profile config or `gpt-image-2-medium` | Selects one of `gpt-image-2-low`, `gpt-image-2-medium`, or `gpt-image-2-high`. |
| `OPENAI_IMAGE_MODEL` | profile config or `gpt-image-2-medium` | Secondary model override checked after `APHRODITE_IMAGE_GEN_MODEL`. |

`image_gen` authentication is not configured with `OPENAI_API_KEY`. The HTTP
route reads a Hermes Codex/OpenAI OAuth token through the private `agent` stack;
without that private auth it returns `auth_required`. To use image generation
without the Hermes auth stack, call `generate_image(payload, client=<your
OpenAI client>)` programmatically.

### SkillOpt

| Variable | Default | Purpose |
| --- | --- | --- |
| `APHRODITE_SKILLOPT_DATA_ROOT` | `data/skillopt` under the repository root | Storage root for SkillOpt runs and evaluations. |
| `SKILLOPT_REPO` | none | Repository containing `scripts/train.py` when a train request does not provide an explicit command. |

### ACP relay

| Variable | Default | Purpose |
| --- | --- | --- |
| `APHRODITE_ACP_PROFILE` | `forge` | Hermes profile used when spawning `hermes -p <profile> acp`. |
| `APHRODITE_ACP_MODEL` | (unset) | Optional model override; only used with `APHRODITE_ACP_PROVIDER`. When unset, the relay uses the Hermes profile's configured engine. |
| `APHRODITE_ACP_PROVIDER` | (unset) | Optional provider override; only used with `APHRODITE_ACP_MODEL`. When unset, the relay uses the Hermes profile's configured engine. |
| `APHRODITE_ACP_HERMES_BIN` | discovered `hermes` executable | Binary used to spawn the external ACP runtime. |
| `APHRODITE_ACP_DB` | `<hermes_root>/aphrodite/acp_relay.sqlite3` | SQLite conversation store path. |
| `APHRODITE_ACP_CWD` | shared Hermes root | Working directory for the ACP subprocess and the base directory for gated request `cwd` overrides. |
| `APHRODITE_ACP_TURN_TIMEOUT` | `240.0` | Per-turn timeout in seconds. |
| `APHRODITE_ACP_AUTH_TOKEN` | (unset; no auth) | Optional bearer token for `/acp/*`. When unset, `/acp` routes remain open for local use; when set, requests must send `Authorization: Bearer <token>`. |
| `APHRODITE_ACP_ALLOWED_PROFILES` | (unset; any profile) | Optional comma-separated allowlist for requested conversation profiles. When unset, any profile may be requested. |
| `APHRODITE_ACP_ALLOW_CWD_OVERRIDE` | `false` | Allows request payloads to override `cwd` only when true; by default request `cwd` values are ignored and the configured relay cwd is used. |
| `APHRODITE_ACP_AUTO_APPROVE` | `true` | Auto-approves ACP permission prompts and sets `HERMES_YOLO_MODE=1` for the subprocess unless already set. Set false to deny permission prompts. |
| `APHRODITE_ACP_ACCEPT_HOOKS` | `true` | Sets `HERMES_ACCEPT_HOOKS=1` for the subprocess unless already set. Set false to avoid accepting Hermes hooks automatically. |

The ACP transport sets `HERMES_YOLO_MODE=1` and `HERMES_ACCEPT_HOOKS=1` in the subprocess environment only while `APHRODITE_ACP_AUTO_APPROVE` and `APHRODITE_ACP_ACCEPT_HOOKS` are true. Both default to true so existing headless forge flows keep running.

All `/acp/*` routes require `Authorization: Bearer <token>` only when `APHRODITE_ACP_AUTH_TOKEN` is set. With the default unset token, the routes are open for local deployments.

`GET /acp/conversations` supports pagination with `limit` and `offset` query parameters. `limit` defaults to `50` and is clamped to a maximum of `200`; `offset` defaults to `0`.

`POST /acp/conversations/{conversation_id}/turns` accepts an idempotency key either in the `Idempotency-Key` header or as `idempotency_key` in the JSON payload. The header wins when both are present. A repeated key for the same conversation returns the stored successful response instead of running the transport again.
