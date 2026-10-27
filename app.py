"""FloorPlan3D Flask app and asynchronous image-processing API."""

import base64
import concurrent.futures
import cv2
import io
import json
import logging
import math
import os
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, send_file
from jsonschema import Draft202012Validator
from PIL import Image, UnidentifiedImageError
from werkzeug.utils import secure_filename

from cloud_services import (
    ProviderError,
    ask_modal_muse_spark_about_scene,
    get_modal_config,
    get_baseten_config,
    is_mock_sam_enabled,
    is_sam_replay_enabled,
)
from demo_data import generate_sample_floorplan_image, get_sample_mask_overlays, get_sample_scene_json, get_two_story_sample_scene_json
from geometry_processor import (
    build_walls_from_rooms,
    estimate_meters_per_pixel_from_doors,
    extract_doors,
    extract_windows,
    mask_to_polygons_with_holes,
)
from sam_service import label_rooms, query_sam_concept

load_dotenv()
logger = logging.getLogger(__name__)

app = Flask(__name__, template_folder="templates", static_folder="static")
MAX_IMAGE_BYTES = 10 * 1024 * 1024
app.config["MAX_CONTENT_LENGTH"] = MAX_IMAGE_BYTES + 64 * 1024  # allow multipart form overhead

SAMPLE_IMG_PATH = os.path.join(app.root_path, "samples", "sample_floorplan.png")
if not os.path.exists(SAMPLE_IMG_PATH):
    generate_sample_floorplan_image(SAMPLE_IMG_PATH)
SCENE_SCHEMA_PATH = os.path.join(app.root_path, "schemas", "scene.schema.json")
with open(SCENE_SCHEMA_PATH, "r", encoding="utf-8") as schema_file:
    SCENE_SCHEMA = json.load(schema_file)
Draft202012Validator.check_schema(SCENE_SCHEMA)
SCENE_VALIDATOR = Draft202012Validator(SCENE_SCHEMA)

JOBS = {}
JOBS_LOCK = threading.Lock()
UPLOAD_RATE_LOCK = threading.Lock()
UPLOAD_REQUESTS = defaultdict(deque)
ALLOWED_IMAGE_FORMATS = {"PNG", "JPEG", "WEBP"}
MAX_ACTIVE_JOBS = 2
UPLOAD_RATE_WINDOW_SECONDS = 60
UPLOAD_RATE_LIMIT = 10
PROVIDER_IMAGE_MAX_SIDE = 2048


def _live_sam_ready():
    return is_mock_sam_enabled() or is_sam_replay_enabled() or get_baseten_config()["is_configured"]


def _processing_mode():
    if is_mock_sam_enabled():
        return "MOCK"
    if is_sam_replay_enabled():
        return "REPLAY"
    return "LIVE" if get_baseten_config()["is_configured"] else "OFFLINE"


def _rate_limit_upload(ip_address):
    now = time.monotonic()
    with UPLOAD_RATE_LOCK:
        requests_for_ip = UPLOAD_REQUESTS[ip_address]
        stale_ips = []
        for address, entries in UPLOAD_REQUESTS.items():
            while entries and now - entries[0] >= UPLOAD_RATE_WINDOW_SECONDS:
                entries.popleft()
            if address != ip_address and not entries:
                stale_ips.append(address)
        for address in stale_ips:
            UPLOAD_REQUESTS.pop(address, None)
        if len(requests_for_ip) >= UPLOAD_RATE_LIMIT:
            retry_after = max(1, int(UPLOAD_RATE_WINDOW_SECONDS - (now - requests_for_ip[0])))
            return retry_after
        requests_for_ip.append(now)
        return 0


