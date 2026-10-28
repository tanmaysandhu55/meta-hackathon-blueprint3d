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

from meta_llama_service import label_rooms, is_labeling_configured, last_error_category
from demo_data import generate_sample_floorplan_image, get_sample_mask_overlays, get_sample_scene_json, get_two_story_sample_scene_json
from geometry_processor import (
    build_walls_from_rooms,
    estimate_meters_per_pixel_from_doors,
    extract_doors,
    extract_windows,
    mask_to_polygons_with_holes,
)
from segmentation_service import prepare_segmentation, segment_prepared_concept

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
QUESTION_REQUESTS = defaultdict(deque)
QUESTION_RATE_LOCK = threading.Lock()
ALLOWED_IMAGE_FORMATS = {"PNG", "JPEG", "WEBP"}
MAX_ACTIVE_JOBS = 2
UPLOAD_RATE_WINDOW_SECONDS = 60
UPLOAD_RATE_LIMIT = 10
QUESTION_RATE_LIMIT = 20
QUESTION_RATE_WINDOW_SECONDS = 60
DEFAULT_METERS_PER_PIXEL = float(os.getenv("DEFAULT_METERS_PER_PIXEL", "0.02"))
DEFAULT_WALL_HEIGHT = float(os.getenv("DEFAULT_WALL_HEIGHT", "3.0"))
DEFAULT_WALL_THICKNESS = float(os.getenv("DEFAULT_WALL_THICKNESS", "0.2"))


class ProviderError(RuntimeError):
    SAFE_MESSAGES = {"timeout": "Room labeling timed out.", "auth": "Llama API authentication failed.",
                     "schema": "Llama returned an unsupported label response.",
                     "budget": "Floor plan processing exceeded its time limit.",
                     "configuration": "Floor plan processing could not use the supplied settings.",
                     "down": "Room labeling is unavailable."}
    def __init__(self, category, detail=""):
        self.safe_message = self.SAFE_MESSAGES.get(category, self.SAFE_MESSAGES["down"])
        super().__init__(detail or self.safe_message)


def segmentation_ready():
    return True


def labeling_ready():
    return is_labeling_configured()


def _processing_mode():
    if os.getenv("MOCK_MODE", "0").strip().lower() in {"1", "true", "yes", "on"}:
        return "MOCK"
    return "LOCAL"


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


def _rate_limit_question(ip_address):
    now = time.monotonic()
    with QUESTION_RATE_LOCK:
        requests_for_ip = QUESTION_REQUESTS[ip_address]
        stale_ips = []
        for address, entries in QUESTION_REQUESTS.items():
            while entries and now - entries[0] >= QUESTION_RATE_WINDOW_SECONDS:
                entries.popleft()
            if address != ip_address and not entries:
                stale_ips.append(address)
        for address in stale_ips:
            QUESTION_REQUESTS.pop(address, None)
        if len(requests_for_ip) >= QUESTION_RATE_LIMIT:
            return max(1, int(QUESTION_RATE_WINDOW_SECONDS - (now - requests_for_ip[0])))
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
    return "Offline scene lookup can answer room, floor, area, and door-count questions."


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
        filename = "sample_plan_mock.png"
    image_url = "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")
    img_w, img_h = image_size
    warnings = []
    if processing_mode == "MOCK":
        warnings.append("MOCK MODE: generated from prepared sample geometry; uploaded pixels were not analyzed by AI.")
    else:
        warnings.append("Local OpenCV heuristic segmentation was used; results are estimates best suited to clean, high-contrast plans.")

    progress("Detecting rooms, walls, doors, and windows", 30)
    job_budget = 180.0
    deadline = time.monotonic() + job_budget

    def ensure_budget(stage):
        if time.monotonic() >= deadline:
            raise ProviderError("budget", f"The job time budget expired during {stage}.")

    concepts = ("room", "wall", "door", "window")
    try:
        prepared_image = prepare_segmentation(image_bytes, image_size)
    except (ValueError, cv2.error) as exc:
        raise ProviderError("configuration", str(exc)) from exc

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="local-segmentation")
    futures = {
        executor.submit(
            segment_prepared_concept,
            prepared_image,
            concept,
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
            masks_by_concept[concept] = future.result()
        except Exception as exc:
            logger.exception("Local %s segmentation failed", concept)
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
    if not wall_masks:
        warnings.append("Local wall segmentation returned no reliable masks; walls will be approximated from room outlines.")
    if not door_masks:
        warnings.append("No reliable door masks were found; door-based scale calibration may use the manual scale instead.")
    if not window_masks:
        warnings.append("No reliable window masks were found; windows may be omitted from the scene.")

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
        if processing_mode == "MOCK":
            labels = {}
        elif labeling_ready():
            labels = label_rooms(image_url, rooms_data, timeout=max(1, deadline - time.monotonic()))
            if not labels:
                category = last_error_category() or "bad_response"
                safe_categories = {"timeout": "timeout", "auth": "authentication failed", "bad_response": "bad response", "unavailable": "provider unavailable"}
                warnings.append(f"Llama labeling {safe_categories.get(category, 'provider unavailable')}; generic room labels are shown.")
        else:
            labels = {}
            warnings.append("Llama labeling is not configured; generic room labels are shown.")
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
            "segmentation": "opencv-heuristic",
            "mock": processing_mode == "MOCK",
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
    return render_template("index.html", processing_ready=True, processing_mode=_processing_mode(), labeling_ready=labeling_ready())


@app.route("/api/health", methods=["GET"])
def health():
    mode = _processing_mode()
    return jsonify({
        "status": "online",
        "service": "FloorPlan3D",
        "pipeline_ready": True,
        "segmentation_ready": True,
        "labeling_ready": labeling_ready(),
        "live_processing_ready": labeling_ready(),
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
    retry_after = _rate_limit_question(request.remote_addr or "unknown")
    if retry_after:
        response = jsonify({"success": False, "error": "Map assistant rate limit reached. Wait before asking again."})
        response.headers["Retry-After"] = str(retry_after)
        return response, 429
    try:
        validate_scene_contract(scene)
    except RuntimeError:
        return jsonify({"success": False, "error": "The current map is not valid enough to query."}), 400

    facts = _build_scene_facts(scene)
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
        mpp = _number_field("metersPerPixel", DEFAULT_METERS_PER_PIXEL, 0.001, 0.1)
        wall_height = _number_field("wallHeight", DEFAULT_WALL_HEIGHT, 0.5, 10.0)
        wall_thickness = _number_field("wallThickness", DEFAULT_WALL_THICKNESS, 0.05, 1.0)
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
