from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

__doc__ = """Adapter discovery tests require the package installed with aphrodite.adapters entry points.

The main agent reinstalls the project editable before running these tests so importlib.metadata
sees the current entry-point metadata.
"""

from aphrodite.modules import discover_adapters
from aphrodite.app import build_router


def test_discover_returns_native_trio():
    adapters = discover_adapters()

    assert adapters.keys() >= {"image_gen", "skillopt", "acp_relay"}
    for name in {"image_gen", "skillopt", "acp_relay"}:
        assert callable(adapters[name])


def test_default_modules_register_trio(monkeypatch):
    monkeypatch.delenv("APHRODITE_MODULES", raising=False)

    assert build_router().systems == ["acp_relay", "image_gen", "skillopt"]


def test_module_filter_limits_registration(monkeypatch):
    monkeypatch.setenv("APHRODITE_MODULES", "skillopt,image_gen")

    assert build_router().systems == ["image_gen", "skillopt"]
    res = build_router().dispatch("skillopt:v1:status")
    assert res["ok"] is True
    assert res["result"].get("message") != "module adapter not implemented yet"


def test_unknown_module_uses_placeholder(monkeypatch):
    monkeypatch.setenv("APHRODITE_MODULES", "bogus")

    router = build_router()
    res = router.dispatch("bogus:v1:ping")

    assert router.systems == ["bogus"]
    assert res["ok"] is True
    assert res["result"] == {
        "ok": False,
        "error": "module adapter 'bogus' is configured but not installed",
        "hint": "pip install -e <your-module-dir> into this environment, then set "
        "APHRODITE_MODULES to include 'bogus' (run: aphrodite modules)",
    }