def _build_scene_facts(scene):
    rooms = []
    for room in scene.get("rooms", [])[:120]:
        polygon = room.get("polygon", [])
        area = 0.0
        if len(polygon) >= 3:
            twice_area = sum(
                point[0] * polygon[(index + 1) % len(polygon)][1]
                - polygon[(index + 1) % len(polygon)][0] * point[1]
                for index, point in enumerate(polygon)
            )
            area = abs(twice_area) / 2
        rooms.append({
            "id": str(room.get("id", ""))[:80],
            "label": str(room.get("label", ""))[:100],
            "type": str(room.get("type", "room"))[:40],
            "floor": int(room.get("floorIndex", room.get("level", 0)) or 0),
            "area_m2": round(area, 2),
        })
    doors = [
        {"id": str(door.get("id", ""))[:80], "connects": [str(room_id)[:80] for room_id in door.get("connects", [])[:8]]}
        for door in scene.get("doors", [])[:180]
    ]
    levels = [
        {"level": int(item.get("floorIndex", item.get("level", 0)) or 0), "name": str(item.get("name", ""))[:80]}
        for item in scene.get("meta", {}).get("levels", [])[:12]
    ]
    return {"levels": levels, "rooms": rooms, "doors": doors}


def _offline_scene_answer(question, facts):
    normalized = " ".join(question.lower().split())
    rooms = facts["rooms"]
    matches = [room for room in rooms if room["label"].lower() in normalized or room["id"].lower() in normalized]
    if matches:
        room = matches[0]
        return (
            f"{room['label'] or room['id']} ({room['id']}) is on Level {room['floor'] + 1}; "
            f"the map estimates its area at {room['area_m2']:.1f} m²."
        )
    if any(term in normalized for term in ("how many room", "room count", "number of room")):
        return f"This map contains {len(rooms)} rooms across {len(facts['levels']) or 1} listed floor(s)."
    if "total area" in normalized or "area of building" in normalized:
        total = sum(room["area_m2"] for room in rooms)
        return f"The mapped rooms total approximately {total:.1f} m². This is an estimate from detected polygons."
    if "door" in normalized and ("how many" in normalized or "count" in normalized):
        return f"The scene contains {len(facts['doors'])} detected doors."
    return "Offline scene lookup can answer room, floor, area, and door-count questions. Configure Modal Muse Spark for open-ended questions."


def _downscale_for_provider(image_bytes):
    """Return PNG bytes reduced to a bounded provider dimension plus its size."""
    with Image.open(io.BytesIO(image_bytes)) as source:
        image = source.convert("RGB")
    width, height = image.size
    longest_side = max(width, height)
    if longest_side <= PROVIDER_IMAGE_MAX_SIDE:
        return image_bytes, (width, height)
    ratio = PROVIDER_IMAGE_MAX_SIDE / longest_side
    size = (max(1, round(width * ratio)), max(1, round(height * ratio)))
    resized = image.resize(size, Image.Resampling.LANCZOS)
    output = io.BytesIO()
    resized.save(output, format="PNG", optimize=True)
    return output.getvalue(), size


def _restore_mask_sizes(masks, from_size, to_size):
    if from_size == to_size:
        return masks
    target_width, target_height = to_size
    return [cv2.resize(mask, (target_width, target_height), interpolation=cv2.INTER_NEAREST) for mask in masks]


def validate_scene_contract(scene):
    errors = sorted(SCENE_VALIDATOR.iter_errors(scene), key=lambda error: list(error.absolute_path))
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.absolute_path) or "scene"
        raise RuntimeError(f"Scene contract validation failed at {location}: {first.message}")
    return scene


def _number_field(name, default, minimum, maximum):
    try:
        value = float(request.form.get(name, default))
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number.")
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}.")
    return value


def _validate_image(file_storage):
    raw = file_storage.read(MAX_IMAGE_BYTES + 1)
    if not raw:
        raise ValueError("The selected image is empty.")
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError("The image must be 10 MB or smaller.")

    try:
        with Image.open(io.BytesIO(raw)) as check_image:
            image_format = (check_image.format or "").upper()
            if image_format not in ALLOWED_IMAGE_FORMATS:
                raise ValueError("Choose a PNG, JPG, or WebP floor plan.")
            width, height = check_image.size
            if width < 16 or height < 16 or width * height > 20_000_000:
                raise ValueError("The image dimensions must be at least 16×16 and no more than 20 megapixels.")
            check_image.verify()
        with Image.open(io.BytesIO(raw)) as source:
            normalized = source.convert("RGB")
            output = io.BytesIO()
            normalized.save(output, format="PNG", optimize=True)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ValueError("This file is not a valid supported image. Try a PNG, JPG, or WebP file.")

    filename = secure_filename(file_storage.filename or "floorplan.png") or "floorplan.png"
    return output.getvalue(), (width, height), filename


