"""FloorPlan3D Flask app and asynchronous image-processing API."""

import base64
import io
import math
import os
import threading
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, send_file
from PIL import Image, UnidentifiedImageError
from werkzeug.utils import secure_filename

from cloud_services import get_baseten_config
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

app = Flask(__name__, template_folder="templates", static_folder="static")
MAX_IMAGE_BYTES = 10 * 1024 * 1024
app.config["MAX_CONTENT_LENGTH"] = MAX_IMAGE_BYTES + 64 * 1024  # allow multipart form overhead

SAMPLE_IMG_PATH = os.path.join(app.root_path, "samples", "sample_floorplan.png")
if not os.path.exists(SAMPLE_IMG_PATH):
    generate_sample_floorplan_image(SAMPLE_IMG_PATH)

JOBS = {}
JOBS_LOCK = threading.Lock()
ALLOWED_IMAGE_FORMATS = {"PNG", "JPEG", "WEBP"}


def _live_sam_ready():
    return get_baseten_config()["is_configured"]


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
    image_url = "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")
    img_w, img_h = image_size

    progress("Detecting rooms", 15)
    room_masks = query_sam_concept(image_url, "room", image_size)

    progress("Detecting walls, doors, and windows", 38)
    wall_masks = query_sam_concept(image_url, "wall", image_size)
    door_masks = query_sam_concept(image_url, "door", image_size)
    window_masks = query_sam_concept(image_url, "window", image_size)

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
    warnings = []
    try:
        labels = label_rooms(image_url, rooms_data, warnings=warnings)
    except Exception:
        labels = {}
        warnings.append("Room labels are unavailable; generic room labels are shown.")
    for room in rooms_data:
        label = labels.get(room["id"])
        if label:
            room.update(label)
        else:
            room["type"] = "room"
            room["label"] = f"Room {room['id'][1:]}"
            room["confidence"] = 0.0
            if not warnings:
                warnings.append("Some room labels are unavailable; generic room labels are shown.")

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
    if calibrate_scale and scale_method.startswith("manual fallback"):
        warnings.append("Automatic scale calibration could not find reliable doors; the selected scale was used.")

    doors_data = extract_doors(door_masks, cleaned_rooms, meters_per_pixel=meters_per_pixel)
    windows_data = extract_windows(window_masks, meters_per_pixel=meters_per_pixel)
    progress("Preparing 3D scene", 94)

    scene = {
        "meta": {
            "source": filename,
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
        with JOBS_LOCK:
            JOBS[job_id].update(status="complete", stage="Complete", progress=100, result=result)
    except Exception as exc:
        app.logger.exception("Floor plan job %s failed", job_id)
        message = str(exc) if isinstance(exc, ValueError) else "The AI processing service failed. Check your API key and provider endpoint settings."
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
    return render_template("index.html", live_ready=_live_sam_ready())


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "online", "service": "FloorPlan3D", "live_processing_ready": _live_sam_ready()})


@app.route("/api/sample", methods=["GET"])
def sample_data():
    try:
        with open(SAMPLE_IMG_PATH, "rb") as sample_file:
            data_url = "data:image/png;base64," + base64.b64encode(sample_file.read()).decode("ascii")
        return jsonify({
            "success": True,
            "scene": get_sample_scene_json(),
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
        return jsonify({
            "success": True,
            "scene": get_two_story_sample_scene_json(),
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
            "error": "Live AI processing is not configured yet. You can use the built-in demo now; add your SAM API key and endpoint settings to .env when you receive them.",
        }), 503
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
        JOBS[job_id] = {
            "status": "processing", "stage": "Queued", "progress": 5,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    worker = threading.Thread(
        target=_run_job,
        args=(job_id, image_bytes, image_size, filename, mpp, wall_height, wall_thickness, calibrate_scale),
        daemon=True,
    )
    worker.start()
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
