"""FloorPlan3D Flask app and asynchronous image-processing API."""

import base64
import concurrent.futures
import cv2
import numpy as np
import io
import json
import logging
import math
import os
import re
import shapely.geometry
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

from baseten_service import answer_scene_question, label_rooms, is_labeling_configured, last_error_category, get_labeling_provider_name
from meta_sam_service import is_sam_configured, query_sam_concept
from meta_media_service import generate_floorplan, image_generation_ready, transcribe_audio, voice_transcription_ready
from demo_data import generate_sample_floorplan_image, get_sample_mask_overlays, get_sample_scene_json, get_two_story_sample_scene_json
from geometry_processor import (
    build_walls_from_rooms,
    check_axis_aligned_fraction,
    detect_doors_and_windows_geometrically,
    choose_scale,
    estimate_wall_thickness_px,
    solidify_wall_band,
    detect_door_swing_radii_px,
    extract_doors,
    extract_windows,
    mask_to_polygons_with_holes,
    reconstruct_walls_from_mask_orthogonal,
    reconstruct_walls_room_first,
    snap_openings_and_cut_walls,
    snap_polygon_orthogonal,
    split_image_at_user_dividers,
    split_multi_plan_image,
    validate_scene_geometry,
)
from segmentation_service import prepare_segmentation, segment_prepared_concept
from usage_tracker import get_provider_usage

load_dotenv()
logger = logging.getLogger(__name__)

app = Flask(__name__, template_folder="templates", static_folder="static")
MAX_IMAGE_BYTES = 10 * 1024 * 1024
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024 + 64 * 1024  # audio endpoint limit plus multipart overhead

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
    SAFE_MESSAGES = {
        "timeout": "Meta model request timed out.",
        "auth": "Meta API authentication failed.",
        "schema": "Meta returned an unsupported response.",
        "budget": "Floor plan processing exceeded its time limit.",
        "configuration": "Floor plan processing could not use the supplied settings.",
        "down": "Meta model service is unavailable.",
    }
    def __init__(self, category, detail=""):
        self.safe_message = self.SAFE_MESSAGES.get(category, self.SAFE_MESSAGES["down"])
        super().__init__(detail or self.safe_message)


def _json_compatible(value):
    """Convert NumPy values in generated geometry into standard JSON types."""
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(key): _json_compatible(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_compatible(item) for item in value]
    return value


def segmentation_ready():
    return True


def labeling_ready():
    return is_labeling_configured()


def sam_ready():
    return is_sam_configured()


def _processing_mode():
    # MOCK_AI is the documented switch. Keep MOCK_MODE as a legacy alias,
    # but default safely to the prepared sample when neither is configured.
    raw_mode = os.getenv("MOCK_AI")
    if raw_mode is None:
        raw_mode = os.getenv("MOCK_MODE")
    if raw_mode is None:
        return "MOCK"

    normalized_mode = raw_mode.strip().lower()
    if normalized_mode in {"1", "true", "yes", "on"}:
        return "MOCK"
    if normalized_mode not in {"0", "false", "no", "off"}:
        app.logger.warning("Unrecognized MOCK_AI value; defaulting to prepared mock mode.")
        return "MOCK"

    return "LIVE" if sam_ready() else "LOCAL"


def _estimate_plan_footprint(prepared_image):
    """Return outer-plan bounds and area in the current image's pixel space.

    Room masks can omit open halls or leak through missed doorways. A closed
    copy of the original line mask gives a more stable exterior outline while
    leaving the source pixels untouched for room and opening detection.
    """
    dark = prepared_image.get("dark")
    if not isinstance(dark, np.ndarray) or dark.ndim != 2 or not dark.size:
        return None
    height, width = dark.shape
    image_area = max(1, width * height)
    close_size = max(5, int(round(min(width, height) / 80)) | 1)
    closed = cv2.morphologyEx(
        dark,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (close_size, close_size)),
        iterations=2,
    )
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []
    for contour in contours:
        area_px = float(cv2.contourArea(contour))
        x, y, box_width, box_height = cv2.boundingRect(contour)
        if area_px < image_area * 0.04 or box_width * box_height < image_area * 0.08:
            continue
        # Contours touching almost every edge are usually the page/background.
        if box_width >= width * 0.98 or box_height >= height * 0.98:
            continue
        candidates.append((area_px, x, y, box_width, box_height))
    if not candidates:
        return None
    area_px, x, y, box_width, box_height = max(candidates)
    return {
        "bounds_px": (int(x), int(y), int(x + box_width), int(y + box_height)),
        "area_px": area_px,
        "contour_area_fraction": area_px / image_area,
    }


