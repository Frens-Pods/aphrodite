<!-- DRAFT v0 (2026-06-17) — review & EDIT before the loop opens PRs. The manager triggers on commits to `main` (git hook → loop-tick); until you trust the digest, just watch. Drafted from observed repo state, not from your intent. -->
# Goal
Keep CI green across the Python 3.10 / 3.11 / 3.12 matrix on every push to `main`, and keep runtime/extra dependencies current toward a first PyPI release. This is a pre-1.0 maintenance loop: small, scoped, reversible changes only.

# Constraints
- NEVER merge or push to `main`. Open a PR; a human merges.
- NEVER modify the Hermes core or violate NO_CORE_POLICY.md.
- NEVER touch security boundaries without escalation: `aphrodite/discord/signature.py`, `aphrodite/discord/intake.py`, `aphrodite/modules/acp_relay.py`.
- NEVER touch supply-chain surfaces without escalation: `aphrodite/update.py`, `install.sh`, `scripts/aphrodite`.
- NEVER commit secrets/overlay: `config/aphrodite.env`, `.local/`, `data/`.
- Keep each change scoped to ONE concern; the diff must be reviewable in one sitting.

# Definition of Done (the rubric the verifier grades against)
- `python -m pytest tests -q` passes (full suite, ~19 test files).
- `bash scripts/verify.sh` exits 0 (focused packs + full suite + read-only command smoke).
- CI workflow `.github/workflows/ci.yml` is green on all three Python versions (3.10 / 3.11 / 3.12).
- No new TODO/FIXME/XXX/HACK; no skipped or xfail'd tests added.
- Diff scoped to the stated task only; no unrelated churn; no new dependency added without a stated reason in the PR body.
- Any README/doc reference touched still resolves.

# Escalate to human (green ≠ correct)
- Any change to Discord signature/intake, `acp_relay`, `update.py`/`install.sh`, or the `pyproject.toml` packaging surface.
- Any dependency MAJOR version bump, or any bump that changes runtime behaviour.
- Any change to production behaviour with no pre-existing test covering it.
- Adding a new lint/typecheck gate (ruff/mypy): propose via PR + escalate; NEVER silently reformat the tree.
- `gh` token is currently invalid — if PR-based work is blocked on auth, escalate rather than working around it.
