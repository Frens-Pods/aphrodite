from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any

from .doctor import doctor_payload
from .readiness import production_endpoint_preflight

_PUBLIC_KEY_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def _read_env_file(root_path: Path) -> dict[str, str]:
    """Read Aphrodite's private env file without exporting secrets globally."""
    env_path = root_path / "config" / "aphrodite.env"
    if not env_path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _env_value(root_env: dict[str, str], name: str) -> str:
    return str(os.environ.get(name) or root_env.get(name) or "").strip()


def preflight_payload(root: Path | str | None = None, production: bool = False) -> dict[str, Any]:
    """Report whether Aphrodite is ready to activate, without starting anything."""
    root_path = Path(root or Path(__file__).resolve().parents[1]).resolve()
    root_env = _read_env_file(root_path)
    doctor = doctor_payload(root=root_path)
    blocking: list[str] = []
    warnings: list[str] = []

    if not doctor.get("ok"):
        for missing in doctor.get("missing", []):
            blocking.append(f"missing required file: {missing}")

    service_path = root_path / "systemd" / "aphrodite.service.example"
    service_text = service_path.read_text(encoding="utf-8") if service_path.exists() else ""
    if "systemctl start" in service_text or "systemctl enable" in service_text:
        blocking.append("systemd template must not auto-start or auto-enable Aphrodite")
    if "uvicorn aphrodite.app:create_app --factory" not in service_text:
        blocking.append("systemd template does not start Aphrodite FastAPI factory")

    public_key = _env_value(root_env, "APHRODITE_DISCORD_PUBLIC_KEY")
    endpoint = production_endpoint_preflight(root_path)
    if production and not endpoint.get("ok"):
        for item in endpoint.get("blocking", []):
            if item not in blocking:
                blocking.append(item)
    if production:
        if not public_key:
            blocking.append("APHRODITE_DISCORD_PUBLIC_KEY missing")
        elif not _PUBLIC_KEY_RE.match(public_key):
            blocking.append("APHRODITE_DISCORD_PUBLIC_KEY must be 64 hex characters")
    elif public_key and not _PUBLIC_KEY_RE.match(public_key):
        warnings.append("APHRODITE_DISCORD_PUBLIC_KEY is configured but not 64 hex characters")

    if not _env_value(root_env, "APHRODITE_DISCORD_ALLOWED_USER_IDS") and not _env_value(
        root_env, "APHRODITE_DISCORD_ALLOWED_ROLE_IDS"
    ):
        warnings.append("No Aphrodite Discord allowlist env configured; Kanban approve/deny will stay unauthorized")

    blocking = list(dict.fromkeys(blocking))
    python_executable = Path(sys.executable).resolve()
    return {
        "ok": not blocking,
        "production": bool(production),
        "root": str(root_path),
        "python": str(python_executable),
        "doctor_ok": bool(doctor.get("ok")),
        "blocking": blocking,
        "warnings": warnings,
        "production_endpoint_preflight": endpoint,
        "next_setup_steps": [
            "write config/aphrodite.env with APHRODITE_DISCORD_PUBLIC_KEY and allowlist env",
            "install/link systemd/aphrodite.service.example only after explicit operator approval",
            "configure HTTPS/Caddy route to /discord/interactions only after service health passes",
            "set Discord application interaction endpoint to the approved public URL",
            "treat APHRODITE_OWNS_DISCORD_INTERACTIONS=1 as the marker that this sidecar owns Discord interactions",
        ],
    }
