from __future__ import annotations

import re
from pathlib import Path
from typing import Any

MODULE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
INVALID_NAME_MESSAGE = "use lowercase letters, digits, underscores, starting with a letter"

MODULE_TEMPLATE = '''"""Aphrodite module adapter: __NAME__.

Aphrodite discovers this module through the `aphrodite.adapters` entry point
declared in pyproject.toml. Aphrodite never imports your code directly, so you
can build and ship this as an independent package.
"""
from __future__ import annotations

from typing import Any


def handle(action: str, payload: list[str], context: dict[str, Any]) -> dict[str, Any]:
    """Handle one dispatch call.

    A custom id looks like `__NAME__:v1:<action>:<arg1>:<arg2>`:
      action  -> the verb (e.g. "ping")
      payload -> the remaining colon-separated args, as a list of strings
      context -> extra data the caller passes in

    Return a JSON-serializable dict. Use `ok: true` on success, or
    `ok: false` plus an `error` string on failure.
    """
    if action == "ping":
        return {"ok": True, "action": action, "message": "__NAME__ is alive"}
    return {"ok": False, "action": action, "error": f"unknown action: {action}"}
'''

PYPROJECT_TEMPLATE = '''[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "aphrodite-__NAME__-adapter"
version = "0.1.0"
description = "Aphrodite module adapter: __NAME__."
requires-python = ">=3.10"
dependencies = []

[project.entry-points."aphrodite.adapters"]
__NAME__ = "__NAME__:handle"

[tool.setuptools]
py-modules = ["__NAME__"]
'''

README_TEMPLATE = '''# Aphrodite __NAME__ adapter

This is a starter Aphrodite module adapter. It ships independently from
Aphrodite and is discovered through the `aphrodite.adapters` entry point.

## Try it

1. `pip install -e .` into the same environment as Aphrodite
2. Add `__NAME__` to `APHRODITE_MODULES`
3. Try it: `aphrodite dispatch-test __NAME__:v1:ping`

Then edit `handle()` to add your own actions.
'''


def scaffold_module(name: str, dest: str | Path = ".") -> dict[str, Any]:
    if not MODULE_NAME_RE.fullmatch(name):
        return {"ok": False, "error": f"invalid module name: {name}; {INVALID_NAME_MESSAGE}"}

    target = Path(dest).expanduser().resolve() / name
    if target.exists():
        return {"ok": False, "error": f"{target} already exists"}

    target.mkdir(parents=True)
    files = {
        f"{name}.py": MODULE_TEMPLATE,
        "pyproject.toml": PYPROJECT_TEMPLATE,
        "README.md": README_TEMPLATE,
    }
    created: list[str] = []
    for filename, template in files.items():
        path = target / filename
        path.write_text(template.replace("__NAME__", name), encoding="utf-8")
        created.append(str(path))

    return {
        "ok": True,
        "module": name,
        "path": str(target),
        "created": created,
        "next_steps": [
            f"pip install -e {target}",
            f"add '{name}' to APHRODITE_MODULES",
            f"aphrodite dispatch-test {name}:v1:ping",
        ],
    }
