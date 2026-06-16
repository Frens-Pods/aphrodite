from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

Handler = Callable[[str, list[str], dict[str, Any]], dict[str, Any]]
_SUPPORTED_VERSIONS = {"v1"}


@dataclass(frozen=True)
class CustomId:
    system: str
    version: str
    action: str
    payload: list[str]


def parse_custom_id(custom_id: str) -> CustomId:
    parts = [part for part in str(custom_id or "").split(":") if part != ""]
    if len(parts) < 3:
        raise ValueError("custom_id must be '<system>:<version>:<action>[:payload...]'")
    return CustomId(
        system=parts[0],
        version=parts[1],
        action=parts[2],
        payload=parts[3:],
    )


class DispatchRouter:
    def __init__(self) -> None:
        self._handlers: dict[str, Handler] = {}

    def register(self, system: str, handler: Handler) -> None:
        key = str(system or "").strip()
        if not key:
            raise ValueError("system is required")
        self._handlers[key] = handler

    @property
    def systems(self) -> list[str]:
        return sorted(self._handlers)

    def dispatch(self, custom_id: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            parsed = parse_custom_id(custom_id)
        except ValueError as exc:
            return {"ok": False, "error": str(exc), "custom_id": custom_id}
        handler = self._handlers.get(parsed.system)
        if handler is None:
            return {
                "ok": False,
                "error": "unknown system",
                "system": parsed.system,
                "version": parsed.version,
                "action": parsed.action,
                "payload": parsed.payload,
            }
        if parsed.version not in _SUPPORTED_VERSIONS:
            return {
                "ok": False,
                "error": "unsupported custom_id version",
                "system": parsed.system,
                "version": parsed.version,
                "action": parsed.action,
                "payload": parsed.payload,
                "supported_versions": sorted(_SUPPORTED_VERSIONS),
            }
        try:
            result = handler(parsed.action, parsed.payload, context or {})
        except Exception as exc:  # defensive boundary for Discord/webhook callbacks
            return {
                "ok": False,
                "error": str(exc),
                "system": parsed.system,
                "version": parsed.version,
                "action": parsed.action,
                "payload": parsed.payload,
            }
        return {
            "ok": True,
            "system": parsed.system,
            "version": parsed.version,
            "action": parsed.action,
            "payload": parsed.payload,
            "result": result,
        }
