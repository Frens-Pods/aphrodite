from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import os
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .config import AphroditeConfig, load_config
from .discord.intake import handle_interaction_payload
from .discord.signature import verify_discord_signature
from .router import DispatchRouter
from .readiness import http_runtime_observability, mcp_readiness, production_endpoint_preflight, service_readiness
from .modules import discover_adapter_specs, discover_adapters
from .modules.acp_relay import router as acp_relay_router


def health_payload(cfg: AphroditeConfig | None = None) -> dict[str, Any]:
    cfg = cfg if cfg is not None else load_config()
    return {
        "ok": True,
        "service": "aphrodite",
        "version": __version__,
        "policy": cfg.no_core_policy,
        "modules": list(cfg.modules),
    }


def build_router(modules: tuple[str, ...] | None = None) -> DispatchRouter:
    router = DispatchRouter()
    adapters = discover_adapters()
    for system in (modules if modules is not None else load_config().modules):
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


def create_app(config: AphroditeConfig | None = None, *, root_path: str | None = None):
    specs, adapter_errors = discover_adapter_specs()
    app = FastAPI(title="Aphrodite", version=__version__, lifespan=_build_adapter_lifespan(specs), root_path=root_path or "")
    cfg = config if config is not None else load_config()
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
    router = build_router(cfg.modules)

    @app.get("/health")
    def health():
        return health_payload(cfg)

    @app.get("/status")
    def status():
        data = health_payload(cfg)
        data["registered_systems"] = router.systems
        data["mcp"] = mcp_readiness()
        data["service_readiness"] = service_readiness()
        data["http_observability"] = http_runtime_observability()
        data["production_endpoint_preflight"] = production_endpoint_preflight()
        data["adapters"] = {
            "load_errors": getattr(app.state, "adapter_errors", {}) or {},
            "quarantined": getattr(app.state, "adapter_quarantine", {}) or {},
            "lifespan_errors": getattr(app.state, "adapter_lifespan_errors", {}) or {},
            "lifespan_started": getattr(app.state, "adapter_lifespan_started", []) or [],
        }
        return data

    @app.post("/dispatch/{custom_id}")
    def dispatch(custom_id: str):
        return router.dispatch(custom_id, context={"source": "http"})

    @app.post("/image/generate")
    def image_generate(payload: dict[str, Any]):
        from .modules.image_gen import generate_image

        return generate_image(payload)


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
