from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


DEFAULT_MODULES = ("image_gen", "skillopt", "acp_relay")


def test_modules_default_when_unset(monkeypatch):
    monkeypatch.delenv("APHRODITE_MODULES", raising=False)

    from aphrodite.config import load_config

    assert load_config().modules == DEFAULT_MODULES


def test_modules_replace_defaults(monkeypatch):
    monkeypatch.setenv("APHRODITE_MODULES", "foo,bar")

    from aphrodite.config import load_config

    assert load_config().modules == ("foo", "bar")


def test_modules_append_to_defaults(monkeypatch):
    monkeypatch.setenv("APHRODITE_MODULES", "+foo")

    from aphrodite.config import load_config

    assert load_config().modules == (*DEFAULT_MODULES, "foo")


def test_modules_append_deduplicates_defaults(monkeypatch):
    monkeypatch.setenv("APHRODITE_MODULES", "+image_gen,foo")

    from aphrodite.config import load_config

    modules = load_config().modules
    assert modules == (*DEFAULT_MODULES, "foo")
    assert len(modules) == 4
    assert modules.count("image_gen") == 1
