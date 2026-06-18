"""Aphrodite module adapter: hello.

Aphrodite discovers this module through the `aphrodite.adapters` entry point
declared in pyproject.toml. Aphrodite never imports your code directly, so you
can build and ship this as an independent package.
"""
from __future__ import annotations

from typing import Any


def handle(action: str, payload: list[str], context: dict[str, Any]) -> dict[str, Any]:
    """Handle one dispatch call.

    A custom id looks like `hello:v1:<action>:<arg1>:<arg2>`:
      action  -> the verb (e.g. "greet")
      payload -> the remaining colon-separated args, as a list of strings
      context -> extra data the caller passes in

    Return a JSON-serializable dict. Use `ok: true` on success, or
    `ok: false` plus an `error` string on failure.
    """
    if action == "greet":
        name = payload[0] if payload else "world"
        return {"ok": True, "action": action, "message": f"hello, {name}!"}
    return {"ok": False, "action": action, "error": f"unknown action: {action}"}
