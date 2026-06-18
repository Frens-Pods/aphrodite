# Deployment

Aphrodite is a FastAPI sidecar. It can run directly with `aphrodite serve` for development or behind a service manager and reverse proxy for production.

For running Aphrodite in a container instead, see
[Container deployment](deployment-docker.md).

## Development server

From the repository root:

```sh
aphrodite serve
```

Advanced/manual Uvicorn equivalent:

```sh
uvicorn aphrodite.app:create_app --factory --host 127.0.0.1 --port 9079
```

Useful local checks:

```sh
curl http://127.0.0.1:9079/health
curl http://127.0.0.1:9079/status
```

`/health` and `/status` are GET-only endpoints. Discord interactions and dispatch calls use POST routes.

## Environment file

Create a private runtime env file from the public template:

```sh
cp config/aphrodite.env.example config/aphrodite.env
```

Fill in only local or deployment-specific values in `config/aphrodite.env`. Keep real Discord tokens, public keys, channel IDs, and filesystem paths out of tracked files.

## Production service template

The public repository ships a systemd template at:

```text
systemd/aphrodite.service.example
```

Treat it as a starting point. Copy it into your host's systemd unit directory, adjust paths, user/group, environment file location, and Uvicorn arguments for that host, then review it before starting anything.

Do not auto-start or auto-enable services from repository templates. A service should only be started by an operator after configuration, secrets, reverse proxy routing, and Discord endpoint settings are reviewed.

## Reverse proxy template

The public Caddy example lives at:

```text
caddy/aphrodite.caddy.example
```

Use placeholder hosts while editing examples, for example:

```text
aphrodite.example.internal
```

The proxy should forward the public HTTPS origin to the local Aphrodite listener. Keep the backend bound to loopback unless your deployment model explicitly requires otherwise.

## Discord application endpoint

In the Discord developer portal, set the application interaction endpoint to:

```text
https://aphrodite.example.internal/discord/interactions
```

The production endpoint verifies Discord's `X-Signature-Ed25519` and `X-Signature-Timestamp` headers against `APHRODITE_DISCORD_PUBLIC_KEY`. Use `/discord/interactions/dry-run` only for local testing; it intentionally skips Discord signatures.

## Minimal production checklist

1. Copy `config/aphrodite.env.example` to a private env file and fill in deployment values.
2. Set `APHRODITE_DISCORD_PUBLIC_KEY` before exposing `/discord/interactions`.
3. Configure the reverse proxy from `caddy/aphrodite.caddy.example` with a real HTTPS hostname.
4. Copy and adapt `systemd/aphrodite.service.example` for the target host.
5. Confirm `GET /health` and `GET /status` work through the proxy.
6. Configure Discord to use `https://aphrodite.example.internal/discord/interactions` or your deployment's equivalent placeholder-replaced URL.
7. Start or enable the service only after the previous checks are complete.