def _door_mask_widths_px(door_masks):
    """Measure plausible widths from the actual door masks selected for extraction."""
    widths = []
    for mask in door_masks or []:
        binary = (np.asarray(mask) > 0).astype(np.uint8)
        if binary.ndim != 2 or not binary.size:
            continue
        cleaned = cv2.morphologyEx(
            binary,
            cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)),
        )
        contours, _ = cv2.findContours(cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            if cv2.contourArea(contour) < 25:
                continue
            (_cx, _cy), (width, height), _angle = cv2.minAreaRect(contour)
            width_px = max(float(width), float(height))
            if 15 <= width_px <= 100:
                widths.append(width_px)
    return widths


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


def _extract_route_request(question, facts):
    """Resolve an explicit natural-language route request against known room names."""
    normalized = " ".join(question.casefold().split())
    route_intent = any(term in normalized for term in (
        "route", "navigate", "way from", "get from", "go from", "directions", "between"
    ))
    if not route_intent:
        return None

    matches = []
    for room in facts["rooms"]:
        candidates = [room["label"], room["id"]]
        positions = [normalized.find(value.casefold()) for value in candidates if value]
        positions = [position for position in positions if position >= 0]
        if positions:
            matches.append((min(positions), room))
    matches.sort(key=lambda item: item[0])
    unique = []
    seen = set()
    for _, room in matches:
        if room["id"] not in seen:
            unique.append(room)
            seen.add(room["id"])
    if len(unique) < 2:
        return None
    start, end = unique[0], unique[1]
    return {
        "startId": start["id"], "endId": end["id"],
        "startLabel": start["label"] or start["id"],
        "endLabel": end["label"] or end["id"],
    }


def _scene_review_facts(scene, facts):
    rooms = scene.get("rooms", [])
    walls = scene.get("walls", [])
    doors = scene.get("doors", [])
    windows = scene.get("windows", [])
    meta = scene.get("meta", {})
    valid_rooms = sum(1 for room in rooms if len(room.get("polygon", [])) >= 3)
    connectors = [room for room in rooms if str(room.get("type", "")).lower() in {"stairs", "stair", "elevator"}]
    floor_ids = {int(room.get("floorIndex", room.get("level", 0)) or 0) for room in rooms}
    scale_method = str(meta.get("scaleMethod", "")).lower()
    interactive_scale = "interactive" in scale_method
    generic_label = lambda value: not value or value.strip().lower().startswith("room ")
    named_rooms = sum(1 for room in rooms if not generic_label(str(room.get("label", ""))))
    findings = [
        {"status": "check" if not rooms or valid_rooms < len(rooms) else "ok", "title": "Room outlines", "detail": f"{valid_rooms} of {len(rooms)} rooms have polygons with at least three points."},
        {"status": "check" if not walls else "ok", "title": "Wall geometry", "detail": f"{len(walls)} wall region(s) are present." if walls else "No wall regions are recorded."},
        {"status": "check" if not doors else "ok", "title": "Door openings", "detail": f"{len(doors)} door opening(s) are recorded; compare them with the source plan."},
        {"status": "check" if len(floor_ids) > 1 and not connectors else "ok", "title": "Floor connection", "detail": f"{len(connectors)} stair/elevator room(s) are recorded across {len(floor_ids) or 1} floor(s)."},
        {"status": "check" if not interactive_scale or "fallback" in scale_method else "ok", "title": "Scale", "detail": "Scale is an estimate; verify it against a known dimension." if not interactive_scale else "Interactive scale calibration is recorded; still verify against a known dimension."},
        {"status": "check" if named_rooms < len(rooms) else "ok", "title": "Room labels", "detail": f"{named_rooms} of {len(rooms)} rooms have specific labels."},
        {"status": "info", "title": "Windows", "detail": f"{len(windows)} window opening(s) are recorded."},
    ]
    warnings = [str(item)[:240] for item in meta.get("warnings", [])[:12] if isinstance(item, str)]
    return {
        "room_count": len(rooms), "valid_room_count": valid_rooms,
        "floor_count": len(floor_ids) or len(facts["levels"]) or 1,
        "total_area_m2": round(sum(room["area_m2"] for room in facts["rooms"]), 2),
        "door_count": len(doors), "window_count": len(windows), "wall_count": len(walls),
        "findings": findings, "warnings": warnings,
    }


def _offline_scene_insight(kind, review, facts):
    if kind == "summary":
        area = review["total_area_m2"]
        by_floor = defaultdict(int)
        for room in facts["rooms"]:
            by_floor[room["floor"] + 1] += 1
        floors = ", ".join(f"Level {floor}: {count} room(s)" for floor, count in sorted(by_floor.items())) or "No rooms recorded"
        return (f"This scene contains {review['room_count']} rooms across {review['floor_count']} floor(s), "
                f"with approximately {area:.1f} m² of mapped room area. It records {review['door_count']} doors, "
                f"{review['window_count']} windows, and {review['wall_count']} wall regions. {floors}. "
                "Areas and geometry are estimates; verify them against the source plan.")
    needs_review = [item["title"] for item in review["findings"] if item["status"] == "check"]
    next_steps = ", ".join(needs_review) if needs_review else "compare the geometry and scale with the source plan"
    return (f"Structural review: {review['valid_room_count']} of {review['room_count']} room outlines are usable; "
            f"{review['door_count']} doors and {review['window_count']} windows are recorded across "
            f"{review['floor_count']} floor(s). Review {next_steps}. This is a geometry checklist, not a "
            "building-code, construction, or safety assessment.")


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


def _process_story_slice(image_bytes, image_size, meters_per_pixel, wall_height, wall_thickness, calibrate_scale, progress, deadline, use_sam, processing_mode, image_url, story_index=0, filename="", scale_source="auto"):
    warnings = []
    concepts = ("room", "wall", "door", "window")
    try:
        prepared_image = prepare_segmentation(image_bytes, image_size)
    except (ValueError, cv2.error) as exc:
        raise ProviderError("configuration", str(exc)) from exc
    plan_footprint_px = _estimate_plan_footprint(prepared_image)

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix=f"local-segmentation-s{story_index}")
    def segment_one(concept):
        if use_sam:
            try:
                sam_result = query_sam_concept(
                    image_bytes,
                    concept,
                    image_size,
                    timeout=min(75, max(1, deadline - time.monotonic())),
                    return_status=True,
                )
                if isinstance(sam_result, tuple) and len(sam_result) == 2 and isinstance(sam_result[1], dict):
                    sam_masks, detail = sam_result
                else:  # Keep small test doubles and older service wrappers compatible.
                    sam_masks = sam_result
                    detail = {"status": "OK" if sam_masks else "EMPTY", "prompt": concept, "category": None}
                if sam_masks:
                    return sam_masks, "sam-3.1", None, detail
                return segment_prepared_concept(prepared_image, concept), "opencv-fallback", "no_matches", {
                    "status": "EMPTY", "prompt": detail.get("prompt", concept), "category": "no_matches"
                }
            except Exception as exc:
                logger.warning(
                    "SAM failed for %s; using local OpenCV fallback (%s)",
                    concept,
                    type(exc).__name__,
                )
                category = getattr(exc, "safe_category", "unavailable")
                return segment_prepared_concept(prepared_image, concept), "opencv-fallback", category, {
                    "status": "EMPTY" if category == "no_matches" else "FAILED",
                    "prompt": concept,
                    "category": category,
                }
        return segment_prepared_concept(prepared_image, concept), "opencv-heuristic", None, {
            "status": "NOT RUN", "prompt": None, "category": None
        }

    futures = {executor.submit(segment_one, concept): concept for concept in concepts}
    done, pending = concurrent.futures.wait(
        futures,
        timeout=max(1, deadline - time.monotonic()),
        return_when=concurrent.futures.ALL_COMPLETED,
    )
    for future in pending:
        future.cancel()
    executor.shutdown(wait=False, cancel_futures=True)

    masks_by_concept = {concept: [] for concept in concepts}
    backends_by_concept = {}
    sam_concepts = {}
    room_failure = None
    for future in done:
        concept = futures[future]
        try:
            masks_by_concept[concept], backends_by_concept[concept], provider_error, sam_concepts[concept] = future.result()
            if provider_error:
                if not use_sam:
                    warnings.append(f"SAM not run (no live key or local mode); {concept} detection used local OpenCV.")
                elif provider_error == "no_matches":
                    warnings.append(
                        f"Meta SAM 3.1 detected no matching '{concept}' regions in this floor plan; local OpenCV fallback was used."
                    )
                elif provider_error == "auth":
                    warnings.append(
                        f"Meta API authentication failed for {concept}; local OpenCV fallback was used."
                    )
                elif provider_error == "timeout":
                    warnings.append(
                        f"Meta SAM 3.1 request for {concept} timed out; local OpenCV fallback was used."
                    )
                elif provider_error == "unavailable":
                    warnings.append(
                        f"Meta SAM 3.1 service was temporarily unavailable for {concept}; local OpenCV fallback was used."
                    )
                else:
                    warnings.append(
                        f"Meta segmentation for {concept} used local OpenCV fallback ({provider_error})."
                    )
        except Exception as exc:
            logger.exception("Local %s segmentation failed", concept)
            sam_concepts[concept] = {
                "status": "FAILED" if use_sam else "NOT RUN",
                "prompt": concept if use_sam else None,
                "category": getattr(exc, "safe_category", "unavailable") if use_sam else None,
            }
            if concept == "room":
                room_failure = exc
            else:
                safe_message = exc.safe_message if isinstance(exc, ProviderError) else ProviderError("down").safe_message
                warnings.append(f"{concept.title()} detection was unavailable: {safe_message}")

    if room_failure:
        if isinstance(room_failure, ProviderError):
            raise room_failure
        if isinstance(room_failure, ValueError):
            raise ProviderError("configuration", str(room_failure)) from room_failure
        if isinstance(room_failure, TimeoutError):
            raise ProviderError("timeout", str(room_failure)) from room_failure
        raise ProviderError("down", str(room_failure)) from room_failure

    room_masks = masks_by_concept["room"]
    wall_masks = [solidify_wall_band(mask) for mask in masks_by_concept["wall"]]
    door_masks = masks_by_concept["door"]
    window_masks = masks_by_concept["window"]

    # Keep the initial scale separate: geometric opening centers are detected
    # in source pixels and must be converted only after a validated scale wins.
    initial_meters_per_pixel = float(meters_per_pixel)
    geometric_openings = detect_doors_and_windows_geometrically(
        image_bytes, initial_meters_per_pixel, return_diagnostics=True
    )
    geo_doors = geometric_openings[0]
    # Scale must be measured from the same source that wins door extraction.
    # Otherwise noisy geometric fallbacks can calibrate a plan even when the
    # selected SAM/OpenCV door masks only contain one or two real openings.
    door_mask_widths_px = _door_mask_widths_px(door_masks)
    geometric_door_widths_px = [float(item.get("pixel_width")) for item in geo_doors if item.get("pixel_width")]
    door_swing_radii_px = detect_door_swing_radii_px(image_bytes)
    door_widths_px = door_swing_radii_px if len(door_swing_radii_px) >= 3 else (door_mask_widths_px or geometric_door_widths_px)
    door_width_source = "door swing arc radii" if len(door_swing_radii_px) >= 3 else ("segmentation masks" if door_mask_widths_px else "geometric candidates")
    union_room_mask = np.zeros((image_size[1], image_size[0]), dtype=np.uint8)
    room_areas_px = []
    for mask in room_masks:
        if isinstance(mask, np.ndarray) and mask.shape[:2] == union_room_mask.shape:
            binary_mask = (mask > 0).astype(np.uint8)
            union_room_mask = cv2.bitwise_or(union_room_mask, binary_mask * 255)
            area_px = int(cv2.countNonZero(binary_mask))
            if area_px >= max(200, int(image_size[0] * image_size[1] * 0.002)):
                room_areas_px.append(area_px)
    ys, xs = np.nonzero(union_room_mask)
    room_bounds_px = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1) if xs.size else None
    room_union_area_px = int(cv2.countNonZero(union_room_mask)) if xs.size else 0
    footprint_bounds_px = (plan_footprint_px or {}).get("bounds_px") or room_bounds_px
    footprint_area_px = float((plan_footprint_px or {}).get("area_px") or room_union_area_px)
    room_footprint_coverage = min(1.0, room_union_area_px / footprint_area_px) if footprint_area_px else 0.0
    user_scale = float(meters_per_pixel) if scale_source in {"user", "manual"} else None
    scale_choice = choose_scale(
        user_scale=user_scale,
        door_widths_px=door_widths_px if calibrate_scale else [],
        footprint_bounds_px=footprint_bounds_px,
        footprint_area_px=footprint_area_px,
        room_areas_px=room_areas_px,
        default_scale=meters_per_pixel,
    )
    meters_per_pixel = round(float(scale_choice["meters_per_pixel"]), 7)
    scale_source = scale_choice["source"]
    scale_confidence = float(scale_choice["confidence"])
    # Opening evidence is filtered at the final selected scale. The first pass
    # above only provides measurements for scale selection.
    geometric_openings = detect_doors_and_windows_geometrically(
        image_bytes, meters_per_pixel, return_diagnostics=True
    )
    geo_doors = geometric_openings[0]
    initial_meters_per_pixel = meters_per_pixel
    scale_method = {
        "user": "interactive two-point calibration",
        "manual": "user-entered scale",
        "door-width": "median of at least three consistent door widths (assumed 0.9 m)",
        "typical-footprint-width": "typical 12 m longest footprint side (unverified estimate)",
        "configured-default": "configured fallback scale (unverified estimate)",
        "needs-review": "scale failed sanity checks; manual calibration required",
    }.get(scale_source, "unverified scale estimate")
    warnings.extend(scale_choice.get("warnings", []))
    scale_quality_issues = [] if scale_choice["accepted"] else [
        "Scale failed sanity checks; set scale using two known points before trusting the 3D model."
    ]
    if room_footprint_coverage and room_footprint_coverage < 0.45:
        coverage_issue = (
            f"Detected room regions cover only {room_footprint_coverage * 100:.0f}% of the estimated outer footprint; "
            "review the 2D room overlay."
        )
        warnings.append(coverage_issue)
        scale_quality_issues.append(coverage_issue)

    def rescale_pixel_openings(opening_sets):
        """Rebuild metric centers/widths from original-image pixel measurements."""
        scale_ratio = meters_per_pixel / max(initial_meters_per_pixel, 1e-9)
        for collection in opening_sets:
            for item in collection or []:
                if item.get("pixel_center"):
                    item["center"] = [round(float(value) * meters_per_pixel, 3) for value in item["pixel_center"]]
                elif item.get("center"):
                    item["center"] = [round(float(value) * scale_ratio, 3) for value in item["center"]]
                if item.get("pixel_width") is not None:
                    item["width"] = round(float(item["pixel_width"]) * meters_per_pixel, 3)
                elif item.get("width") is not None:
                    item["width"] = round(float(item["width"]) * scale_ratio, 3)

    opening_diagnostics = geometric_openings[3] if len(geometric_openings) > 3 else []
    if any("cap reached" in str(item.get("reason", "")) for item in opening_diagnostics):
        warnings.append("The exterior-window candidate cap was reached; review the 2D window detections.")
    if geometric_openings:
        rescale_pixel_openings(geometric_openings[:2])
        for item in geo_doors[:]:
            opening_kind = str(item.get("kind") or "swing")
            low, high = (0.7, 1.5) if opening_kind == "open-doorway" else (1.4, 2.4) if opening_kind == "double" else (0.7, 1.2)
            if not low <= float(item.get("width") or 0.0) <= high:
                opening_diagnostics.append({
                    "kind": "door", "candidate": item.get("id"), "accepted": False,
                    "pixelCenter": item.get("pixel_center"),
                    "reason": f"estimated {opening_kind} width {float(item.get('width') or 0.0):.2f} m is outside {low:.1f}-{high:.1f} m",
                })
                geo_doors.remove(item)
        for item in geometric_openings[1][:]:
            if not 0.5 <= float(item.get("width") or 0.0) <= 3.0:
                opening_diagnostics.append({
                    "kind": "window", "candidate": item.get("id"), "accepted": False,
                    "pixelCenter": item.get("pixel_center"),
                    "reason": f"estimated width {float(item.get('width') or 0.0):.2f} m is outside 0.5-3.0 m",
                })
                geometric_openings[1].remove(item)

    prefix = f"s{story_index}_" if story_index > 0 else ""
    def build_room_records(masks):
        records = []
        for mask in masks:
            for polygon in mask_to_polygons_with_holes(mask, meters_per_pixel=meters_per_pixel, min_area_px=200):
                polygon_shape = shapely.geometry.Polygon(polygon["polygon"], polygon.get("holes", []))
                minx, miny, maxx, maxy = polygon_shape.bounds
                if polygon_shape.area < 1.5 or min(maxx - minx, maxy - miny) < 0.5:
                    continue
                room_num = len(records) + 1
                room_id = f"{prefix}r{room_num}"
                default_label = f"Room G{room_num}" if story_index == 0 else f"Room {story_index}.{room_num}"
                records.append({
                    "id": room_id,
                    "type": "room",
                    "label": default_label,
                    "confidence": 0.0,
                    "polygon": polygon["polygon"],
                    "holes": polygon.get("holes", []),
                    "centroid": polygon["centroid"],
                    "area_m2": polygon["area_m2"],
                })
        return records

    rooms_data = build_room_records(room_masks)
    # SAM can return one large, syntactically valid mask when open doorways
    # connect most of the interior. Compare that result with the local
    # white-region extractor before accepting it as a single-room building.
    largest_room_mask_px = max(
        (int(cv2.countNonZero(np.asarray(mask, dtype=np.uint8))) for mask in room_masks if isinstance(mask, np.ndarray)),
        default=0,
    )
    if use_sam and len(rooms_data) == 1 and largest_room_mask_px >= int(image_size[0] * image_size[1] * 0.12):
        try:
            local_room_masks = segment_prepared_concept(prepared_image, "room")
            local_rooms = build_room_records(local_room_masks)
            if len(local_rooms) > len(rooms_data):
                room_masks = local_room_masks
                rooms_data = local_rooms
                backends_by_concept["room"] = "opencv-fallback"
                warnings.append(
                    "Meta SAM returned one large room region; local OpenCV found more enclosed rooms, so its room outlines were used."
                )
        except Exception:
            logger.exception("Local room comparison failed after a single large SAM region")

    if not rooms_data and use_sam:
        # A provider can return syntactically valid masks that are too small or
        # malformed to become room polygons. Retry room extraction locally
        # before failing the upload, just as we do when SAM returns no masks.
        try:
            local_room_masks = segment_prepared_concept(prepared_image, "room")
            local_rooms = build_room_records(local_room_masks)
            if local_rooms:
                room_masks = local_room_masks
                rooms_data = local_rooms
                backends_by_concept["room"] = "opencv-fallback"
                warnings.append(
                    "Meta SAM returned no usable room outlines; local OpenCV room detection was used instead."
                )
        except Exception:
            logger.exception("Local room recovery failed after unusable SAM masks")

    if prepared_image.get("adaptive_room_closing"):
        warnings.append(
            "Room outlines were recovered by closing wider door gaps; verify them in the 2D review before relying on the geometry."
        )

    if not rooms_data:
        raise ValueError("No rooms were detected. Try a clearer, higher-contrast floor plan.")

    if footprint_area_px:
        largest_room_area = max((float(room.get("area_m2") or 0.0) for room in rooms_data), default=0.0)
        footprint_area_m2 = footprint_area_px * meters_per_pixel * meters_per_pixel
        if footprint_area_m2 and largest_room_area > footprint_area_m2 * 0.70:
            warning = "Room split failed: one detected room covers over 70% of the estimated footprint. Review the 2D overlay before using this model."
            warnings.append(warning)
            scale_quality_issues.append(warning)

    used_sam_concepts = set()
    if backends_by_concept.get("room") == "sam-3.1" and rooms_data:
        used_sam_concepts.add("room")

    try:
        if processing_mode == "MOCK":
            labels = {}
        elif labeling_ready():
            labels = label_rooms(image_url, rooms_data, timeout=max(1, deadline - time.monotonic()))
            if not labels:
                category = last_error_category() or "bad_response"
                safe_categories = {"timeout": "timed out", "auth": "authentication failed", "bad_response": "returned an unsupported response", "unavailable": "provider unavailable"}
                warnings.append(f"Muse room labeling {safe_categories.get(category, 'provider unavailable')}; generic room labels are shown.")
        else:
            labels = {}
            warnings.append("Muse room labeling is not configured; generic room labels are shown.")
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
            room_num = room["id"].split("r")[-1]
            room["label"] = f"Room G{room_num}" if story_index == 0 else f"Room {story_index}.{room_num}"
            room["confidence"] = 0.0
    labeling_used = bool(labels) and processing_mode != "MOCK"

    # Snap room polygons orthogonally (7 degrees, 0.15m merge)
    for r in rooms_data:
        r["polygon"] = snap_polygon_orthogonal(r["polygon"], tolerance_deg=7.0, snap_dist=0.15)

    cleaned_rooms = [
        {key: room[key] for key in ("id", "type", "label", "confidence", "polygon", "holes")}
        for room in rooms_data
    ]
    for idx, r in enumerate(cleaned_rooms):
        r["centroid"] = rooms_data[idx]["centroid"]
        try:
            room_geometry = shapely.geometry.Polygon(r["polygon"], r["holes"])
            r["area_m2"] = round(room_geometry.area, 2) if room_geometry.is_valid else rooms_data[idx]["area_m2"]
        except Exception:
            r["area_m2"] = rooms_data[idx]["area_m2"]

    # Rebuild walls: Room-first as primary method
    walls_data = []
    wall_method = "none"
    rf_walls, rf_ratio = reconstruct_walls_room_first(cleaned_rooms, wall_thickness_m=wall_thickness)
    if rf_walls and rf_ratio >= 0.85:
        walls_data = rf_walls
        wall_method = "room-boundary-reconstruction"
    elif wall_masks:
        mask_walls, mask_ratio = reconstruct_walls_from_mask_orthogonal(wall_masks, meters_per_pixel, wall_thickness_m=wall_thickness)
        if mask_walls:
            walls_data = mask_walls
            wall_method = "orthogonal-mask-snapping"
    if not walls_data:
        walls_data = build_walls_from_rooms(cleaned_rooms, meters_per_pixel, image_size, wall_thickness)
        wall_method = "approximate-room-outlines"
        warnings.append("Walls were approximated from detected room outlines.")
    if wall_method == "orthogonal-mask-snapping" and backends_by_concept.get("wall") == "sam-3.1":
        used_sam_concepts.add("wall")

    for idx, w in enumerate(walls_data):
        w["id"] = f"{prefix}w{idx + 1}"

    doors_data = extract_doors(door_masks, cleaned_rooms, meters_per_pixel=meters_per_pixel)
    windows_data = extract_windows(window_masks, meters_per_pixel=meters_per_pixel)
    sam_door_candidates = bool(doors_data) and backends_by_concept.get("door") == "sam-3.1"
    sam_window_candidates = bool(windows_data) and backends_by_concept.get("window") == "sam-3.1"

    # When SAM is not used or found no openings, detect doors and windows geometrically
    if not doors_data or not windows_data:
        if geometric_openings is None:
            geometric_openings = detect_doors_and_windows_geometrically(image_bytes, meters_per_pixel)
        geo_doors, geo_windows, _ = geometric_openings[:3]
        if not doors_data and geo_doors:
            doors_data = geo_doors
        if not windows_data and geo_windows:
            windows_data = geo_windows

    for idx, d in enumerate(doors_data):
        d["id"] = f"{prefix}d{idx + 1}"
    for idx, win in enumerate(windows_data):
        win["id"] = f"{prefix}win{idx + 1}"

    detected_doors_count = len(doors_data)
    detected_windows_count = len(windows_data)
    opening_pixel_centers = {
        (kind, str(item.get("id"))): item.get("pixel_center") or [
            round(float(item.get("center", [0, 0])[0]) / meters_per_pixel, 2),
            round(float(item.get("center", [0, 0])[1]) / meters_per_pixel, 2),
        ]
        for kind, collection in (("door", doors_data), ("window", windows_data))
        for item in collection
    }
    # Snap in original source-pixel coordinates using the measured wall stroke width.
    # The closed/cleaned wall segmentation is intentionally much thicker than
    # the ink in the uploaded drawing. Measure the source line mask instead so
    # the pixel-space snap tolerance reflects actual wall strokes.
    thickness_masks = [prepared_image.get("dark")] if isinstance(prepared_image.get("dark"), np.ndarray) else wall_masks
    stroke_thickness_px = estimate_wall_thickness_px(
        thickness_masks, meters_per_pixel=meters_per_pixel, wall_thickness_m=wall_thickness
    )
    band_masks = [solidify_wall_band(mask) for mask in thickness_masks]
    wall_thickness_px = estimate_wall_thickness_px(
        band_masks, meters_per_pixel=meters_per_pixel, wall_thickness_m=wall_thickness
    )
    walls_data, doors_data, windows_data, dropped_openings = snap_openings_and_cut_walls(
        walls_data, doors_data, windows_data, wall_thickness_m=wall_thickness,
        meters_per_pixel=meters_per_pixel, wall_thickness_px=wall_thickness_px,
    )
    for drop_msg in dropped_openings:
        warnings.append(drop_msg)
        match = re.match(r"^(Door|Window)\s+(\S+)\s+dropped\s*\((.*)\)\.?$", drop_msg, re.IGNORECASE)
        if match:
            kind = match.group(1).lower()
            candidate_id = match.group(2)
            opening_diagnostics.append({
                "kind": kind,
                "candidate": candidate_id,
                "accepted": False,
                "pixelCenter": opening_pixel_centers.get((kind, candidate_id)),
                "reason": match.group(3),
            })
    if sam_door_candidates and doors_data:
        used_sam_concepts.add("door")
    if sam_window_candidates and windows_data:
        used_sam_concepts.add("window")
    for opening in [*doors_data, *windows_data]:
        opening.pop("pixel_center", None)
        opening.pop("pixel_width", None)

    for concept, detail in sam_concepts.items():
        detail["used"] = concept in used_sam_concepts
    used_sam = bool(used_sam_concepts)
    used_fallback = any(value != "sam-3.1" for value in backends_by_concept.values())
    if used_sam and used_fallback:
        segmentation_backend = "sam-3.1+opencv-fallback"
    elif used_sam:
        segmentation_backend = "sam-3.1"
    elif use_sam:
        segmentation_backend = "opencv-fallback"
    else:
        segmentation_backend = "opencv-heuristic"

    return {
        "rooms": cleaned_rooms,
        "walls": walls_data,
        "doors": doors_data,
        "windows": windows_data,
        "warnings": warnings,
        "meters_per_pixel": meters_per_pixel,
        "door_swing_radii_px": [round(float(value), 2) for value in door_swing_radii_px],
        "wall_stroke_thickness_px": round(float(stroke_thickness_px), 2),
        "wall_band_thickness_px": round(float(wall_thickness_px), 2),
        "snap_tolerance_px": round(max(6.0, 1.5 * float(wall_thickness_px)), 2),
        "footprint_bounds": [round(float(value) * meters_per_pixel, 3) for value in footprint_bounds_px] if footprint_bounds_px else None,
        "footprint_area_m2": round(float(footprint_area_px) * meters_per_pixel * meters_per_pixel, 2) if footprint_area_px else 0.0,
        "room_footprint_coverage": round(float(room_footprint_coverage), 4),
        "footprint_bounds_px": list(map(int, footprint_bounds_px)) if footprint_bounds_px else None,
        "footprint_contour_area_px": round(float(footprint_area_px), 2),
        "door_widths_px_for_scale": [round(float(width), 2) for width in door_widths_px],
        "door_width_source": door_width_source,
        "scale_method": scale_method,
        "scale_source": scale_source,
        "scale_confidence": scale_confidence,
        "scale_accepted": bool(scale_choice["accepted"]),
        "scale_quality_issues": scale_quality_issues,
        "wall_thickness_px": wall_thickness_px,
        "opening_counts": {
            "doorsDetected": detected_doors_count,
            "doorsKept": len(doors_data),
            "windowsDetected": detected_windows_count,
            "windowsKept": len(windows_data),
            "dropped": len(dropped_openings),
        },
        "segmentation_backend": segmentation_backend,
        "sam_concepts": [
            {"concept": concept, **detail}
            for concept, detail in sam_concepts.items()
        ],
        "opening_diagnostics": opening_diagnostics,
        "used_sam_concepts": sorted(used_sam_concepts),
        "labeling_used": labeling_used,
        "wall_method": wall_method,
    }


