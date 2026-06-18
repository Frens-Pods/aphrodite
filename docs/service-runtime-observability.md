# Aphrodite service runtime observability

This pack is for the first operator checks after an explicitly approved Aphrodite service/proxy activation. It is intentionally read-only: it documents expected `GET` checks and `/status` fields, but it does not authorize service starts/restarts/reloads, Hermes config edits, cron changes, Discord endpoint changes, or live Discord message mutations.

## Safe local checks after approved activation

Run only after `aphrodite.service` is already running under an approved activation window:

```bash
curl -fsS http://127.0.0.1:9079/health
curl -fsS http://127.0.0.1:9079/status
.venv/bin/python scripts/aphrodite doctor
```

Expected `/health` shape:

```json
{
  "ok": true,
  "service": "aphrodite",
  "policy": "no-hermes-core"
}
```

Expected `/status` top-level fields:

- `ok`, `service`, `version`, `policy`, `modules`
- `registered_systems`
- `mcp`
- `service_readiness`
- `http_observability`

`service_readiness.live` is read-only systemd evidence. It may report the service missing or stale; that is a blocker report, not approval to restart. `http_observability` repeats the read-only curl commands and the forbidden-without-approval list so a live operator can see the boundary from the service itself.

## Safe proxy checks after approved Caddy/proxy activation

After the approved proxy route is applied and Caddy reload is explicitly approved/completed, repeat the same GET-only checks through the approved public host:

```bash
curl -fsS https://<approved-host>/health
curl -fsS https://<approved-host>/status
```

Then confirm the production Discord interaction route fails closed for unsigned input:

```bash
curl -i -X POST https://<approved-host>/discord/interactions \
  -H 'Content-Type: application/json' \
  -d '{}'
```

Expected result: `401 Invalid Discord interaction signature`, or `503 Discord public key is not configured` if production env has not been installed. It must not return a successful action.

## Boundary

Forbidden without named approval:

- `systemctl start`, `restart`, `reload`, `enable`, or `disable` for `aphrodite.service`
- Caddy reload or proxy config changes
- Hermes config edits or Hermes gateway reload/restart/replace
- `hermes gateway run --replace`
- Discord application interaction endpoint changes
- Discord POST/PATCH/PUT/DELETE/pin/unpin live card mutations
- cron creation, removal, or recursive management

Rollback after an approved activation remains: remove or disable the Aphrodite proxy route, restore the prior Discord application interaction endpoint or clear it, stop/disable `aphrodite.service` only under the same named-approval discipline, and restore any state files from the activation bundle backups.
