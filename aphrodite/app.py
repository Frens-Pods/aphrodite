from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import os
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from . import __version__
from .config import load_config
from .discord.intake import handle_interaction_payload
from .discord.signature import verify_discord_signature
from .router import DispatchRouter
from .readiness import http_runtime_observability, mcp_readiness, production_endpoint_preflight, service_readiness
from .modules import discover_adapter_specs, discover_adapters
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
    adapters = discover_adapters()
    for system in load_config().modules:
        handler = adapters.get(system)
        router.register(system, handler if handler is not None else _placeholder_handler(system))
    return router


def _placeholder_handler(system: str):
    def handle(action: str, payload: list[str], context: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": False,
            "error": f"module adapter '{system}' is configured but not installed",
            "hint": f"pip install -e <your-module-dir> into this environment, then set APHRODITE_MODULES to include '{system}' (run: aphrodite modules)",
        }

    return handle


def _require_adapter_auth(authorization: str | None = Header(default=None)):
    token = os.environ.get("APHRODITE_ADAPTER_AUTH_TOKEN", "").strip()
    if not token:
        raise HTTPException(
            status_code=503,
            detail="adapter auth required but APHRODITE_ADAPTER_AUTH_TOKEN is not configured",
        )
    if not authorization or not hmac.compare_digest(authorization, f"Bearer {token}"):
        raise HTTPException(status_code=401, detail="invalid or missing adapter bearer token")


def _build_adapter_lifespan(specs):
    @contextlib.asynccontextmanager
    async def _lifespan(app):
        started: list[str] = []
        errors: dict[str, Any] = {}
        timeout = float(os.environ.get("APHRODITE_ADAPTER_LIFESPAN_TIMEOUT", "30") or 30)
        async with contextlib.AsyncExitStack() as stack:
            for system, spec in specs.items():
                if spec.lifespan is None:
                    continue
                try:
                    await asyncio.wait_for(stack.enter_async_context(spec.lifespan(app)), timeout=timeout)
                    started.append(system)
                except Exception as exc:  # isolate: one adapter's startup failure must not crash the app
                    errors[system] = {"name": system, "phase": "startup", "error": repr(exc)}
            app.state.adapter_lifespan_started = started
            app.state.adapter_lifespan_errors = errors
            yield
        # AsyncExitStack guarantees shutdown of successfully-started adapters

    return _lifespan


def create_app():
    specs, adapter_errors = discover_adapter_specs()
    app = FastAPI(title="Aphrodite", version=__version__, lifespan=_build_adapter_lifespan(specs))
    cfg = load_config()
    if cfg.cors_origins:
        if "*" in cfg.cors_origins:
            allow_origins = ["*"]
            allow_credentials = False
        else:
            allow_origins = list(cfg.cors_origins)
            allow_credentials = True
        app.add_middleware(
            CORSMiddleware,
            allow_origins=allow_origins,
            allow_credentials=allow_credentials,
            allow_methods=["*"],
            allow_headers=["*"],
        )
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

    quarantined: dict[str, Any] = {}
    for system, spec in specs.items():
        if spec.router is None:
            continue
        try:
            deps = [Depends(_require_adapter_auth)] if spec.requires_auth else None
            app.include_router(spec.router, prefix=f"/{system}", dependencies=deps)
        except Exception as exc:  # mount-time quarantine: one bad adapter must not crash create_app
            quarantined[system] = {"name": system, "phase": "mount", "error": repr(exc)}
    app.state.adapter_errors = adapter_errors
    app.state.adapter_quarantine = quarantined

    app.include_router(acp_relay_router)
    return app
