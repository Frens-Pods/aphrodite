from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .config import DEFAULT_MODULES

SKILLOPT_MCP_TOOLS = [
    "aphrodite_skillopt_list_runs",
    "aphrodite_skillopt_get_run",
    "aphrodite_skillopt_train_run",
    "aphrodite_skillopt_create_eval",
    "aphrodite_skillopt_list_evals",
    "aphrodite_skillopt_get_eval",
    "aphrodite_skillopt_evaluate_run",
    "aphrodite_skillopt_get_evaluation",
    "aphrodite_skillopt_import_candidate",
    "aphrodite_skillopt_export_bundle",
]

_CODE_MTIME_GLOBS = [
    "aphrodite/*.py",
    "aphrodite/modules/*.py",
    "aphrodite/discord/*.py",
    "scripts/aphrodite",
    "scripts/*.py",
    "scripts/*.sh",
    "systemd/*.service",
    "config/*.example",
]


def _iso_mtime(path: Path) -> str | None:
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()


def _latest_disk_mtime(root_path: Path) -> dict[str, Any]:
    latest_path: Path | None = None
    latest_mtime = 0.0
    for pattern in _CODE_MTIME_GLOBS:
        for path in root_path.glob(pattern):
            if path.is_file() and path.stat().st_mtime > latest_mtime:
                latest_path = path
                latest_mtime = path.stat().st_mtime
    return {
        "latest_path": str(latest_path.relative_to(root_path)) if latest_path else None,
        "latest_mtime": datetime.fromtimestamp(latest_mtime, tz=timezone.utc).isoformat() if latest_path else None,
        "latest_mtime_epoch": latest_mtime if latest_path else None,
    }


def _parse_systemctl_show(output: str) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in output.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            data[key] = value
    return data


def _read_env_file(root_path: Path) -> dict[str, str]:
    env_path = root_path / "config" / "aphrodite.env"
    if not env_path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('\"').strip("'")
    return values


def _env_with_source(root_env: dict[str, str], name: str) -> tuple[str, str | None]:
    shell_value = str(os.environ.get(name) or "").strip()
    if shell_value:
        return shell_value, "process env"
    file_value = str(root_env.get(name) or "").strip()
    if file_value:
        return file_value, "config/aphrodite.env"
    return "", None


def _caddy_host(template: str) -> str | None:
    for raw_line in template.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "{" not in line:
            continue
        host = line.split("{", 1)[0].strip()
        if host and not host.startswith("@"):
            return host
    return None


