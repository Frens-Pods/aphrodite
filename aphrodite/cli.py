from __future__ import annotations

import argparse
import json
import sys

from .app import build_router, health_payload
from .doctor import doctor_payload
from .preflight import preflight_payload
from .readiness import production_endpoint_preflight


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aphrodite", description="Aphrodite sidecar backend CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("health")
    sub.add_parser("doctor")
    sub.add_parser("endpoint-preflight")
    preflight = sub.add_parser("preflight")
    preflight.add_argument("--production", action="store_true")
    dispatch = sub.add_parser("dispatch-test")
    dispatch.add_argument("custom_id")
    args = parser.parse_args(argv)

    if args.command == "health":
        print(json.dumps(health_payload(), indent=2))
        return 0
    if args.command == "doctor":
        payload = doctor_payload()
        print(json.dumps(payload, indent=2))
        return 0 if payload["ok"] else 1
    if args.command == "endpoint-preflight":
        payload = production_endpoint_preflight()
        print(json.dumps(payload, indent=2))
        return 0 if payload["ok"] else 1
    if args.command == "preflight":
        payload = preflight_payload(production=bool(getattr(args, "production", False)))
        print(json.dumps(payload, indent=2))
        return 0 if payload["ok"] else 1
    if args.command == "dispatch-test":
        router = build_router()
        print(json.dumps(router.dispatch(args.custom_id, context={"source": "cli"}), indent=2))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
