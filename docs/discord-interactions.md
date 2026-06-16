# Discord interactions

Aphrodite exposes Discord interaction intake through `aphrodite.app.create_app()` and delegates payload handling to `aphrodite.discord.intake`.

## Production endpoint

```text
POST /discord/interactions
```

This endpoint is for Discord's application interaction callback URL. Discord must send these headers:

- `X-Signature-Ed25519`
- `X-Signature-Timestamp`

Aphrodite reads `APHRODITE_DISCORD_PUBLIC_KEY` from the environment and verifies the raw request body with `aphrodite.discord.signature.verify_discord_signature()`.

Verification details from `aphrodite/discord/signature.py`:

- Discord signs `timestamp + raw_body` with the application Ed25519 key.
- The verifier returns `False` for missing or malformed inputs instead of raising.
- Bad signatures and malformed hex fail closed.

HTTP failure behavior from `aphrodite/app.py`:

- `503` when `APHRODITE_DISCORD_PUBLIC_KEY` is unset.
- `401` when signature verification fails.
- `400` when the signed body is not valid JSON or is not a JSON object.

## Dry-run endpoint

```text
POST /discord/interactions/dry-run
```

The dry-run endpoint calls the same payload handler as production but skips Discord signature verification. Use it only for local tests and fixture-driven development.

## Payload handling

`aphrodite.discord.intake.handle_interaction_payload(payload, router)` handles the Discord payload after HTTP-level verification.

Supported interaction paths:

- Discord ping (`type: 1`) returns pong (`type: 1`).
- Component interactions (`type: 3`) read `data.custom_id` and dispatch it through `DispatchRouter`.
- Missing `custom_id`, router failures, unsupported adapter actions, and adapter-level `ok: false` responses return ephemeral error messages.
- Successful adapter dispatch returns a Discord channel message (`type: 4`) unless the adapter asks for `discord_response: "deferred_update"`, in which case Aphrodite returns deferred update (`type: 6`).

The context passed into adapters includes user, member, role, message, channel, guild, selected component values, and raw interaction data when those fields are present in the Discord payload.

## Custom IDs

Component custom IDs use the router format:

```text
system:v1:action:arg1:arg2
```

Examples:

```text
skillopt:v1:status
image_gen:v1:status
acp_relay:v1:health
```

Keep custom IDs small and deterministic; Discord sends them back verbatim during component interactions.
