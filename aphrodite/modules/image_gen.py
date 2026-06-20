from __future__ import annotations

import base64
import datetime as _dt
import mimetypes
import os
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

API_MODEL = "gpt-image-2"
DEFAULT_MODEL = "gpt-image-2-medium"
CODEX_CHAT_MODEL = "gpt-5.4"
CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"
CODEX_INSTRUCTIONS = (
    "You are an assistant that must fulfill image generation requests by using "
    "the image_generation tool when provided."
)

MODELS: dict[str, dict[str, Any]] = {
    "gpt-image-2-low": {"quality": "low", "display": "GPT Image 2 (Low)"},
    "gpt-image-2-medium": {"quality": "medium", "display": "GPT Image 2 (Medium)"},
    "gpt-image-2-high": {"quality": "high", "display": "GPT Image 2 (High)"},
}

SIZES = {
    "landscape": "1536x1024",
    "square": "1024x1024",
    "portrait": "1024x1536",
}

_GENERATION_LOCK = threading.Lock()


def _normalize_aspect_ratio(value: Any) -> str:
    candidate = str(value or "landscape").strip().lower()
    return candidate if candidate in SIZES else "landscape"


def _normalize_reference_images(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        raise ValueError("reference_images/image_paths must be a string or list of strings")
    refs = [str(item).strip() for item in value if str(item).strip()]
    if len(refs) > 8:
        raise ValueError("at most 8 reference images are allowed")
    return refs


def _reference_image_to_url(reference: str) -> str:
    lower = reference.lower()
    if lower.startswith(("http://", "https://", "data:image/")):
        return reference

    path = Path(reference).expanduser()
    if not path.exists() or not path.is_file():
        raise ValueError(f"Reference image does not exist or is not a file: {reference}")

    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    if not mime.startswith("image/"):
        raise ValueError(f"Reference file is not an image: {reference}")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


@contextmanager
def _temporary_hermes_home(profile_home: str | None):
    if not profile_home:
        yield
        return
    old = os.environ.get("HERMES_HOME")
    os.environ["HERMES_HOME"] = str(Path(profile_home).expanduser())
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("HERMES_HOME", None)
        else:
            os.environ["HERMES_HOME"] = old


def _read_profile_image_config(profile_home: str | None) -> dict[str, Any]:
    if not profile_home:
        return {}
    path = Path(profile_home).expanduser() / "config.yaml"
    if not path.exists():
        return {}
    try:
        import yaml

        data = yaml.safe_load(path.read_text()) or {}
    except Exception:
        return {}
    section = data.get("image_gen") if isinstance(data, dict) else None
    return section if isinstance(section, dict) else {}


def _resolve_model(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    explicit = str(payload.get("model") or "").strip()
    if explicit in MODELS:
        return explicit, MODELS[explicit]

    env_model = os.environ.get("APHRODITE_IMAGE_GEN_MODEL") or os.environ.get("OPENAI_IMAGE_MODEL")
    if env_model in MODELS:
        return env_model, MODELS[env_model]

    cfg = _read_profile_image_config(payload.get("profile_home"))
    sub = cfg.get("openai-codex") if isinstance(cfg.get("openai-codex"), dict) else {}
    for candidate in (sub.get("model") if isinstance(sub, dict) else None, cfg.get("model")):
        if isinstance(candidate, str) and candidate in MODELS:
            return candidate, MODELS[candidate]

    return DEFAULT_MODEL, MODELS[DEFAULT_MODEL]


def _read_codex_access_token() -> str | None:
    try:
        from agent.auxiliary_client import _read_codex_access_token as reader

        token = reader()
    except Exception:
        return None
    if isinstance(token, str) and token.strip():
        return token.strip()
    return None


def _build_codex_client() -> Any | None:
    token = _read_codex_access_token()
    if not token:
        return None
    try:
        import openai
        from agent.auxiliary_client import _codex_cloudflare_headers

        return openai.OpenAI(
            api_key=token,
            base_url=CODEX_BASE_URL,
            default_headers=_codex_cloudflare_headers(token),
        )
    except Exception:
        return None


def _collect_image_b64(
    client: Any,
    *,
    prompt: str,
    size: str,
    quality: str,
    image_urls: list[str],
) -> str | None:
    image_b64: str | None = None
    content: list[dict[str, Any]] = [{"type": "input_text", "text": prompt}]
    for image_url in image_urls:
        content.append({"type": "input_image", "image_url": image_url})

    with client.responses.stream(
        model=CODEX_CHAT_MODEL,
        store=False,
        instructions=CODEX_INSTRUCTIONS,
        input=[{"type": "message", "role": "user", "content": content}],
        tools=[{
            "type": "image_generation",
            "model": API_MODEL,
            "size": size,
            "quality": quality,
            "output_format": "png",
            "background": "opaque",
            "partial_images": 1,
        }],
        tool_choice={
            "type": "allowed_tools",
            "mode": "required",
            "tools": [{"type": "image_generation"}],
        },
    ) as stream:
        for event in stream:
            event_type = getattr(event, "type", "")
            if event_type == "response.output_item.done":
                item = getattr(event, "item", None)
                if getattr(item, "type", None) == "image_generation_call":
                    result = getattr(item, "result", None)
                    if isinstance(result, str) and result:
                        image_b64 = result
            elif event_type == "response.image_generation_call.partial_image":
                partial = getattr(event, "partial_image_b64", None)
                if isinstance(partial, str) and partial:
                    image_b64 = partial
        final = stream.get_final_response()

    for item in getattr(final, "output", None) or []:
        if getattr(item, "type", None) == "image_generation_call":
            result = getattr(item, "result", None)
            if isinstance(result, str) and result:
                image_b64 = result
    return image_b64


def _cache_dir(profile_home: str | None) -> Path:
    root = Path(profile_home).expanduser() if profile_home else Path.home() / ".hermes"
    path = root / "image_cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _save_png(b64_data: str, *, profile_home: str | None, model: str) -> Path:
    raw = base64.b64decode(b64_data)
    ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    short = uuid.uuid4().hex[:8]
    path = _cache_dir(profile_home) / f"aphrodite_openai_codex_{model}_{ts}_{short}.png"
    path.write_bytes(raw)
    return path


def generate_image(payload: dict[str, Any], *, client: Any | None = None) -> dict[str, Any]:
    """Generate an image through Aphrodite's no-core backend boundary."""
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        return {"ok": False, "error_type": "invalid_argument", "error": "prompt is required"}

    profile_home = str(payload.get("profile_home") or "").strip() or None
    aspect = _normalize_aspect_ratio(payload.get("aspect_ratio"))
    try:
        reference_images = _normalize_reference_images(
            payload.get("image_paths") if payload.get("image_paths") is not None else payload.get("reference_images")
        )
        image_urls = [_reference_image_to_url(ref) for ref in reference_images]
    except ValueError as exc:
        return {"ok": False, "error_type": "invalid_reference_image", "error": str(exc)}

    model, meta = _resolve_model({**payload, "profile_home": profile_home})
    size = SIZES[aspect]

    with _GENERATION_LOCK, _temporary_hermes_home(profile_home):
        active_client = client or _build_codex_client()
        if active_client is None:
            return {
                "ok": False,
                "error_type": "auth_required",
                "error": "Could not initialize Codex image client; sign in with Hermes Codex/OpenAI OAuth for the selected profile.",
                "provider": "aphrodite-openai-codex",
                "model": model,
            }
        try:
            b64 = _collect_image_b64(
                active_client,
                prompt=prompt,
                size=size,
                quality=str(meta["quality"]),
                image_urls=image_urls,
            )
        except Exception as exc:
            return {
                "ok": False,
                "error_type": "api_error",
                "error": f"Codex image generation failed: {exc}",
                "provider": "aphrodite-openai-codex",
                "model": model,
            }

        if not b64:
            return {
                "ok": False,
                "error_type": "empty_response",
                "error": "Codex response contained no image_generation_call result",
                "provider": "aphrodite-openai-codex",
                "model": model,
            }
        try:
            saved = _save_png(b64, profile_home=profile_home, model=model)
        except Exception as exc:
            return {
                "ok": False,
                "error_type": "io_error",
                "error": f"Could not save image to cache: {exc}",
                "provider": "aphrodite-openai-codex",
                "model": model,
            }

    return {
        "ok": True,
        "provider": "aphrodite-openai-codex",
        "model": model,
        "prompt": prompt,
        "aspect_ratio": aspect,
        "size": size,
        "quality": meta["quality"],
        "reference_images": reference_images,
        "image": str(saved),
        "profile_home": profile_home,
    }


def handle(action: str, payload: list[str], context: dict[str, Any]) -> dict[str, Any]:
    if action == "status":
        return {
            "ok": True,
            "module": "image_gen",
            "provider": "aphrodite-openai-codex",
            "default_model": DEFAULT_MODEL,
        }
    if action == "models":
        return {
            "ok": True,
            "module": "image_gen",
            "provider": "aphrodite-openai-codex",
            "models": list(MODELS),
            "default_model": DEFAULT_MODEL,
        }
    if action in {"sizes", "aspect_ratios"}:
        return {
            "ok": True,
            "module": "image_gen",
            "sizes": list(SIZES),
            "aspect_ratios": list(SIZES),
        }
    return {
        "ok": False,
        "error": f"unknown action: {action}",
        "supported_actions": ["aspect_ratios", "models", "sizes", "status"],
        "examples": [
            "aphrodite dispatch-test image_gen:v1:status",
            "aphrodite dispatch-test image_gen:v1:models",
            "POST /image/generate",
        ],
    }
