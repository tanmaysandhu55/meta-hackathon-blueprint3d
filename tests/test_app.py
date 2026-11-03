import io
import time
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image
from werkzeug.datastructures import FileStorage

import app as app_module


def png_bytes(size=(160, 120)):
    image = Image.new("RGB", size, "white")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def editable_scene(*, scale_source="user", needs_review=False, one_room=False):
    rooms = [{
        "id": "r1", "type": "classroom", "label": "Room A", "confidence": 0.9,
        "polygon": [[0, 0], [5, 0], [5, 5], [0, 5]], "holes": [],
        "centroid": [2.5, 2.5], "area_m2": 25.0, "floorIndex": 0, "level": 0,
    }]
    if not one_room:
        rooms.append({
            "id": "r2", "type": "lab", "label": "Room B", "confidence": 0.9,
            "polygon": [[5, 0], [10, 0], [10, 5], [5, 5]], "holes": [],
            "centroid": [7.5, 2.5], "area_m2": 25.0, "floorIndex": 0, "level": 0,
        })
    return {
        "meta": {
            "source": "editable-plan.png", "imageSize": [500, 500], "metersPerPixel": 0.02,
            "wallHeight": 3.0, "wallThickness": 0.2, "floorHeight": 3.2,
            "levelCount": 1, "scaleSource": scale_source, "scaleConfidence": 0.9,
            "needsReview": needs_review, "reviewIssues": ["Scale failed sanity checks; manual calibration is required."],
            "openingCounts": {"doorsDetected": 0, "doorsKept": 0, "windowsDetected": 0, "windowsKept": 0, "dropped": 0},
            "levels": [{"level": 0, "floorIndex": 0, "name": "Ground Floor", "elevation": 0.0,
                        "metersPerPixel": 0.02, "scaleSource": scale_source, "scaleConfidence": 0.9,
                        "planOffset": [0.0, 0.0]}],
            "warnings": ["Scale failed sanity checks; manual calibration is required.", "Keep this unrelated warning."],
        },
        "rooms": rooms, "walls": [], "doors": [], "windows": [],
    }


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


def test_scale_door_width_candidates_come_from_selected_masks():
    mask = np.zeros((100, 160), dtype=np.uint8)
    for x in (10, 60, 110):
        cv2.rectangle(mask, (x, 20), (x + 29, 24), 255, thickness=-1)
    widths = app_module._door_mask_widths_px([mask])
    assert len(widths) == 3
    assert all(28 <= width <= 31 for width in widths)


def test_review_gate_flags_a_single_region_covering_most_of_the_plan():
    scene = editable_scene(needs_review=False, one_room=True)
    issues = app_module._apply_scene_sanity_gate(scene)
    assert scene["meta"]["needsReview"] is True
    assert any("covers 100%" in issue and "missed room dividers" in issue for issue in issues)


def test_geometry_rebuild_rechecks_review_gate_and_clears_stale_scale_issue(client):
    scene = editable_scene(scale_source="user", needs_review=True)
    response = client.post("/api/scene/rebuild-geometry", json={"scene": scene})

    assert response.status_code == 200
    result = response.get_json()["scene"]
    assert result["walls"]
    assert result["meta"]["needsReview"] is False
    assert result["meta"]["reviewIssues"] == []
    assert "Scale failed sanity checks; manual calibration is required." not in result["meta"]["warnings"]
    assert "Keep this unrelated warning." in result["meta"]["warnings"]


def test_upload_job_completes_using_mock_pipeline_without_keys(client, monkeypatch):
    monkeypatch.setenv("MOCK_AI", "1")
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
    monkeypatch.setenv("MOCK_AI", "0")
    monkeypatch.setenv("MOCK_MODE", "0")
    monkeypatch.setenv("META_API_KEY", "")
    monkeypatch.setenv("BASETEN_API_KEY", "")
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


