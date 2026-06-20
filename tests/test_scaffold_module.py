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
    assert (target / "test_basic.py").exists()
    pyproject = (target / "pyproject.toml").read_text(encoding="utf-8")
    assert 'dependencies = ["fastapi"]' in pyproject
    assert 'my_module = "my_module"' in pyproject
    assert payload["next_steps"] == [
        f"{sys.executable} -m pip install -e {target}",
        "export APHRODITE_MODULES=+my_module  # leading + appends to the built-in modules; a bare list replaces them — use bare only to intentionally reduce the set",
        "aphrodite dispatch-test my_module:v1:ping",
    ]
    readme = (target / "README.md").read_text(encoding="utf-8")
    assert "`<aphrodite-python> -m pip install -e .`" in readme
    assert "`export APHRODITE_MODULES=+my_module`" in readme
    assert '"result": {"ok": true, "action": "ping", "message": "my_module is alive"}' in readme


def test_generated_adapter_handle_ping_and_unknown_action(tmp_path):
    from aphrodite.scaffold import scaffold_module

    scaffold_module("my_module", tmp_path)
    module = _load_generated_module(tmp_path / "my_module" / "my_module.py")
    assert hasattr(module, "router")
    assert module.requires_auth is False

    ping = module.handle("ping", [], {})
    assert ping["ok"] is True
    assert ping["message"] == "my_module is alive"
    unknown = module.handle("nope", [], {})
    assert unknown["ok"] is False
    assert unknown["error"] == "unknown action: nope"
    assert unknown["supported_actions"] == ["ping"]
    assert unknown["examples"] == ["aphrodite dispatch-test my_module:v1:ping"]


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

    invalid = scaffold_module("Bad-Name", tmp_path)
    assert invalid["ok"] is False
    assert invalid["hint"] == "try: bad_name"
    assert cli.main(["new-module", "Bad-Name", "--dir", str(tmp_path)]) == 1


def test_existing_target_is_not_clobbered(tmp_path):
    from aphrodite.scaffold import scaffold_module

    assert scaffold_module("my_module", tmp_path)["ok"] is True
    second = scaffold_module("my_module", tmp_path)

    assert second["ok"] is False
    assert "already exists" in second["error"]
    assert second["fix"] == "Choose a different name, pass --dir <empty-dir>, or remove the existing directory if you no longer need it."