def _build_scene(image_bytes, image_size, filename, meters_per_pixel, wall_height, wall_thickness, calibrate_scale, progress):
    processing_mode = _processing_mode()
    if processing_mode == "MOCK":
        # Mock masks are deliberately tied to the prepared sample plan, never to
        # the uploaded pixels. Show the same sample image to avoid implying AI analysis.
        with open(SAMPLE_IMG_PATH, "rb") as sample_file:
            image_bytes = sample_file.read()
        with Image.open(io.BytesIO(image_bytes)) as sample_image:
            image_size = sample_image.size
        filename = "mock_sample_floorplan.png"
    provider_bytes, provider_size = _downscale_for_provider(image_bytes)
    provider_image_url = "data:image/png;base64," + base64.b64encode(provider_bytes).decode("ascii")
    image_url = "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")
    img_w, img_h = image_size
    warnings = []
    if processing_mode == "MOCK":
        warnings.append("MOCK MODE: generated from prepared sample geometry; uploaded pixels were not analyzed by AI.")
    elif processing_mode == "REPLAY":
        warnings.append("REPLAY MODE: stored SAM responses were used; no live SAM request was made.")

    progress("Detecting rooms, walls, doors, and windows", 30)
    job_budget = max(10.0, float(os.environ.get("SAM_JOB_TIMEOUT_SECONDS", "180")))
    deadline = time.monotonic() + job_budget

    def ensure_budget(stage):
        if time.monotonic() >= deadline:
            raise ProviderError("budget", f"The job time budget expired during {stage}.")

    concepts = ("room", "wall", "door", "window")
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="sam-concept")
    futures = {
        executor.submit(
            query_sam_concept,
            provider_image_url,
            concept,
            provider_size,
            max(1.0, deadline - time.monotonic()),
        ): concept
        for concept in concepts
    }
    done, pending = concurrent.futures.wait(
        futures,
        timeout=job_budget,
        return_when=concurrent.futures.ALL_COMPLETED,
    )
    for future in pending:
        future.cancel()
    executor.shutdown(wait=False, cancel_futures=True)

    masks_by_concept = {concept: [] for concept in concepts}
    room_failure = None
    for future in done:
        concept = futures[future]
        try:
            masks_by_concept[concept] = _restore_mask_sizes(future.result(), provider_size, image_size)
        except Exception as exc:
            logger.exception("SAM %s segmentation failed", concept)
            if concept == "room":
                room_failure = exc
            else:
                safe_message = exc.safe_message if isinstance(exc, ProviderError) else ProviderError("down").safe_message
                warnings.append(f"{concept.title()} detection was unavailable: {safe_message}")

    if pending:
        pending_concepts = {futures[future] for future in pending}
        for future in pending:
            future.cancel()
        if "room" in pending_concepts:
            room_failure = ProviderError("budget", "Room segmentation exceeded the job time budget.")
        for concept in pending_concepts - {"room"}:
            warnings.append(f"{concept.title()} detection exceeded the processing time limit and was skipped.")

    if room_failure:
        if isinstance(room_failure, ProviderError):
            raise room_failure
        if isinstance(room_failure, ValueError):
            raise ProviderError("configuration", str(room_failure)) from room_failure
        if isinstance(room_failure, TimeoutError):
            raise ProviderError("timeout", str(room_failure)) from room_failure
        raise ProviderError("down", str(room_failure)) from room_failure

    room_masks = masks_by_concept["room"]
    wall_masks = masks_by_concept["wall"]
    door_masks = masks_by_concept["door"]
    window_masks = masks_by_concept["window"]

    scale_method = "manual"
    if calibrate_scale:
        estimated_scale = estimate_meters_per_pixel_from_doors(door_masks)
        if estimated_scale is not None and 0.001 <= estimated_scale <= 0.1:
            meters_per_pixel = estimated_scale
            scale_method = "median detected door width (assumed 0.9 m)"
        else:
            scale_method = "manual fallback; no reliable door width detected"

    progress("Cleaning geometry", 62)
    rooms_data = []
    for mask in room_masks:
        for polygon in mask_to_polygons_with_holes(mask, meters_per_pixel=meters_per_pixel, min_area_px=200):
            room_id = f"r{len(rooms_data) + 1}"
            rooms_data.append({
                "id": room_id,
                "type": "room",
                "label": f"Room {len(rooms_data) + 1}",
                "confidence": 0.0,
                "polygon": polygon["polygon"],
                "centroid": polygon["centroid"],
                "area_m2": polygon["area_m2"],
            })

    if not rooms_data:
        raise ValueError("No rooms were detected. Try a clearer, higher-contrast floor plan.")

    progress("Classifying rooms", 79)
    try:
        ensure_budget("room geometry processing")
        remaining_budget = deadline - time.monotonic()
        if remaining_budget <= 0:
            raise ProviderError("budget", "The processing deadline expired before room labeling.")
        labels = label_rooms(image_url, rooms_data, warnings=warnings, timeout=remaining_budget)
    except Exception as exc:
        logger.exception("Room classification failed")
        labels = {}
        if isinstance(exc, ProviderError):
            warnings.append(f"Room labels are unavailable: {exc.safe_message}")
        else:
            warnings.append("Room labels are unavailable; generic room labels are shown.")
    for room in rooms_data:
        label = labels.get(room["id"])
        if label:
            room.update(label)
        else:
            room["type"] = "room"
            room["label"] = f"Room {room['id'][1:]}"
            room["confidence"] = 0.0
            fallback_warning = "Some room labels are unavailable; generic room labels are shown."
            if fallback_warning not in warnings:
                warnings.append(fallback_warning)
    ensure_budget("room labeling")

    cleaned_rooms = [
        {key: room[key] for key in ("id", "type", "label", "confidence", "polygon")}
        for room in rooms_data
    ]

    walls_data = []
    for mask in wall_masks:
        for polygon in mask_to_polygons_with_holes(mask, meters_per_pixel=meters_per_pixel, min_area_px=100):
            walls_data.append({
                "id": f"w{len(walls_data) + 1}",
                "polygon": polygon["polygon"],
                "holes": polygon["holes"],
            })
    if not walls_data:
        walls_data = build_walls_from_rooms(cleaned_rooms, meters_per_pixel, image_size, wall_thickness)
        warnings.append("Walls were approximated from detected room outlines.")
    ensure_budget("wall geometry processing")
    if calibrate_scale and scale_method.startswith("manual fallback"):
        warnings.append("Automatic scale calibration could not find reliable doors; the selected scale was used.")

    doors_data = extract_doors(door_masks, cleaned_rooms, meters_per_pixel=meters_per_pixel)
    windows_data = extract_windows(window_masks, meters_per_pixel=meters_per_pixel)
    ensure_budget("opening geometry processing")
    progress("Preparing 3D scene", 94)

    scene = {
        "meta": {
            "source": filename,
            "processingMode": processing_mode,
            "imageSize": [img_w, img_h],
            "metersPerPixel": meters_per_pixel,
            "scaleMethod": scale_method,
            "wallHeight": wall_height,
            "wallThickness": wall_thickness,
            "warnings": warnings,
        },
        "rooms": cleaned_rooms,
        "walls": walls_data,
        "doors": doors_data,
        "windows": windows_data,
    }
    overlays = {
        "room": [{"id": room["id"], "label": room["label"], "polygon": room["polygon"]} for room in cleaned_rooms],
        "wall": [{"id": wall["id"], "polygon": wall["polygon"]} for wall in walls_data],
        "door": [{"id": door["id"], "center": door["center"], "width": door["width"]} for door in doors_data],
        "window": [{"id": window["id"], "center": window["center"], "width": window["width"]} for window in windows_data],
    }
    return {"scene": scene, "overlays": overlays, "imageUrl": image_url}


