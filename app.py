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
from meta_sam_service import is_sam_configured, query_sam_concept, SamEmptyOutcome, SamFailedOutcome
from meta_media_service import generate_floorplan, image_generation_ready, transcribe_audio, voice_transcription_ready
from demo_data import generate_sample_floorplan_image, get_sample_mask_overlays, get_sample_scene_json, get_two_story_sample_scene_json
from geometry_processor import (
    build_walls_from_rooms,
    check_axis_aligned_fraction,
    detect_doors_and_windows_geometrically,
    estimate_meters_per_pixel_from_doors,
    extract_doors,
    extract_windows,
    mask_to_polygons_with_holes,
    reconstruct_walls_from_mask_orthogonal,
    reconstruct_walls_room_first,
    snap_openings_and_cut_walls,
    snap_polygon_orthogonal,
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
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

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


def segmentation_ready():
    return True


def labeling_ready():
    return is_labeling_configured()


def sam_ready():
    return is_sam_configured()


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
        {"status": "check" if not doors else "ok", "title": "Door openings", "detail": f"{len(doors)} (estimated from wall gaps; SAM found none)" if (doors and all(d.get("source") == "estimated" for d in doors)) else f"{len(doors)} door opening(s) are recorded; compare them with the source plan."},
        {"status": "check" if len(floor_ids) > 1 and not connectors else "ok", "title": "Floor connection", "detail": f"{len(connectors)} stair/elevator room(s) are recorded across {len(floor_ids) or 1} floor(s)."},
        {"status": "check" if not interactive_scale or "fallback" in scale_method else "ok", "title": "Scale", "detail": "Scale is an estimate; verify it against a known dimension." if not interactive_scale else "Interactive scale calibration is recorded; still verify against a known dimension."},
        {"status": "check" if named_rooms < len(rooms) else "ok", "title": "Room labels", "detail": f"{named_rooms} of {len(rooms)} rooms have specific labels."},
        {"status": "info", "title": "Windows", "detail": f"{len(windows)} (estimated from line symbols; SAM found none)" if (windows and all(w.get("source") == "estimated" for w in windows)) else f"{len(windows)} window opening(s) are recorded."},
    ]
    sam_status = meta.get("sam_status", {})
    for concept, sinfo in sam_status.items():
        if isinstance(sinfo, dict):
            status = sinfo.get("status")
            if status == "FAILED":
                findings.append({"status": "check", "title": f"SAM {concept}", "detail": f"SAM failed for '{concept}': {sinfo.get('reason', 'unknown error')}."})
            elif status == "EMPTY":
                findings.append({"status": "check", "title": f"SAM {concept}", "detail": f"SAM found no '{concept}'."})
            elif status == "OK":
                findings.append({"status": "ok", "title": f"SAM {concept}", "detail": f"SAM detected {sinfo.get('count', 1)} matching region(s)."})
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