def _rescale_story_result(result, target_meters_per_pixel):
    """Put a story's already-built metric geometry onto a shared m/px scale."""
    source_scale = float(result.get("meters_per_pixel") or target_meters_per_pixel)
    target_scale = float(target_meters_per_pixel)
    if source_scale <= 0 or target_scale <= 0:
        return
    factor = target_scale / source_scale
    if math.isclose(factor, 1.0, rel_tol=1e-7, abs_tol=1e-9):
        result["meters_per_pixel"] = target_scale
        return

    def scale_ring(ring):
        return [[round(float(point[0]) * factor, 3), round(float(point[1]) * factor, 3)] for point in ring]

    for room in result.get("rooms", []):
        room["polygon"] = scale_ring(room.get("polygon", []))
        room["holes"] = [scale_ring(hole) for hole in room.get("holes", [])]
        if room.get("centroid"):
            room["centroid"] = [round(float(value) * factor, 3) for value in room["centroid"]]
        if room.get("area_m2") is not None:
            room["area_m2"] = round(float(room["area_m2"]) * factor * factor, 2)
    for wall in result.get("walls", []):
        wall["polygon"] = scale_ring(wall.get("polygon", []))
        wall["holes"] = [scale_ring(hole) for hole in wall.get("holes", [])]
    for collection in ("doors", "windows"):
        for opening in result.get(collection, []):
            if opening.get("center"):
                opening["center"] = [round(float(value) * factor, 3) for value in opening["center"]]
            if opening.get("width") is not None:
                opening["width"] = round(float(opening["width"]) * factor, 3)
    if result.get("footprint_bounds"):
        result["footprint_bounds"] = [round(float(value) * factor, 3) for value in result["footprint_bounds"]]
    if result.get("footprint_area_m2") is not None:
        result["footprint_area_m2"] = round(float(result["footprint_area_m2"]) * factor * factor, 2)
    result["meters_per_pixel"] = target_scale