def _run_job(job_id, image_bytes, image_size, filename, meters_per_pixel, wall_height, wall_thickness, calibrate_scale):
    def progress(stage, percent):
        with JOBS_LOCK:
            if job_id in JOBS:
                JOBS[job_id].update(stage=stage, progress=percent)

    try:
        result = _build_scene(image_bytes, image_size, filename, meters_per_pixel, wall_height, wall_thickness, calibrate_scale, progress)
        validate_scene_contract(result["scene"])
        with JOBS_LOCK:
            JOBS[job_id].update(status="complete", stage="Complete", progress=100, result=result)
    except Exception as exc:
        app.logger.exception("Floor plan job %s failed", job_id)
        if isinstance(exc, ProviderError):
            message = exc.safe_message
        elif isinstance(exc, ValueError):
            message = str(exc)
        else:
            message = "The floor plan could not be processed because of an internal error. Details were logged on the server."
        with JOBS_LOCK:
            JOBS[job_id].update(status="failed", stage="Processing failed", error=message)


def _prune_old_jobs():
    """Bound in-memory scene/image retention for a long-running demo session."""
    cutoff = datetime.now(timezone.utc).timestamp() - 60 * 60
    with JOBS_LOCK:
        expired = []
        for job_id, job in JOBS.items():
            if job.get("status") == "processing":
                continue
            try:
                created = datetime.fromisoformat(job["created_at"]).timestamp()
                if created < cutoff:
                    expired.append(job_id)
            except (KeyError, ValueError):
                expired.append(job_id)
        for job_id in expired:
            JOBS.pop(job_id, None)

        completed = sorted(
            ((job.get("created_at", ""), job_id) for job_id, job in JOBS.items() if job.get("status") != "processing"),
            key=lambda item: item[0],
        )
        for _created, job_id in completed[:-16]:
            JOBS.pop(job_id, None)


