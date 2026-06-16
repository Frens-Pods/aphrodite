# Aphrodite production endpoint preflight

Purpose: prepare a non-live checker for the public Discord Interaction Endpoint URL before any approved cutover. This pack validates disk/env shape and prints operator checks only. It does not call Discord, does not change Discord endpoint configuration, does not reload Caddy, and does not start/restart/reload Hermes, Forge, or Aphrodite.

## Non-live checker

Run from the Aphrodite root:

```bash
cd ~/aphrodite
PYTHONDONTWRITEBYTECODE=1 python scripts/aphrodite endpoint-preflight
```

The checker reports:

- `APHRODITE_PUBLIC_BASE_URL`: the approved public HTTPS origin only, for example `https://<approved-host>`. The interaction path is appended by Aphrodite as `https://<approved-host>/discord/interactions`.
- `APHRODITE_DISCORD_PUBLIC_KEY`: Discord application public key, not the bot token. It must be 64 hex characters and comes from process env or `config/aphrodite.env`.
- Caddy template expectations: host block present, `POST /discord/interactions` routed to Aphrodite, and `GET /health` / `GET /status` exposed without a catch-all proxy.
- Safe follow-up checks to run only after an approved service/proxy activation.

If `APHRODITE_PUBLIC_BASE_URL` is not configured, the checker falls back to the host in `caddy/aphrodite.caddy.example` or `<approved-host>` as an operator placeholder. Placeholder output is not approval to edit the Discord application endpoint.

## Required env shape

Private env file or service environment:

```bash
APHRODITE_PUBLIC_BASE_URL=https://<approved-host>
APHRODITE_DISCORD_PUBLIC_KEY=<64-hex Discord application public key>
```

Do not include `/discord/interactions`, query strings, or fragments in `APHRODITE_PUBLIC_BASE_URL`; Aphrodite appends the path and reports the exact `interaction_url`.

## GET-only public smokes after approved activation

After the service is already running and the approved Caddy/proxy route is already active, use GET-only checks first:

```bash
curl -fsS https://<approved-host>/health
curl -fsS https://<approved-host>/status
```

Expected:

- `/health`: JSON with `ok=true`, `service=aphrodite`, and `policy=no-hermes-core`.
- `/status`: JSON including `service_readiness`, `http_observability`, and `production_endpoint_preflight`.

Then check fail-closed unsigned interaction behavior without mutating Discord state:

```bash
curl -i -X POST https://<approved-host>/discord/interactions \
  -H 'Content-Type: application/json' \
  -d '{}'
```

Expected result: `401 Invalid Discord interaction signature`, or `503 Discord public key is not configured` before env is installed. It must never return a successful Nudge/Kanban action.

## Activation boundary

Do not change the Discord application interaction endpoint during an autonomous tick. Do not start, restart, reload, enable, or disable services. Do not reload Caddy. Do not edit Hermes config. Do not run `hermes gateway run --replace`. Do not create/update/remove cron jobs. Do not perform Discord POST/PATCH/PUT/DELETE/pin/unpin live card mutations.

If the endpoint preflight says a public URL, public key, Caddy host/path, service, proxy, secret, or Discord endpoint action is missing, stop and report that exact blocker until an operator gives named approval for the relevant activation step.

## Rollback

Rollback is also approval-bound: restore the previous Discord application endpoint or clear it, remove/disable the Aphrodite Caddy route, and stop/disable Aphrodite service only in an approved activation/rollback window. Disk docs/tests/checkers remain safe to keep and rerun.
