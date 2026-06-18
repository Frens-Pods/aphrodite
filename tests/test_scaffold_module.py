from pathlib import Path
import importlib.util
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _load_generated_module(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_scaffold_module_creates_adapter_package(tmp_path):
    from aphrodite.scaffold import scaffold_module

    payload = scaffold_module("my_module", tmp_path)

    assert payload["ok"] is True
    target = tmp_path / "my_module"
    assert (target / "my_module.py").exists()
    assert (target / "pyproject.toml").exists()
    assert (target / "README.md").exists()
    assert 'my_module = "my_module:handle"' in (target / "pyproject.toml").read_text(encoding="utf-8")


def test_generated_adapter_handle_ping_and_unknown_action(tmp_path):
    from aphrodite.scaffold import scaffold_module

    scaffold_module("my_module", tmp_path)
    module = _load_generated_module(tmp_path / "my_module" / "my_module.py")

    ping = module.handle("ping", [], {})
    assert ping["ok"] is True
    assert ping["message"] == "my_module is alive"
    assert module.handle("nope", [], {})["ok"] is False


def test_new_module_cli_creates_adapter_package(tmp_path, monkeypatch):
    import aphrodite.cli as cli

    monkeypatch.setattr(cli, "maybe_notify_update", lambda command: None)

    assert cli.main(["new-module", "my_cli_mod", "--dir", str(tmp_path)]) == 0
    target = tmp_path / "my_cli_mod"
    assert (target / "my_cli_mod.py").exists()
    assert (target / "pyproject.toml").exists()
    assert (target / "README.md").exists()


def test_invalid_module_name_returns_error_and_cli_failure(tmp_path, monkeypatch):
    from aphrodite.scaffold import scaffold_module
    import aphrodite.cli as cli

    monkeypatch.setattr(cli, "maybe_notify_update", lambda command: None)

    assert scaffold_module("Bad-Name", tmp_path)["ok"] is False
    assert cli.main(["new-module", "Bad-Name", "--dir", str(tmp_path)]) == 1


def test_existing_target_is_not_clobbered(tmp_path):
    from aphrodite.scaffold import scaffold_module

    assert scaffold_module("my_module", tmp_path)["ok"] is True
    second = scaffold_module("my_module", tmp_path)

    assert second["ok"] is False
    assert "already exists" in second["error"]
