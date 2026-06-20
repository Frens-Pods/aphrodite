from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MODULES = ["image_gen", "skillopt", "acp_relay"]


@dataclass(frozen=True)
class AphroditeConfig:
    host: str = "127.0.0.1"
    port: int = 9079
    hermes_home: Path = Path.home() / ".hermes"
    modules: tuple[str, ...] = tuple(DEFAULT_MODULES)
    cors_origins: tuple[str, ...] = ()
    no_core_policy: str = "no-hermes-core"
    warnings: tuple[str, ...] = ()


def load_config() -> AphroditeConfig:
    port_raw = os.environ.get("APHRODITE_PORT", "9079")
    warnings: list[str] = []
    try:
        port = int(port_raw)
    except ValueError:
        port = 9079
        warnings.append(
            f"APHRODITE_PORT={port_raw!r} is not a valid integer; using default {port}. "
            "Set APHRODITE_PORT to an integer, e.g. 9079."
        )
    modules_raw = os.environ.get("APHRODITE_MODULES", "").strip()
    if modules_raw.startswith("+"):
        extra = tuple(
            part.strip() for part in modules_raw[1:].split(",") if part.strip()
        )
        modules = tuple(dict.fromkeys([*DEFAULT_MODULES, *extra]))
    elif modules_raw:
        modules = tuple(
            part.strip() for part in modules_raw.split(",") if part.strip()
        )
    else:
        modules = tuple(DEFAULT_MODULES)
    cors_origins_raw = os.environ.get("APHRODITE_CORS_ORIGINS", "").strip()
    cors_origins = tuple(
        part.strip() for part in cors_origins_raw.split(",") if part.strip()
    )
    return AphroditeConfig(
        host=os.environ.get("APHRODITE_HOST", "127.0.0.1"),
        port=port,
        hermes_home=Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes")).expanduser(),
        modules=modules,
        cors_origins=cors_origins,
        warnings=tuple(warnings),
    )
