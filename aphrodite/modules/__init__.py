"""Aphrodite product modules."""

from __future__ import annotations

import os
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from importlib.metadata import entry_points
from typing import Any, Protocol

Handler = Callable[[str, list[str], dict[str, Any]], dict[str, Any]]
ADAPTER_ENTRY_POINT_GROUP = "aphrodite.adapters"
_BUILTIN_ADAPTERS = {"image_gen", "skillopt", "acp_relay"}


@dataclass(frozen=True)
class AdapterSpec:
    system: str
    handle: Handler
    router: Any | None = None
    metadata: dict[str, Any] | None = None
    readiness: Callable[[], dict[str, Any]] | None = None
    lifespan: Any | None = None
    api_version: int = 0
    capabilities: tuple[str, ...] = ()
    supported_versions: tuple[str, ...] = ("v1",)
    requires_auth: bool = True
    source: str = "third_party"


class AdapterModule(Protocol):
    """Adapter object shape.

    Required attribute: handle.
    Optional attributes: router, metadata, readiness, lifespan, api_version,
    capabilities, supported_versions, requires_auth.
    """

    handle: Handler


def _normalize_adapter(system: str, loaded: object, *, source: str) -> AdapterSpec:
    if callable(loaded):
        return AdapterSpec(system=system, handle=loaded, source=source)

    handle = getattr(loaded, "handle", None)
    if not callable(handle):
        raise ValueError(
            f"adapter '{system}' must be callable or expose a callable handle"
        )

    return AdapterSpec(
        system=system,
        handle=handle,
        router=getattr(loaded, "router", None),
        metadata=getattr(loaded, "metadata", None),
        readiness=getattr(loaded, "readiness", None),
        lifespan=getattr(loaded, "lifespan", None),
        api_version=getattr(loaded, "api_version", 0),
        capabilities=getattr(loaded, "capabilities", ()),
        supported_versions=getattr(loaded, "supported_versions", ("v1",)),
        requires_auth=getattr(loaded, "requires_auth", True),
        source=source,
    )


def _trusted_adapters() -> set[str] | None:
    trusted = {
        name.strip()
        for name in os.environ.get("APHRODITE_TRUSTED_ADAPTERS", "").split(",")
        if name.strip()
    }
    return trusted or None


def discover_adapter_specs() -> tuple[dict[str, AdapterSpec], dict[str, dict[str, Any]]]:
    """Discover typed adapter specs and fail loud with per-entry-point errors."""
    specs: dict[str, AdapterSpec] = {}
    errors: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    trusted = _trusted_adapters()

    for ep in entry_points(group=ADAPTER_ENTRY_POINT_GROUP):
        name = ep.name
        if name in seen:
            errors[name] = {
                "name": name,
                "phase": "collision",
                "error": f"duplicate adapter entry point '{name}'",
            }
            continue
        seen.add(name)

        if trusted is not None and name not in trusted and name not in _BUILTIN_ADAPTERS:
            errors[name] = {
                "name": name,
                "phase": "blocked",
                "error": (
                    f"adapter '{name}' is not listed in "
                    "APHRODITE_TRUSTED_ADAPTERS"
                ),
            }
            continue

        source = "builtin" if name in _BUILTIN_ADAPTERS else "third_party"
        try:
            specs[name] = _normalize_adapter(name, ep.load(), source=source)
        except Exception as exc:
            errors[name] = {
                "name": name,
                "phase": "load",
                "error": repr(exc),
                "traceback": traceback.format_exc(),
            }

    return specs, errors


def discover_adapters() -> dict[str, Handler]:
    """Discover dispatch adapters published under the entry-point group.

    Entry-point name == system name; returned value == dispatch handler.
    Third-party / overlay packages register adapters by declaring their own
    entry points in this group, so no public-tree imports are required.
    Rich adapter specs are available through discover_adapter_specs().
    """
    specs, _errors = discover_adapter_specs()
    return {name: spec.handle for name, spec in specs.items()}
