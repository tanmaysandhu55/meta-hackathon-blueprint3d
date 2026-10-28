import io
import time

import pytest
from PIL import Image
from werkzeug.datastructures import FileStorage

import app as app_module


def png_bytes(size=(160, 120)):
    image = Image.new("RGB", size, "white")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


@pytest.fixture
def client():
    app_module.app.config.update(TESTING=True)
    app_module.JOBS.clear()
    app_module.UPLOAD_REQUESTS.clear()
    app_module.QUESTION_REQUESTS.clear()
    return app_module.app.test_client()


def test_image_validation_accepts_png_and_rejects_non_image():
    valid = FileStorage(stream=io.BytesIO(png_bytes()), filename="plan.png")
    normalized, size, filename = app_module._validate_image(valid)
    assert size == (160, 120)
    assert filename == "plan.png"
    assert normalized.startswith(b"\x89PNG")

    invalid = FileStorage(stream=io.BytesIO(b"not an image"), filename="plan.png")
    with pytest.raises(ValueError, match="not a valid supported image"):
        app_module._validate_image(invalid)


def test_image_validation_rejects_unsupported_format():
    image = Image.new("RGB", (50, 50), "white")
    output = io.BytesIO()
    image.save(output, format="BMP")
    upload = FileStorage(stream=io.BytesIO(output.getvalue()), filename="plan.bmp")

    with pytest.raises(ValueError, match="PNG, JPG, or WebP"):
        app_module._validate_image(upload)


