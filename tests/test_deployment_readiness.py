from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _minimal_preflight_root(tmp_path: Path, env_text: str | None = None) -> Path:
    root = tmp_path / "aphrodite"
    for rel in ("config", "systemd", "caddy"):
        (root / rel).mkdir(parents=True, exist_ok=True)
    (root / "config" / "aphrodite.env.example").write_text("APHRODITE_DISCORD_PUBLIC_KEY=\n", encoding="utf-8")
    if env_text is not None:
        (root / "config" / "aphrodite.env").write_text(env_text, encoding="utf-8")
    (root / "systemd" / "aphrodite.service.example").write_text(
        "ExecStart=/venv/bin/python -m uvicorn aphrodite.app:create_app --factory\n",
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
    for rel in (
        "aphrodite/__init__.py",
        "aphrodite/app.py",
        "aphrodite/config.py",
        "aphrodite/router.py",
        "aphrodite/paths.py",
        "aphrodite/preflight.py",
        "aphrodite/doctor.py",
        "aphrodite/readiness.py",
        "aphrodite/mcp_server.py",
        "aphrodite/discord/__init__.py",
        "aphrodite/discord/intake.py",
        "aphrodite/discord/signature.py",
        "aphrodite/modules/__init__.py",
        "aphrodite/modules/image_gen.py",
        "aphrodite/modules/skillopt.py",
        "aphrodite/modules/acp_relay.py",
        "scripts/aphrodite",
        "scripts/verify.sh",
        "README.md",
        "NO_CORE_POLICY.md",
        "ROADMAP.md",
    ):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# present\n", encoding="utf-8")
    return root


def test_doctor_reports_discord_public_key_readiness(monkeypatch):
    from aphrodite.doctor import doctor_payload

    monkeypatch.delenv("APHRODITE_DISCORD_PUBLIC_KEY", raising=False)
    missing = doctor_payload(root=ROOT)
    assert missing["env"]["APHRODITE_DISCORD_PUBLIC_KEY"]["configured"] is False
    assert missing["env"]["APHRODITE_DISCORD_PUBLIC_KEY"]["required_for"] == "production Discord HTTP interactions"

    monkeypatch.setenv("APHRODITE_DISCORD_PUBLIC_KEY", "a" * 64)
    configured = doctor_payload(root=ROOT)
    assert configured["env"]["APHRODITE_DISCORD_PUBLIC_KEY"]["configured"] is True


def test_deployment_templates_exist_and_do_not_autostart_service():
    env_example = ROOT / "config" / "aphrodite.env.example"
    service = ROOT / "systemd" / "aphrodite.service.example"

    assert env_example.exists()
    assert service.exists()

    env_text = env_example.read_text(encoding="utf-8")
    service_text = service.read_text(encoding="utf-8")

    assert "APHRODITE_PUBLIC_BASE_URL=https://<approved-host>" in env_text
    assert "APHRODITE_DISCORD_PUBLIC_KEY=" in env_text
    assert "APHRODITE_HOST=127.0.0.1" in env_text
    assert "APHRODITE_PORT=9079" in env_text
    assert "ExecStart=" in service_text
    assert "uvicorn aphrodite.app:create_app --factory" in service_text
    assert "WantedBy=multi-user.target" in service_text
    assert "systemctl start" not in service_text


def test_caddy_route_template_exists_without_secrets_or_service_actions():
    caddy = ROOT / "caddy" / "aphrodite.caddy.example"

    assert caddy.exists()
    text = caddy.read_text(encoding="utf-8")
    assert "reverse_proxy @discord_interactions 127.0.0.1:9079" in text
    assert "reverse_proxy @health 127.0.0.1:9079" in text
    assert "reverse_proxy 127.0.0.1:9079" not in text
    assert "/discord/interactions" in text
    assert "systemctl" not in text


def test_readme_documents_deploy_without_starting():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "APHRODITE_DISCORD_PUBLIC_KEY" in readme
    assert "systemd/aphrodite.service" in readme
    assert "Do not start or enable the service until" in readme


def test_preflight_blocks_production_without_valid_public_key(monkeypatch, tmp_path):
    from aphrodite.preflight import preflight_payload

    monkeypatch.delenv("APHRODITE_DISCORD_PUBLIC_KEY", raising=False)
    root = _minimal_preflight_root(tmp_path)
    missing = preflight_payload(root=root, production=True)
    assert missing["ok"] is False
    assert "APHRODITE_DISCORD_PUBLIC_KEY missing" in missing["blocking"]

    monkeypatch.setenv("APHRODITE_DISCORD_PUBLIC_KEY", "not-hex")
    invalid = preflight_payload(root=root, production=True)
    assert invalid["ok"] is False
    assert "APHRODITE_DISCORD_PUBLIC_KEY must be 64 hex characters" in invalid["blocking"]

    monkeypatch.setenv("APHRODITE_DISCORD_PUBLIC_KEY", "a" * 64)
    ready = preflight_payload(root=root, production=True)
    assert "APHRODITE_DISCORD_PUBLIC_KEY" not in "\n".join(ready["blocking"])


def test_preflight_reads_private_env_file_without_shell_export(monkeypatch, tmp_path):
    from aphrodite.preflight import preflight_payload

    monkeypatch.delenv("APHRODITE_DISCORD_PUBLIC_KEY", raising=False)
    root = _minimal_preflight_root(tmp_path, "APHRODITE_DISCORD_PUBLIC_KEY=" + "b" * 64 + "\n")

    payload = preflight_payload(root=root, production=True)
    assert payload["ok"] is True
    assert payload["blocking"] == []


def test_preflight_cli_returns_nonzero_when_production_not_ready(monkeypatch, capsys):
    import aphrodite.cli as cli

    monkeypatch.setenv("APHRODITE_DISCORD_PUBLIC_KEY", "not-hex")

    assert cli.main(["preflight", "--production"]) == 1
    assert "APHRODITE_DISCORD_PUBLIC_KEY must be 64 hex characters" in capsys.readouterr().out
