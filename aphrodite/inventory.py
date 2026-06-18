from __future__ import annotations

from typing import Any

from .config import load_config
from .modules import discover_adapters


def modules_payload() -> dict[str, Any]:
    """Return configured and discovered module adapter inventory."""
    cfg = load_config()
    configured = list(cfg.modules)
    discovered = sorted(discover_adapters())
    discovered_set = set(discovered)
    configured_set = set(configured)
    active = [name for name in configured if name in discovered_set]
    missing = [name for name in configured if name not in discovered_set]
    available = [name for name in discovered if name not in configured_set]
    hint_parts = [
        "Missing modules are placeholders; pip install -e <your-module-dir> into this environment.",
        "Enable available modules by adding them to APHRODITE_MODULES.",
    ]
    if not missing and not available:
        hint_parts.append("All configured modules are installed.")
    return {
        "ok": True,
        "configured": configured,
        "discovered": discovered,
        "active": active,
        "missing": missing,
        "available": available,
        "hint": " ".join(hint_parts),
    }
