# Aphrodite no-core policy

Aphrodite is a unified sidecar backend for dynamic behavior around local Hermes plugin products.

Hard boundary:

- Do not edit Hermes core to make Aphrodite work.
- Do not require custom Hermes gateway hooks.
- Do not mount routes by modifying Hermes dashboard/server code.
- Do not make Hermes core aware of Nudge, Readsurface, Soulglass, Kanban, or Aphrodite product logic.

Allowed integration surfaces:

- Existing Hermes plugin APIs for agent-facing tools/commands/hooks.
- Plugin/shared core libraries imported from stable local paths.
- Discord Bot API / webhooks owned by Aphrodite.
- FastAPI/HTTP routes owned by Aphrodite.
- Static files served by Aphrodite or Caddy.
- Cron/systemd jobs that call Aphrodite or plugin scripts.
- SQLite/filesystem state documented by each module.

If an upstream Hermes extension point is missing, redesign through Aphrodite/static/cron/MCP/webhook/CLI instead of patching Hermes core.
