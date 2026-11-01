#!/usr/bin/env python3
"""
scripts/smoke.py - End-to-end smoke test for FloorPlan3D.
Runs the complete mock pipeline, exercises REST endpoints,
and validates output scene.json against the formal schema contract.

Zero emoji policy enforced.
"""

import io
import json
import os
import sys
import time
from pathlib import Path

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def run_smoke_tests():
    print("Starting FloorPlan3D smoke test suite (mock mode)...")

    # 1. Initialize validator
    schema_path = Path(__file__).resolve().parent.parent / "schemas" / "scene.schema.json"
    try:
        from jsonschema import Draft202012Validator
        with open(schema_path, "r", encoding="utf-8") as f:
            schema = json.load(f)
        validator = Draft202012Validator(schema)
        def validate_scene(scene):
            errors = list(validator.iter_errors(scene))
            return errors[0].message if errors else None
        print("[PASS] Schema loaded and Draft202012Validator initialized.")
    except ImportError:
        from app import validate_scene_contract
        def validate_scene(scene):
            try:
                validate_scene_contract(scene)
                return None
            except Exception as e:
                return str(e)
        print("[PASS] Schema loaded and app validate_scene_contract initialized.")

    # 2. Initialize Flask test client in mock mode
    os.environ["MOCK_AI"] = "1"
    os.environ["MOCK_MODE"] = "1"
    from app import app, SAMPLE_IMG_PATH

    client = app.test_client()

    # 3. Test /api/config/status
    config_resp = client.get("/api/config/status")
    if config_resp.status_code != 200:
        print(f"[FAIL] /api/config/status returned HTTP {config_resp.status_code}")
        return False
    config_data = config_resp.get_json()
    assert "live_ready" in config_data, "Missing live_ready in config status"
    assert "mock_mode" in config_data, "Missing mock_mode in config status"
    print("[PASS] /api/config/status is healthy.")

    # 4. Test /api/sample
    sample_resp = client.get("/api/sample")
    if sample_resp.status_code != 200:
        print(f"[FAIL] /api/sample returned HTTP {sample_resp.status_code}")
        return False
    sample_data = sample_resp.get_json()
    err = validate_scene(sample_data["scene"])
    if err:
        print(f"[FAIL] Sample scene failed schema validation: {err}")
        return False
    print("[PASS] Single-story demo scene matches scene.schema.json contract.")

    # 5. Test /api/sample/two-story
    two_story_resp = client.get("/api/sample/two-story")
    if two_story_resp.status_code != 200:
        print(f"[FAIL] /api/sample/two-story returned HTTP {two_story_resp.status_code}")
        return False
    two_story_data = two_story_resp.get_json()
    err = validate_scene(two_story_data["scene"])
    if err:
        print(f"[FAIL] Two-story scene failed schema validation: {err}")
        return False
    print("[PASS] Two-story demo scene matches scene.schema.json contract.")

    # 6. Test full upload and processing pipeline
    with open(SAMPLE_IMG_PATH, "rb") as f:
        img_bytes = f.read()

    upload_resp = client.post(
        "/api/upload",
        data={"file": (io.BytesIO(img_bytes), "smoke_test_plan.png"), "calibrateScale": "false"},
        content_type="multipart/form-data"
    )
    if upload_resp.status_code != 202:
        print(f"[FAIL] /api/upload returned HTTP {upload_resp.status_code}")
        return False
    job_id = upload_resp.get_json().get("job_id")
    if not job_id:
        print("[FAIL] /api/upload did not return a job_id.")
        return False
    print(f"[PASS] Upload accepted. Job ID: {job_id}")

    # Poll status
    deadline = time.monotonic() + 30
    final_status = None
    while time.monotonic() < deadline:
        status_resp = client.get(f"/api/status/{job_id}")
        if status_resp.status_code != 200:
            print(f"[FAIL] /api/status returned HTTP {status_resp.status_code}")
            return False
        status_data = status_resp.get_json()
        if status_data.get("status") in ("complete", "failed"):
            final_status = status_data
            break
        time.sleep(0.1)

    if not final_status or final_status.get("status") != "complete":
        print(f"[FAIL] Job did not complete successfully: {final_status}")
        return False
    print("[PASS] Asynchronous pipeline processing completed.")

    # Fetch scene
    scene_resp = client.get(f"/api/scene/{job_id}")
    if scene_resp.status_code != 200:
        print(f"[FAIL] /api/scene returned HTTP {scene_resp.status_code}")
        return False
    scene_payload = scene_resp.get_json()
    pipeline_scene = scene_payload.get("scene")
    err = validate_scene(pipeline_scene)
    if err:
        print(f"[FAIL] Pipeline output failed schema validation: {err}")
        return False
    print("[PASS] Pipeline scene output matches scene.schema.json contract.")

    # Verify provenance and warnings
    meta = pipeline_scene.get("meta", {})
    assert "warnings" in meta and len(meta["warnings"]) > 0, "Missing warnings in scene meta"
    assert meta.get("processingMode") == "MOCK", f"Unexpected mode: {meta.get('processingMode')}"
    print("[PASS] Honest provenance tracking confirmed (MOCK mode).")

    print("\nALL SMOKE TESTS PASSED.")
    return True


if __name__ == "__main__":
    success = run_smoke_tests()
    sys.exit(0 if success else 1)
