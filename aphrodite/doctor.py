from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .config import DEFAULT_MODULES
from .readiness import http_runtime_observability, mcp_readiness, production_endpoint_preflight, service_readiness
from .update import latest_version_nudge

REQUIRED_MODULE_FILES = [
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
]

REQUIRED_REPO_ARTIFACTS = [
    "scripts/aphrodite",
    "scripts/verify.sh",
    "README.md",
    "NO_CORE_POLICY.md",
    "ROADMAP.md",
    "config/aphrodite.env.example",
    "systemd/aphrodite.service.example",
    "caddy/aphrodite.caddy.example",
]


def doctor_payload(root: Path | str | None = None) -> dict[str, Any]:
    root_path = Path(root or Path(__file__).resolve().parents[1]).resolve()
    is_source_tree = (root_path / "pyproject.toml").exists()
    required = list(REQUIRED_MODULE_FILES)
    if is_source_tree:
        required.extend(REQUIRED_REPO_ARTIFACTS)
    present = [rel for rel in required if (root_path / rel).exists()]
    missing = [rel for rel in required if not (root_path / rel).exists()]
    return {
        "ok": not missing,
        "service": "aphrodite",
        "root": str(root_path),
        "install_mode": "source" if is_source_tree else "installed",
        "modules": list(DEFAULT_MODULES),
        "hermes_core_policy": "read-only / untouched",
        "required_files_present": present,
        "missing": missing,
        "env": _env_readiness(),
        "mcp": mcp_readiness(root_path),
        "service_readiness": service_readiness(root_path),
        "http_observability": http_runtime_observability(),
        "production_endpoint_preflight": production_endpoint_preflight(root_path),
        "latest_version": latest_version_nudge(),
    }


def _env_readiness() -> dict[str, dict[str, Any]]:
    public_key = str(os.environ.get("APHRODITE_DISCORD_PUBLIC_KEY") or "").strip()
    return {
        "APHRODITE_DISCORD_PUBLIC_KEY": {
            "configured": bool(public_key),
            "required_for": "production Discord HTTP interactions",
            "expected": "Discord application public key as 64 hex characters",
        },
        "APHRODITE_HOST": {
            "configured": bool(str(os.environ.get("APHRODITE_HOST") or "").strip()),
            "default": "127.0.0.1",
            "required_for": "serving Aphrodite on a non-default interface",
        },
        "APHRODITE_PORT": {
            "configured": bool(str(os.environ.get("APHRODITE_PORT") or "").strip()),
            "default": "9079",
            "required_for": "serving Aphrodite on a non-default port",
        },
    }
