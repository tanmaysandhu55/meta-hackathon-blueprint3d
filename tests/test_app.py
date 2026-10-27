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


def test_provider_image_downscales_long_side_and_masks_restore_size():
    source = png_bytes(size=(2400, 1200))
    smaller, size = app_module._downscale_for_provider(source)
    assert max(size) == 2048
    assert size == (2048, 1024)
    mask = __import__("numpy").ones((size[1], size[0]), dtype="uint8")
    restored = app_module._restore_mask_sizes([mask], size, (2400, 1200))
    assert restored[0].shape == (1200, 2400)


def test_upload_job_completes_using_mock_pipeline_without_keys(client, monkeypatch):
    monkeypatch.setenv("MOCK_SAM", "1")
    monkeypatch.delenv("REPLAY_SAM_RESPONSES", raising=False)
    monkeypatch.delenv("BASETEN_API_KEY", raising=False)
    monkeypatch.delenv("BASETEN_MODEL_ID", raising=False)
    monkeypatch.delenv("BASETEN_SAM_URL", raising=False)

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
    assert payload["scene"]["meta"]["source"] == "mock_sample_floorplan.png"


def test_mock_health_is_ready_but_never_claims_live_processing(client, monkeypatch):
    monkeypatch.setenv("MOCK_SAM", "1")

    health = client.get("/api/health").get_json()
    page = client.get("/").get_data(as_text=True)

    assert health["pipeline_ready"] is True
    assert health["live_processing_ready"] is False
    assert health["processing_mode"] == "MOCK"
    assert "Mock pipeline ready" in page
    assert "Run Mock Pipeline" in page
    assert "Live processing configured" not in page


def test_scene_question_uses_explicit_offline_lookup_without_modal(client, monkeypatch):
    monkeypatch.setattr(app_module, "get_modal_config", lambda: {"is_configured": False})
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


def test_upload_returns_429_when_concurrency_cap_is_reached(client, monkeypatch):
    monkeypatch.setenv("MOCK_SAM", "1")
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
    monkeypatch.setenv("MOCK_SAM", "1")
    monkeypatch.setattr(app_module, "UPLOAD_RATE_LIMIT", 1)
    app_module._rate_limit_upload("127.0.0.1")

    response = client.post(
        "/api/upload",
        data={"file": (io.BytesIO(png_bytes()), "plan.png")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 429
    assert response.headers.get("Retry-After")
