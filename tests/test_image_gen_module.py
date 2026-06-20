from __future__ import annotations

import base64
from types import SimpleNamespace

import pytest

from fastapi.testclient import TestClient

from aphrodite.app import create_app
from aphrodite.modules import image_gen


PNG_B64 = base64.b64encode(
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
).decode("ascii")


class FakeStream:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def __iter__(self):
        item = SimpleNamespace(type="image_generation_call", result=PNG_B64)
        yield SimpleNamespace(type="response.output_item.done", item=item)

    def get_final_response(self):
        return SimpleNamespace(output=[])


class FakeResponses:
    def __init__(self):
        self.kwargs = None

    def stream(self, **kwargs):
        self.kwargs = kwargs
        return FakeStream()


class FakeClient:
    def __init__(self):
        self.responses = FakeResponses()


def test_generate_image_accepts_reference_images_and_saves_profile_cache(tmp_path):
    fake_client = FakeClient()
    ref = tmp_path / "ref.png"
    ref.write_bytes(base64.b64decode(PNG_B64))
    profile = tmp_path / "profile"
    profile.mkdir()

    data = image_gen.generate_image(
        {
            "prompt": "make a small icon from this reference",
            "aspect_ratio": "square",
            "reference_images": [str(ref)],
            "profile_home": str(profile),
            "model": "gpt-image-2-low",
        },
        client=fake_client,
    )

    assert data["ok"] is True
    assert data["provider"] == "aphrodite-openai-codex"
    assert data["model"] == "gpt-image-2-low"
    assert data["image"].startswith(str(profile / "image_cache"))
    assert (profile / "image_cache").exists()
    content = fake_client.responses.kwargs["input"][0]["content"]
    assert content[0] == {"type": "input_text", "text": "make a small icon from this reference"}
    assert content[1]["type"] == "input_image"
    assert content[1]["image_url"].startswith("data:image/png;base64,")


