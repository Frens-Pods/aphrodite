from __future__ import annotations

from pathlib import Path

from aphrodite.modules import image_gen, skillopt
from aphrodite.modules.acp_relay import AcpRelay, RelayConfig, configure_relay, handle as acp_handle, reset_relay


def _assert_unknown_payload(data: dict, action: str) -> list[str]:
    assert data["ok"] is False
    assert data["error"] == f"unknown action: {action}"
    assert data["supported_actions"]
    assert data["supported_actions"] == sorted(data["supported_actions"])
    assert data["examples"]
    return data["supported_actions"]


def _assert_okish(data: dict) -> None:
    assert data.get("ok") is not False or data.get("handled") is True


def test_image_gen_unknown_action_lists_real_dispatch_actions():
    unknown = image_gen.handle("bogus", [], {})
    supported = _assert_unknown_payload(unknown, "bogus")
    assert supported == ["aspect_ratios", "models", "sizes", "status"]
    assert "aphrodite dispatch-test image_gen:v1:status" in unknown["examples"]
    assert "POST /image/generate" in unknown["examples"]

    for action in supported:
        _assert_okish(image_gen.handle(action, [], {}))


def test_skillopt_unknown_action_lists_real_dispatch_actions(monkeypatch, tmp_path):
    monkeypatch.setenv("APHRODITE_SKILLOPT_DATA_ROOT", str(tmp_path / "skillopt"))
    run = skillopt.create_run(
        {
            "run_id": "skillopt-module-action-run",
            "skill_name": "module-action",
            "best_skill_md": "# Module action test\n",
        }
    )
    assert run["ok"] is True
    run_id = run["run_id"]
    run_dir = Path(run["run_dir"])
    (run_dir / "logs.txt").write_text("ready\n")
    evaluation = skillopt.evaluate_run(run_id, {"baseline_score": 1.0, "candidate_score": 1.2})
    assert evaluation["ok"] is True
    created_eval = skillopt.create_eval({"eval_id": "module-action-eval", "min_delta": 0.1})
    assert created_eval["ok"] is True
    eval_id = created_eval["eval_id"]

    unknown = skillopt.handle("bogus", [], {})
    supported = _assert_unknown_payload(unknown, "bogus")
    assert supported == [
        "details",
        "diff",
        "evaluation",
        "get_eval",
        "get_run",
        "list_evals",
        "list_runs",
        "logs",
        "status",
    ]

    payloads = {
        "details": [run_id],
        "diff": [run_id],
        "evaluation": [run_id],
        "get_eval": [eval_id],
        "get_run": [run_id],
        "list_evals": [],
        "list_runs": [],
        "logs": [run_id],
        "status": [],
    }
    for action in supported:
        _assert_okish(skillopt.handle(action, payloads[action], {}))


def test_acp_relay_unknown_action_lists_real_dispatch_actions(tmp_path):
    relay = AcpRelay(RelayConfig(cwd=str(tmp_path), db_path=str(tmp_path / "acp.sqlite3")))
    configure_relay(relay)
    try:
        conversation_id = relay.create_conversation(title="module action test")["id"]
        unknown = acp_handle("turn", [conversation_id, "hello"], {})
        supported = _assert_unknown_payload(unknown, "turn")
        assert supported == ["get", "health", "list", "readiness", "status"]
        assert "aphrodite dispatch-test acp_relay:v1:status" in unknown["examples"]
        assert "POST /acp/conversations/{id}/turns" in unknown["examples"]

        payloads = {
            "get": [conversation_id],
            "health": [],
            "list": [],
            "readiness": [],
            "status": [],
        }
        for action in supported:
            _assert_okish(acp_handle(action, payloads[action], {}))
    finally:
        reset_relay()
