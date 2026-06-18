from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_load_config_warns_and_falls_back_for_invalid_port(monkeypatch):
    from aphrodite.config import load_config

    monkeypatch.setenv("APHRODITE_PORT", "notaport")

    config = load_config()

    assert config.port == 9079
    assert config.warnings
    assert "APHRODITE_PORT" in config.warnings[0]


def test_doctor_env_readiness_entries_include_fixes(monkeypatch):
    from aphrodite.doctor import doctor_payload

    monkeypatch.delenv("APHRODITE_PORT", raising=False)

    payload = doctor_payload(root=ROOT)

    for entry in payload["env"].values():
        assert entry["fix"]


def test_doctor_payload_surfaces_config_warnings(monkeypatch):
    from aphrodite.doctor import doctor_payload

    monkeypatch.setenv("APHRODITE_PORT", "notaport")

    payload = doctor_payload(root=ROOT)

    assert payload["warnings"]
    assert "APHRODITE_PORT" in payload["warnings"][0]


def test_preflight_deduplicates_invalid_public_key_blocking(monkeypatch):
    from aphrodite.preflight import preflight_payload

    monkeypatch.setenv("APHRODITE_PUBLIC_BASE_URL", "http://bad")
    monkeypatch.setenv("APHRODITE_DISCORD_PUBLIC_KEY", "abc")

    payload = preflight_payload(root=ROOT, production=True)

    assert payload["blocking"].count("APHRODITE_DISCORD_PUBLIC_KEY must be 64 hex characters") == 1
