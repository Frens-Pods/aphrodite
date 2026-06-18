from __future__ import annotations

from typing import Any


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _join(values: Any) -> str:
    items = [str(item) for item in _as_list(values) if item]
    return ", ".join(items)


def _first_text(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, (list, tuple)):
            text = _join(value)
        elif value:
            text = str(value)
        else:
            text = ""
        if text:
            return text
    return None


def _compact(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        for key in ("message", "status", "summary", "ok"):
            if key in value:
                return f"{key}={value.get(key)}"
        return ", ".join(f"{key}={value[key]}" for key in list(value)[:3])
    if isinstance(value, list):
        return _join(value[:3])
    return str(value)


def _render_health(payload: dict[str, Any]) -> list[str]:
    modules = _join(payload.get("modules")) or "none"
    version = payload.get("version", "unknown")
    if payload.get("ok", False):
        return [f"Aphrodite OK — v{version}, modules: {modules}"]
    error = _first_text(payload.get("error"), payload.get("hint")) or "health check failed"
    return [f"Aphrodite FAIL — {error}"]


def _render_version(payload: dict[str, Any]) -> list[str]:
    version = payload.get("version", "unknown")
    source = payload.get("install_source", "unknown")
    return [f"aphrodite {version} (install source: {source})"]


def _render_modules(payload: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for label, key in (("Active", "active"), ("Missing", "missing"), ("Available", "available")):
        values = _join(payload.get(key))
        if values:
            lines.append(f"{label}: {values}")
    if not lines:
        lines.append("No modules discovered.")
    if _as_list(payload.get("missing")):
        hint = _first_text(payload.get("hint"), payload.get("fix"))
        if hint:
            lines.append(f"NEXT: {hint}")
    return lines


def _render_doctor(payload: dict[str, Any]) -> list[str]:
    lines = ["OK" if payload.get("ok", False) else "NEEDS ATTENTION"]
    lines.extend(f"- {warning}" for warning in _as_list(payload.get("warnings")))
    fixes: list[str] = []
    env = payload.get("env")
    if isinstance(env, dict):
        for name, entry in env.items():
            if isinstance(entry, dict) and not entry.get("configured", False):
                fix = _first_text(entry.get("fix"), entry.get("expected"))
                if fix:
                    fixes.append(fix)
                    lines.append(f"- {name}: {fix}")
    next_line = _first_text(fixes[0] if fixes else None, "aphrodite preflight --production")
    lines.append(f"NEXT: {next_line}")
    return lines


def _render_preflight(payload: dict[str, Any]) -> list[str]:
    lines = ["OK" if payload.get("ok", False) else "BLOCKED"]
    blocking = _as_list(payload.get("blocking"))
    if blocking:
        lines.extend(f"- {item}" for item in blocking)
    else:
        steps = _as_list(payload.get("next_setup_steps"))[:2]
        if steps:
            lines.append("NEXT for production:")
            lines.extend(f"- {step}" for step in steps)
    return lines


def _render_dispatch(payload: dict[str, Any]) -> list[str]:
    raw_result = payload.get("result")
    result = raw_result if isinstance(raw_result, dict) else {}
    result_ok = result.get("ok", True)
    if payload.get("ok", False) and result_ok:
        system = payload.get("system", "?")
        action = payload.get("action", "?")
        compact = _compact(raw_result)
        suffix = f" — {compact}" if compact else ""
        return [f"OK {system}:{action}{suffix}"]

    error = _first_text(payload.get("error"), result.get("error") if isinstance(result, dict) else None) or "dispatch failed"
    lines = [f"FAIL: {error}"]
    next_text = _first_text(
        payload.get("fix"),
        payload.get("hint"),
        payload.get("example"),
        payload.get("known_systems"),
        payload.get("supported_actions"),
        result.get("fix") if isinstance(result, dict) else None,
        result.get("hint") if isinstance(result, dict) else None,
        result.get("example") if isinstance(result, dict) else None,
        result.get("known_systems") if isinstance(result, dict) else None,
        result.get("supported_actions") if isinstance(result, dict) else None,
    )
    if next_text:
        lines.append(f"NEXT: {next_text}")
    return lines


def _render_new_module(payload: dict[str, Any]) -> list[str]:
    if not payload.get("ok", False):
        lines = [f"FAIL: {_first_text(payload.get('error')) or 'module was not created'}"]
        next_text = _first_text(payload.get("fix"), payload.get("hint"))
        if next_text:
            lines.append(f"NEXT: {next_text}")
        return lines
    lines = [f"Created module '{payload.get('module', '?')}' at {payload.get('path', '?')}"]
    for index, step in enumerate(_as_list(payload.get("next_steps")), start=1):
        lines.append(f"{index}. {step}")
    return lines


def _render_update(payload: dict[str, Any]) -> list[str]:
    status = "OK" if payload.get("ok", False) else "FAIL"
    if payload.get("update_available"):
        line = f"{status}: update available {payload.get('before', 'unknown')} -> {payload.get('latest', 'unknown')}"
    elif payload.get("updated"):
        line = f"{status}: updated {payload.get('before', 'unknown')} -> {payload.get('after', 'unknown')}"
    elif payload.get("after"):
        line = f"{status}: already at {payload.get('after')}"
    else:
        line = f"{status}: version {payload.get('before', payload.get('version', 'unknown'))}"
    lines = [line]
    note = _first_text(payload.get("summary"), payload.get("note"))
    if note:
        lines.append(note)
    return lines


def render(command: str, payload: dict) -> str:
    renderers = {
        "health": _render_health,
        "version": _render_version,
        "modules": _render_modules,
        "doctor": _render_doctor,
        "preflight": _render_preflight,
        "endpoint-preflight": _render_preflight,
        "dispatch-test": _render_dispatch,
        "new-module": _render_new_module,
        "update": _render_update,
    }
    renderer = renderers.get(command)
    lines = renderer(payload) if renderer is not None else ["OK" if payload.get("ok", False) else "FAIL"]
    return "\n".join(str(line) for line in lines if line)
