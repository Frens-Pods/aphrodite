from __future__ import annotations

from typing import Any

from .config import load_config
from .modules import discover_adapter_specs


def _dedupe(names: list[str] | tuple[str, ...]) -> list[str]:
    return list(dict.fromkeys(names))


def modules_payload() -> dict[str, Any]:
    """Return configured and discovered module adapter inventory."""
    cfg = load_config()
    configured = _dedupe(cfg.modules)
    specs, errors = discover_adapter_specs()
    discovered = sorted(specs)
    discovered_set = set(discovered)
    configured_set = set(configured)
    active = _dedupe([name for name in configured if name in discovered_set])
    missing = [name for name in configured if name not in discovered_set]
    available = [name for name in discovered if name not in configured_set]
    hint_parts: list[str] = []
    if missing:
        hint_parts.append(
            "Missing modules are placeholders; pip install -e <your-module-dir> into this environment."
        )
    if available:
        hint_parts.append("Enable available modules by adding them to APHRODITE_MODULES.")
    if not hint_parts:
        hint_parts.append("All configured modules are installed and active.")
    return {
        "ok": not missing,
        "configured": configured,
        "discovered": discovered,
        "active": active,
        "missing": missing,
        "available": available,
        "hint": " ".join(hint_parts),
        "errors": errors,
        "sources": {name: spec.source for name, spec in specs.items()},
    }
