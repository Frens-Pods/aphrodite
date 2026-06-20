from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from types import SimpleNamespace
from typing import Any

import aphrodite.modules as modules
from aphrodite.modules import (
    AdapterSpec,
    _normalize_adapter,
    discover_adapter_specs,
    discover_adapters,
)


def handler(action: str, payload: list[str], context: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, "action": action, "payload": payload, "context": context}


class FakeEntryPoint:
    def __init__(
        self,
        name: str,
        loaded: object = handler,
        exc: Exception | None = None,
    ) -> None:
        self.name = name
        self._loaded = loaded
        self._exc = exc

    def load(self) -> object:
        if self._exc is not None:
            raise self._exc
        return self._loaded


def test_normalize_bare_callable_uses_safe_defaults() -> None:
    spec = _normalize_adapter("hello", handler, source="third_party")

    assert isinstance(spec, AdapterSpec)
    assert spec.system == "hello"
    assert spec.handle is handler
    assert spec.requires_auth is True
    assert spec.source == "third_party"


def test_normalize_module_object_carries_router_and_metadata() -> None:
    router = object()
    loaded = SimpleNamespace(
        handle=handler,
        router=router,
        metadata={"label": "Hello"},
    )

    spec = _normalize_adapter("hello", loaded, source="builtin")

    assert spec.handle is handler
    assert spec.router is router
    assert spec.metadata == {"label": "Hello"}
    assert spec.source == "builtin"


def test_discover_adapter_specs_records_load_error_with_traceback(monkeypatch) -> None:
    monkeypatch.delenv("APHRODITE_TRUSTED_ADAPTERS", raising=False)
    monkeypatch.setattr(
        modules,
        "entry_points",
        lambda group: [FakeEntryPoint("broken", exc=RuntimeError("boom"))],
    )

    specs, errors = discover_adapter_specs()

    assert specs == {}
    assert errors["broken"]["name"] == "broken"
    assert errors["broken"]["phase"] == "load"
    assert "RuntimeError('boom')" in errors["broken"]["error"]
    assert "RuntimeError: boom" in errors["broken"]["traceback"]


def test_trusted_adapters_allowlist_exempts_builtins_and_blocks_unlisted_third_party(monkeypatch) -> None:
    from aphrodite.modules import skillopt

    monkeypatch.setenv("APHRODITE_TRUSTED_ADAPTERS", "allowed")
    monkeypatch.setattr(
        modules,
        "entry_points",
        lambda group: [
            FakeEntryPoint("allowed"),
            FakeEntryPoint("skillopt", skillopt),
            FakeEntryPoint("blocked"),
        ],
    )

    specs, errors = discover_adapter_specs()

    assert list(specs) == ["allowed", "skillopt"]
    assert specs["allowed"].handle is handler
    assert specs["skillopt"].router is skillopt.router
    assert specs["skillopt"].source == "builtin"
    assert errors["blocked"]["name"] == "blocked"
    assert errors["blocked"]["phase"] == "blocked"


def test_discover_adapters_still_returns_name_to_callable(monkeypatch) -> None:
    monkeypatch.delenv("APHRODITE_TRUSTED_ADAPTERS", raising=False)
    monkeypatch.setattr(
        modules,
        "entry_points",
        lambda group: [FakeEntryPoint("hello")],
    )

    adapters = discover_adapters()

    assert adapters == {"hello": handler}
    assert callable(adapters["hello"])
