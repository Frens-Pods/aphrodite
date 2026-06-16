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
    no_core_policy: str = "no-hermes-core"


def load_config() -> AphroditeConfig:
    port_raw = os.environ.get("APHRODITE_PORT", "9079")
    try:
        port = int(port_raw)
    except ValueError:
        port = 9079
    modules_raw = os.environ.get("APHRODITE_MODULES", "").strip()
    modules = tuple(
        part.strip() for part in modules_raw.split(",") if part.strip()
    ) or tuple(DEFAULT_MODULES)
    return AphroditeConfig(
        host=os.environ.get("APHRODITE_HOST", "127.0.0.1"),
        port=port,
        hermes_home=Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes")).expanduser(),
        modules=modules,
    )
