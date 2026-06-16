from __future__ import annotations

import base64
from types import SimpleNamespace

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


def test_image_generate_route_accepts_reference_images_and_saves_profile_cache(monkeypatch, tmp_path):
    fake_client = FakeClient()
    monkeypatch.setattr(image_gen, "_build_codex_client", lambda: fake_client)
    ref = tmp_path / "ref.png"
    ref.write_bytes(base64.b64decode(PNG_B64))
    profile = tmp_path / "profile"
    profile.mkdir()

    client = TestClient(create_app())
    response = client.post(
        "/image/generate",
        json={
            "prompt": "make a small icon from this reference",
            "aspect_ratio": "square",
            "reference_images": [str(ref)],
            "profile_home": str(profile),
            "model": "gpt-image-2-low",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["provider"] == "aphrodite-openai-codex"
    assert data["model"] == "gpt-image-2-low"
    assert data["image"].startswith(str(profile / "image_cache"))
    assert (profile / "image_cache").exists()
    content = fake_client.responses.kwargs["input"][0]["content"]
    assert content[0] == {"type": "input_text", "text": "make a small icon from this reference"}
    assert content[1]["type"] == "input_image"
    assert content[1]["image_url"].startswith("data:image/png;base64,")


def test_image_generate_route_rejects_missing_reference(monkeypatch, tmp_path):
    monkeypatch.setattr(image_gen, "_build_codex_client", lambda: FakeClient())
    client = TestClient(create_app())
    response = client.post(
        "/image/generate",
        json={"prompt": "x", "image_paths": [str(tmp_path / "missing.png")]},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert data["error_type"] == "invalid_reference_image"


def test_image_generate_route_accepts_multiple_url_references(monkeypatch, tmp_path):
    fake_client = FakeClient()
    monkeypatch.setattr(image_gen, "_build_codex_client", lambda: fake_client)
    profile = tmp_path / "profile"
    profile.mkdir()

    client = TestClient(create_app())
    response = client.post(
        "/image/generate",
        json={
            "prompt": "combine these sources",
            "image_paths": ["https://example.com/a.png", "data:image/png;base64,abc"],
            "profile_home": str(profile),
        },
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    content = fake_client.responses.kwargs["input"][0]["content"]
    assert [item["image_url"] for item in content[1:]] == ["https://example.com/a.png", "data:image/png;base64,abc"]


def test_image_generate_route_rejects_too_many_references_without_client(monkeypatch):
    def fail_build():  # pragma: no cover - should not be called
        raise AssertionError("client should not be built when validation fails")

    monkeypatch.setattr(image_gen, "_build_codex_client", fail_build)
    client = TestClient(create_app())
    refs = [f"https://example.com/{idx}.png" for idx in range(9)]
    response = client.post("/image/generate", json={"prompt": "draw it", "image_paths": refs})

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert data["error_type"] == "invalid_reference_image"
    assert "at most 8" in data["error"]


def test_image_generate_route_rejects_non_image_local_file(monkeypatch, tmp_path):
    monkeypatch.setattr(image_gen, "_build_codex_client", lambda: FakeClient())
    note = tmp_path / "note.txt"
    note.write_text("not an image")
    client = TestClient(create_app())
    response = client.post("/image/generate", json={"prompt": "draw it", "image_paths": [str(note)]})

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert data["error_type"] == "invalid_reference_image"
    assert "not an image" in data["error"]
