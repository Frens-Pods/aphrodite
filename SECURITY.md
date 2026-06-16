# Security Policy

## Reporting

Open a private security advisory on the GitHub repository to report vulnerabilities.

## Discord interaction verification

Inbound Discord interaction requests are verified with Ed25519 using `APHRODITE_DISCORD_PUBLIC_KEY`. Unsigned or invalid requests are rejected with HTTP 401. If the public key is not configured, the interaction endpoint returns HTTP 503.

## Secrets handling

Never commit secrets. `config/aphrodite.env` is gitignored and is intended for local or deployment-specific values. Use environment variables or the systemd `EnvironmentFile` to provide secrets at runtime.

## Supported versions

| Version | Supported |
| --- | --- |
| 0.1.x | Yes |
