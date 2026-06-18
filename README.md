# Aphrodite

Aphrodite is a small, self-contained sidecar backend for local Hermes plugin
products. It exposes a FastAPI service that verifies and routes Discord
interactions, serves a handful of HTTP/MCP surfaces, and dispatches actions to
pluggable **module adapters** — without ever modifying the Hermes core.

Hermes is treated as an external agent runtime. Aphrodite integrates with it
only through documented plugin APIs, Discord/webhook traffic, FastAPI routes,
static files, cron/systemd, and the local filesystem. See
[`NO_CORE_POLICY.md`](NO_CORE_POLICY.md) for the design rule.

Hermes = the external local agent runtime Aphrodite never patches.
MCP = Model Context Protocol stdio server for tool clients.
ACP = Agent Client Protocol relay for conversations.

## Start here (local in 5 commands)

```bash
curl --proto '=https' --tlsv1.2 -fsSL https://raw.githubusercontent.com/Advenaa/aphrodite/main/install.sh | bash
aphrodite serve &
curl --retry 20 --retry-delay 1 --retry-connrefused -fsS http://127.0.0.1:9079/health
aphrodite new-module demo
aphrodite modules
```

The background server keeps running; bring it back with `fg`, then press Ctrl-C
when you are done.

## Features

- **Discord interaction endpoint** with fail-closed Ed25519 signature
  verification (`POST /discord/interactions`) plus an unsigned
  `POST /discord/interactions/dry-run` for local testing.
- **Custom-id dispatch router**: interactions and HTTP calls are routed by a
  `system:v1:action:...` custom id to a registered module adapter.
- **Bundled module adapters**: `skillopt` runs fully inside Aphrodite;
  `image_gen` and `acp_relay` are integration adapters that need private
  Hermes runtime/auth pieces for live work. Additional module adapters can be
  enabled with `APHRODITE_MODULES`; unknown names register a placeholder
  handler instead of breaking startup.
- **Operator-readiness surfaces**: `/health`, `/status`, a `doctor` command,
  and read-only deployment preflight checks.
- **Optional MCP server** (`aphrodite/mcp_server.py`) exposing skillopt tools
  over stdio.

If you see references to `nudge`/`readsurface`/`soulglass`/`kanban`/`nixie`, those are operator-private adapters; public users do not need them — unknown configured names become harmless placeholders (see `aphrodite modules`).

### Write your own module

Modules are ordinary Python plugins discovered through the
`aphrodite.adapters` entry point, so you can add one without editing Aphrodite
core. Start fastest with `aphrodite new-module <name>`, or copy the worked
starter in `examples/hello_adapter/`; full details live in
[`docs/module-adapters.md`](docs/module-adapters.md).

## Install

Install from GitHub (no clone needed):

```bash
pip install "git+https://github.com/Advenaa/aphrodite"
# with optional extras (MCP server, ACP relay transport):
pip install "aphrodite-sidecar[mcp,acp] @ git+https://github.com/Advenaa/aphrodite"
```

Or from a clone:

```bash
git clone https://github.com/Advenaa/aphrodite && cd aphrodite
python3 -m venv .venv && . .venv/bin/activate
.venv/bin/python -m pip install .                  # users
.venv/bin/python -m pip install -e ".[dev]"        # contributors (editable + test deps)
```

Requires Python 3.10+. Runtime dependencies: `fastapi`, `pynacl`, `uvicorn`. Extras: `mcp` (MCP server), `acp` (ACP relay transport).

## Updating

Use the same one-line installer for first installs and later updates:

```bash
curl --proto '=https' --tlsv1.2 -fsSL https://raw.githubusercontent.com/Advenaa/aphrodite/main/install.sh | bash
```

From an existing install:

```bash
aphrodite update          # self-upgrade; prints before -> after and preserves [mcp,acp] extras automatically
aphrodite update --check  # compare only; makes no changes
aphrodite version         # print the installed Aphrodite version
```

Aphrodite shows a daily update notice in interactive terminals. Disable it with
`APHRODITE_NO_UPDATE_NOTIFIER=1`.

Manual fallback:

```bash
pip install --upgrade "aphrodite-sidecar[mcp,acp] @ git+https://github.com/Advenaa/aphrodite"
```

## Quickstart

```bash
# Run the service (development)
aphrodite serve

# In another shell
curl -fsS http://127.0.0.1:9079/health
curl -fsS http://127.0.0.1:9079/status
```

Advanced/manual Uvicorn equivalent:

```bash
uvicorn aphrodite.app:create_app --factory --host 127.0.0.1 --port 9079
```

## CLI

The `aphrodite` console script (and `.venv/bin/python scripts/aphrodite` from a clone) exposes:

| Command | Purpose |
| --- | --- |
| `serve [--host H] [--port P] [--reload]` | Start the FastAPI service using config defaults unless overridden. |
| `modules` | Print configured, discovered, active, missing, and available module adapters. |
| `new-module <name> [--dir DIR]` | Scaffold a ready-to-edit third-party module adapter package. |
| `health` | Print the health payload. |
| `doctor` | Report required files, env, MCP and service readiness. |
| `preflight [--production]` | Report whether the service is ready to activate, without starting it. |
| `endpoint-preflight` | Read-only readiness for the public Discord interaction endpoint. |
| `dispatch-test <custom_id>` | Dispatch a custom id through the configured router; exits nonzero when routing or handler `result.ok` fails. |
| `version` | Print the installed Aphrodite version. |
| `update [--check]` | Self-upgrade the install and print before/after versions; `--check` only compares. |

