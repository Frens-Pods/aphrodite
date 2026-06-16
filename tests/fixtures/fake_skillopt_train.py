from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: fake_skillopt_train.py OUTPUT_DIR", file=sys.stderr)
        return 2
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    (out / "best_skill.md").write_text("# Fake Optimized Skill\n\n- Use the trained candidate.\n")
    (out / "scores.json").write_text(json.dumps({"baseline_score": 0.5, "candidate_score": 0.75}, indent=2) + "\n")
    (out / "history.json").write_text(json.dumps({"steps": [{"score": 0.75}]}, indent=2) + "\n")
    print("fake skillopt complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