def test_upload_recovers_generated_plan_with_wide_door_gaps(client, monkeypatch):
    monkeypatch.setenv("MOCK_AI", "0")
    monkeypatch.setenv("MOCK_MODE", "0")
    monkeypatch.setenv("MODEL_API_KEY", "")
    monkeypatch.setenv("META_API_KEY", "")
    monkeypatch.setenv("BASETEN_API_KEY", "")
    monkeypatch.setenv("SAM_MODEL", "sam-3.1")

    path = Path(__file__).parents[1] / "samples" / "generated_meta_floorplan.png"
    response = client.post(
        "/api/upload",
        data={"file": (io.BytesIO(path.read_bytes()), path.name), "calibrateScale": "false"},
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
    scene = result.get_json()["scene"]
    assert len(scene["rooms"]) >= 4
    assert any("wider door gaps" in warning for warning in scene["meta"]["warnings"])


def test_unusable_sam_room_masks_fall_back_to_local_rooms(monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "")
    monkeypatch.setenv("META_API_KEY", "")
    monkeypatch.setenv("BASETEN_API_KEY", "")
    monkeypatch.setattr(app_module, "query_sam_concept", lambda *_args, **_kwargs: [])

    path = Path(__file__).parents[1] / "samples" / "generated_meta_floorplan.png"
    raw = path.read_bytes()
    with Image.open(io.BytesIO(raw)) as image:
        image_size = image.size
    result = app_module._process_story_slice(
        raw,
        image_size,
        0.02,
        3.0,
        0.2,
        False,
        lambda *_args: None,
        time.monotonic() + 30,
        True,
        "LOCAL",
        "data:image/png;base64,",
        filename=path.name,
    )

    assert len(result["rooms"]) >= 4
    assert result["segmentation_backend"] == "opencv-fallback"
    assert any("no matching 'room' regions" in warning for warning in result["warnings"])


def test_mock_health_is_ready_but_never_claims_live_processing(client, monkeypatch):
    monkeypatch.setenv("MOCK_AI", "1")
    monkeypatch.setenv("MOCK_MODE", "1")
    monkeypatch.setenv("BASETEN_API_KEY", "")
    monkeypatch.setenv("META_API_KEY", "")

    health = client.get("/api/health").get_json()
    page = client.get("/").get_data(as_text=True)

    assert health["pipeline_ready"] is True
    assert health["live_processing_ready"] is False
    assert health["processing_mode"] == "MOCK"
    assert "MOCK MODE" in page
    assert "Run Mock Pipeline" in page
    assert "Muse labels on" not in page


def test_processing_mode_defaults_to_safe_prepared_demo(monkeypatch):
    monkeypatch.delenv("MOCK_AI", raising=False)
    monkeypatch.delenv("MOCK_MODE", raising=False)
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("META_API_KEY", raising=False)
    monkeypatch.delenv("BASETEN_API_KEY", raising=False)
    assert app_module._processing_mode() == "MOCK"


def test_mock_ai_flag_controls_processing_mode(monkeypatch):
    monkeypatch.setenv("MOCK_AI", "1")
    monkeypatch.setenv("MOCK_MODE", "0")
    monkeypatch.setenv("MODEL_API_KEY", "test-only")
    assert app_module._processing_mode() == "MOCK"

    monkeypatch.setenv("MOCK_AI", "0")
    assert app_module._processing_mode() == "LIVE"


@pytest.mark.parametrize("route, expected_floors", [
    ("/api/sample", 1),
    ("/api/sample/two-story", 2),
])
def test_prepared_demos_load_without_provider_keys(client, monkeypatch, route, expected_floors):
    monkeypatch.setenv("META_API_KEY", "")
    monkeypatch.setenv("BASETEN_API_KEY", "")
    monkeypatch.setenv("SAM_MODEL", "")
    monkeypatch.setenv("BASETEN_MUSE_MODEL", "")

    response = client.get(route)

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["demoMode"] is True
    assert payload["scene"]["meta"]["processingMode"] == "DEMO"
    assert len(payload["scene"]["meta"].get("levels", [{"level": 0}])) == expected_floors


def test_scene_job_serializes_numpy_geometry_values(client):
    scene = app_module.get_sample_scene_json()
    scene["doors"][0]["pixel_width"] = np.int32(44)
    app_module.JOBS["numpy-scene"] = {
        "status": "complete",
        "result": {"scene": scene},
    }

    response = client.get("/api/scene/numpy-scene")

    assert response.status_code == 200
    assert response.get_json()["scene"]["doors"][0]["pixel_width"] == 44
    assert type(response.get_json()["scene"]["doors"][0]["pixel_width"]) is int


def test_health_reports_local_fallback_without_meta_key(client, monkeypatch):
    monkeypatch.setenv("MOCK_AI", "0")
    monkeypatch.setenv("MOCK_MODE", "0")
    monkeypatch.setenv("META_API_KEY", "")
    monkeypatch.setenv("BASETEN_API_KEY", "")
    monkeypatch.setenv("SAM_MODEL", "")
    monkeypatch.setenv("BASETEN_MUSE_MODEL", "")

    health = client.get("/api/health").get_json()

    assert health["segmentation_ready"] is True
    assert health["sam_ready"] is False
    assert health["labeling_ready"] is False
    assert health["live_processing_ready"] is False
    assert health["segmentation_mode"] == "opencv-heuristic"


def test_media_endpoints_are_disabled_cleanly_without_meta_key(client, monkeypatch):
    monkeypatch.setenv("META_API_KEY", "")
    monkeypatch.setenv("BASETEN_API_KEY", "")
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
    monkeypatch.setenv("BASETEN_API_KEY", "")
    scene = app_module.get_sample_scene_json()
    response = client.post("/api/scene/ask", json={"question": "Where is the Computer Lab?", "scene": scene})

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["provider"] == "Offline scene lookup (Baseten returned no usable answer)"
    assert "Computer Lab" in payload["answer"]
    assert "m²" in payload["answer"]


def test_scene_question_uses_baseten_when_configured(client, monkeypatch):
    monkeypatch.setenv("BASETEN_API_KEY", "test-only")
    monkeypatch.setattr(app_module, "answer_scene_question", lambda question, facts: "AI: the lab is on Level 1.")
    scene = app_module.get_sample_scene_json()

    response = client.post("/api/scene/ask", json={"question": "Where is the lab?", "scene": scene})

    assert response.status_code == 200
    assert response.get_json()["provider"] == "Baseten Muse Spark Open (scene-grounded)"
    assert "Level 1" in response.get_json()["answer"]


def test_scene_question_turns_named_route_into_current_scene_route(client, monkeypatch):
    monkeypatch.setenv("BASETEN_API_KEY", "")
    scene = app_module.get_sample_scene_json()
    response = client.post("/api/scene/ask", json={
        "question": "Route from East Lobby to Computer Lab",
        "scene": scene,
    })

    assert response.status_code == 200
    result = response.get_json()
    assert result["route"]["startLabel"] == "East Lobby"
    assert result["route"]["endLabel"] == "Computer Lab"
    assert result["provider"] == "Scene route planner (current geometry)"


def test_scene_insights_work_without_a_provider_key(client, monkeypatch):
    monkeypatch.setenv("BASETEN_API_KEY", "")
    scene = app_module.get_two_story_sample_scene_json()

    review = client.post("/api/scene/insight", json={"kind": "review", "scene": scene})
    summary = client.post("/api/scene/insight", json={"kind": "summary", "scene": scene})

    assert review.status_code == 200
    assert summary.status_code == 200
    assert review.get_json()["provider"] == "Offline scene analysis (Baseten returned no usable answer)"
    assert "Structural review" in review.get_json()["answer"]
    assert "2 floor(s)" in summary.get_json()["answer"]
    assert review.get_json()["review"]["room_count"] == len(scene["rooms"])


def test_scene_insight_uses_grounded_model_when_configured(client, monkeypatch):
    monkeypatch.setenv("BASETEN_API_KEY", "test-only")
    monkeypatch.setattr(app_module, "answer_scene_question", lambda _question, _facts: "Grounded scene review.")
    scene = app_module.get_sample_scene_json()

    response = client.post("/api/scene/insight", json={"kind": "review", "scene": scene})

    assert response.status_code == 200
    assert response.get_json()["provider"] == "Baseten Muse Spark Open (scene-grounded)"
    assert response.get_json()["answer"] == "Grounded scene review."


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
    monkeypatch.setenv("MOCK_AI", "1")
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
    monkeypatch.setenv("MOCK_AI", "1")
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


def test_config_status_endpoint_returns_json_and_never_leaks_key(client):
    response = client.get("/api/config/status")
    assert response.status_code == 200
    data = response.get_json()
    assert isinstance(data, dict)
    assert "live_ready" in data
    assert "mock_mode" in data
    assert "key_configured" in data
    assert "sam_model" in data
    assert "muse_model" in data
    assert "MODEL_API_KEY" not in data
    assert "api_key" not in data
    text = response.get_data(as_text=True)
    assert "sk-" not in text
