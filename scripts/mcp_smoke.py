from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "aphrodite" / "mcp_server.py"
FAKE_TRAIN = ROOT / "tests" / "fixtures" / "fake_skillopt_train.py"


def _decode_tool_result(result: Any) -> dict[str, Any]:
    # FastMCP returns dicts as JSON text content over the MCP wire.
    structured = getattr(result, "structuredContent", None) or getattr(result, "structured_content", None)
    if isinstance(structured, dict):
        return structured
    content = getattr(result, "content", None) or []
    for item in content:
        text = getattr(item, "text", None)
        if isinstance(text, str):
            try:
                data = json.loads(text)
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                continue
    raise AssertionError(f"Could not decode MCP result as JSON dict: {result!r}")


async def _run_smoke() -> dict[str, Any]:
    if importlib.util.find_spec("mcp") is None:
        return {"ok": True, "skipped": True, "reason": "mcp Python SDK is not installed"}

    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    with tempfile.TemporaryDirectory(prefix="aphrodite-mcp-smoke-") as tmp:
        data_root = Path(tmp) / "skillopt-data"
        env = os.environ.copy()
        env["APHRODITE_SKILLOPT_DATA_ROOT"] = str(data_root)
        params = StdioServerParameters(
            command=sys.executable,
            args=[str(SERVER)],
            cwd=str(ROOT),
            env=env,
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools_result = await session.list_tools()
                tool_names = sorted(tool.name for tool in tools_result.tools)
                required = {
                    "aphrodite_skillopt_list_runs",
                    "aphrodite_skillopt_train_run",
                    "aphrodite_skillopt_create_eval",
                    "aphrodite_skillopt_evaluate_run",
                    "aphrodite_skillopt_export_bundle",
                }
                missing = sorted(required - set(tool_names))
                if missing:
                    raise AssertionError(f"Missing MCP tools: {missing}")

                listed = _decode_tool_result(await session.call_tool("aphrodite_skillopt_list_runs", {}))
                assert listed["ok"] is True

                run_id = "mcp-smoke-run"
                output_dir = data_root / "runs" / run_id / "work"
                trained = _decode_tool_result(
                    await session.call_tool(
                        "aphrodite_skillopt_train_run",
                        {
                            "payload": {
                                "run_id": run_id,
                                "skill_name": "mcp-smoke-skill",
                                "command": [sys.executable, str(FAKE_TRAIN), str(output_dir)],
                                "timeout_seconds": 30,
                            }
                        },
                    )
                )
                assert trained["ok"] is True, trained
                assert trained["status"] == "candidate_ready", trained

                created_eval = _decode_tool_result(
                    await session.call_tool(
                        "aphrodite_skillopt_create_eval",
                        {"payload": {"eval_id": "mcp-smoke-eval", "skill_family": "qa", "min_delta": 0.1}},
                    )
                )
                assert created_eval["ok"] is True, created_eval

                evaluation = _decode_tool_result(
                    await session.call_tool(
                        "aphrodite_skillopt_evaluate_run",
                        {"run_id": run_id, "payload": {"eval_id": "mcp-smoke-eval"}},
                    )
                )
                assert evaluation["ok"] is True, evaluation
                assert evaluation["status"] == "recommended", evaluation

                bundle = _decode_tool_result(
                    await session.call_tool("aphrodite_skillopt_export_bundle", {"run_id": run_id})
                )
                assert bundle["ok"] is True, bundle
                assert Path(bundle["bundle"]).exists(), bundle
                return {
                    "ok": True,
                    "skipped": False,
                    "tools": tool_names,
                    "run_id": run_id,
                    "bundle_exists": True,
                    "data_root": str(data_root),
                }


def main() -> int:
    try:
        result = asyncio.run(_run_smoke())
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2, sort_keys=True))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