def _translate_story_result(result, dx, dy):
    """Translate every plan-space point in a story by the same metric offset."""
    def move_ring(ring):
        return [[round(float(point[0]) + dx, 3), round(float(point[1]) + dy, 3)] for point in ring]

    for room in result.get("rooms", []):
        room["polygon"] = move_ring(room.get("polygon", []))
        room["holes"] = [move_ring(hole) for hole in room.get("holes", [])]
        if room.get("centroid"):
            room["centroid"] = [round(float(room["centroid"][0]) + dx, 3), round(float(room["centroid"][1]) + dy, 3)]
    for wall in result.get("walls", []):
        wall["polygon"] = move_ring(wall.get("polygon", []))
        wall["holes"] = [move_ring(hole) for hole in wall.get("holes", [])]
    for collection in ("doors", "windows"):
        for opening in result.get(collection, []):
            if opening.get("center"):
                opening["center"] = [round(float(opening["center"][0]) + dx, 3), round(float(opening["center"][1]) + dy, 3)]
    if result.get("footprint_bounds"):
        bounds = list(result["footprint_bounds"])
        result["footprint_bounds"] = [
            round(float(bounds[0]) + dx, 3), round(float(bounds[1]) + dy, 3),
            round(float(bounds[2]) + dx, 3), round(float(bounds[3]) + dy, 3),
        ]


def _connector_kind(room):
    description = f"{room.get('type', '')} {room.get('label', '')}".lower()
    if "elevator" in description or "lift" in description:
        return "elevator"
    if "stair" in description:
        return "stairs"
    return None


def _story_connector(rooms):
    candidates = [room for room in rooms if _connector_kind(room)]
    if not candidates:
        return None
    return max(candidates, key=lambda room: float(room.get("area_m2") or 0.0))


def _story_footprint_bounds(result):
    """Get the exterior plan outline, with geometry-derived fallbacks."""
    footprint = result.get("footprint_bounds")
    if isinstance(footprint, (list, tuple)) and len(footprint) == 4:
        try:
            values = tuple(float(value) for value in footprint)
            if all(math.isfinite(value) for value in values) and values[2] > values[0] and values[3] > values[1]:
                return values
        except (TypeError, ValueError):
            pass
    polygons = []
    for entity in [*(result.get("rooms", []) or []), *(result.get("walls", []) or [])]:
        try:
            polygon = shapely.geometry.Polygon(entity.get("polygon", []))
            if polygon.is_valid and not polygon.is_empty:
                polygons.append(polygon)
        except Exception:
            continue
    if not polygons:
        return None
    return shapely.ops.unary_union(polygons).bounds