def test_upload_job_completes_using_mock_pipeline_without_keys(client, monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "1")

    response = client.post(
        "/api/upload",
        data={"file": (io.BytesIO(png_bytes()), "unrelated-upload.png"), "calibrateScale": "false"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 202
    job_id = response.get_json()["job_id"]

    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        status = client.get(f"/api/status/{job_id}").get_json()
        if status["status"] != "processing":
            break
        time.sleep(0.05)
    assert status["status"] == "complete", status

    result = client.get(f"/api/scene/{job_id}")
    assert result.status_code == 200
    payload = result.get_json()
    assert payload["scene"]["meta"]["processingMode"] == "MOCK"
    assert any("MOCK MODE" in warning for warning in payload["scene"]["meta"]["warnings"])
    assert payload["scene"]["meta"]["source"] == "sample_plan_mock.png"


def test_upload_job_completes_locally_without_meta_key(client, monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "0")
    monkeypatch.setenv("META_API_KEY", "")
    monkeypatch.setenv("MUSE_MODEL", "")
    sample = app_module.SAMPLE_IMG_PATH
    with open(sample, "rb") as source:
        response = client.post("/api/upload", data={"file": (io.BytesIO(source.read()), "sample.png"), "calibrateScale": "false"}, content_type="multipart/form-data")
    assert response.status_code == 202
    job_id = response.get_json()["job_id"]
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        status = client.get(f"/api/status/{job_id}").get_json()
        if status["status"] != "processing":
            break
        time.sleep(0.05)
    assert status["status"] == "complete", status
    scene = client.get(f"/api/scene/{job_id}").get_json()["scene"]
    assert scene["meta"]["segmentation"] == "opencv-heuristic"
    assert scene["rooms"]
    assert any("Muse room labeling is not configured" in warning for warning in scene["meta"]["warnings"])


def test_mock_health_is_ready_but_never_claims_live_processing(client, monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "1")

    health = client.get("/api/health").get_json()
    page = client.get("/").get_data(as_text=True)

    assert health["pipeline_ready"] is True
    assert health["live_processing_ready"] is False
    assert health["processing_mode"] == "MOCK"
    assert "MOCK MODE" in page
    assert "Run Mock Pipeline" in page
    assert "Muse labels on" not in page


@pytest.mark.parametrize("route, expected_floors", [
    ("/api/sample", 1),
    ("/api/sample/two-story", 2),
])
def test_prepared_demos_load_without_provider_keys(client, monkeypatch, route, expected_floors):
    monkeypatch.setenv("META_API_KEY", "")
    monkeypatch.setenv("SAM_MODEL", "")
    monkeypatch.setenv("MUSE_MODEL", "")

    response = client.get(route)

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["demoMode"] is True
    assert payload["scene"]["meta"]["processingMode"] == "DEMO"
    assert len(payload["scene"]["meta"].get("levels", [{"level": 0}])) == expected_floors


def test_health_reports_local_fallback_without_meta_key(client, monkeypatch):
    monkeypatch.setenv("META_API_KEY", "")
    monkeypatch.setenv("SAM_MODEL", "")
    monkeypatch.setenv("MUSE_MODEL", "")

    health = client.get("/api/health").get_json()

    assert health["segmentation_ready"] is True
    assert health["sam_ready"] is False
    assert health["labeling_ready"] is False
    assert health["live_processing_ready"] is False
    assert health["segmentation_mode"] == "opencv-heuristic"


def test_media_endpoints_are_disabled_cleanly_without_meta_key(client, monkeypatch):
    monkeypatch.setenv("META_API_KEY", "")
    monkeypatch.setenv("MUSE_IMAGE_MODEL", "muse-image-1.0")
    monkeypatch.setenv("MUSE_VOICE_MODEL", "muse-voice-transcribe-1.0")

    image = client.post("/api/generate-floorplan", json={"prompt": "A small two-bedroom apartment"})
    audio = client.post("/api/transcribe")

    assert image.status_code == 503
    assert audio.status_code == 503
    assert "META_API_KEY" in image.get_json()["error"]
    assert "META_API_KEY" in audio.get_json()["error"]


def test_media_endpoints_use_safe_mocked_provider_results(client, monkeypatch):
    monkeypatch.setenv("META_API_KEY", "test-only")
    monkeypatch.setattr(app_module, "image_generation_ready", lambda: True)
    monkeypatch.setattr(app_module, "voice_transcription_ready", lambda: True)
    monkeypatch.setattr(app_module, "generate_floorplan", lambda _prompt: b"\x89PNG\r\n\x1a\n")
    monkeypatch.setattr(app_module, "transcribe_audio", lambda _audio, _filename: "Where is the computer lab?")

    image = client.post("/api/generate-floorplan", json={"prompt": "A small two-bedroom apartment"})
    audio = client.post("/api/transcribe", data={"audio": (io.BytesIO(b"test"), "question.wav")}, content_type="multipart/form-data")

    assert image.status_code == 200
    assert image.get_json()["imageUrl"].startswith("data:image/png;base64,")
    assert audio.status_code == 200
    assert audio.get_json()["transcript"] == "Where is the computer lab?"


def test_scene_question_uses_explicit_offline_lookup(client, monkeypatch):
    scene = app_module.get_sample_scene_json()
    response = client.post("/api/scene/ask", json={"question": "Where is the Computer Lab?", "scene": scene})

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["provider"] == "Offline scene lookup (no model call)"
    assert "Computer Lab" in payload["answer"]
    assert "m²" in payload["answer"]


def test_scene_question_rejects_missing_or_invalid_inputs(client):
    empty = client.post("/api/scene/ask", json={"question": "", "scene": {}})
    assert empty.status_code == 400

    no_scene = client.post("/api/scene/ask", json={"question": "How many rooms?"})
    assert no_scene.status_code == 400


def test_scene_question_rate_limit_returns_429(client, monkeypatch):
    monkeypatch.setattr(app_module, "QUESTION_RATE_LIMIT", 1)
    scene = app_module.get_sample_scene_json()
    payload = {"question": "How many rooms?", "scene": scene}

    assert client.post("/api/scene/ask", json=payload).status_code == 200
    limited = client.post("/api/scene/ask", json=payload)
    assert limited.status_code == 429
    assert limited.headers.get("Retry-After")


def test_upload_returns_429_when_concurrency_cap_is_reached(client, monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "1")
    app_module.JOBS["already-running-1"] = {"status": "processing"}
    app_module.JOBS["already-running-2"] = {"status": "processing"}

    response = client.post(
        "/api/upload",
        data={"file": (io.BytesIO(png_bytes()), "plan.png")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 429
    assert response.headers.get("Retry-After")


def test_upload_rate_limit_returns_429(client, monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "1")
    monkeypatch.setattr(app_module, "UPLOAD_RATE_LIMIT", 1)
    app_module._rate_limit_upload("127.0.0.1")

    response = client.post(
        "/api/upload",
        data={"file": (io.BytesIO(png_bytes()), "plan.png")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 429
    assert response.headers.get("Retry-After")