@app.errorhandler(413)
def request_too_large(_error):
    return jsonify({"success": False, "error": "The image must be 10 MB or smaller."}), 413


@app.route("/")
def index():
    return render_template("index.html", processing_ready=_live_sam_ready(), processing_mode=_processing_mode())


@app.route("/api/health", methods=["GET"])
def health():
    mode = _processing_mode()
    return jsonify({
        "status": "online",
        "service": "FloorPlan3D",
        "pipeline_ready": _live_sam_ready(),
        "live_processing_ready": mode == "LIVE",
        "processing_mode": mode,
    })


@app.route("/api/scene/ask", methods=["POST"])
def ask_about_scene():
    payload = request.get_json(silent=True) or {}
    question = payload.get("question")
    scene = payload.get("scene")
    if not isinstance(question, str) or not question.strip() or len(question) > 500:
        return jsonify({"success": False, "error": "Enter a question of 1 to 500 characters."}), 400
    if not isinstance(scene, dict):
        return jsonify({"success": False, "error": "Load a floor-plan scene before asking a question."}), 400
    try:
        validate_scene_contract(scene)
    except RuntimeError:
        return jsonify({"success": False, "error": "The current map is not valid enough to query."}), 400

    facts = _build_scene_facts(scene)
    if get_modal_config()["is_configured"]:
        try:
            answer = ask_modal_muse_spark_about_scene(question.strip(), facts)
            return jsonify({"success": True, "answer": answer, "provider": "Muse Spark via Modal"})
        except Exception:
            app.logger.exception("Muse Spark map question failed")
    answer = _offline_scene_answer(question.strip(), facts)
    return jsonify({
        "success": True,
        "answer": answer,
        "provider": "Offline scene lookup (no model call)",
    })


@app.route("/api/sample", methods=["GET"])
def sample_data():
    try:
        with open(SAMPLE_IMG_PATH, "rb") as sample_file:
            data_url = "data:image/png;base64," + base64.b64encode(sample_file.read()).decode("ascii")
        scene = get_sample_scene_json()
        scene["meta"]["processingMode"] = "DEMO"
        scene["meta"].setdefault("warnings", []).append("Prepared demo scene; this is not a live AI result.")
        validate_scene_contract(scene)
        return jsonify({
            "success": True,
            "scene": scene,
            "overlays": get_sample_mask_overlays(),
            "imageUrl": data_url,
            "demoMode": True,
        })
    except Exception:
        app.logger.exception("Could not load the built-in demo scene")
        return jsonify({"success": False, "error": "The built-in demo could not be loaded."}), 500