def _story_footprint_mismatch(ground_result, upper_result):
    ground_bounds = _story_footprint_bounds(ground_result)
    upper_bounds = _story_footprint_bounds(upper_result)
    if not ground_bounds or not upper_bounds:
        return None
    ground_width = max(1e-6, ground_bounds[2] - ground_bounds[0])
    ground_depth = max(1e-6, ground_bounds[3] - ground_bounds[1])
    upper_width = max(1e-6, upper_bounds[2] - upper_bounds[0])
    upper_depth = max(1e-6, upper_bounds[3] - upper_bounds[1])
    ground_area = ground_width * ground_depth
    upper_area = upper_width * upper_depth
    return max(
        abs(ground_width - upper_width) / max(ground_width, upper_width),
        abs(ground_depth - upper_depth) / max(ground_depth, upper_depth),
        abs(ground_area - upper_area) / max(ground_area, upper_area),
    )


def _align_upper_story(ground_result, upper_result):
    """Center plan footprints only; stair locations never distort alignment."""
    ground_connector = _story_connector(ground_result.get("rooms", []))
    upper_candidates = [
        room for room in upper_result.get("rooms", [])
        if ground_connector and _connector_kind(room) == _connector_kind(ground_connector)
    ]
    upper_connector = max(upper_candidates, key=lambda room: float(room.get("area_m2") or 0.0)) if upper_candidates else None
    ground_bounds, upper_bounds = _story_footprint_bounds(ground_result), _story_footprint_bounds(upper_result)
    if not ground_bounds or not upper_bounds:
        return 0.0, 0.0, None, None
    ground_cx = (ground_bounds[0] + ground_bounds[2]) / 2
    ground_cy = (ground_bounds[1] + ground_bounds[3]) / 2
    upper_cx = (upper_bounds[0] + upper_bounds[2]) / 2
    upper_cy = (upper_bounds[1] + upper_bounds[3]) / 2
    dx, dy = round(ground_cx - upper_cx, 3), round(ground_cy - upper_cy, 3)
    _translate_story_result(upper_result, dx, dy)
    return dx, dy, ground_connector, upper_connector


def _build_scene(image_bytes, image_size, filename, meters_per_pixel, wall_height, wall_thickness, calibrate_scale, progress, scale_source="auto", floor_count=1, split_orientation="vertical", split_positions=None):
    processing_mode = _processing_mode()
    if processing_mode == "MOCK":
        with open(SAMPLE_IMG_PATH, "rb") as sample_file:
            image_bytes = sample_file.read()
        with Image.open(io.BytesIO(image_bytes)) as sample_image:
            image_size = sample_image.size
        filename = "sample_plan_mock.png"
    image_url = "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")
    img_w, img_h = image_size
    warnings = []
    use_sam = processing_mode != "MOCK" and sam_ready()
    if processing_mode == "MOCK":
        warnings.append("MOCK MODE: generated from prepared sample geometry; uploaded pixels were not analyzed by AI.")
    elif not use_sam:
        warnings.append("Local OpenCV heuristic segmentation was used; results are estimates best suited to clean, high-contrast plans.")

    progress("Detecting plans and layout structure", 15)
    job_budget = 180.0
    deadline = time.monotonic() + job_budget

    # A multi-story image is never split automatically: a user must choose its
    # floor count and divider positions in the upload controls.
    if processing_mode == "MOCK" or int(floor_count or 1) <= 1:
        crops = [(image_bytes, (0, 0, img_w, img_h))]
    else:
        crops = split_image_at_user_dividers(
            image_bytes, int(floor_count), split_orientation, split_positions or []
        )
    slab_thickness = 0.2

    if len(crops) >= 2:
        warnings.append(f"User-selected split: processing {len(crops)} floor plans. Verify the divider positions and each floor in 2D review.")
        story_results = []
        story_origins = []
        for story_index, (crop_bytes, crop_bounds) in enumerate(crops):
            story_origins.append((int(crop_bounds[0]), int(crop_bounds[1])))
            with Image.open(io.BytesIO(crop_bytes)) as crop_image:
                crop_size = crop_image.size
            crop_url = "data:image/png;base64," + base64.b64encode(crop_bytes).decode("ascii")
            progress(f"Processing floor {story_index + 1} of {len(crops)}", 25 + int(60 * story_index / len(crops)))
            result = _process_story_slice(
                crop_bytes, crop_size, meters_per_pixel, wall_height, wall_thickness,
                calibrate_scale, progress, deadline, use_sam, processing_mode, crop_url,
                story_index=story_index, filename=filename, scale_source=scale_source,
            )
            story_results.append(result)

        accepted_results = [result for result in story_results if result.get("scale_accepted")]
        common_scale_results = accepted_results or story_results
        common_mpp = math.exp(
            sum(math.log(max(float(result.get("meters_per_pixel") or meters_per_pixel), 1e-9)) for result in common_scale_results)
            / len(common_scale_results)
        )
        common_mpp = round(common_mpp, 7)
        for result in story_results:
            _rescale_story_result(result, common_mpp)
            for warning in result.get("warnings", []):
                if warning not in warnings:
                    warnings.append(warning)

        if all(result.get("scale_source") == "user" and result.get("scale_accepted") for result in story_results):
            scene_scale_source = "user"
            scale_method = "interactive two-point calibration"
        elif all(result.get("scale_source") == "door-width" for result in story_results):
            scene_scale_source = "door-width"
            scale_method = "median of consistent detected door widths across floors (assumed 0.9 m)"
        else:
            source_counts = {}
            for result in common_scale_results:
                source = str(result.get("scale_source") or "unknown")
                source_counts[source] = source_counts.get(source, 0) + 1
            scene_scale_source = max(source_counts, key=source_counts.get) if source_counts else "needs-review"
            scale_method = "combined estimate across user-selected floor crops"
        scene_scale_confidence = min(float(result.get("scale_confidence") or 0.0) for result in common_scale_results)
        scale_review_issues = list(dict.fromkeys(
            issue for result in story_results for issue in result.get("scale_quality_issues", [])
        ))

        story_offsets = [{"level": 0, "dx": 0.0, "dy": 0.0}]
        for story_index in range(1, len(story_results)):
            previous = story_results[story_index - 1]
            current = story_results[story_index]
            mismatch = _story_footprint_mismatch(previous, current)
            dx, dy, lower_connector, upper_connector = _align_upper_story(previous, current)
            story_offsets.append({"level": story_index, "dx": dx, "dy": dy})
            if mismatch is None:
                mismatch = 1.0
            if mismatch > 0.15:
                issue = f"Floor {story_index + 1} footprint differs from the floor below by {mismatch * 100:.1f}%; footprints were not resized. Review the floor alignment."
                warnings.append(issue)
                scale_review_issues.append(issue)
            connector_delta = math.inf
            if lower_connector and upper_connector and lower_connector.get("centroid") and upper_connector.get("centroid"):
                connector_delta = math.dist(lower_connector["centroid"], upper_connector["centroid"])
            if lower_connector and upper_connector and mismatch <= 0.15 and connector_delta <= 2.0:
                lower_connector["connectsTo"] = upper_connector["id"]
                upper_connector["connectsTo"] = lower_connector["id"]
                connector_type = _connector_kind(lower_connector)
                lower_connector["type"] = connector_type
                upper_connector["type"] = connector_type
            else:
                warnings.append(f"No verified stair/elevator alignment links floor {story_index} to floor {story_index + 1}. Check vertical access manually.")

        for story_index, result in enumerate(story_results):
            for collection in ("rooms", "walls", "doors", "windows"):
                for entity in result.get(collection, []):
                    entity["floorIndex"] = story_index
                    entity["level"] = story_index
                    if collection == "rooms":
                        entity["floor"] = story_index

        cleaned_rooms = [room for result in story_results for room in result["rooms"]]
        walls_data = [wall for result in story_results for wall in result["walls"]]
        doors_data = [door for result in story_results for door in result["doors"]]
        windows_data = [window for result in story_results for window in result["windows"]]
        used_sam = any("sam-3.1" in str(result.get("segmentation_backend", "")) for result in story_results)
        has_fallback = any("opencv" in str(result.get("segmentation_backend", "")) for result in story_results)
        segmentation_backend = "sam-3.1+opencv-fallback" if used_sam and has_fallback else "sam-3.1" if used_sam else "opencv-fallback" if use_sam else "opencv-heuristic"
        scale_needs_review = bool(scale_review_issues) or len(accepted_results) != len(story_results)
        if len(accepted_results) != len(story_results) and "At least one floor scale failed sanity checks; review calibration." not in scale_review_issues:
            scale_review_issues.append("At least one floor scale failed sanity checks; review calibration.")
        level_names = ["Ground Floor", "Second Floor", "Third Floor"]
        floor_height = round(wall_height + slab_thickness, 2)
        scene = {
            "meta": {
                "source": filename,
                "processingMode": "MOCK" if processing_mode == "MOCK" else "LIVE" if used_sam or any(result.get("labeling_used") for result in story_results) else "LOCAL",
                "segmentation": segmentation_backend,
                "labeling": "muse" if any(result.get("labeling_used") for result in story_results) else "generic",
                "mock": processing_mode == "MOCK",
                "imageSize": [img_w, img_h],
                "metersPerPixel": common_mpp,
                "scaleMethod": scale_method,
                "scaleSource": scene_scale_source,
                "scaleConfidence": scene_scale_confidence,
                "needsReview": scale_needs_review,
                "reviewIssues": scale_review_issues,
                "openingCounts": {
                    key: sum(int(result.get("opening_counts", {}).get(key, 0)) for result in story_results)
                    for key in ("doorsDetected", "doorsKept", "windowsDetected", "windowsKept", "dropped")
                },
                "openingDiagnostics": [
                    {
                        **item,
                        "pixelCenter": [
                            round(float(item["pixelCenter"][0]) + story_origins[story_index][0], 2),
                            round(float(item["pixelCenter"][1]) + story_origins[story_index][1], 2),
                        ] if isinstance(item.get("pixelCenter"), (list, tuple)) and len(item["pixelCenter"]) == 2 else None,
                        "floorIndex": story_index,
                    }
                    for story_index, result in enumerate(story_results)
                    for item in result.get("opening_diagnostics", [])
                ][:200],
                "samConcepts": [
                    {"concept": item.get("concept"), "floorIndex": story_index,
                     **{key: value for key, value in item.items() if key != "concept"}}
                    for story_index, result in enumerate(story_results)
                    for item in result.get("sam_concepts", [])
                ],
                "wallHeight": wall_height,
                "wallThickness": wall_thickness,
                "wall_method": ", ".join(sorted({str(result.get("wall_method", "unknown")) for result in story_results})),
                "floorHeight": floor_height,
                "slabThickness": slab_thickness,
                "levelCount": len(story_results),
                "levels": [
                    {"level": index, "floorIndex": index, "name": level_names[index],
                     "elevation": round(floor_height * index, 2), "metersPerPixel": common_mpp,
                     "scaleSource": str(story_results[index].get("scale_source") or "needs-review"),
                     "scaleConfidence": float(story_results[index].get("scale_confidence") or 0.0),
                     # Invert the metric story-centering transform when drawing
                     # overlays on the original unsplit upload image.
                     "planOffset": [
                         round(story_offsets[index]["dx"] - story_origins[index][0] * common_mpp, 6),
                         round(story_offsets[index]["dy"] - story_origins[index][1] * common_mpp, 6),
                     ]}
                    for index in range(len(story_results))
                ],
                "storyOffsets": story_offsets,
                "warnings": warnings,
            },
            "rooms": cleaned_rooms,
            "walls": walls_data,
            "doors": doors_data,
            "windows": windows_data,
        }
    else:
        progress("Detecting rooms, walls, doors, and windows", 30)
        res = _process_story_slice(image_bytes, image_size, meters_per_pixel, wall_height, wall_thickness, calibrate_scale, progress, deadline, use_sam, processing_mode, image_url, story_index=0, filename=filename, scale_source=scale_source)
        for w_item in res["warnings"]:
            if w_item not in warnings:
                warnings.append(w_item)
        cleaned_rooms = res["rooms"]
        walls_data = res["walls"]
        doors_data = res["doors"]
        windows_data = res["windows"]
        mpp = res["meters_per_pixel"]
        scale_method = res["scale_method"]
        scene_scale_source = res.get("scale_source", "needs-review")
        scene_scale_confidence = float(res.get("scale_confidence", 0.0))
        scale_review_issues = list(res.get("scale_quality_issues", []))
        scale_needs_review = bool(scale_review_issues)
        segmentation_backend = res["segmentation_backend"]

        scene = {
            "meta": {
                "source": filename,
                "processingMode": "MOCK" if processing_mode == "MOCK" else "LIVE" if "sam-3.1" in segmentation_backend else "LOCAL",
                "segmentation": segmentation_backend,
                "labeling": "muse" if res.get("labeling_used") else "generic",
                "mock": processing_mode == "MOCK",
                "imageSize": [img_w, img_h],
                "metersPerPixel": mpp,
                "scaleMethod": scale_method,
                "scaleSource": scene_scale_source,
                "scaleConfidence": scene_scale_confidence,
                "needsReview": scale_needs_review,
                "reviewIssues": scale_review_issues,
                "openingCounts": res.get("opening_counts", {}),
                "openingDiagnostics": res.get("opening_diagnostics", [])[:200],
                "samConcepts": res.get("sam_concepts", []),
                "wallHeight": wall_height,
                "wallThickness": wall_thickness,
                "wall_method": res.get("wall_method", "room-boundary-reconstruction"),
                "levels": [{
                    "level": 0, "floorIndex": 0, "name": "Ground Floor",
                    "elevation": 0.0, "metersPerPixel": mpp,
                    "scaleSource": scene_scale_source,
                    "scaleConfidence": scene_scale_confidence,
                    "planOffset": [0.0, 0.0],
                }],
                "warnings": warnings,
            },
            "rooms": cleaned_rooms,
            "walls": walls_data,
            "doors": doors_data,
            "windows": windows_data,
        }

    _apply_scene_sanity_gate(scene)

    # Run geometry validator on complete scene
    val_warnings = validate_scene_geometry(scene)
    for v_warn in val_warnings:
        if v_warn not in scene["meta"]["warnings"]:
            scene["meta"]["warnings"].append(v_warn)

    overlays = {
        "room": [{"id": room["id"], "label": room["label"], "polygon": room["polygon"]} for room in cleaned_rooms],
        "wall": [{"id": wall["id"], "polygon": wall["polygon"]} for wall in walls_data],
        "door": [{"id": door["id"], "center": door["center"], "width": door["width"]} for door in doors_data],
        "window": [{"id": window["id"], "center": window["center"], "width": window["width"]} for window in windows_data],
    }
    progress("Preparing 3D scene", 94)
    return _json_compatible({"scene": scene, "overlays": overlays, "imageUrl": image_url})


