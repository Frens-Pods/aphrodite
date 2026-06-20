# Security Policy

## Reporting

Open a private security advisory on the GitHub repository to report vulnerabilities.

## Discord interaction verification

Inbound Discord interaction requests are verified with Ed25519 using `APHRODITE_DISCORD_PUBLIC_KEY`. Unsigned or invalid requests are rejected with HTTP 401. If the public key is not configured, the interaction endpoint returns HTTP 503.

## Secrets handling

Never commit secrets. `config/aphrodite.env` is gitignored and is intended for local or deployment-specific values. Use environment variables or the systemd `EnvironmentFile` to provide secrets at runtime.

## Adapter security model

Aphrodite discovers third-party adapters through the `aphrodite.adapters` entry-point group. Adapters run **in-process, with the host's privileges, in the host's virtual environment** — there is no sandbox. Treat installing an adapter as running arbitrary code.

- **Supply-chain trust.** By default every installed `aphrodite.adapters` entry point is loaded. Set `APHRODITE_TRUSTED_ADAPTERS` to a comma-separated allowlist to load only named adapters; others are recorded as `blocked` (visible in `aphrodite doctor` and `/status`). Built-in adapters report `source: "builtin"`; everything else reports `source: "third_party"`.
- **HTTP auth by default.** A discovered adapter's router is mounted under `/<system>` and gated by a host bearer token (`APHRODITE_ADAPTER_AUTH_TOKEN`) unless the adapter explicitly sets `requires_auth=False`. With no token configured the gate fails closed (HTTP 503). The bearer check uses constant-time comparison.
- **Fault isolation.** A failed adapter import, route mount, or lifespan startup is quarantined (surfaced in `/status` and `aphrodite doctor`) and never crashes the host app.
- **Shared dependencies.** Adapters share the host interpreter and cannot safely pin conflicting core dependency versions; `aphrodite doctor` reports the core dependency floor and what is installed. There is no per-adapter dependency isolation.

## Supported versions

| Version | Supported |
| --- | --- |
| 0.1.x | Yes |