@app.route("/api/sample/two-story", methods=["GET"])
def two_story_sample_data():
    try:
        with open(SAMPLE_IMG_PATH, "rb") as sample_file:
            data_url = "data:image/png;base64," + base64.b64encode(sample_file.read()).decode("ascii")
        scene = get_two_story_sample_scene_json()
        scene["meta"]["processingMode"] = "DEMO"
        scene["meta"].setdefault("warnings", []).append("Prepared two-story demo scene; this is not a live AI result.")
        validate_scene_contract(scene)
        return jsonify({
            "success": True,
            "scene": scene,
            "overlays": get_sample_mask_overlays(),
            "imageUrl": data_url,
            "demoMode": True,
        })
    except Exception:
        app.logger.exception("Could not load the built-in two-story demo scene")
        return jsonify({"success": False, "error": "The two-story demo could not be loaded."}), 500


@app.route("/api/sample_image", methods=["GET"])
def sample_image():
    return send_file(SAMPLE_IMG_PATH, mimetype="image/png")


@app.route("/api/upload", methods=["POST"])
def upload_floorplan():
    if not _live_sam_ready():
        return jsonify({
            "success": False,
            "error": "Live AI processing is not configured. Use the prepared demo, or enable MOCK_SAM / REPLAY_SAM_RESPONSES for an offline pipeline run.",
        }), 503
    retry_after = _rate_limit_upload(request.remote_addr or "unknown")
    if retry_after:
        response = jsonify({"success": False, "error": "Upload rate limit reached. Please wait before trying again."})
        response.headers["Retry-After"] = str(retry_after)
        return response, 429
    if "file" not in request.files:
        return jsonify({"success": False, "error": "Choose a floor plan image first."}), 400
    file = request.files["file"]
    if not file.filename:
        return jsonify({"success": False, "error": "Choose a floor plan image first."}), 400

    try:
        image_bytes, image_size, filename = _validate_image(file)
        mpp = _number_field("metersPerPixel", 0.02, 0.001, 0.1)
        wall_height = _number_field("wallHeight", 3.0, 0.5, 10.0)
        wall_thickness = _number_field("wallThickness", 0.2, 0.05, 1.0)
        calibrate_scale = request.form.get("calibrateScale", "true").strip().lower() in {"1", "true", "yes", "on"}
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400

    _prune_old_jobs()
    job_id = uuid.uuid4().hex
    with JOBS_LOCK:
        active_jobs = sum(job.get("status") == "processing" for job in JOBS.values())
        if active_jobs >= MAX_ACTIVE_JOBS:
            response = jsonify({"success": False, "error": "The processing queue is full. Wait for a current job to finish and try again."})
            response.headers["Retry-After"] = "10"
            return response, 429
        JOBS[job_id] = {
            "status": "processing", "stage": "Queued", "progress": 5,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    worker = threading.Thread(
        target=_run_job,
        args=(job_id, image_bytes, image_size, filename, mpp, wall_height, wall_thickness, calibrate_scale),
        daemon=True,
    )
    try:
        worker.start()
    except RuntimeError:
        with JOBS_LOCK:
            JOBS.pop(job_id, None)
        app.logger.exception("Could not start floor plan job %s", job_id)
        return jsonify({"success": False, "error": "The processing worker could not be started. Please retry shortly."}), 503
    return jsonify({"success": True, "job_id": job_id}), 202


@app.route("/api/status/<job_id>", methods=["GET"])
def job_status(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return jsonify({"error": "Processing job not found."}), 404
        return jsonify({key: job[key] for key in ("status", "stage", "progress", "error") if key in job})


@app.route("/api/scene/<job_id>", methods=["GET"])
def job_scene(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return jsonify({"error": "Processing job not found."}), 404
        if job["status"] != "complete":
            return jsonify({"error": "The scene is not ready yet."}), 409
        validate_scene_contract(job["result"]["scene"])
        return jsonify(job["result"])


@app.route("/api/process", methods=["POST"])
def process_floorplan_compat():
    """Compatibility endpoint for clients that still submit synchronously."""
    return jsonify({
        "success": False,
        "error": "Processing now uses /api/upload followed by /api/status/<job_id>.",
    }), 410


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0").strip().lower() in {"1", "true", "yes"}
    app.run(host="127.0.0.1", port=port, debug=debug)
