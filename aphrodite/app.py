from __future__ import annotations

import json
import os
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse

from . import __version__
from .config import load_config
from .discord.intake import handle_interaction_payload
from .discord.signature import verify_discord_signature
from .router import DispatchRouter
from .readiness import http_runtime_observability, mcp_readiness, production_endpoint_preflight, service_readiness
from .modules.acp_relay import router as acp_relay_router


def health_payload() -> dict[str, Any]:
    cfg = load_config()
    return {
        "ok": True,
        "service": "aphrodite",
        "version": __version__,
        "policy": cfg.no_core_policy,
        "modules": list(cfg.modules),
    }


def build_router() -> DispatchRouter:
    router = DispatchRouter()
    for system in load_config().modules:
        if system == "image_gen":
            from .modules.image_gen import handle as handle_image_gen

            router.register(system, handle_image_gen)
        elif system == "skillopt":
            from .modules.skillopt import handle as handle_skillopt

            router.register(system, handle_skillopt)
        elif system == "acp_relay":
            from .modules.acp_relay import handle as handle_acp_relay

            router.register(system, handle_acp_relay)
        else:
            router.register(system, _placeholder_handler(system))
    return router


def _placeholder_handler(system: str):
    def handle(action: str, payload: list[str], context: dict[str, Any]) -> dict[str, Any]:
        return {
            "handled": False,
            "system": system,
            "action": action,
            "payload": payload,
            "message": "module adapter not implemented yet",
        }

    return handle


def create_app():
    app = FastAPI(title="Aphrodite", version=__version__)
    router = build_router()

    @app.get("/health")
    def health():
        return health_payload()

    @app.get("/status")
    def status():
        data = health_payload()
        data["registered_systems"] = router.systems
        data["mcp"] = mcp_readiness()
        data["service_readiness"] = service_readiness()
        data["http_observability"] = http_runtime_observability()
        data["production_endpoint_preflight"] = production_endpoint_preflight()
        return data

    @app.post("/dispatch/{custom_id}")
    def dispatch(custom_id: str):
        return router.dispatch(custom_id, context={"source": "http"})

    @app.post("/image/generate")
    def image_generate(payload: dict[str, Any]):
        from .modules.image_gen import generate_image

        return generate_image(payload)

    @app.post("/skillopt/runs")
    def skillopt_create_run(payload: dict[str, Any]):
        from .modules.skillopt import create_run

        return create_run(payload)

    @app.post("/skillopt/runs/train")
    def skillopt_train_run(payload: dict[str, Any]):
        from .modules.skillopt import train_run

        return train_run(payload)

    @app.get("/skillopt/ui", response_class=HTMLResponse)
    def skillopt_ui():
        from .modules.skillopt import review_html

        return review_html()

    @app.post("/skillopt/evals")
    def skillopt_create_eval(payload: dict[str, Any]):
        from .modules.skillopt import create_eval

        return create_eval(payload)

    @app.get("/skillopt/evals")
    def skillopt_list_evals():
        from .modules.skillopt import list_evals

        return list_evals()

    @app.get("/skillopt/evals/{eval_id}")
    def skillopt_get_eval(eval_id: str):
        from .modules.skillopt import get_eval

        return get_eval(eval_id)

    @app.get("/skillopt/runs")
    def skillopt_list_runs():
        from .modules.skillopt import list_runs

        return list_runs()

    @app.get("/skillopt/runs/{run_id}")
    def skillopt_get_run(run_id: str):
        from .modules.skillopt import get_run

        return get_run(run_id)

    @app.get("/skillopt/runs/{run_id}/diff")
    def skillopt_get_run_diff(run_id: str):
        from .modules.skillopt import get_diff

        return get_diff(run_id)

    @app.get("/skillopt/runs/{run_id}/review", response_class=HTMLResponse)
    def skillopt_get_run_review(run_id: str):
        from .modules.skillopt import review_html

        return review_html(run_id)

    @app.get("/skillopt/runs/{run_id}/files/{filename}")
    def skillopt_get_run_file(run_id: str, filename: str):
        from .modules.skillopt import get_file

        return get_file(run_id, filename)

    @app.post("/skillopt/runs/{run_id}/evaluate")
    def skillopt_evaluate_run(run_id: str, payload: dict[str, Any]):
        from .modules.skillopt import evaluate_run

        return evaluate_run(run_id, payload)

    @app.get("/skillopt/runs/{run_id}/evaluation")
    def skillopt_get_evaluation(run_id: str):
        from .modules.skillopt import get_evaluation

        return get_evaluation(run_id)

    @app.post("/skillopt/runs/{run_id}/bundle")
    def skillopt_export_bundle(run_id: str):
        from .modules.skillopt import export_bundle

        return export_bundle(run_id)

    @app.post("/skillopt/runs/{run_id}/import")
    def skillopt_import_run(run_id: str, payload: dict[str, Any]):
        from .modules.skillopt import import_candidate

        return import_candidate(run_id, payload)

    @app.post("/discord/interactions/dry-run")
    def discord_interactions_dry_run(payload: dict[str, Any]):
        return handle_interaction_payload(payload, router)

    @app.post("/discord/interactions")
    async def discord_interactions(
        request: Request,
        x_signature_ed25519: str = Header(default="", alias="X-Signature-Ed25519"),
        x_signature_timestamp: str = Header(default="", alias="X-Signature-Timestamp"),
    ):
        public_key = str(os.environ.get("APHRODITE_DISCORD_PUBLIC_KEY") or "").strip()
        if not public_key:
            raise HTTPException(status_code=503, detail="Discord public key is not configured")
        body = await request.body()
        if not verify_discord_signature(
            public_key,
            x_signature_ed25519,
            x_signature_timestamp,
            body,
        ):
            raise HTTPException(status_code=401, detail="Invalid Discord interaction signature")
        try:
            payload = json.loads(body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON payload")
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid JSON payload")
        return handle_interaction_payload(payload, router)

    app.include_router(acp_relay_router)
    return app
