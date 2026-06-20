from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

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
        "aphrodite_image_gen_status",
        "aphrodite_image_gen_models",
        "aphrodite_image_gen_sizes",
        "aphrodite_acp_relay_readiness",
        "aphrodite_acp_relay_list_conversations",
        "aphrodite_acp_relay_get_conversation",
        "aphrodite_adapters",
        "aphrodite_dispatch",
    ]


def test_mcp_wrapper_tool_names_include_discovery_dispatch():
    assert "aphrodite_adapters" in mcp_server.TOOL_NAMES
    assert "aphrodite_dispatch" in mcp_server.TOOL_NAMES


def test_mcp_dispatch_wrapper_routes_builtin_custom_id(monkeypatch):
    monkeypatch.delenv("APHRODITE_MODULES", raising=False)
    monkeypatch.delenv("APHRODITE_TRUSTED_ADAPTERS", raising=False)

    dispatched = mcp_server.aphrodite_dispatch("image_gen:v1:status")

    json.dumps(dispatched)
    assert dispatched["ok"] is True
    assert dispatched["system"] == "image_gen"
    assert isinstance(dispatched["result"], dict)


def test_mcp_adapters_wrapper_lists_native_trio(monkeypatch):
    monkeypatch.delenv("APHRODITE_TRUSTED_ADAPTERS", raising=False)

    inventory = mcp_server.aphrodite_adapters()

    json.dumps(inventory)
    assert inventory["ok"] is True
    assert isinstance(inventory["errors"], dict)
    for name in {"image_gen", "skillopt", "acp_relay"}:
        assert name in inventory["adapters"]
        assert inventory["adapters"][name]["source"] == "builtin"
        assert isinstance(inventory["adapters"][name]["has_router"], bool)


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


def test_mcp_image_gen_wrappers_return_static_metadata():
    status = mcp_server.aphrodite_image_gen_status()
    json.dumps(status)
    assert status["handled"] is True
    assert status["default_model"]

    models = mcp_server.aphrodite_image_gen_models()
    json.dumps(models)
    assert models["handled"] is True
    assert isinstance(models["models"], list)
    assert models["models"]
    assert models["default_model"]

    sizes = mcp_server.aphrodite_image_gen_sizes()
    json.dumps(sizes)
    assert sizes["handled"] is True
    assert isinstance(sizes["sizes"], list)
    assert sizes["sizes"]
    assert isinstance(sizes["aspect_ratios"], list)
    assert sizes["aspect_ratios"]


def test_mcp_acp_relay_wrappers_return_read_only_store_metadata(monkeypatch, tmp_path):
    db_path = tmp_path / "acp.sqlite3"
    monkeypatch.setenv("APHRODITE_ACP_DB", str(db_path))
    relay = mcp_server.acp_relay.AcpRelay(
        mcp_server.acp_relay.RelayConfig(cwd=str(tmp_path), db_path=str(db_path))
    )
    mcp_server.acp_relay.configure_relay(relay)
    try:
        readiness = mcp_server.aphrodite_acp_relay_readiness()
        assert readiness["ok"] is True
        json.dumps(readiness)
        assert readiness["readiness"]["db_path"] == str(db_path)

        listed = mcp_server.aphrodite_acp_relay_list_conversations()
        assert listed["ok"] is True
        assert listed["conversations"] == []
        json.dumps(listed)

        missing = mcp_server.aphrodite_acp_relay_get_conversation("does-not-exist")
        assert missing["ok"] is False
        assert missing["error_type"] == "not_found"
        json.dumps(missing)

        invalid = mcp_server.aphrodite_acp_relay_get_conversation("")
        assert invalid["ok"] is False
        assert invalid["error_type"] == "invalid_argument"
        json.dumps(invalid)

        created = relay.create_conversation(title="mcp wrapper")
        found = mcp_server.aphrodite_acp_relay_get_conversation(created["id"])
        assert found["ok"] is True
        assert found["conversation"]["id"] == created["id"]
        assert found["conversation"]["title"] == "mcp wrapper"
        json.dumps(found)
    finally:
        mcp_server.acp_relay.reset_relay()

@pytest.mark.skipif(mcp_server.FastMCP is None, reason="mcp Python SDK is not installed")
def test_mcp_fastmcp_registers_expected_tools(skillopt_data):
    async def collect_names():
        server = mcp_server.build_server()
        tools = await server.list_tools()
        return sorted(tool.name for tool in tools)

    assert asyncio.run(collect_names()) == sorted(mcp_server.TOOL_NAMES)
