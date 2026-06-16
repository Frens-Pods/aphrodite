# Signed Discord interaction negative fixtures

This pack is a non-activation readiness check for Aphrodite-owned Discord interaction handling.

## What it proves

`tests/test_signed_interaction_negative_fixtures.py` posts deterministic Ed25519-signed requests to the production route (`POST /discord/interactions`) and verifies fail-closed handling for:

- stale component custom-id versions such as `skillopt:v0:status`;
- malformed custom IDs that do not match `<system>:<version>:<action>[:payload...]`;
- unknown systems such as `unknown:v1:*`;
- unsupported actions such as `skillopt:v1:archive:*`;
- component payloads missing `data.custom_id`;
- invalid JSON after signature verification.

The stale-version case runs with valid request signing on purpose. It proves that an old signed `v0` button is rejected by the router before a module can perform module side effects.

## Expected safe failure behavior

For component-level failures Aphrodite returns a private ephemeral Discord response (`type: 4`, `data.flags: 64`) with the diagnostic embedded in `aphrodite`. It does **not** return a public channel message, perform Discord REST writes, publish cards, or perform module side effects. Invalid JSON is rejected at the HTTP boundary with `400 Invalid JSON payload` before dispatch.

Current custom-id version policy is intentionally narrow: registered sidecar component routes support `v1` only. Future versions should be added deliberately in `aphrodite/router.py` with regression coverage for stale-version rejection and migration behavior.

## Safe command

```bash
cd ~/aphrodite
PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_signed_interaction_negative_fixtures.py -q
```

This command starts no service, changes no external runtime config, changes no Discord endpoint, performs no live Discord REST calls, mutates no live card, and manages no cron jobs.

## Activation boundary

These fixtures are disk/readiness evidence only. Live cutover still requires explicit approval for Aphrodite service/proxy activation, Discord interaction endpoint changes, production secrets/allowlists, and any surrounding runtime restart or reload.
