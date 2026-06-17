# Module adapters

Aphrodite routes Discord component custom IDs and HTTP dispatch calls through `aphrodite.router.DispatchRouter`.

## Custom ID format

The router expects this form:

```text
system:v1:action:arg1:arg2
```

Parsing rules from `aphrodite/router.py`:

- `system` selects a registered adapter.
- `v1` is the supported custom-id version.
- `action` selects behavior inside the adapter.
- Remaining colon-separated fields are passed as `payload: list[str]`.
- The adapter also receives a `context: dict[str, Any]` built by the caller.

A successful dispatch response includes `ok`, `system`, `version`, `action`, `payload`, and `result`. Unknown systems, unsupported versions, parsing errors, and adapter exceptions return structured `ok: false` responses instead of escaping through the HTTP boundary.

## Bundled adapters

`aphrodite.app.build_router()` discovers dispatch handlers published under the
`aphrodite.adapters` entry-point group, then registers the configured names from
`APHRODITE_MODULES`. The default public set is `image_gen,skillopt,acp_relay`.

| Adapter | Purpose | Standalone behavior |
| --- | --- | --- |
| `skillopt` | Manages SkillOpt runs, diffs, evaluations, review HTML, bundles, and candidate import/export artifacts. | Self-contained aside from configured local storage and optional train commands. |
| `image_gen` | Provides a dispatch status action and the `/image/generate` HTTP route for Codex-backed image generation. | Live HTTP generation requires Hermes Codex/OpenAI OAuth from the private `agent` stack; no plain API-key environment path exists. |
| `acp_relay` | Bridges Aphrodite to an external ACP agent runtime and exposes both dispatch and `/acp/*` HTTP surfaces. | Requires a working external Hermes/ACP runtime for real turns; fake transports can test the Aphrodite-owned pieces. |

Adapters that bridge private Hermes plugins belong in the operator overlay, not
the public module set. Custom modules can still be enabled by listing their
system names in `APHRODITE_MODULES`; each system name must match an entry-point
name. Unknown names fall back to a placeholder handler so startup remains
deterministic.

## Adding an adapter

1. Implement a dispatch handler in your module:

```python
def handle(action: str, payload: list[str], context: dict[str, Any]) -> dict[str, Any]:
    ...
```

2. Declare an entry point in your package's `pyproject.toml` so Aphrodite can
   discover it. The entry-point group is `aphrodite.adapters`; the entry-point
   name is the system name used in `APHRODITE_MODULES`, and the value points to
   the handler:

```toml
[project.entry-points."aphrodite.adapters"]
my_adapter = "your_pkg.your_module:handle"
```

3. Reinstall the package so Python refreshes the entry-point metadata:

```bash
pip install -e .
```

4. Add the adapter name to `APHRODITE_MODULES` when it should be active. A
   configured name with no discovered adapter falls back to Aphrodite's
   placeholder handler instead of crashing.

Return dictionaries with stable fields. Prefer `ok: true` or `ok: false` plus
an `error` string for failures.

Third-party packages and private-overlay adapters register the same way: they
ship their own entry points in the `aphrodite.adapters` group. Aphrodite's
public tree never imports them directly, which keeps the `NO_CORE_POLICY` /
private-overlay fresh-clone rule intact. The native trio (`image_gen`,
`skillopt`, and `acp_relay`) is registered exactly this way in Aphrodite's own
`pyproject.toml`.

Keep adapter boundaries narrow: Aphrodite should call public plugin/runtime APIs and should not patch the external runtime core.

## Image generation auth

`aphrodite/modules/image_gen.py` does not read `OPENAI_API_KEY` or any other
plain API-key environment variable for the HTTP route. `/image/generate` calls
`_build_codex_client()`, which reads a Codex/OpenAI OAuth token through the
private Hermes `agent.auxiliary_client` stack and constructs:

```python
openai.OpenAI(
    api_key=token,
    base_url="https://chatgpt.com/backend-api/codex",
    ...
)
```

If that private OAuth token is unavailable, the route returns an
`auth_required` error and performs no generation. The standalone integration
path is programmatic: import `generate_image` and pass a client you own, for
example `generate_image(payload, client=<openai.OpenAI instance>)`.

Model selection can still be influenced with `APHRODITE_IMAGE_GEN_MODEL` or
`OPENAI_IMAGE_MODEL`, but those variables select quality/model only; they do
not authenticate the OpenAI/Codex client.

## ACP relay

`aphrodite/modules/acp_relay.py` bridges Aphrodite to an external ACP agent runtime.

Public surfaces:

- `handle(action, payload, context)` for `DispatchRouter` registration. Actions `health`, `readiness`, and `status` report relay readiness. Other actions currently return a handled-false response that points callers to the `/acp` HTTP routes.
- `router = APIRouter(prefix="/acp", tags=["acp_relay"])`, included by `create_app()`, with conversation and turn endpoints.
- `AcpRelay`, `ConversationStore`, and configuration helpers used by the HTTP router and tests.

Runtime behavior:

- Conversation metadata and turns are stored in SQLite owned by Aphrodite.
- The real transport spawns `hermes -p <profile> acp` and drives one ACP turn.
- The `acp` Python client is imported lazily inside `acp_transport`; environments that do not install the optional client can still import the module and use tests/fake transports.
- Default profile, provider, model, binary, working directory, database path, and turn timeout are configurable with `APHRODITE_ACP_*` environment variables.

Default relay settings in the current code are profile `forge` and timeout `240.0` seconds. Provider and model are unset by default, so the relay uses the Hermes profile's configured engine unless `APHRODITE_ACP_PROVIDER` and `APHRODITE_ACP_MODEL` are both set.