def _apply_scene_sanity_gate(scene):
    """Mark implausible estimates for review before the frontend creates 3D."""
    meta = scene.setdefault("meta", {})
    if meta.get("mock") or meta.get("processingMode") == "DEMO":
        return []
    previous_issues = set(meta.get("reviewIssues") or [])
    issues = []
    rooms = scene.get("rooms") or []
    areas = [float(room.get("area_m2") or 0.0) for room in rooms]
    total_area = sum(areas)
    level_records = meta.get("levels") or []
    for level in level_records:
        if str(level.get("scaleSource") or "").lower() == "needs-review":
            level_number = int(level.get("level", level.get("floorIndex", 0)) or 0) + 1
            issues.append(f"Scale for floor {level_number} failed sanity checks; calibrate it before trusting the 3D model.")
    if not level_records and str(meta.get("scaleSource") or "").lower() == "needs-review":
        issues.append("Scale failed sanity checks; set it using two known points before trusting the 3D model.")
    if not rooms:
        issues.append("No usable room regions were detected. Review the 2D plan before creating the 3D model.")
    if not 20 <= total_area <= 1500:
        issues.append(f"Estimated building area is {total_area:.1f} m2; expected 20-1500 m2. Check the scale.")
    for room, area in zip(rooms, areas):
        if area < 1.5 or area > 300:
            issues.append(f"Room {room.get('label') or room.get('id')} is {area:.1f} m2; expected 1.5-300 m2.")

    # A single connected white region that occupies almost the whole footprint
    # usually means room dividers or doorway gaps were missed. Do not turn that
    # into an apparently complete 3D model without asking for a 2D review.
    if total_area > 0:
        for room, area in zip(rooms, areas):
            share = area / total_area
            if share > 0.80:
                issues.append(
                    f"Room {room.get('label') or room.get('id')} covers {share * 100:.0f}% of mapped room area; "
                    "check whether the plan contains missed room dividers."
                )
        if len(rooms) <= 1:
            issues.extend(issue for issue in previous_issues if str(issue).startswith("Room split failed:"))

    counts = meta.get("openingCounts") or {}
    detected = int(counts.get("doorsDetected", 0)) + int(counts.get("windowsDetected", 0))
    dropped = int(counts.get("dropped", 0))
    if detected and dropped / detected > 0.40:
        issues.append(f"{dropped} of {detected} detected openings were dropped; review the 2D detections.")
    doors_count = int(counts.get("doorsDetected", len(scene.get("doors") or [])))
    windows_count = int(counts.get("windowsDetected", len(scene.get("windows") or [])))
    if windows_count > 6 * max(doors_count, 1):
        issues.append(f"{windows_count} window candidates for {doors_count} doors is implausible; review the opening detections.")
    for door in scene.get("doors") or []:
        width = float(door.get("width") or 0.0)
        if not 0.7 <= width <= 1.2:
            issues.append(f"Door {door.get('id')} is {width:.2f} m wide; expected 0.7-1.2 m.")

    # Floor crops are aligned by translation only. Their measured dimensions
    # should therefore remain within the same 15% tolerance used at ingestion.
    by_floor = {}
    for room in rooms:
        floor = int(room.get("floorIndex", room.get("level", 0)) or 0)
        polygon = room.get("polygon") or []
        if len(polygon) >= 3:
            by_floor.setdefault(floor, []).extend(polygon)
    floor_bounds = []
    for floor, points in sorted(by_floor.items()):
        try:
            xs = [float(point[0]) for point in points]
            ys = [float(point[1]) for point in points]
            floor_bounds.append((floor, min(xs), min(ys), max(xs), max(ys)))
        except (TypeError, ValueError, IndexError):
            continue
    if len(floor_bounds) > 1:
        reference = floor_bounds[0]
        reference_width = max(reference[3] - reference[1], 1e-6)
        reference_depth = max(reference[4] - reference[2], 1e-6)
        for floor, min_x, min_y, max_x, max_y in floor_bounds[1:]:
            width = max_x - min_x
            depth = max_y - min_y
            mismatch = max(
                abs(width - reference_width) / max(width, reference_width, 1e-6),
                abs(depth - reference_depth) / max(depth, reference_depth, 1e-6),
            )
            if mismatch > 0.15:
                issues.append(
                    f"Floor {floor + 1} footprint differs from the floor below by {mismatch * 100:.1f}%; "
                    "review story alignment."
                )

    unique_issues = list(dict.fromkeys(issues))
    meta["reviewIssues"] = unique_issues
    meta["needsReview"] = bool(unique_issues)
    warnings = meta.setdefault("warnings", [])
    # Replace the old gate messages instead of accumulating stale errors after
    # users calibrate scale or edit their outlines.
    meta["warnings"] = [warning for warning in warnings if warning not in previous_issues]
    warnings = meta["warnings"]
    for issue in unique_issues:
        if issue not in warnings:
            warnings.append(issue)
    return unique_issues


