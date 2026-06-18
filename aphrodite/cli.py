from __future__ import annotations

import argparse
import json
import sys

from .app import build_router, health_payload
from .doctor import doctor_payload
from .preflight import preflight_payload
from .config import load_config
from .inventory import modules_payload
from .readiness import production_endpoint_preflight
from .scaffold import scaffold_module
from .serve import run_server
from .update import maybe_notify_update, update_payload, version_payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aphrodite", description="Aphrodite sidecar backend CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("health")
    sub.add_parser("doctor")
    sub.add_parser("endpoint-preflight")
    sub.add_parser("version")
    update = sub.add_parser("update")
    update.add_argument("--check", action="store_true")
    preflight = sub.add_parser("preflight")
    preflight.add_argument("--production", action="store_true")
    dispatch = sub.add_parser(
        "dispatch-test",
        help="Dispatch one custom-id through the configured router",
        description="Dispatch a custom-id formatted as system:v1:action[:arg...] through the configured router.",
    )
    dispatch.add_argument("custom_id")
    new_module = sub.add_parser(
        "new-module",
        help="Scaffold an adapter package",
        description="Scaffold a ready-to-edit Aphrodite adapter package with entry-point metadata.",
    )
    new_module.add_argument("name")
    new_module.add_argument("--dir", default=".")
    serve = sub.add_parser(
        "serve",
        help="Run the Aphrodite FastAPI server",
        description="Run the Aphrodite FastAPI server with uvicorn.",
    )
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)
    serve.add_argument("--reload", action="store_true")
    sub.add_parser(
        "modules",
        help="List configured and discovered module adapters",
        description="Print Aphrodite module adapter inventory as JSON.",
    )
    args = parser.parse_args(argv)
    maybe_notify_update(args.command)

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
        payload = router.dispatch(args.custom_id, context={"source": "cli"})
        print(json.dumps(payload, indent=2))
        return 0 if payload["ok"] and payload.get("result", {}).get("ok", True) else 1
    if args.command == "version":
        print(json.dumps(version_payload(), indent=2))
        return 0
    if args.command == "update":
        payload = update_payload(check=bool(getattr(args, "check", False)))
        print(json.dumps(payload, indent=2))
        return 0 if payload["ok"] else 1
    if args.command == "serve":
        cfg = load_config()
        host = args.host or cfg.host
        port = args.port or cfg.port
        print(f"Starting Aphrodite on http://{host}:{port} (Ctrl-C to stop)")
        run_server(host, port, args.reload)
        return 0
    if args.command == "modules":
        payload = modules_payload()
        print(json.dumps(payload, indent=2))
        return 0 if payload["ok"] else 1
    if args.command == "new-module":
        payload = scaffold_module(args.name, getattr(args, "dir", "."))
        print(json.dumps(payload, indent=2))
        return 0 if payload["ok"] else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