def test_image_generate_route_rejects_missing_reference(tmp_path):
    client = TestClient(create_app())
    response = client.post(
        "/image/generate",
        json={"prompt": "x", "image_paths": [str(tmp_path / "missing.png")]},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert data["error_type"] == "invalid_reference_image"


def test_generate_image_accepts_multiple_url_references(tmp_path):
    fake_client = FakeClient()
    profile = tmp_path / "profile"
    profile.mkdir()

    data = image_gen.generate_image(
        {
            "prompt": "combine these sources",
            "image_paths": ["https://example.com/a.png", "data:image/png;base64,abc"],
            "profile_home": str(profile),
        },
        client=fake_client,
    )

    assert data["ok"] is True
    content = fake_client.responses.kwargs["input"][0]["content"]
    assert [item["image_url"] for item in content[1:]] == ["https://example.com/a.png", "data:image/png;base64,abc"]


def test_image_generate_route_rejects_too_many_references_without_client():
    client = TestClient(create_app())
    refs = [f"https://example.com/{idx}.png" for idx in range(9)]
    response = client.post("/image/generate", json={"prompt": "draw it", "image_paths": refs})

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert data["error_type"] == "invalid_reference_image"
    assert "at most 8" in data["error"]


def test_image_generate_route_rejects_non_image_local_file(tmp_path):
    note = tmp_path / "note.txt"
    note.write_text("not an image")
    client = TestClient(create_app())
    response = client.post("/image/generate", json={"prompt": "draw it", "image_paths": [str(note)]})

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert data["error_type"] == "invalid_reference_image"
    assert "not an image" in data["error"]


def test_dispatch_status_includes_provider_and_default_model():
    data = image_gen.handle("status", [], {})

    assert data["ok"] is True
    assert data["module"] == "image_gen"
    assert data["provider"] == "aphrodite-openai-codex"
    assert data["default_model"] == image_gen.DEFAULT_MODEL


def test_dispatch_models_lists_supported_keys_and_default():
    data = image_gen.handle("models", [], {})

    assert data["ok"] is True
    assert data["module"] == "image_gen"
    assert data["models"] == list(image_gen.MODELS)
    assert data["default_model"] == image_gen.DEFAULT_MODEL
    assert data["default_model"] in data["models"]


def test_dispatch_sizes_lists_supported_size_keys():
    data = image_gen.handle("sizes", [], {})

    assert data["ok"] is True
    assert data["module"] == "image_gen"
    assert data["sizes"] == list(image_gen.SIZES)
    assert data["aspect_ratios"] == list(image_gen.SIZES)


def test_dispatch_aspect_ratios_alias_lists_supported_size_keys():
    data = image_gen.handle("aspect_ratios", [], {})

    assert data["ok"] is True
    assert data["module"] == "image_gen"
    assert data["sizes"] == list(image_gen.SIZES)
    assert data["aspect_ratios"] == list(image_gen.SIZES)


def test_dispatch_unsupported_action_remains_unhandled():
    data = image_gen.handle("generate", ["ignored"], {"ignored": True})

    assert data["ok"] is False
    assert data["error"] == "unknown action: generate"
    assert data["supported_actions"] == ["aspect_ratios", "models", "sizes", "status"]
    assert "aphrodite dispatch-test image_gen:v1:status" in data["examples"]
    assert "POST /image/generate" in data["examples"]


def test_dispatch_router_wraps_new_read_only_actions():
    from aphrodite.router import DispatchRouter

    router = DispatchRouter()
    router.register("image_gen", image_gen.handle)

    result = router.dispatch("image_gen:v1:models", context={"source": "test"})

    assert result["ok"] is True
    assert result["system"] == "image_gen"
    assert result["version"] == "v1"
    assert result["action"] == "models"
    assert result["payload"] == []
    assert result["result"]["ok"] is True
    assert result["result"]["models"] == list(image_gen.MODELS)


def test_normalize_reference_images_accepts_string_sequences_and_rejects_bad_shapes():
    assert image_gen._normalize_reference_images(None) == []
    assert image_gen._normalize_reference_images(" https://example.com/ref.png ") == ["https://example.com/ref.png"]
    assert image_gen._normalize_reference_images(["a", " ", "b"]) == ["a", "b"]
    assert image_gen._normalize_reference_images(("a", "b")) == ["a", "b"]

    with pytest.raises(ValueError, match="string or list"):
        image_gen._normalize_reference_images({"bad": "shape"})
    with pytest.raises(ValueError, match="at most 8"):
        image_gen._normalize_reference_images([f"https://example.com/{idx}.png" for idx in range(9)])


def test_reference_image_to_url_preserves_urls_and_encodes_local_images(tmp_path):
    assert image_gen._reference_image_to_url("https://example.com/ref.png") == "https://example.com/ref.png"
    assert image_gen._reference_image_to_url("data:image/png;base64,abc") == "data:image/png;base64,abc"

    ref = tmp_path / "ref.png"
    ref.write_bytes(base64.b64decode(PNG_B64))
    url = image_gen._reference_image_to_url(str(ref))

    assert url.startswith("data:image/png;base64,")
    assert url.split(",", 1)[1]


def test_reference_image_to_url_rejects_missing_and_non_image_files(tmp_path):
    with pytest.raises(ValueError, match="does not exist"):
        image_gen._reference_image_to_url(str(tmp_path / "missing.png"))

    note = tmp_path / "note.txt"
    note.write_text("not an image")
    with pytest.raises(ValueError, match="not an image"):
        image_gen._reference_image_to_url(str(note))


def test_resolve_model_prefers_explicit_then_env_then_profile_config(monkeypatch, tmp_path):
    model_keys = list(image_gen.MODELS)
    explicit, env_model, cfg_model = model_keys[:3]
    monkeypatch.delenv("APHRODITE_IMAGE_GEN_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_IMAGE_MODEL", raising=False)

    assert image_gen._resolve_model({"model": explicit}) == (explicit, image_gen.MODELS[explicit])

    monkeypatch.setenv("APHRODITE_IMAGE_GEN_MODEL", env_model)
    assert image_gen._resolve_model({"model": "not-supported"}) == (env_model, image_gen.MODELS[env_model])

    monkeypatch.delenv("APHRODITE_IMAGE_GEN_MODEL")
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "config.yaml").write_text(f"image_gen:\n  openai-codex:\n    model: {cfg_model}\n")
    assert image_gen._resolve_model({"profile_home": str(profile)}) == (cfg_model, image_gen.MODELS[cfg_model])


def test_resolve_model_falls_back_to_default_for_unsupported_values(monkeypatch, tmp_path):
    monkeypatch.setenv("APHRODITE_IMAGE_GEN_MODEL", "not-supported")
    monkeypatch.setenv("OPENAI_IMAGE_MODEL", "also-not-supported")
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "config.yaml").write_text("image_gen:\n  model: not-supported\n")

    assert image_gen._resolve_model({"model": "missing", "profile_home": str(profile)}) == (
        image_gen.DEFAULT_MODEL,
        image_gen.MODELS[image_gen.DEFAULT_MODEL],
    )


def test_generate_image_returns_auth_required_when_only_plain_openai_api_key_is_available(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-used")
    profile = tmp_path / "profile"
    profile.mkdir()

    data = image_gen.generate_image({"prompt": "draw a tiny icon", "profile_home": str(profile)})

    assert data["ok"] is False
    assert data["error_type"] == "auth_required"
    assert data["provider"] == "aphrodite-openai-codex"
    assert data["model"] in image_gen.MODELS
    assert not (profile / "image_cache").exists()