def _rebuild_edited_scene_geometry(scene):
    """Rebuild walls and snap current openings without calling any AI provider."""
    meta = scene.setdefault("meta", {})
    mpp = float(meta.get("metersPerPixel") or 0.0)
    if not math.isfinite(mpp) or mpp <= 0:
        raise ValueError("Set a valid plan scale before rebuilding geometry.")
    wall_thickness = float(meta.get("wallThickness") or DEFAULT_WALL_THICKNESS)
    wall_thickness = min(1.0, max(0.05, wall_thickness))
    rooms = scene.get("rooms") or []
    warnings = []
    rebuilt_walls = []
    kept_doors = []
    kept_windows = []
    floor_indices = sorted({
        int(item.get("floorIndex", item.get("level", 0)) or 0)
        for collection in (rooms, scene.get("doors", []), scene.get("windows", []))
        for item in collection
    }) or [0]
    detected_doors = 0
    detected_windows = 0

    for floor_index in floor_indices:
        level_info = next(
            (level for level in meta.get("levels", []) if int(level.get("level", level.get("floorIndex", 0)) or 0) == floor_index),
            {},
        )
        floor_mpp = float(level_info.get("metersPerPixel") or mpp)
        floor_rooms = [room for room in rooms if int(room.get("floorIndex", room.get("level", 0)) or 0) == floor_index]
        floor_doors = [dict(door) for door in scene.get("doors", []) if int(door.get("floorIndex", door.get("level", 0)) or 0) == floor_index]
        floor_windows = [dict(window) for window in scene.get("windows", []) if int(window.get("floorIndex", window.get("level", 0)) or 0) == floor_index]
        detected_doors += len(floor_doors)
        detected_windows += len(floor_windows)
        floor_walls, _aligned = reconstruct_walls_room_first(floor_rooms, wall_thickness_m=wall_thickness)

        if floor_walls and (floor_doors or floor_windows):
            floor_walls, floor_doors, floor_windows, dropped = snap_openings_and_cut_walls(
                floor_walls,
                floor_doors,
                floor_windows,
                wall_thickness_m=wall_thickness,
                meters_per_pixel=floor_mpp,
                wall_thickness_px=wall_thickness / floor_mpp,
            )
            warnings.extend(dropped)
        elif floor_doors or floor_windows:
            warnings.extend(
                f"{kind.title()} {opening.get('id', 'opening')} removed because no room boundary wall was available to attach it."
                for kind, openings in (("door", floor_doors), ("window", floor_windows))
                for opening in openings
            )
            floor_doors, floor_windows = [], []

        # Recompute door connectivity from the edited room polygons. This keeps
        # route finding consistent when an opening is added or moved.
        room_shapes = []
        for room in floor_rooms:
            try:
                shape = shapely.geometry.Polygon(room.get("polygon", []), room.get("holes", []))
                if shape.is_valid and not shape.is_empty:
                    room_shapes.append((room["id"], shape))
            except Exception:
                continue
        for door in floor_doors:
            center = door.get("center") or [0.0, 0.0]
            point = shapely.geometry.Point(float(center[0]), float(center[1]))
            radius = max(0.45, min(1.0, float(door.get("width") or 0.9) / 2 + 0.25))
            nearby = sorted(
                ((shape.distance(point), room_id) for room_id, shape in room_shapes),
                key=lambda pair: pair[0],
            )
            connected = [room_id for distance, room_id in nearby if distance <= radius][:2]
            if not connected:
                warnings.append(f"Door {door.get('id', 'opening')} removed because it does not connect to a room outline.")
                continue
            if len(connected) == 1:
                connected.append("outside")
            door["connects"] = connected
            kept_doors.append(door)

        kept_windows.extend(floor_windows)
        for index, wall in enumerate(floor_walls, start=len(rebuilt_walls) + 1):
            wall["id"] = f"w{index}"
            wall["floorIndex"] = floor_index
            wall["level"] = floor_index
            rebuilt_walls.append(wall)

    scene["walls"] = rebuilt_walls
    scene["doors"] = kept_doors
    scene["windows"] = kept_windows
    scene["meta"]["openingCounts"] = {
        "doorsDetected": detected_doors,
        "doorsKept": len(kept_doors),
        "windowsDetected": detected_windows,
        "windowsKept": len(kept_windows),
        "dropped": max(0, detected_doors - len(kept_doors)) + max(0, detected_windows - len(kept_windows)),
    }
    scene["meta"]["openingDiagnostics"] = []
    warnings.append("Geometry rebuilt from the edited outlines and openings; segmentation models were not called.")
    meta["warnings"] = list(dict.fromkeys([*(meta.get("warnings") or []), *warnings]))[-80:]
    _apply_scene_sanity_gate(scene)
    return scene


def _run_job(job_id, image_bytes, image_size, filename, meters_per_pixel, wall_height, wall_thickness, calibrate_scale, scale_source="auto", floor_count=1, split_orientation="vertical", split_positions=None):
    def progress(stage, percent):
        with JOBS_LOCK:
            if job_id in JOBS:
                JOBS[job_id].update(stage=stage, progress=percent)

    try:
        result = _build_scene(
            image_bytes, image_size, filename, meters_per_pixel, wall_height, wall_thickness,
            calibrate_scale, progress, scale_source, floor_count, split_orientation, split_positions,
        )
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


@app.errorhandler(400)
def bad_request(error):
    message = getattr(error, "description", "Bad request.")
    return jsonify({"success": False, "error": message, "code": "BAD_REQUEST"}), 400


@app.errorhandler(404)
def not_found(error):
    message = getattr(error, "description", "Resource not found.")
    return jsonify({"success": False, "error": message, "code": "NOT_FOUND"}), 404


@app.errorhandler(405)
def method_not_allowed(_error):
    return jsonify({"success": False, "error": "Method not allowed.", "code": "METHOD_NOT_ALLOWED"}), 405


@app.errorhandler(413)
def request_too_large(_error):
    return jsonify({"success": False, "error": "The image must be 10 MB or smaller.", "code": "PAYLOAD_TOO_LARGE"}), 413


@app.errorhandler(500)
def server_error(error):
    app.logger.exception("Internal server error: %s", error)
    return jsonify({
        "success": False,
        "error": "An internal server error occurred. Details were logged.",
        "code": "SERVER_ERROR",
    }), 500


@app.route("/")
def index():
    return render_template(
        "index.html",
        processing_ready=True,
        processing_mode=_processing_mode(),
        sam_ready=sam_ready(),
        labeling_ready=labeling_ready(),
        labeling_provider_name=get_labeling_provider_name(),
        image_generation_ready=image_generation_ready(),
        voice_transcription_ready=voice_transcription_ready(),
    )


@app.route("/api/config/status", methods=["GET"])
def config_status():
    from config import get_config_status
    return jsonify(get_config_status())


@app.route("/api/health", methods=["GET"])
def health():
    mode = _processing_mode()
    return jsonify({
        "status": "online",
        "service": "FloorPlan3D",
        "pipeline_ready": True,
        "segmentation_ready": True,
        "sam_ready": sam_ready(),
        "labeling_ready": labeling_ready(),
        "image_generation_ready": image_generation_ready(),
        "voice_transcription_ready": voice_transcription_ready(),
        "live_processing_ready": mode != "MOCK" and (sam_ready() or labeling_ready()),
        "segmentation_mode": (
            "mock-sample" if mode == "MOCK"
            else "sam-3.1" if sam_ready()
            else "opencv-heuristic"
        ),
        "processing_mode": mode,
    })


@app.route("/api/usage", methods=["GET"])
def provider_usage():
    return jsonify({"success": True, "provider": "Meta Model API", "usage": get_provider_usage()})