## MCP server

Aphrodite ships an optional [MCP](https://modelcontextprotocol.io) server exposing the review-gated SkillOpt tools plus read-only image_gen and acp_relay metadata over stdio. It requires the `mcp` extra:

```bash
.venv/bin/python -m pip install "aphrodite-sidecar[mcp] @ git+https://github.com/Advenaa/aphrodite"
.venv/bin/python -m aphrodite.mcp_server      # stdio transport from a clone
```

Register it with an MCP client by pointing the client at your venv's Python:

```json
{
  "mcpServers": {
    "aphrodite": {
      "command": "/path/to/.venv/bin/python",
      "args": ["-m", "aphrodite.mcp_server"]
    }
  }
}
```

For the Hermes agent, add the same entry under `mcp_servers.aphrodite` in the relevant Hermes profile config and start a fresh Hermes process. Run `aphrodite doctor` to confirm MCP readiness.

## Configuration

Configuration is environment-driven. The most important variables:

- `APHRODITE_HOST` (default `127.0.0.1`), `APHRODITE_PORT` (default `9079`)
- `APHRODITE_MODULES` — comma-separated list of enabled module adapters
- APHRODITE_CORS_ORIGINS — comma-separated browser origins allowed to call the HTTP API cross-origin (unset = CORS disabled; * allows any origin with credentials disabled)
- `HERMES_HOME` — locates the external Hermes home (falls back to `~/.hermes`)
- `APHRODITE_DISCORD_PUBLIC_KEY` — Discord application public key used to verify
  inbound interaction signatures (required for the production endpoint)
- `APHRODITE_PUBLIC_BASE_URL` — public HTTPS base URL of the deployment
- `image_gen` HTTP generation does **not** read an `OPENAI_API_KEY`. The
  route builds a Codex/OpenAI client from the Hermes `agent` stack's OAuth
  token. Without that private auth it returns `auth_required`; standalone
  callers must invoke `generate_image(payload, client=<openai.OpenAI>)` with
  their own client.

Copy the template and edit locally (the real file is gitignored):

```bash
cp config/aphrodite.env.example config/aphrodite.env
```

See [`docs/configuration.md`](docs/configuration.md) for the full list.

## Documentation

| If you want to… | Read | Audience |
| --- | --- | --- |
| configure host, port, modules, CORS, Discord, or ACP auth | [Configuration](docs/configuration.md) | operator |
| deploy on a host with systemd and a reverse proxy | [Deployment](docs/deployment.md) | operator |
| run the sidecar in Docker or Compose | [Container deployment](docs/deployment-docker.md) | operator |
| understand signed Discord interaction intake | [Discord interactions](docs/discord-interactions.md) | operator, contributor |
| write or troubleshoot a module adapter | [Module adapters](docs/module-adapters.md) | author |
| use the ACP conversation relay | [ACP relay](docs/acp-relay.md) | operator, author |
| keep private deployment material out of the public repo | [Private overlay](docs/private-overlay.md) | operator, contributor |
| interpret live service staleness reports | [Live service staleness](docs/live-service-staleness.md) | operator |
| preflight the public Discord endpoint before cutover | [Production endpoint preflight](docs/production-endpoint-preflight.md) | operator |
| observe a running service after approved activation | [Service runtime observability](docs/service-runtime-observability.md) | operator |
| maintain negative signed-interaction fixtures | [Signed interaction negative fixtures](docs/signed-interaction-negative-fixtures.md) | contributor |
| see release history | [Changelog](CHANGELOG.md) | operator, contributor |

## Deployment

Templates ship as examples only:

- `config/aphrodite.env.example` — environment file template
- `systemd/aphrodite.service.example` — systemd unit template
- `caddy/aphrodite.caddy.example` — reverse-proxy route template

The systemd template intentionally does not auto-start or enable the service.
**Do not start or enable the service until** preflight passes and an operator
has approved activation. Set `APHRODITE_DISCORD_PUBLIC_KEY` (the Discord
application public key, not the bot token) before exposing the production
interaction endpoint. See [`docs/deployment.md`](docs/deployment.md).

Aphrodite also ships a multi-stage `Dockerfile`, `.dockerignore`, and a
`docker-compose.yml` example for container deployments. The container binds
`0.0.0.0` (the app default stays loopback) and publishes to host loopback for a
reverse proxy to front. See [`docs/deployment-docker.md`](docs/deployment-docker.md).

## Development

```bash
.venv/bin/python -m pytest tests -q     # run the test suite
bash scripts/verify.sh        # compile, focused packs, full suite, read-only command smoke
```

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Operator-private material (real env,
real Discord IDs, absolute deployment paths, activation runbooks) lives in a
gitignored `.local/` overlay and is never committed.

## License

MIT. See [`LICENSE`](LICENSE).
