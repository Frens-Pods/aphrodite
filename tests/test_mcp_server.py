from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from aphrodite import mcp_server


SOURCE_SKILL = """---
name: old-qa
description: "Old skill."
---

# Old

- Be vague.
"""


@pytest.fixture()
def skillopt_data(monkeypatch, tmp_path):
    data_root = tmp_path / "skillopt-data"
    monkeypatch.setenv("APHRODITE_SKILLOPT_DATA_ROOT", str(data_root))
    return data_root


def test_mcp_wrapper_tool_names_are_stable():
    assert mcp_server.TOOL_NAMES == [
        "aphrodite_skillopt_list_runs",
        "aphrodite_skillopt_get_run",
        "aphrodite_skillopt_train_run",
        "aphrodite_skillopt_create_eval",
        "aphrodite_skillopt_list_evals",
        "aphrodite_skillopt_get_eval",
        "aphrodite_skillopt_evaluate_run",
        "aphrodite_skillopt_get_evaluation",
        "aphrodite_skillopt_import_candidate",
        "aphrodite_skillopt_export_bundle",
    ]


def test_mcp_wrappers_reuse_skillopt_module_for_train_eval_bundle(skillopt_data, tmp_path):
    source = tmp_path / "source.md"
    source.write_text(SOURCE_SKILL)
    fake_train = Path(__file__).parent / "fixtures" / "fake_skillopt_train.py"
    output_dir = skillopt_data / "runs" / "mcp-train-test" / "work"

    listed = mcp_server.aphrodite_skillopt_list_runs()
    assert listed == {"ok": True, "runs": [], "count": 0}

    trained = mcp_server.aphrodite_skillopt_train_run(
        {
            "run_id": "mcp-train-test",
            "skill_name": "mcp-trained",
            "source_skill_path": str(source),
            "command": [sys.executable, str(fake_train), str(output_dir)],
            "timeout_seconds": 30,
        }
    )
    assert trained["ok"] is True
    assert trained["status"] == "candidate_ready"
    assert trained["candidate_ready"] is True

    detail = mcp_server.aphrodite_skillopt_get_run("mcp-train-test")
    assert detail["ok"] is True
    assert "candidate_SKILL.md" in detail["files"]
    assert "logs.txt" in detail["files"]

    created_eval = mcp_server.aphrodite_skillopt_create_eval(
        {"eval_id": "mcp-eval", "skill_family": "qa", "min_delta": 0.1}
    )
    assert created_eval["ok"] is True
    assert mcp_server.aphrodite_skillopt_list_evals()["count"] == 1
    assert mcp_server.aphrodite_skillopt_get_eval("mcp-eval")["manifest"]["min_delta"] == 0.1

    evaluation = mcp_server.aphrodite_skillopt_evaluate_run("mcp-train-test", {"eval_id": "mcp-eval"})
    assert evaluation["ok"] is True
    assert evaluation["status"] == "recommended"
    assert mcp_server.aphrodite_skillopt_get_evaluation("mcp-train-test")["ok"] is True

    bundle = mcp_server.aphrodite_skillopt_export_bundle("mcp-train-test")
    assert bundle["ok"] is True
    assert Path(bundle["bundle"]).exists()


def test_mcp_import_wrapper_preserves_explicit_replace_boundary(skillopt_data, tmp_path):
    run = mcp_server.aphrodite_skillopt_train_run(
        {
            "run_id": "mcp-import-test",
            "skill_name": "mcp-imported",
            "command": [
                sys.executable,
                str(Path(__file__).parent / "fixtures" / "fake_skillopt_train.py"),
                str(skillopt_data / "runs" / "mcp-import-test" / "work"),
            ],
            "timeout_seconds": 30,
        }
    )
    assert run["ok"] is True
    profile = tmp_path / "profile"
    imported = mcp_server.aphrodite_skillopt_import_candidate(
        "mcp-import-test", {"profile_home": str(profile)}
    )
    assert imported["ok"] is True
    refused = mcp_server.aphrodite_skillopt_import_candidate(
        "mcp-import-test", {"profile_home": str(profile)}
    )
    assert refused["ok"] is False
    assert refused["error_type"] == "exists"


@pytest.mark.skipif(mcp_server.FastMCP is None, reason="mcp Python SDK is not installed")
def test_mcp_fastmcp_registers_expected_tools(skillopt_data):
    async def collect_names():
        server = mcp_server.build_server()
        tools = await server.list_tools()
        return sorted(tool.name for tool in tools)

    assert asyncio.run(collect_names()) == sorted(mcp_server.TOOL_NAMES)
