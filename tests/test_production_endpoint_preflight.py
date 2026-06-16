from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DOC = ROOT / "docs" / "production-endpoint-preflight.md"
VERIFY = ROOT / "scripts" / "verify.sh"


def test_production_endpoint_preflight_reports_url_caddy_env_and_get_only_checks(monkeypatch, tmp_path):
    from aphrodite.readiness import production_endpoint_preflight

    root = tmp_path / "aphrodite"
    (root / "config").mkdir(parents=True)
    (root / "caddy").mkdir(parents=True)
    (root / "config" / "aphrodite.env").write_text(
        "APHRODITE_PUBLIC_BASE_URL=https://aphrodite.example.internal\n"
        "APHRODITE_DISCORD_PUBLIC_KEY=" + "a" * 64 + "\n",
        encoding="utf-8",
    )
    (root / "caddy" / "aphrodite.caddy.example").write_text(
        "aphrodite.example.internal {\n"
        "  @discord_interactions {\n"
        "    path /discord/interactions\n"
        "    method POST\n"
        "  }\n"
        "  @health {\n"
        "    path /health /status\n"
        "    method GET\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("APHRODITE_PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("APHRODITE_DISCORD_PUBLIC_KEY", raising=False)

    payload = production_endpoint_preflight(root)

    assert payload["ok"] is True
    assert payload["read_only"] is True
    assert payload["base_url"] == "https://aphrodite.example.internal"
    assert payload["interaction_url"] == "https://aphrodite.example.internal/discord/interactions"
    assert payload["required_env"]["APHRODITE_DISCORD_PUBLIC_KEY"]["configured"] is True
    assert payload["required_env"]["APHRODITE_DISCORD_PUBLIC_KEY"]["source"] == "config/aphrodite.env"
    assert payload["caddy"]["host"] == "aphrodite.example.internal"
    assert payload["caddy"]["has_discord_interaction_path"] is True
    assert payload["caddy"]["has_get_only_health_status"] is True
    assert payload["checks"]["health"]["method"] == "GET"
    assert payload["checks"]["health"]["curl"] == "curl -fsS https://aphrodite.example.internal/health"
    assert payload["checks"]["status"]["curl"] == "curl -fsS https://aphrodite.example.internal/status"
    assert payload["checks"]["unsigned_interaction"]["method"] == "POST"
    assert "401 Invalid Discord interaction signature" in payload["checks"]["unsigned_interaction"]["expected"]
    forbidden = "\n".join(payload["forbidden_without_named_approval"])
    assert "Discord application endpoint changes" in forbidden
    assert "systemctl start/restart/reload" in forbidden


def test_production_endpoint_preflight_blocks_bad_public_url_and_missing_public_key(monkeypatch, tmp_path):
    from aphrodite.readiness import production_endpoint_preflight

    root = tmp_path / "aphrodite"
    (root / "config").mkdir(parents=True)
    (root / "caddy").mkdir(parents=True)
    (root / "config" / "aphrodite.env").write_text(
        "APHRODITE_PUBLIC_BASE_URL=http://bad.example/discord/interactions\n",
        encoding="utf-8",
    )
    (root / "caddy" / "aphrodite.caddy.example").write_text(
        "bad.example { reverse_proxy 127.0.0.1:9079 }\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("APHRODITE_PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("APHRODITE_DISCORD_PUBLIC_KEY", raising=False)

    payload = production_endpoint_preflight(root)

    assert payload["ok"] is False
    blocking = "\n".join(payload["blocking"])
    assert "APHRODITE_PUBLIC_BASE_URL must use https://" in blocking
    assert "APHRODITE_PUBLIC_BASE_URL should be the public origin only" in blocking
    assert "APHRODITE_DISCORD_PUBLIC_KEY missing" in blocking
    assert "Caddy template must route path /discord/interactions" in blocking
    assert "Caddy template must expose /health and /status as GET-only" in blocking


def test_doctor_status_and_cli_include_production_endpoint_preflight(monkeypatch, capsys):
    from fastapi.testclient import TestClient
    import aphrodite.cli as cli
    from aphrodite.app import create_app
    from aphrodite.doctor import doctor_payload

    monkeypatch.setattr(
        "aphrodite.doctor.production_endpoint_preflight",
        lambda root: {"ok": False, "read_only": True, "blocking": ["approval missing"]},
    )
    doctor = doctor_payload(root=ROOT)
    assert doctor["production_endpoint_preflight"]["read_only"] is True

    monkeypatch.setattr(
        "aphrodite.app.production_endpoint_preflight",
        lambda: {"ok": True, "read_only": True, "interaction_url": "https://aphrodite.example.internal/discord/interactions"},
    )
    status = TestClient(create_app()).get("/status").json()
    assert status["production_endpoint_preflight"]["interaction_url"].endswith("/discord/interactions")

    monkeypatch.setattr(
        "aphrodite.cli.production_endpoint_preflight",
        lambda: {"ok": False, "read_only": True, "blocking": ["APHRODITE_DISCORD_PUBLIC_KEY missing"]},
    )
    assert cli.main(["endpoint-preflight"]) == 1
    assert "APHRODITE_DISCORD_PUBLIC_KEY missing" in capsys.readouterr().out


def test_production_endpoint_preflight_doc_and_verify_regressions():
    assert DOC.exists()
    text = DOC.read_text(encoding="utf-8")
    required = [
        "python scripts/aphrodite endpoint-preflight",
        "APHRODITE_PUBLIC_BASE_URL",
        "https://<approved-host>/discord/interactions",
        "APHRODITE_DISCORD_PUBLIC_KEY",
        "Discord application public key, not the bot token",
        "curl -fsS https://<approved-host>/health",
        "curl -fsS https://<approved-host>/status",
        "401 Invalid Discord interaction signature",
        "503 Discord public key is not configured",
        "Do not change the Discord application interaction endpoint",
        "Do not start, restart, reload, enable, or disable services",
        "hermes gateway run --replace",
    ]
    for marker in required:
        assert marker in text

    verify_text = VERIFY.read_text(encoding="utf-8")
    endpoint_index = verify_text.index("tests/test_production_endpoint_preflight.py")
    full_suite_index = verify_text.index("python -m pytest tests -q")
    assert endpoint_index < full_suite_index
