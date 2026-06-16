from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_hermes_root_collapses_named_profile_home(monkeypatch, tmp_path):
    profile_home = tmp_path / ".hermes" / "profiles" / "forge"
    profile_home.mkdir(parents=True)
    (tmp_path / ".hermes" / "profiles").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HERMES_HOME", str(profile_home))

    from aphrodite.paths import hermes_root

    assert hermes_root() == (tmp_path / ".hermes").resolve()


def test_plugin_paths_use_canonical_hermes_root(monkeypatch, tmp_path):
    profile_home = tmp_path / ".hermes" / "profiles" / "forge"
    profile_home.mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(profile_home))

    from aphrodite.paths import plugin_dir

    assert plugin_dir("example-plugin") == (tmp_path / ".hermes" / "plugins" / "example-plugin").resolve()
