from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    # Support the documented stdio launch form:
    #   python /path/to/aphrodite/aphrodite/mcp_server.py
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aphrodite.modules import acp_relay, discover_adapter_specs, image_gen, skillopt

try:  # pragma: no cover - exercised when the optional SDK is installed.
    from mcp.server.fastmcp import FastMCP
except Exception:  # pragma: no cover - unit tests still cover wrapper logic without mcp.
    FastMCP = None  # type: ignore[assignment]


TOOL_NAMES = [
    "aphrodite_skillopt_list_runs",
    "aphrodite_skillopt_get_run",
    "aphrodite_skillopt_train_run",
    "aphrodite_skillopt_create_eval",
    "aphrodite_skillopt_list_evals",
    "aphrodite_skillopt_get_eval",
    "aphrodite_skillopt_evaluate_run",
    "aphrodite_skillopt_get_evaluation",
    "aphrodite_skillopt_import_candidate",
    "aphrodite_skillopt_export_bundle",
    "aphrodite_image_gen_status",
    "aphrodite_image_gen_models",
    "aphrodite_image_gen_sizes",
    "aphrodite_acp_relay_readiness",
    "aphrodite_acp_relay_list_conversations",
    "aphrodite_acp_relay_get_conversation",
    "aphrodite_adapters",
    "aphrodite_dispatch",
]


def _payload(payload: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    if payload:
        merged.update(payload)
    merged.update({k: v for k, v in kwargs.items() if v is not None})
    return merged


def _json_safe(value: Any) -> Any:
    """Return a JSON-safe value so MCP handlers never expose Path/object instances."""
    try:
        json.dumps(value)
        return value
    except TypeError:
        if isinstance(value, dict):
            return {str(k): _json_safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [_json_safe(v) for v in value]
        return str(value)


def aphrodite_skillopt_list_runs() -> dict[str, Any]:
    """List Aphrodite SkillOpt runs."""
    return _json_safe(skillopt.list_runs())


def aphrodite_skillopt_get_run(run_id: str) -> dict[str, Any]:
    """Get metadata and file inventory for one SkillOpt run."""
    return _json_safe(skillopt.get_run(run_id))


def aphrodite_skillopt_train_run(payload: dict[str, Any]) -> dict[str, Any]:
    """Launch a bounded SkillOpt training command in an Aphrodite run workspace."""
    return _json_safe(skillopt.train_run(_payload(payload)))


def aphrodite_skillopt_create_eval(payload: dict[str, Any]) -> dict[str, Any]:
    """Create or replace a SkillOpt evaluation manifest/cases/rubric."""
    return _json_safe(skillopt.create_eval(_payload(payload)))


def aphrodite_skillopt_list_evals() -> dict[str, Any]:
    """List registered SkillOpt eval manifests."""
    return _json_safe(skillopt.list_evals())


def aphrodite_skillopt_get_eval(eval_id: str) -> dict[str, Any]:
    """Get one SkillOpt eval manifest and file inventory."""
    return _json_safe(skillopt.get_eval(eval_id))


def aphrodite_skillopt_evaluate_run(run_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Evaluate a SkillOpt candidate against scores/policy/regression gates."""
    return _json_safe(skillopt.evaluate_run(run_id, _payload(payload)))


def aphrodite_skillopt_get_evaluation(run_id: str) -> dict[str, Any]:
    """Get evaluation artifacts for a SkillOpt run."""
    return _json_safe(skillopt.get_evaluation(run_id))


def aphrodite_skillopt_import_candidate(run_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Import a candidate SKILL.md into <profile_home>/skills/generated/<skill_name>/SKILL.md."""
    return _json_safe(skillopt.import_candidate(run_id, _payload(payload)))


def aphrodite_skillopt_export_bundle(run_id: str) -> dict[str, Any]:
    """Export a portable tar.gz bundle for a SkillOpt run."""
    return _json_safe(skillopt.export_bundle(run_id))


def aphrodite_image_gen_status() -> dict[str, Any]:
    """Report Aphrodite image_gen provider and default model."""
    return _json_safe(image_gen.handle("status", [], {}))


def aphrodite_image_gen_models() -> dict[str, Any]:
    """List Aphrodite image_gen models and the default model."""
    return _json_safe(image_gen.handle("models", [], {}))


def aphrodite_image_gen_sizes() -> dict[str, Any]:
    """List Aphrodite image_gen sizes and aspect ratios."""
    return _json_safe(image_gen.handle("sizes", [], {}))


def aphrodite_acp_relay_readiness() -> dict[str, Any]:
    """Report Aphrodite ACP relay readiness (hermes bin, acp library, db path)."""
    return _json_safe(acp_relay.handle("readiness", [], {}))


def aphrodite_acp_relay_list_conversations() -> dict[str, Any]:
    """List Aphrodite ACP relay conversations (metadata only)."""
    return _json_safe(acp_relay.handle("list", [], {}))


def aphrodite_acp_relay_get_conversation(conversation_id: str) -> dict[str, Any]:
    """Get one Aphrodite ACP relay conversation with messages, or a not_found envelope."""
    return _json_safe(acp_relay.handle("get", [conversation_id], {}))


def aphrodite_adapters() -> dict[str, Any]:
    """List discovered Aphrodite adapters and per-adapter discovery errors."""
    specs, errors = discover_adapter_specs()
    adapters = {
        name: {
            "source": spec.source,
            "has_router": spec.router is not None,
        }
        for name, spec in specs.items()
    }
    return _json_safe({"ok": True, "adapters": adapters, "errors": errors})


def aphrodite_dispatch(custom_id: str) -> dict[str, Any]:
    """Dispatch an Aphrodite custom_id through the discovered adapter router."""
    from aphrodite.app import build_router

    router = build_router()
    return _json_safe(router.dispatch(custom_id, context={"source": "mcp"}))


def build_server() -> Any:
    """Build the optional FastMCP stdio server without starting it."""
    if FastMCP is None:
        raise RuntimeError("mcp Python SDK is not installed; install mcp to run the Aphrodite MCP server")
    mcp = FastMCP(
        "aphrodite",
        instructions=(
            "Aphrodite no-core sidecar MCP server. Exposes review-gated SkillOpt tools, "
            "read-only image_gen and acp_relay metadata, and discovery-backed adapter "
            "inventory/dispatch over stdio. Image generation and ACP conversational turns "
            "stay on the Aphrodite HTTP surface. SkillOpt recommendations are advisory; "
            "imports are explicit generated-skill writes."
        ),
    )
    for fn in (
        aphrodite_skillopt_list_runs,
        aphrodite_skillopt_get_run,
        aphrodite_skillopt_train_run,
        aphrodite_skillopt_create_eval,
        aphrodite_skillopt_list_evals,
        aphrodite_skillopt_get_eval,
        aphrodite_skillopt_evaluate_run,
        aphrodite_skillopt_get_evaluation,
        aphrodite_skillopt_import_candidate,
        aphrodite_skillopt_export_bundle,
        aphrodite_image_gen_status,
        aphrodite_image_gen_models,
        aphrodite_image_gen_sizes,
        aphrodite_acp_relay_readiness,
        aphrodite_acp_relay_list_conversations,
        aphrodite_acp_relay_get_conversation,
        aphrodite_adapters,
        aphrodite_dispatch,
    ):
        mcp.tool(name=fn.__name__)(fn)
    return mcp


def main() -> int:
    if FastMCP is None:
        print("Aphrodite MCP server requires the optional 'mcp' Python SDK.", file=sys.stderr)
        return 2
    build_server().run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
