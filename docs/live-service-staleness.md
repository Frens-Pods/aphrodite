# Aphrodite live service staleness guidance

Purpose: explain `service_readiness.live.stale_vs_disk` without turning a scheduled readiness tick into an activation or restart.

## What the field means

`service_readiness.live.stale_vs_disk=true` means Aphrodite could read systemd metadata for `aphrodite.service`, compare `ExecMainStartTimestamp` against the latest Aphrodite disk code/template mtime, and the live process appears older than the disk artifacts.

That is evidence only. It usually means disk verification is newer than the currently running service. It does **not** prove the service is broken, and it does **not** authorize Forge to start, restart, reload, enable, disable, or reconfigure anything.

If `service_readiness.live.available=false`, the service may be absent, systemd may be unavailable, or `systemctl show` may have failed. Treat that as a blocker/reporting state, not as approval to install or start the service.

## Read-only checks allowed during autonomous ticks

From the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python scripts/aphrodite doctor
PYTHONDONTWRITEBYTECODE=1 python scripts/aphrodite endpoint-preflight
bash scripts/verify.sh
```

These checks may report `service_readiness.live.stale_vs_disk`; they must not resolve it.

## Approval phrases required to resolve staleness

Use named, scoped approval. Do not infer one approval from another.

- `I approve installing Aphrodite private env now.`
- `I approve installing and starting aphrodite.service now.`
- `I approve restarting/reloading aphrodite.service now.`
- `I approve applying the Aphrodite Caddy route and reloading Caddy now.`
- `I approve setting the Discord application interaction endpoint to <URL> now.`
- `I approve restarting/reloading <exact Hermes service> now.`

## Forbidden without named approval

- Do not start, restart, reload, enable, disable, or install `aphrodite.service`.
- Do not reload Caddy or apply proxy config.
- Do not edit Hermes config or restart/reload/replace Hermes, Forge, Aphrodite, or any gateway.
- Do not run `hermes gateway run --replace`.
- Do not change the Discord application interaction endpoint.
- Do not POST/PATCH/PUT/DELETE/pin/unpin live Discord cards.
- Do not create, update, remove, or recursively manage cron jobs.

## Rollback boundary

Rollback also needs named approval unless a live service is already proven broken and rollback is the agreed repair. Restore prior env/unit/proxy/Discord endpoint/card state inside that approved window. Do not run `hermes gateway run --replace` as rollback without named approval.

## Where this appears

- `python scripts/aphrodite doctor` includes `service_readiness.live.staleness_guidance` when systemd status is available.
- `/status` includes the same `service_readiness` payload after approved service activation.
- `docs/deployment.md` and `docs/production-endpoint-preflight.md` point back here for interpretation.