def _process_story_slice(image_bytes, image_size, meters_per_pixel, wall_height, wall_thickness, calibrate_scale, progress, deadline, use_sam, processing_mode, image_url, story_index=0, filename=""):
    warnings = []
    concepts = ("room", "wall", "door", "window")
    try:
        prepared_image = prepare_segmentation(image_bytes, image_size)
    except (ValueError, cv2.error) as exc:
        raise ProviderError("configuration", str(exc)) from exc

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix=f"local-segmentation-s{story_index}")
    def segment_one(concept):
        if use_sam:
            try:
                masks = query_sam_concept(
                    image_bytes,
                    concept,
                    image_size,
                    timeout=min(75, max(1, deadline - time.monotonic())),
                )
                concept_used = getattr(masks, "concept_used", concept)
                return masks, "sam-3.1", None, {"status": "OK", "count": len(masks), "concept_used": concept_used}
            except SamEmptyOutcome as exc:
                logger.info("SAM found no %s: %s", concept, exc)
                return segment_prepared_concept(prepared_image, concept), "opencv-fallback", "no_matches", {"status": "EMPTY", "reason": getattr(exc, "reason", f"SAM found no '{concept}'"), "concept": concept}
            except Exception as exc:
                outcome = getattr(exc, "outcome", None)
                reason = getattr(exc, "reason", str(exc))
                cat = getattr(exc, "safe_category", "unavailable")
                if outcome == "EMPTY" or cat == "no_matches":
                    return segment_prepared_concept(prepared_image, concept), "opencv-fallback", "no_matches", {"status": "EMPTY", "reason": f"SAM found no '{concept}'", "concept": concept}
                logger.warning("SAM failed for %s (%s): %s", concept, type(exc).__name__, reason)
                return segment_prepared_concept(prepared_image, concept), "opencv-fallback", cat, {"status": "FAILED", "reason": reason, "concept": concept}
        return segment_prepared_concept(prepared_image, concept), "opencv-heuristic", None, {"status": "NOT_RUN", "reason": "no live key or local mode", "concept": concept}

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
    sam_status_by_concept = {}
    concept_used_by_concept = {}
    room_failure = None
    for future in done:
        concept = futures[future]
        try:
            masks_by_concept[concept], backends_by_concept[concept], provider_error, sinfo = future.result()
            sam_status_by_concept[concept] = sinfo
            if sinfo.get("concept_used"):
                concept_used_by_concept[concept] = sinfo["concept_used"]
            if not use_sam:
                warnings.append(f"SAM not run (no live key or local mode); {concept} detection used local OpenCV.")
            elif sinfo["status"] == "EMPTY":
                warnings.append(f"SAM found no '{concept}'.")
            elif sinfo["status"] == "FAILED":
                warnings.append(f"SAM failed for '{concept}': {sinfo.get('reason', 'unavailable')}.")
        except Exception as exc:
            logger.exception("Local %s segmentation failed", concept)
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
    wall_masks = masks_by_concept["wall"]
    door_masks = masks_by_concept["door"]
    window_masks = masks_by_concept["window"]

    scale_method = "manual"
    if calibrate_scale:
        estimated_scale = estimate_meters_per_pixel_from_doors(door_masks)
        if estimated_scale is not None and 0.01 <= estimated_scale <= 0.08:
            meters_per_pixel = estimated_scale
            scale_method = "median detected door width (assumed 0.9 m)"
        else:
            scale_method = "manual fallback; no reliable door width detected"

    rooms_data = []
    prefix = f"s{story_index}_" if story_index > 0 else ""
    for mask in room_masks:
        for polygon in mask_to_polygons_with_holes(mask, meters_per_pixel=meters_per_pixel, min_area_px=200):
            room_num = len(rooms_data) + 1
            room_id = f"{prefix}r{room_num}"
            default_label = f"Room G{room_num}" if story_index == 0 else f"Room {story_index}.{room_num}"
            rooms_data.append({
                "id": room_id,
                "type": "room",
                "label": default_label,
                "confidence": 0.0,
                "polygon": polygon["polygon"],
                "centroid": polygon["centroid"],
                "area_m2": polygon["area_m2"],
            })

    if not rooms_data:
        raise ValueError("No rooms were detected. Try a clearer, higher-contrast floor plan.")

    used_sam = any(value == "sam-3.1" for value in backends_by_concept.values())
    used_fallback = any(value == "opencv-fallback" for value in backends_by_concept.values())
    if used_sam and used_fallback:
        segmentation_backend = "sam-3.1+opencv-fallback"
    elif used_sam:
        segmentation_backend = "sam-3.1"
    elif use_sam:
        segmentation_backend = "opencv-fallback"
    else:
        segmentation_backend = "opencv-heuristic"

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

    cleaned_rooms = [
        {key: room[key] for key in ("id", "type", "label", "confidence", "polygon")}
        for room in rooms_data
    ]
    for idx, r in enumerate(cleaned_rooms):
        r["centroid"] = rooms_data[idx]["centroid"]
        r["area_m2"] = rooms_data[idx]["area_m2"]

    # Snap room polygons orthogonally (7 degrees, 0.15m merge)
    for r in rooms_data:
        r["polygon"] = snap_polygon_orthogonal(r["polygon"], tolerance_deg=7.0, snap_dist=0.15)

    cleaned_rooms = [
        {key: room[key] for key in ("id", "type", "label", "confidence", "polygon")}
        for room in rooms_data
    ]
    for idx, r in enumerate(cleaned_rooms):
        r["centroid"] = rooms_data[idx]["centroid"]
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

    for idx, w in enumerate(walls_data):
        w["id"] = f"{prefix}w{idx + 1}" 

    sam_door_ok = sam_status_by_concept.get("door", {}).get("status") == "OK"
    sam_win_ok = sam_status_by_concept.get("window", {}).get("status") == "OK"

    doors_data = extract_doors(door_masks, cleaned_rooms, meters_per_pixel=meters_per_pixel) if sam_door_ok else []
    for d in doors_data:
        d["source"] = "sam"
    windows_data = extract_windows(window_masks, meters_per_pixel=meters_per_pixel) if sam_win_ok else []
    for win in windows_data:
        win["source"] = "sam"

    # Geometric fallback from drawing when SAM finds none or not run
    if not doors_data or not windows_data:
        geo_doors, geo_windows, med_door_w = detect_doors_and_windows_geometrically(image_bytes, meters_per_pixel)
        if not doors_data and geo_doors:
            doors_data = geo_doors
            if calibrate_scale and med_door_w and 15 <= med_door_w <= 100:
                old_mpp = meters_per_pixel
                meters_per_pixel = round(0.90 / med_door_w, 5)
                scale_method = f"median detected door width ({int(med_door_w)} px -> 0.90 m)"
                scale_ratio = meters_per_pixel / old_mpp
                # Rescale rooms and walls to match calibrated meters_per_pixel
                import shapely.geometry
                from shapely.validation import make_valid
                for r in cleaned_rooms:
                    r["polygon"] = [[round(pt[0] * scale_ratio, 3), round(pt[1] * scale_ratio, 3)] for pt in r.get("polygon", [])]
                    try:
                        p_check = shapely.geometry.Polygon(r["polygon"])
                        if not p_check.is_valid:
                            vp = make_valid(p_check)
                            if vp.geom_type == "Polygon":
                                r["polygon"] = [[round(pt[0], 3), round(pt[1], 3)] for pt in list(vp.exterior.coords)[:-1]]
                            elif vp.geom_type == "MultiPolygon":
                                largest = max(vp.geoms, key=lambda g: g.area)
                                r["polygon"] = [[round(pt[0], 3), round(pt[1], 3)] for pt in list(largest.exterior.coords)[:-1]]
                    except Exception:
                        pass
                    if "centroid" in r:
                        r["centroid"] = [round(r["centroid"][0] * scale_ratio, 3), round(r["centroid"][1] * scale_ratio, 3)]
                    if "area_m2" in r:
                        r["area_m2"] = round(r["area_m2"] * scale_ratio * scale_ratio, 2)
                for w in walls_data:
                    w["polygon"] = [[round(pt[0] * scale_ratio, 3), round(pt[1] * scale_ratio, 3)] for pt in w.get("polygon", [])]
                    if w.get("holes"):
                        w["holes"] = [[[round(pt[0] * scale_ratio, 3), round(pt[1] * scale_ratio, 3)] for pt in hole] for hole in w["holes"]]
                for d in doors_data:
                    if "pixel_center" in d:
                        d["center"] = [round(d["pixel_center"][0] * meters_per_pixel, 3), round(d["pixel_center"][1] * meters_per_pixel, 3)]
        if not windows_data and geo_windows:
            windows_data = geo_windows
            if calibrate_scale and med_door_w and 15 <= med_door_w <= 100:
                for win in windows_data:
                    if "pixel_center" in win:
                        win["center"] = [round(win["pixel_center"][0] * meters_per_pixel, 3), round(win["pixel_center"][1] * meters_per_pixel, 3)]

    for idx, d in enumerate(doors_data):
        d["id"] = f"{prefix}d{idx + 1}"
    for idx, win in enumerate(windows_data):
        win["id"] = f"{prefix}win{idx + 1}"

    # Snap openings to walls, cut rectangular opening gaps, and compute connects
    walls_data, doors_data, windows_data, dropped_openings = snap_openings_and_cut_walls(
        walls_data, doors_data, windows_data, wall_thickness_m=wall_thickness, cleaned_rooms=cleaned_rooms
    )
    for drop_msg in dropped_openings:
        warnings.append(drop_msg)

    return {
        "rooms": cleaned_rooms,
        "walls": walls_data,
        "doors": doors_data,
        "windows": windows_data,
        "warnings": warnings,
        "meters_per_pixel": meters_per_pixel,
        "scale_method": scale_method,
        "segmentation_backend": segmentation_backend,
        "wall_method": wall_method,
        "sam_status": sam_status_by_concept,
        "concept_used": concept_used_by_concept,
    }


