from __future__ import annotations

import os
from pathlib import Path


def hermes_root() -> Path:
    """Return the canonical Hermes root, collapsing named profile homes.

    Aphrodite runs as a sidecar and often under the Forge profile environment,
    while local plugins live under the shared Hermes root. If HERMES_HOME points
    at `<root>/profiles/<name>`, use `<root>` for plugin discovery.
    """
    raw = os.environ.get("HERMES_HOME")
    if raw:
        home = Path(raw).expanduser().resolve()
    else:
        try:
            from hermes_constants import get_hermes_home

            home = get_hermes_home().expanduser().resolve()
        except Exception:
            home = (Path.home() / ".hermes").expanduser().resolve()
    if home.parent.name == "profiles" and home.parent.parent.exists():
        return home.parent.parent.resolve()
    return home


def plugin_dir(name: str) -> Path:
    return (hermes_root() / "plugins" / name).resolve()
