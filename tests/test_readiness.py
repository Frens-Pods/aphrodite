from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from aphrodite.app import create_app
from aphrodite import readiness
from aphrodite.doctor import doctor_payload, REQUIRED_MODULE_FILES, REQUIRED_REPO_ARTIFACTS

ROOT = Path(__file__).resolve().parents[1]


def test_mcp_readiness_reports_entrypoint_tools_and_activation_boundary():
    payload = readiness.mcp_readiness(ROOT)

    assert payload["available_on_disk"] is True
    assert payload["entrypoint"].endswith("aphrodite/mcp_server.py")
    assert payload["transport"] == "stdio"
    assert payload["tool_count"] == 10
    assert "aphrodite_skillopt_train_run" in payload["tools"]
    assert payload["activation_state"] == "disk_ready_config_not_applied"
    assert "mcp_servers.aphrodite" in payload["activation_boundary"]


def test_http_runtime_observability_is_read_only_and_names_expected_curls(monkeypatch):
    monkeypatch.setenv("APHRODITE_HOST", "127.0.0.1")
    monkeypatch.setenv("APHRODITE_PORT", "9079")

    payload = readiness.http_runtime_observability()

    assert payload["base_url"] == "http://127.0.0.1:9079"
    assert payload["read_only"] is True
    assert payload["requires_running_service"] is True
    assert "explicitly approved" in payload["activation_boundary"]
    assert payload["endpoints"]["/health"]["method"] == "GET"
    assert payload["endpoints"]["/health"]["curl"] == "curl -fsS http://127.0.0.1:9079/health"
    assert payload["endpoints"]["/health"]["expected"] == {
        "ok": True,
        "service": "aphrodite",
        "policy": "no-hermes-core",
    }
    assert payload["endpoints"]["/status"]["method"] == "GET"
    assert "service_readiness" in payload["endpoints"]["/status"]["expected_fields"]
    assert "http_observability" in payload["endpoints"]["/status"]["expected_fields"]
    assert "production_endpoint_preflight" in payload["endpoints"]["/status"]["expected_fields"]
    forbidden = "\n".join(payload["forbidden_without_named_approval"])
    assert "restart" in forbidden
    assert "Hermes config" in forbidden
    assert "Discord application endpoint" in forbidden


def test_service_readiness_reports_stale_live_service_without_mutating(monkeypatch, tmp_path):
    root = tmp_path / "aphrodite"
    (root / "aphrodite").mkdir(parents=True)
    code = root / "aphrodite" / "mcp_server.py"
    code.write_text("# new code\n")
    (root / "systemd").mkdir()
    (root / "systemd" / "aphrodite.service").write_text("ExecStart=python -m uvicorn aphrodite.app:create_app --factory\n")
    (root / "config").mkdir()
    (root / "config" / "aphrodite.env.example").write_text("APHRODITE_PORT=9079\n")

    def fake_run(command, **kwargs):
        if command[:2] == ["systemctl", "show"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=(
                    "ActiveState=active\n"
                    "SubState=running\n"
                    "MainPID=123\n"
                    "ExecMainStartTimestamp=Sun 2026-01-01 00:00:00 UTC\n"
                    "FragmentPath=/etc/systemd/system/aphrodite.service\n"
                ),
                stderr="",
            )
        if command[:2] == ["date", "-d"]:
            return subprocess.CompletedProcess(command, 0, stdout="1767225600\n", stderr="")
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr(readiness.subprocess, "run", fake_run)
    monkeypatch.setattr(readiness, "_latest_disk_mtime", lambda root_path: {"latest_path": "aphrodite/mcp_server.py", "latest_mtime": "2026-06-01T00:00:00+00:00", "latest_mtime_epoch": 1780272000.0})

    payload = readiness.service_readiness(root)

    assert payload["unit_template_present"] is True
    assert payload["env_example_present"] is True
    assert payload["live"]["checked"] is True
    assert payload["live"]["available"] is True
    assert payload["live"]["active_state"] == "active"
    assert payload["live"]["stale_vs_disk"] is True
    assert "predates latest disk" in payload["live"]["stale_reason"]
    guidance = payload["live"]["staleness_guidance"]
    assert guidance["read_only"] is True
    assert guidance["field"] == "service_readiness.live.stale_vs_disk"
    assert "I approve restarting/reloading aphrodite.service now." in guidance["approval_phrases"]
    forbidden = "\n".join(guidance["forbidden_without_named_approval"])
    assert "hermes gateway run --replace" in forbidden
    assert "cron creation" in forbidden