def _build_scene(image_bytes, image_size, filename, meters_per_pixel, wall_height, wall_thickness, calibrate_scale, progress):
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

    crops = split_multi_plan_image(image_bytes) if processing_mode != "MOCK" else [(image_bytes, (0, 0, img_w, img_h))]
    slab_thickness = 0.2

    if len(crops) >= 2:
        warnings.append("Multi-story plan detected in single image; automatically split into 2 stories.")
        progress("Processing Ground Floor story", 30)
        crop0_bytes, bbox0 = crops[0]
        with Image.open(io.BytesIO(crop0_bytes)) as c0_img:
            c0_size = c0_img.size
        c0_url = "data:image/png;base64," + base64.b64encode(crop0_bytes).decode("ascii")
        res0 = _process_story_slice(crop0_bytes, c0_size, meters_per_pixel, wall_height, wall_thickness, calibrate_scale, progress, deadline, use_sam, processing_mode, c0_url, story_index=0, filename=filename)

        shared_mpp = res0.get("meters_per_pixel", meters_per_pixel)
        progress("Processing Second Floor story", 65)
        crop1_bytes, bbox1 = crops[1]
        with Image.open(io.BytesIO(crop1_bytes)) as c1_img:
            c1_size = c1_img.size
        c1_url = "data:image/png;base64," + base64.b64encode(crop1_bytes).decode("ascii")
        res1 = _process_story_slice(crop1_bytes, c1_size, shared_mpp, wall_height, wall_thickness, False, progress, deadline, use_sam, processing_mode, c1_url, story_index=1, filename=filename)

        coords0 = [pt for r in res0["rooms"] for pt in r["polygon"]]
        coords1 = [pt for r in res1["rooms"] for pt in r["polygon"]]
        if coords0 and coords1:
            x_min_0 = min(pt[0] for pt in coords0)
            y_min_0 = min(pt[1] for pt in coords0)
            x_min_1 = min(pt[0] for pt in coords1)
            y_min_1 = min(pt[1] for pt in coords1)
            dx = round(x_min_0 - x_min_1, 3)
            dy = round(y_min_0 - y_min_1, 3)
        else:
            dx, dy = 0.0, 0.0

        for r in res0["rooms"]:
            r["floor"] = 0
            r["floorIndex"] = 0
            r["level"] = 0
        for w in res0["walls"]:
            w["floorIndex"] = 0
            w["level"] = 0
        for d in res0["doors"]:
            d["floorIndex"] = 0
            d["level"] = 0
        for win in res0["windows"]:
            win["floorIndex"] = 0
            win["level"] = 0

        for r in res1["rooms"]:
            r["polygon"] = [[round(p[0] + dx, 3), round(p[1] + dy, 3)] for p in r["polygon"]]
            if "centroid" in r:
                r["centroid"] = [round(r["centroid"][0] + dx, 3), round(r["centroid"][1] + dy, 3)]
            r["floor"] = 1
            r["floorIndex"] = 1
            r["level"] = 1
        for w in res1["walls"]:
            w["polygon"] = [[round(p[0] + dx, 3), round(p[1] + dy, 3)] for p in w["polygon"]]
            w["holes"] = [[[round(p[0] + dx, 3), round(p[1] + dy, 3)] for p in h] for h in w.get("holes", [])]
            w["floorIndex"] = 1
            w["level"] = 1
        for d in res1["doors"]:
            d["center"] = [round(d["center"][0] + dx, 3), round(d["center"][1] + dy, 3)]
            d["floorIndex"] = 1
            d["level"] = 1
        for win in res1["windows"]:
            win["center"] = [round(win["center"][0] + dx, 3), round(win["center"][1] + dy, 3)]
            win["floorIndex"] = 1
            win["level"] = 1

        stair0 = next((r for r in res0["rooms"] if "stair" in r.get("type", "").lower() or "stair" in r.get("label", "").lower()), None)
        stair1 = next((r for r in res1["rooms"] if "stair" in r.get("type", "").lower() or "stair" in r.get("label", "").lower()), None)
        if stair0 and stair1:
            stair_dist = math.hypot(stair0["centroid"][0] - stair1["centroid"][0], stair0["centroid"][1] - stair1["centroid"][1])
            if stair_dist > 1.0:
                warnings.append("stairs not aligned between floors")
            stair0["connectsTo"] = stair1["id"]
            stair1["connectsTo"] = stair0["id"]
            stair0["type"] = "stairs"
            stair1["type"] = "stairs"

        for w_item in res0["warnings"] + res1["warnings"]:
            if w_item not in warnings:
                warnings.append(w_item)

        mpp = res0.get("meters_per_pixel", meters_per_pixel)
        scale_method = res0.get("scale_method", "manual")
        segmentation_backend = res0.get("segmentation_backend", "opencv-fallback")

        cleaned_rooms = res0["rooms"] + res1["rooms"]
        walls_data = res0["walls"] + res1["walls"]
        doors_data = res0["doors"] + res1["doors"]
        windows_data = res0["windows"] + res1["windows"]

        combined_sam = dict(res0.get("sam_status", {}), **res1.get("sam_status", {}))
        combined_cu = dict(res0.get("concept_used", {}), **res1.get("concept_used", {}))
        scene = {
            "meta": {
                "source": filename,
                "sam_status": combined_sam,
                "concept_used": combined_cu,
                "segmentation": segmentation_backend,
                "mock": processing_mode == "MOCK",
                "imageSize": [img_w, img_h],
                "metersPerPixel": mpp,
                "scaleMethod": scale_method,
                "wallHeight": wall_height,
                "wallThickness": wall_thickness,
                "wall_method": res0.get("wall_method", "room-boundary-reconstruction"),
                "floorHeight": round(wall_height + slab_thickness, 2),
                "slabThickness": slab_thickness,
                "levelCount": 2,
                "levels": [
                    {"level": 0, "floorIndex": 0, "name": "Ground Floor", "elevation": 0.0, "planOffset": [-round(bbox0[0] * shared_mpp, 3), -round(bbox0[1] * shared_mpp, 3)]},
                    {"level": 1, "floorIndex": 1, "name": "Second Floor", "elevation": round(wall_height + slab_thickness, 2), "planOffset": [round(dx - bbox1[0] * shared_mpp, 3), round(dy - bbox1[1] * shared_mpp, 3)]},
                ],
                "storyOffsets": [
                    {"level": 0, "dx": 0.0, "dy": 0.0},
                    {"level": 1, "dx": dx, "dy": dy},
                ],
                "warnings": warnings,
            },
            "rooms": cleaned_rooms,
            "walls": walls_data,
            "doors": doors_data,
            "windows": windows_data,
        }
    else:
        progress("Detecting rooms, walls, doors, and windows", 30)
        res = _process_story_slice(image_bytes, image_size, meters_per_pixel, wall_height, wall_thickness, calibrate_scale, progress, deadline, use_sam, processing_mode, image_url, story_index=0, filename=filename)
        for w_item in res["warnings"]:
            if w_item not in warnings:
                warnings.append(w_item)
        cleaned_rooms = res["rooms"]
        walls_data = res["walls"]
        doors_data = res["doors"]
        windows_data = res["windows"]
        mpp = res["meters_per_pixel"]
        scale_method = res["scale_method"]
        segmentation_backend = res["segmentation_backend"]

        scene = {
            "meta": {
                "source": filename,
                "sam_status": res.get("sam_status", {}),
                "concept_used": res.get("concept_used", {}),
                "processingMode": "MOCK" if processing_mode == "MOCK" else "LIVE" if "sam-3.1" in segmentation_backend else "LOCAL",
                "segmentation": segmentation_backend,
                "mock": processing_mode == "MOCK",
                "imageSize": [img_w, img_h],
                "metersPerPixel": mpp,
                "scaleMethod": scale_method,
                "wallHeight": wall_height,
                "wallThickness": wall_thickness,
                "wall_method": res.get("wall_method", "room-boundary-reconstruction"),
                "warnings": warnings,
            },
            "rooms": cleaned_rooms,
            "walls": walls_data,
            "doors": doors_data,
            "windows": windows_data,
        }

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
        "live_processing_ready": sam_ready() or labeling_ready(),
        "segmentation_mode": "sam-3.1" if sam_ready() else "opencv-heuristic",
        "processing_mode": mode,
    })


@app.route("/api/usage", methods=["GET"])
def provider_usage():
    return jsonify({"success": True, "provider": "Meta Model API", "usage": get_provider_usage()})


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
