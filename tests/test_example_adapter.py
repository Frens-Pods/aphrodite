from pathlib import Path
import importlib.util
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

EXAMPLE_DIR = ROOT / "examples" / "hello_adapter"


def load_example_handle():
    module_path = EXAMPLE_DIR / "hello_adapter.py"
    spec = importlib.util.spec_from_file_location("aphrodite_example_hello_adapter", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.handle


def test_example_adapter_dispatches_greet_action():
    from aphrodite.router import DispatchRouter

    router = DispatchRouter()
    router.register("hello", load_example_handle())

    result = router.dispatch("hello:v1:greet:there", context={"source": "test"})

    assert result == {
        "ok": True,
        "system": "hello",
        "version": "v1",
        "action": "greet",
        "payload": ["there"],
        "result": {"ok": True, "action": "greet", "message": "hello, there!"},
    }
    assert result["ok"] is True
    assert result["system"] == "hello"
    assert result["action"] == "greet"
    assert result["result"]["message"] == "hello, there!"


def test_example_adapter_declares_aphrodite_entry_point():
    pyproject = (EXAMPLE_DIR / "pyproject.toml").read_text()

    assert '[project.entry-points."aphrodite.adapters"]' in pyproject
    assert 'hello = "hello_adapter:handle"' in pyproject
