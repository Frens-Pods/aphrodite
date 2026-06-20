from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .config import DEFAULT_MODULES, load_config
from .readiness import http_runtime_observability, mcp_readiness, production_endpoint_preflight, service_readiness
from .update import latest_version_nudge
from .modules import discover_adapter_specs

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
    config = load_config()
    required = list(REQUIRED_MODULE_FILES)
    if is_source_tree:
        required.extend(REQUIRED_REPO_ARTIFACTS)
    present = [rel for rel in required if (root_path / rel).exists()]
    missing = [rel for rel in required if not (root_path / rel).exists()]
    payload = {
        "ok": not missing,
        "service": "aphrodite",
        "root": str(root_path),
        "install_mode": "source" if is_source_tree else "installed",
        "modules": list(DEFAULT_MODULES),
        "hermes_core_policy": "read-only / untouched",
        "required_files_present": present,
        "missing": missing,
        "env": _env_readiness(),
        "warnings": list(config.warnings),
        "mcp": mcp_readiness(root_path),
        "service_readiness": service_readiness(root_path),
        "http_observability": http_runtime_observability(),
        "production_endpoint_preflight": production_endpoint_preflight(root_path),
        "latest_version": latest_version_nudge(),
    }
    payload["adapters"] = _adapter_lint()
    payload["dependencies"] = _dependency_health()
    return payload


def _adapter_lint() -> dict:
    specs, errors = discover_adapter_specs()
    return {
        "ok": not errors,
        "adapters": [
            {
                "name": spec.system,
                "source": spec.source,
                "has_router": spec.router is not None,
                "requires_auth": spec.requires_auth,
                "has_readiness": spec.readiness is not None,
                "has_lifespan": spec.lifespan is not None,
                "api_version": spec.api_version,
            }
            for spec in specs.values()
        ],
        "errors": errors,
    }


def _dependency_health() -> dict[str, Any]:
    from importlib import metadata as _md

    core = {"fastapi": ">=0.110", "pynacl": ">=1.5", "uvicorn": ">=0.29"}
    try:
        from packaging.specifiers import SpecifierSet
        from packaging.version import Version

        can_compare = True
    except Exception:
        can_compare = False
    found: dict[str, str] = {}
    missing: list[str] = []
    below_floor: dict[str, str] = {}
    for dist, floor in core.items():
        try:
            ver = _md.version(dist)
        except _md.PackageNotFoundError:
            missing.append(dist)
            continue
        found[dist] = ver
        if can_compare:
            try:
                if Version(ver) not in SpecifierSet(floor):
                    below_floor[dist] = f"{ver} does not satisfy {floor}"
            except Exception:
                pass
    return {
        "ok": not missing and not below_floor,
        "core_floor": core,
        "installed": found,
        "missing": missing,
        "below_floor": below_floor,
        "version_check": "active" if can_compare else "presence-only (packaging unavailable)",
        "note": (
            "adapters share this interpreter/venv; a conflicting pin in an installed "
            "adapter can break the host. Aphrodite does not sandbox adapter code."
        ),
    }


def _env_readiness() -> dict[str, dict[str, Any]]:
    public_key = str(os.environ.get("APHRODITE_DISCORD_PUBLIC_KEY") or "").strip()
    return {
        "APHRODITE_DISCORD_PUBLIC_KEY": {
            "configured": bool(public_key),
            "required_for": "production Discord HTTP interactions",
            "expected": "Discord application public key as 64 hex characters",
            "fix": "cp config/aphrodite.env.example config/aphrodite.env, set APHRODITE_DISCORD_PUBLIC_KEY=<your Discord app public key>, then run aphrodite preflight --production",
        },
        "APHRODITE_HOST": {
            "configured": bool(str(os.environ.get("APHRODITE_HOST") or "").strip()),
            "default": "127.0.0.1",
            "required_for": "serving Aphrodite on a non-default interface",
            "fix": "Set APHRODITE_HOST=<host> in config/aphrodite.env or the process environment when Aphrodite must bind somewhere other than 127.0.0.1.",
        },
        "APHRODITE_PORT": {
            "configured": bool(str(os.environ.get("APHRODITE_PORT") or "").strip()),
            "default": "9079",
            "required_for": "serving Aphrodite on a non-default port",
            "fix": "Set APHRODITE_PORT=<integer> in config/aphrodite.env or the process environment, e.g. APHRODITE_PORT=9079.",
        },
    }