def test_live_service_staleness_guidance_doc_and_verify_boundary():
    payload = readiness.live_service_staleness_guidance()
    assert payload["read_only"] is True
    assert payload["not_a_failure_by_itself"] is True
    assert "service_readiness.live.stale_vs_disk" in payload["field"]
    assert "I approve installing and starting aphrodite.service now." in payload["approval_phrases"]
    assert "bash scripts/verify.sh" in payload["safe_next_checks"]

    doc = ROOT / "docs" / "live-service-staleness.md"
    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    required = [
        "service_readiness.live.stale_vs_disk=true",
        "I approve restarting/reloading aphrodite.service now.",
        "I approve setting the Discord application interaction endpoint to <URL> now.",
        "Do not run `hermes gateway run --replace`.",
        "Do not create, update, remove, or recursively manage cron jobs.",
        "PYTHONDONTWRITEBYTECODE=1 python scripts/aphrodite doctor",
        "bash scripts/verify.sh",
    ]
    for marker in required:
        assert marker in text

    verify_text = (ROOT / "scripts" / "verify.sh").read_text(encoding="utf-8")
    forbidden_verify_markers = [
        "systemctl start",
        "systemctl restart",
        "systemctl reload",
        "systemctl enable",
        "systemctl disable",
        "hermes gateway run --replace",
        "crontab",
        "curl -X POST https://discord.com",
        "curl -X PATCH https://discord.com",
        "curl -X PUT https://discord.com",
        "curl -X DELETE https://discord.com",
    ]
    for marker in forbidden_verify_markers:
        assert marker not in verify_text


def _touch_required_files(root: Path, required: list[str]) -> None:
    for relative_path in required:
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")


def _stub_doctor_dependencies(monkeypatch) -> None:
    monkeypatch.setattr("aphrodite.doctor.mcp_readiness", lambda root: {"ok": True})
    monkeypatch.setattr("aphrodite.doctor.service_readiness", lambda root: {"ok": True})
    monkeypatch.setattr("aphrodite.doctor.http_runtime_observability", lambda: {"ok": True})
    monkeypatch.setattr("aphrodite.doctor.production_endpoint_preflight", lambda root: {"ok": True})
    monkeypatch.setattr("aphrodite.doctor.latest_version_nudge", lambda: {"checked": False})


def test_doctor_ok_true_on_installed_layout_without_repo_artifacts(monkeypatch, tmp_path):
    _stub_doctor_dependencies(monkeypatch)
    _touch_required_files(tmp_path, REQUIRED_MODULE_FILES)

    payload = doctor_payload(root=tmp_path)

    assert payload["ok"] is True
    assert payload["install_mode"] == "installed"
    assert payload["missing"] == []


def test_doctor_ok_false_in_source_tree_when_artifact_missing(monkeypatch, tmp_path):
    _stub_doctor_dependencies(monkeypatch)
    _touch_required_files(tmp_path, REQUIRED_MODULE_FILES)
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    _touch_required_files(
        tmp_path,
        [relative_path for relative_path in REQUIRED_REPO_ARTIFACTS if relative_path != "scripts/verify.sh"],
    )

    payload = doctor_payload(root=tmp_path)

    assert payload["ok"] is False
    assert payload["install_mode"] == "source"
    assert "scripts/verify.sh" in payload["missing"]


def test_doctor_includes_mcp_and_service_readiness(monkeypatch):
    from aphrodite.doctor import doctor_payload

    monkeypatch.setattr("aphrodite.doctor.service_readiness", lambda root: {"service_name": "aphrodite.service", "live": {"checked": False}})
    payload = doctor_payload(root=ROOT)

    assert payload["ok"] is True
    assert payload["mcp"]["available_on_disk"] is True
    assert "aphrodite_skillopt_export_bundle" in payload["mcp"]["tools"]
    assert payload["service_readiness"]["service_name"] == "aphrodite.service"
    assert payload["http_observability"]["read_only"] is True
    assert payload["http_observability"]["endpoints"]["/health"]["method"] == "GET"


def test_status_endpoint_includes_mcp_and_service_readiness(monkeypatch):
    monkeypatch.setattr("aphrodite.app.service_readiness", lambda: {"service_name": "aphrodite.service", "live": {"checked": False}})
    client = TestClient(create_app())

    payload = client.get("/status").json()

    assert payload["ok"] is True
    assert "skillopt" in payload["modules"]
    assert payload["mcp"]["transport"] == "stdio"
    assert payload["mcp"]["tool_count"] == 10
    assert payload["service_readiness"]["service_name"] == "aphrodite.service"
    assert payload["http_observability"]["base_url"].startswith("http://")
    assert payload["http_observability"]["endpoints"]["/status"]["method"] == "GET"
    assert payload["production_endpoint_preflight"]["read_only"] is True


def test_service_runtime_observability_doc_regresses_safe_checks_and_boundaries():
    doc = ROOT / "docs" / "service-runtime-observability.md"

    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    required = [
        "curl -fsS http://127.0.0.1:9079/health",
        "curl -fsS http://127.0.0.1:9079/status",
        "curl -fsS https://<approved-host>/health",
        "curl -fsS https://<approved-host>/status",
        "service_readiness.live",
        "http_observability",
        "hermes gateway run --replace",
        "Discord application interaction endpoint changes",
        "cron creation, removal, or recursive management",
    ]
    for marker in required:
        assert marker in text

    forbidden_phrases = [
        "systemctl restart aphrodite.service",
        "systemctl reload aphrodite.service",
        "systemctl start aphrodite.service",
    ]
    for phrase in forbidden_phrases:
        assert phrase not in text
