<!-- v1 (2026-06-19) - operator-approved direction; supersedes DRAFT v0. The manager triggers on commits to `main` (git hook -> loop-tick). The adapter extension surfaces below land via the open `feat/adapter-*` PR stack; treat them as the contract to protect once merged. -->
# Goal
Grow aphrodite as an **extensible adapter platform** that outsiders can build apps and modules on top of, while keeping CI green across the Python 3.10 / 3.11 / 3.12 matrix and dependencies current toward a 1.0 / PyPI release. Still a pre-1.0 loop: small, scoped, reversible changes, one concern per PR.

# Constraints
- NEVER merge or push to `main` autonomously. Open a PR; a human merges. (The operator MAY override case-by-case with explicit authorization.)
- NEVER modify the Hermes core or violate NO_CORE_POLICY.md.
- NEVER touch security boundaries without escalation: `aphrodite/discord/signature.py`, `aphrodite/discord/intake.py`, `aphrodite/modules/acp_relay.py`.
- NEVER weaken the adapter security defaults without escalation: bearer-token auth on mounted routers (`APHRODITE_ADAPTER_AUTH_TOKEN`), the `APHRODITE_TRUSTED_ADAPTERS` allowlist, mount-time quarantine, per-adapter lifespan timeout.
- NEVER touch supply-chain surfaces without escalation: `aphrodite/update.py`, `install.sh`, `scripts/aphrodite`.
- NEVER commit secrets/overlay: `config/aphrodite.env`, `.local/`, `data/`.
- Keep each change scoped to ONE concern; the diff must be reviewable in one sitting.

# Extension surface (the platform contract — keep backward-compatible)
- Adapter discovery via the `aphrodite.adapters` entry-point group: name == system; value resolves to a `handle(action, payload, context)` callable or an object exposing `.handle` (+ optional `.router`, `.metadata`, `.readiness`, `.lifespan`).
- The `AdapterSpec` contract and `discover_adapter_specs()` / `discover_adapters()` shapes in `aphrodite/modules/__init__.py`.
- The public SDK (`aphrodite.sdk`) and testing kit (`aphrodite.testing`) re-exports.
- The embeddable `create_app(config=, root_path=)` factory.
- Config: `APHRODITE_MODULES` (incl. the `+name` append form) and `adapter_env()` namespacing.
- Existing `v1` adapters MUST keep working; gate new behaviour behind optional spec fields, not breaking changes.
- The authoring guide (`docs/module-adapters.md`) and `examples/hello_adapter/` stay accurate to the contract.

# Definition of Done (the rubric the verifier grades against)
- `python -m pytest tests -q` passes (full suite).
- `bash scripts/verify.sh` exits 0 (focused packs + full suite + read-only command smoke).
- CI workflow `.github/workflows/ci.yml` is green on all three Python versions (3.10 / 3.11 / 3.12).
- Touching any extension surface above keeps it backward-compatible, with an adapter/contract test covering the change.
- No new TODO/FIXME/XXX/HACK; no skipped or xfail'd tests added.
- Diff scoped to the stated task only; no unrelated churn; no new dependency added without a stated reason in the PR body.
- Any README/doc reference touched still resolves.

# Escalate to human (green = correct)
- Any change to Discord signature/intake, `acp_relay`, `update.py`/`install.sh`, or the `pyproject.toml` packaging/entry-point surface.
- Any breaking change to the adapter contract (AdapterSpec, entry-point group, SDK/testing exports, `create_app` signature) or any loosening of the auth/allowlist defaults.
- Committing to public-API stability signals (`__all__`, `py.typed`) — that is a 1.0 promise; deferred until decided.
- Any dependency MAJOR version bump, or any bump that changes runtime behaviour.
- Any change to production behaviour with no pre-existing test covering it.
- Adding a new lint/typecheck gate (ruff/mypy): propose via PR + escalate; NEVER silently reformat the tree.
- `gh` token is currently invalid - if PR-based work is blocked on auth, escalate rather than working around it.
