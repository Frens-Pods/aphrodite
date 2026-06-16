# Aphrodite roadmap

Aphrodite is a sidecar backend for local Hermes plugin products: a FastAPI
service that verifies and routes Discord interactions and dispatches actions to
pluggable module adapters, without modifying the Hermes core.

This roadmap tracks the reusable, public surface of the project. Operator- and
deployment-specific activation history lives in the private `.local/` overlay
and is intentionally out of scope here.

## Status

The dispatch core, Discord interaction verification, MCP server, and the
bundled module adapters are implemented and covered by the test suite. The
project is pre-1.0; interfaces may still change.

## Module adapters

The public module set is the native trio implemented in Aphrodite itself:

- `skillopt` — self-contained SkillOpt run storage, evaluations, review UI, and
  status dispatch.
- `image_gen` — image generation HTTP surface and dispatch status action; live
  HTTP generation depends on Hermes Codex/OpenAI OAuth from the private `agent`
  stack, while standalone callers can inject their own OpenAI client.
- `acp_relay` — bridge to an external ACP agent runtime with optional transport
  dependencies.

## Planned

- Broaden adapter registration to a discovery-based mechanism.
- Expand the MCP tool surface beyond skillopt.
- First-class packaging for downstream reuse and versioned releases.
- More end-to-end deployment examples (containerized and bare-metal).

## Non-goals

- Modifying or depending on internals of the Hermes core (see
  `NO_CORE_POLICY.md`).
- Shipping operator-specific secrets, IDs, hostnames, or activation runbooks in
  the public repository.
