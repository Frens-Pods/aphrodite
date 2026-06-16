from __future__ import annotations

from copy import deepcopy
from typing import Any


_PRIVATE_FAILURE_PREFIX = "Aphrodite handled this button privately and did not execute it."
_NO_SIDE_EFFECTS = "No task, card, endpoint, service, Hermes config, or cron state was changed."


def private_failure_guidance(content: str, result: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Return operator-facing private guidance plus annotated Aphrodite result.

    This helper is intentionally pure/read-only. It does not call Discord, touch
    Kanban/Nudge state, start services, edit config, or manage cron. It only
    normalizes stale/malformed/unknown component failures into consistent private
    UX so old buttons fail closed without looking like a public action succeeded.
    """
    annotated = deepcopy(result if isinstance(result, dict) else {"ok": False, "error": "unknown error"})
    category = _classify_failure(annotated)
    guidance = _guidance_for_category(category, content)
    annotated["operator_guidance"] = guidance
    return guidance["content"], annotated


def _classify_failure(result: dict[str, Any]) -> str:
    error = str(result.get("error") or "").lower()
    module_result = result.get("result") if isinstance(result.get("result"), dict) else {}
    module_error = str(module_result.get("error") or "").lower()
    action = str(module_result.get("action") or result.get("action") or "").lower()

    if "missing custom_id" in error:
        return "missing_custom_id"
    if "custom_id must be" in error:
        return "malformed_custom_id"
    if "unsupported custom_id version" in error:
        return "stale_version"
    if "unknown system" in error:
        return "unknown_system"
    if "unsupported" in module_error or "unsupported" in error:
        if action:
            return "unsupported_action"
        return "unsupported_component"
    if "unauthorized" in module_error or "not authorized" in str(module_result.get("message") or "").lower():
        return "unauthorized_mutation"
    return "handler_failure"


def _guidance_for_category(category: str, raw_content: str) -> dict[str, Any]:
    if category == "stale_version":
        next_step = "Refresh or republish the card; do not reuse old-version buttons."
    elif category == "malformed_custom_id":
        next_step = "Refresh the card and use a supported button ID shaped as <system>:v1:<action>[:payload]."
    elif category == "missing_custom_id":
        next_step = "This interaction payload had no component custom_id; inspect the publisher fixture before enabling it."
    elif category == "unknown_system":
        next_step = "Only registered Aphrodite systems should publish buttons; leave unknown systems fail-closed."
    elif category == "unsupported_action":
        next_step = "Leave this action fail-closed unless an operator explicitly approves a narrow handler plus tests."
    elif category == "unauthorized_mutation":
        next_step = "Ask an allowlisted operator to approve/trash, or update allowlists only after explicit approval."
    else:
        next_step = "Retry from the canonical card or run the documented readiness checks before enabling live interactions."

    detail = str(raw_content or "Aphrodite action failed").strip()
    content = f"{_PRIVATE_FAILURE_PREFIX}\n{detail}\n{next_step}\n{_NO_SIDE_EFFECTS}"
    return {
        "category": category,
        "private": True,
        "ephemeral": True,
        "public_message": False,
        "deferred_update": False,
        "mutation_attempted": False,
        "safe_to_retry": True,
        "next_step": next_step,
        "no_side_effects": _NO_SIDE_EFFECTS,
        "content": content[:1900],
    }