def _parse_timestamp(raw_timestamp: str) -> float | None:
    """Parse a systemd/ISO timestamp to epoch seconds without shelling out.

    systemd's ExecMainStartTimestamp looks like ``Wed 2026-06-17 12:34:56 UTC``;
    ISO 8601 is also accepted. Naive values are treated as UTC. Pure-Python so
    it works off-Linux, where GNU ``date -d`` is unavailable (macOS/BSD).
    """
    candidate = raw_timestamp
    head, _, tail = candidate.partition(" ")
    if tail and len(head) == 3 and head.isalpha():
        candidate = tail  # drop a leading weekday name ("Wed 2026-..." -> "2026-...")
    for fmt in ("%Y-%m-%d %H:%M:%S %Z", "%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(candidate, fmt)
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _date_epoch(raw_timestamp: str) -> float | None:
    raw_timestamp = str(raw_timestamp or "").strip()
    if not raw_timestamp or raw_timestamp == "n/a":
        return None
    parsed = _parse_timestamp(raw_timestamp)
    if parsed is not None:
        return parsed
    # Fallback to GNU `date -d` where available (Linux) for exotic formats.
    try:
        result = subprocess.run(
            ["date", "-d", raw_timestamp, "+%s"],
            text=True,
            capture_output=True,
            timeout=2,
            check=False,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    try:
        return float(result.stdout.strip())
    except ValueError:
        return None


def mcp_readiness(root: Path | str | None = None) -> dict[str, Any]:
    root_path = Path(root or Path(__file__).resolve().parents[1]).resolve()
    entrypoint = root_path / "aphrodite" / "mcp_server.py"
    sdk_available = importlib.util.find_spec("mcp") is not None
    return {
        "available_on_disk": entrypoint.exists(),
        "entrypoint": str(entrypoint),
        "python": sys.executable,
        "mcp_sdk_available": sdk_available,
        "transport": "stdio",
        "tools": list(SKILLOPT_MCP_TOOLS),
        "tool_count": len(SKILLOPT_MCP_TOOLS),
        "smoke_command": "PYTHONDONTWRITEBYTECODE=1 python scripts/mcp_smoke.py",
        "activation_state": "disk_ready_config_not_applied",
        "activation_boundary": "Add mcp_servers.aphrodite to the relevant Hermes profile config and start a fresh Hermes process before expecting tools to appear.",
    }


def production_endpoint_preflight(root: Path | str | None = None) -> dict[str, Any]:
    """Non-live readiness report for the public Discord interaction endpoint.

    This function validates disk/env shape and returns operator commands only. It
    must not call Discord, curl public URLs, reload Caddy, or touch services.
    """
    root_path = Path(root or Path(__file__).resolve().parents[1]).resolve()
    root_env = _read_env_file(root_path)
    public_base_url, base_source = _env_with_source(root_env, "APHRODITE_PUBLIC_BASE_URL")
    public_key, public_key_source = _env_with_source(root_env, "APHRODITE_DISCORD_PUBLIC_KEY")
    if not public_base_url:
        caddy_text_for_host = (root_path / "caddy" / "aphrodite.caddy.example").read_text(encoding="utf-8") if (root_path / "caddy" / "aphrodite.caddy.example").exists() else ""
        host = _caddy_host(caddy_text_for_host) or "<approved-host>"
        public_base_url = f"https://{host}"
        base_source = "caddy/aphrodite.caddy.example" if host != "<approved-host>" else None

    parsed = urlparse(public_base_url)
    normalized_base = public_base_url.rstrip("/")
    interaction_url = f"{normalized_base}/discord/interactions"
    blocking: list[str] = []
    warnings: list[str] = []

    if parsed.scheme != "https":
        blocking.append("APHRODITE_PUBLIC_BASE_URL must use https://")
    if parsed.path and parsed.path != "/":
        blocking.append("APHRODITE_PUBLIC_BASE_URL should be the public origin only; /discord/interactions is appended by Aphrodite")
    if parsed.query or parsed.fragment:
        blocking.append("APHRODITE_PUBLIC_BASE_URL must not include query strings or fragments")
    if not parsed.netloc or parsed.netloc == "<approved-host>":
        warnings.append("approved public host is not configured; using placeholder host for operator docs")

    public_key_re = re.compile(r"^[0-9a-fA-F]{64}$")
    if not public_key:
        blocking.append("APHRODITE_DISCORD_PUBLIC_KEY missing")
    elif not public_key_re.match(public_key):
        blocking.append("APHRODITE_DISCORD_PUBLIC_KEY must be 64 hex characters")

    caddy_path = root_path / "caddy" / "aphrodite.caddy.example"
    caddy_text = caddy_path.read_text(encoding="utf-8") if caddy_path.exists() else ""
    has_interaction_path = "/discord/interactions" in caddy_text and "method POST" in caddy_text
    has_get_health = "/health" in caddy_text and "/status" in caddy_text and "method GET" in caddy_text
    if not caddy_text:
        blocking.append("caddy/aphrodite.caddy.example missing")
    if not has_interaction_path:
        blocking.append("Caddy template must route path /discord/interactions as POST-only")
    if not has_get_health:
        blocking.append("Caddy template must expose /health and /status as GET-only")

    return {
        "ok": not blocking,
        "read_only": True,
        "root": str(root_path),
        "base_url": normalized_base,
        "base_url_source": base_source,
        "interaction_url": interaction_url,
        "required_env": {
            "APHRODITE_PUBLIC_BASE_URL": {
                "configured": bool(base_source),
                "source": base_source,
                "expected": "approved HTTPS origin only, e.g. https://<approved-host>",
            },
            "APHRODITE_DISCORD_PUBLIC_KEY": {
                "configured": bool(public_key),
                "source": public_key_source,
                "expected": "Discord application public key as 64 hex characters; not the bot token",
            },
        },
        "caddy": {
            "template": str(caddy_path),
            "present": caddy_path.exists(),
            "host": _caddy_host(caddy_text),
            "has_discord_interaction_path": has_interaction_path,
            "has_get_only_health_status": has_get_health,
        },
        "checks": {
            "health": {
                "method": "GET",
                "curl": f"curl -fsS {normalized_base}/health",
                "expected": "200 JSON with ok=true, service=aphrodite, policy=no-hermes-core",
            },
            "status": {
                "method": "GET",
                "curl": f"curl -fsS {normalized_base}/status",
                "expected": "200 JSON including service_readiness, http_observability, and production_endpoint_preflight",
            },
            "unsigned_interaction": {
                "method": "POST",
                "curl": f"curl -i -X POST {interaction_url} -H 'Content-Type: application/json' -d '{{}}'",
                "expected": "401 Invalid Discord interaction signature, or 503 Discord public key is not configured before env is installed; never a successful action",
            },
        },
        "blocking": blocking,
        "warnings": warnings,
        "forbidden_without_named_approval": [
            "systemctl start/restart/reload/enable/disable aphrodite.service",
            "Caddy reload or proxy config changes",
            "Hermes config edits or Hermes gateway reload/restart/replace",
            "hermes gateway run --replace",
            "Discord application endpoint changes",
            "Discord POST/PATCH/PUT/DELETE/pin/unpin live card mutations",
            "cron creation, removal, or recursive management",
        ],
    }


def http_runtime_observability(host: str | None = None, port: str | int | None = None) -> dict[str, Any]:
    """Read-only operator expectations for the HTTP runtime after service setup.

    This deliberately returns commands/documentation only. It must not probe the
    network by itself, because scheduled verification should not require a live
    service and must not imply a deployment change.
    """
    resolved_host = str(host or os.environ.get("APHRODITE_HOST", "127.0.0.1"))
    resolved_port = str(port or os.environ.get("APHRODITE_PORT", "9079"))
    base_url = f"http://{resolved_host}:{resolved_port}"
    return {
        "base_url": base_url,
        "read_only": True,
        "requires_running_service": True,
        "activation_boundary": "These GET checks are for after aphrodite.service/proxy setup is explicitly approved; scripts/verify.sh must not start, restart, reload, enable, or configure services.",
        "endpoints": {
            "/health": {
                "method": "GET",
                "curl": f"curl -fsS {base_url}/health",
                "expected": {
                    "ok": True,
                    "service": "aphrodite",
                    "policy": "no-hermes-core",
                },
                "purpose": "Liveness: process is accepting HTTP and serving the no-core sidecar health payload.",
            },
            "/status": {
                "method": "GET",
                "curl": f"curl -fsS {base_url}/status",
                "expected_fields": [
                    "ok",
                    "service",
                    "version",
                    "policy",
                    "modules",
                    "registered_systems",
                    "mcp",
                    "service_readiness",
                    "http_observability",
                    "production_endpoint_preflight",
                ],
                "purpose": "Operator readiness: registered systems, MCP disk readiness, systemd/env template state, live staleness, and safe follow-up checks.",
            },
        },
        "forbidden_without_named_approval": [
            "systemctl start/restart/reload/enable/disable aphrodite.service",
            "Caddy reload or proxy config changes",
            "Hermes config edits or Hermes gateway reload/restart/replace",
            "Discord application endpoint changes",
            "Discord POST/PATCH/PUT/DELETE/pin/unpin live card mutations",
            "cron creation, removal, or recursive management",
        ],
    }


def live_service_staleness_guidance(service_name: str = "aphrodite.service") -> dict[str, Any]:
    """Explain stale-live-service evidence without authorizing service changes.

    The stale bit is derived from read-only systemd metadata plus disk mtimes. A
    scheduled check may report it, but resolving it requires explicit operator
    approval because resolution normally means installing env/unit/proxy changes
    or restarting/reloading a live service.
    """
    approval_phrases = [
        "I approve installing Aphrodite private env now.",
        f"I approve installing and starting {service_name} now.",
        f"I approve restarting/reloading {service_name} now.",
        "I approve applying the Aphrodite Caddy route and reloading Caddy now.",
        "I approve setting the Discord application interaction endpoint to <URL> now.",
        "I approve restarting/reloading <exact Hermes service> now.",
    ]
    forbidden = [
        f"systemctl start/restart/reload/enable/disable {service_name}",
        "Caddy reload or proxy config changes",
        "Hermes config edits or Hermes gateway reload/restart/replace",
        "hermes gateway run --replace",
        "Discord application endpoint changes",
        "Discord POST/PATCH/PUT/DELETE/pin/unpin live card mutations",
        "cron creation, removal, or recursive management",
    ]
    return {
        "read_only": True,
        "field": "service_readiness.live.stale_vs_disk",
        "interpretation": "true means the live systemd process start timestamp predates Aphrodite disk code/template mtimes; disk verification may be newer than the running service.",
        "not_a_failure_by_itself": True,
        "activation_boundary": "Autonomous verification may report stale live state, but must not resolve it by starting, restarting, reloading, enabling, disabling, editing config/endpoints, mutating Discord cards, or managing cron.",
        "approval_phrases": approval_phrases,
        "safe_next_checks": [
            "PYTHONDONTWRITEBYTECODE=1 python scripts/aphrodite doctor",
            "PYTHONDONTWRITEBYTECODE=1 python scripts/aphrodite endpoint-preflight",
            "bash scripts/verify.sh",
        ],
        "forbidden_without_named_approval": forbidden,
        "rollback_note": "If an approved service change fails, restore the prior env/unit/proxy/Discord endpoint or card state only inside that approved rollback window; do not run hermes gateway run --replace as rollback without named approval.",
    }


def service_readiness(root: Path | str | None = None, service_name: str = "aphrodite.service") -> dict[str, Any]:
    root_path = Path(root or Path(__file__).resolve().parents[1]).resolve()
    env_file = root_path / "config" / "aphrodite.env"
    env_example = root_path / "config" / "aphrodite.env.example"
    unit_template = root_path / "systemd" / "aphrodite.service"
    disk = _latest_disk_mtime(root_path)
    payload: dict[str, Any] = {
        "service_name": service_name,
        "unit_template": str(unit_template),
        "unit_template_present": unit_template.exists(),
        "env_file": str(env_file),
        "env_file_present": env_file.exists(),
        "env_example_present": env_example.exists(),
        "host": os.environ.get("APHRODITE_HOST", "127.0.0.1"),
        "port": os.environ.get("APHRODITE_PORT", "9079"),
        "configured_modules": list(DEFAULT_MODULES),
        "disk_latest": disk,
        "live": {
            "checked": False,
            "available": False,
            "reason": "systemctl not queried",
        },
    }
    try:
        result = subprocess.run(
            [
                "systemctl",
                "show",
                service_name,
                "-p",
                "ActiveState",
                "-p",
                "SubState",
                "-p",
                "MainPID",
                "-p",
                "ExecMainStartTimestamp",
                "-p",
                "FragmentPath",
                "--no-pager",
            ],
            text=True,
            capture_output=True,
            timeout=3,
            check=False,
        )
    except Exception as exc:
        payload["live"] = {"checked": True, "available": False, "reason": f"systemctl unavailable: {exc}"}
        return payload
    if result.returncode != 0:
        payload["live"] = {
            "checked": True,
            "available": False,
            "reason": (result.stderr or result.stdout or "systemctl show failed").strip(),
        }
        return payload
    data = _parse_systemctl_show(result.stdout)
    start_raw = data.get("ExecMainStartTimestamp", "")
    start_epoch = _date_epoch(start_raw)
    latest_epoch = disk.get("latest_mtime_epoch")
    stale: bool | None = None
    if start_epoch is not None and isinstance(latest_epoch, (int, float)):
        stale = start_epoch < float(latest_epoch)
    payload["live"] = {
        "checked": True,
        "available": True,
        "active_state": data.get("ActiveState"),
        "sub_state": data.get("SubState"),
        "main_pid": data.get("MainPID"),
        "fragment_path": data.get("FragmentPath"),
        "start_timestamp": start_raw,
        "start_epoch": start_epoch,
        "stale_vs_disk": stale,
        "stale_reason": "live process start predates latest disk code/template mtime" if stale else None,
        "staleness_guidance": live_service_staleness_guidance(service_name),
    }
    return payload