@app.route("/api/scene/rebuild-geometry", methods=["POST"])
def rebuild_scene_geometry():
    """Apply reviewed 2D edits locally; this endpoint never calls SAM or Muse."""
    payload = request.get_json(silent=True) or {}
    scene = payload.get("scene")
    if not isinstance(scene, dict):
        return jsonify({"success": False, "error": "A valid scene is required to rebuild geometry."}), 400
    try:
        validate_scene_contract(scene)
        rebuilt = _rebuild_edited_scene_geometry(scene)
        validate_scene_contract(rebuilt)
        return jsonify({"success": True, "scene": _json_compatible(rebuilt), "provider": "Local geometry rebuild (no model calls)"})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except RuntimeError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception:
        app.logger.exception("Edited-scene geometry rebuild failed")
        return jsonify({"success": False, "error": "Could not rebuild the edited geometry. Details were logged on the server."}), 500


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
    route = _extract_route_request(question.strip(), facts)
    if route:
        return jsonify({
            "success": True,
            "answer": f"Finding the door-aware route from {route['startLabel']} to {route['endLabel']} using the current scene.",
            "provider": "Scene route planner (current geometry)",
            "route": route,
        })
    answer = answer_scene_question(question.strip(), facts) if labeling_ready() else None
    labeling_prov = get_labeling_provider_name()
    if labeling_prov.startswith("Meta"):
        provider = "Meta Muse Spark (scene-grounded)" if answer else "Offline scene lookup (Muse returned no usable answer)"
    else:
        provider = "Baseten Muse Spark Open (scene-grounded)" if answer else "Offline scene lookup (Baseten returned no usable answer)"
    if not answer:
        answer = _offline_scene_answer(question.strip(), facts)
    return jsonify({
        "success": True,
        "answer": answer,
        "provider": provider,
    })


@app.route("/api/scene/insight", methods=["POST"])
def scene_insight():
    payload = request.get_json(silent=True) or {}
    kind = payload.get("kind")
    scene = payload.get("scene")
    if kind not in {"review", "summary"}:
        return jsonify({"success": False, "error": "Choose review or summary."}), 400
    if not isinstance(scene, dict):
        return jsonify({"success": False, "error": "Load a floor-plan scene first."}), 400
    retry_after = _rate_limit_question(request.remote_addr or "unknown")
    if retry_after:
        response = jsonify({"success": False, "error": "Map assistant rate limit reached. Wait before asking again."})
        response.headers["Retry-After"] = str(retry_after)
        return response, 429
    try:
        validate_scene_contract(scene)
    except RuntimeError:
        return jsonify({"success": False, "error": "The current map is not valid enough to review."}), 400

    facts = _build_scene_facts(scene)
    review = _scene_review_facts(scene, facts)
    kind_prompt = (
        "Write a short structural review from these computed findings only. Prioritize items marked check. "
        "Do not invent defects or make code, construction, or safety claims. Areas are estimates."
        if kind == "review" else
        "Write a concise building summary from these computed scene facts only. Include floor and room counts, "
        "estimated area, and detected geometry counts. Do not invent facts; state that measurements are estimates."
    )
    ai_answer = answer_scene_question(kind_prompt + "\nComputed review facts: " + json.dumps(review, ensure_ascii=False), facts) if labeling_ready() else None
    answer = ai_answer or _offline_scene_insight(kind, review, facts)
    labeling_prov = get_labeling_provider_name()
    if labeling_prov.startswith("Meta"):
        provider = "Meta Muse Spark (scene-grounded)" if ai_answer else "Offline scene analysis (Muse returned no usable answer)"
    else:
        provider = "Baseten Muse Spark Open (scene-grounded)" if ai_answer else "Offline scene analysis (Baseten returned no usable answer)"
    return jsonify({"success": True, "kind": kind, "answer": answer, "provider": provider, "review": review})


@app.route("/api/sample", methods=["GET"])
def sample_data():
    try:
        with open(SAMPLE_IMG_PATH, "rb") as sample_file:
            data_url = "data:image/png;base64," + base64.b64encode(sample_file.read()).decode("ascii")
        scene = get_sample_scene_json()
        scene["meta"]["processingMode"] = "DEMO"
        scene["meta"].setdefault("warnings", []).append(
            "Curated demo scene with predefined geometry and labels; loading it does not run a model."
        )
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


@app.route("/api/sample/<sample_id>", methods=["GET"])
def saved_sample_data(sample_id):
    """Load a precomputed review sample without running any model provider."""
    saved_samples = {
        "two-plans": ("two_plans_test.json", "two_plans_test.png"),
        "three-story": ("three_story.json", "three_story.png"),
        "four-story": ("four_story.json", "four_story.png"),
    }
    entry = saved_samples.get(sample_id)
    if not entry:
        return jsonify({"success": False, "error": "That saved sample does not exist."}), 404

    sample_root = os.path.join(app.root_path, "samples", "demo_plans")
    scene_path = os.path.join(sample_root, entry[0])
    image_path = os.path.join(sample_root, entry[1])
    try:
        with open(scene_path, "r", encoding="utf-8") as scene_file:
            scene = json.load(scene_file)
        with open(image_path, "rb") as image_file:
            image_bytes = image_file.read()
        scene.setdefault("meta", {})["processingMode"] = "DEMO"
        scene["meta"]["preparedSample"] = True
        scene["meta"]["liveInferenceAtLoad"] = False
        if sample_id in {"three-story", "four-story"}:
            scene["meta"]["sampleLabel"] = f"{scene['meta'].get('levelCount', 3)}-story prepared building"
        scene["meta"].setdefault("warnings", []).append(
            "Saved sample scene. Review its estimated geometry against the source plan."
        )
        validate_scene_contract(scene)
        overlays = {
            "room": [{"id": room.get("id"), "label": room.get("label"), "polygon": room.get("polygon", [])} for room in scene.get("rooms", [])],
            "wall": [{"id": wall.get("id"), "polygon": wall.get("polygon", [])} for wall in scene.get("walls", [])],
            "door": [{"id": door.get("id"), "center": door.get("center", []), "width": door.get("width")} for door in scene.get("doors", [])],
            "window": [{"id": window.get("id"), "center": window.get("center", []), "width": window.get("width")} for window in scene.get("windows", [])],
        }
        mime = "image/jpeg" if image_path.lower().endswith((".jpg", ".jpeg")) else "image/png"
        return jsonify({
            "success": True,
            "scene": scene,
            "overlays": _json_compatible(overlays),
            "imageUrl": f"data:{mime};base64," + base64.b64encode(image_bytes).decode("ascii"),
            "demoMode": True,
        })
    except FileNotFoundError:
        app.logger.error("Saved sample assets are missing for %s", sample_id)
        return jsonify({"success": False, "error": "This sample's saved scene or source image is missing."}), 404
    except Exception:
        app.logger.exception("Could not load saved sample %s", sample_id)
        return jsonify({"success": False, "error": "The saved sample could not be loaded."}), 500


@app.route("/api/sample_image", methods=["GET"])
def sample_image():
    return send_file(SAMPLE_IMG_PATH, mimetype="image/png")


@app.route("/api/generate-floorplan", methods=["POST"])
def generate_floorplan_image():
    retry_after = _rate_limit_upload(request.remote_addr or "unknown")
    if retry_after:
        return jsonify({"success": False, "error": "Generation rate limit reached. Please wait before trying again."}), 429
    if not image_generation_ready():
        return jsonify({"success": False, "error": "Muse Image requires MODEL_API_KEY or META_API_KEY."}), 503
    payload = request.get_json(silent=True) or {}
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not 8 <= len(prompt.strip()) <= 500:
        return jsonify({"success": False, "error": "Describe the plan in 8 to 500 characters."}), 400
    try:
        image_bytes = generate_floorplan(prompt.strip())
        data_url = "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")
        return jsonify({"success": True, "imageUrl": data_url, "model": os.getenv("MUSE_IMAGE_MODEL", "muse-image-1.0")})
    except Exception as exc:
        app.logger.warning("Muse Image generation failed (%s)", type(exc).__name__)
        return jsonify({"success": False, "error": "Muse Image could not generate a plan. Check model access and try again."}), 502


@app.route("/api/transcribe", methods=["POST"])
def transcribe_map_question():
    retry_after = _rate_limit_upload(request.remote_addr or "unknown")
    if retry_after:
        return jsonify({"success": False, "error": "Transcription rate limit reached. Please wait before trying again."}), 429
    if not voice_transcription_ready():
        return jsonify({"success": False, "error": "Muse Voice Transcribe requires MODEL_API_KEY or META_API_KEY."}), 503
    audio = request.files.get("audio")
    if not audio or not audio.filename:
        return jsonify({"success": False, "error": "Choose a WAV recording first."}), 400
    try:
        transcript = transcribe_audio(audio.read(32 * 1024 * 1024 + 1), audio.filename)
        return jsonify({"success": True, "transcript": transcript, "model": os.getenv("MUSE_VOICE_MODEL", "muse-voice-transcribe-1.0")})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        app.logger.warning("Muse Voice Transcribe failed (%s)", type(exc).__name__)
        return jsonify({"success": False, "error": "Meta transcription is unavailable. Check model access and try again."}), 502


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
        scale_source = request.form.get("scaleSource", "auto").strip().lower()
        if scale_source not in {"auto", "user", "manual"}:
            raise ValueError("Scale source must be auto, user, or manual.")
        floor_count = int(_number_field("floorCount", 1, 1, 3))
        split_orientation = request.form.get("splitOrientation", "vertical").strip().lower()
        split_positions = []
        if floor_count >= 2:
            split_positions.append(_number_field("splitPosition1", 0.5, 0.08, 0.92))
        if floor_count >= 3:
            split_positions.append(_number_field("splitPosition2", 0.67, 0.08, 0.92))
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
        args=(
            job_id, image_bytes, image_size, filename, mpp, wall_height, wall_thickness,
            calibrate_scale, scale_source, floor_count, split_orientation, split_positions,
        ),
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
        return jsonify(_json_compatible(job["result"]))


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
