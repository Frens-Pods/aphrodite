# Aphrodite roadmap

Aphrodite is a sidecar backend for local Hermes plugin products: a FastAPI
service that verifies and routes Discord interactions and dispatches actions to
pluggable module adapters, without modifying the Hermes core.

This roadmap tracks the reusable, public surface of the project. Operator- and
deployment-specific activation history lives in the private `.local/` overlay
and is intentionally out of scope here.

## Status

The dispatch core, Discord interaction verification, bundled module adapters,
discovery-based adapter registration, deployment examples, and optional MCP
server are implemented and covered by the test suite. Adapters are discovered
via the `aphrodite.adapters` entry-point group; deployment examples cover Docker
and bare-metal; and the MCP server covers `skillopt` plus read-only `image_gen`
and `acp_relay` metadata. The project is pre-1.0; interfaces may still change.

## Module adapters

The public module set is the native trio implemented in Aphrodite itself.
Adapters are discovered through the `aphrodite.adapters` entry-point group, so
third-party and overlay packages register their own adapters.

- `skillopt` — self-contained SkillOpt run storage, evaluations, review UI, and
  status dispatch.
- `image_gen` — image generation HTTP surface and dispatch status action; live
  HTTP generation depends on Hermes Codex/OpenAI OAuth from the private `agent`
  stack, while standalone callers can inject their own OpenAI client.
- `acp_relay` — bridge to an external ACP agent runtime with optional transport
  dependencies.

## Planned

- Publish versioned releases to PyPI (packaging groundwork is in place in
  `pyproject.toml`).

## Non-goals

- Modifying or depending on internals of the Hermes core (see
  `NO_CORE_POLICY.md`).
- Shipping operator-specific secrets, IDs, hostnames, or activation runbooks in
  the public repository.
