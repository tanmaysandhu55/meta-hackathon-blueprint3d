"""Run FloorPlan3D's upload pipeline against a local floor-plan evaluation set.

The script imports the same scene builder used by /api/upload. It does not
change application behavior. SAM calls are made only with ``--mode sam`` (or
when ``--mode current`` resolves to the live SAM mode); Muse labeling is
disabled unless ``--with-muse-labeling`` is supplied.

Expected-count format (samples/eval/expected.json)::

    {"plan-a.png": {"floors": 1, "rooms": 5, "area_m2": 120}}

The room and area expectations are treated as rough checks (±35% and ±50%
respectively). ``floors`` is an exact check.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import math
import re
import sys
import threading
import textwrap
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from shapely.geometry import Polygon

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app as app_module  # noqa: E402  (app imports rely on repository root)


CONCEPTS = ("room", "wall", "door", "window", "staircase", "corridor")
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
CAPTURE_LOCK = threading.Lock()
STORY_CONTEXT = threading.local()


def _safe_name(path: Path) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", path.stem).strip("._") or "plan"


def _image_key(image_bytes: bytes) -> str:
    return hashlib.sha1(image_bytes).hexdigest()


def _load_font(size=16):
    try:
        return ImageFont.truetype("arial.ttf", size)
    except OSError:
        return ImageFont.load_default()


def _banner(image, text, color=(25, 35, 55)):
    output = image.copy().convert("RGB")
    draw = ImageDraw.Draw(output)
    draw.rectangle((0, 0, output.width, 30), fill=color)
    draw.text((8, 6), text, fill="white", font=_load_font(15))
    return output


def _decode_data_url(data_url):
    try:
        raw = base64.b64decode(data_url.split(",", 1)[1])
        return Image.open(io.BytesIO(raw)).convert("RGB")
    except (ValueError, IndexError, OSError):
        return None


def _mask_overlay(base, masks, title, color):
    canvas = np.asarray(base.convert("RGB")).copy()
    if masks:
        combined = np.zeros(canvas.shape[:2], dtype=np.uint8)
        for entry in masks:
            if isinstance(entry, dict):
                mask = entry.get("mask")
                origin_x, origin_y = entry.get("origin", (0, 0))
                bounds = entry.get("bounds")
            else:
                mask = entry
                origin_x, origin_y = 0, 0
                bounds = None
            if mask is None:
                continue
            array = np.asarray(mask, dtype=np.uint8)
            if array.ndim != 2 or not array.size:
                continue
            if bounds and len(bounds) == 4:
                _bx, _by, target_width, target_height = map(int, bounds)
            else:
                target_width, target_height = array.shape[1], array.shape[0]
            if target_width <= 0 or target_height <= 0:
                continue
            if array.shape != (target_height, target_width):
                array = cv2.resize(array, (target_width, target_height), interpolation=cv2.INTER_NEAREST)
            x0, y0 = int(origin_x), int(origin_y)
            x1, y1 = x0 + target_width, y0 + target_height
            clipped_x0, clipped_y0 = max(0, x0), max(0, y0)
            clipped_x1, clipped_y1 = min(canvas.shape[1], x1), min(canvas.shape[0], y1)
            if clipped_x1 <= clipped_x0 or clipped_y1 <= clipped_y0:
                continue
            source = array[clipped_y0 - y0:clipped_y1 - y0, clipped_x0 - x0:clipped_x1 - x0]
            combined[clipped_y0:clipped_y1, clipped_x0:clipped_x1] = cv2.bitwise_or(
                combined[clipped_y0:clipped_y1, clipped_x0:clipped_x1], source
            )
        tint = np.zeros_like(canvas)
        tint[:] = color
        active = combined > 0
        canvas[active] = (canvas[active].astype(np.float32) * 0.42 + tint[active].astype(np.float32) * 0.58).astype(np.uint8)
    image = Image.fromarray(canvas)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, image.width, 30), fill=(25, 35, 55))
    draw.text((8, 6), title, fill="white", font=_load_font(15))
    if not masks:
        draw.text((12, 42), "No masks returned for this concept in this run.", fill=(190, 35, 35), font=_load_font(16))
    return image


def _draw_scene_polygons(base, polygons, mpp, fill, outline=None, width=2):
    canvas = base.convert("RGBA")
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    if mpp <= 0:
        return canvas.convert("RGB")
    for ring in polygons:
        if len(ring) < 3:
            continue
        points = [(round(float(point[0]) / mpp), round(float(point[1]) / mpp)) for point in ring]
        draw.polygon(points, fill=fill, outline=outline, width=width if outline else 1)
    return Image.alpha_composite(canvas, layer).convert("RGB")


def _draw_story_entities(base, entities, mpp, origins, offsets, fill, outline, width=2):
    canvas = base.convert("RGBA")
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for entity in entities:
        floor = int(entity.get("floorIndex", entity.get("level", 0)) or 0)
        ox, oy = origins.get(floor, (0, 0))
        dx, dy = offsets.get(floor, (0.0, 0.0))
        for ring in [entity.get("polygon", []), *entity.get("holes", [])]:
            if len(ring) < 3:
                continue
            points = [(round((float(point[0]) - dx) / mpp + ox), round((float(point[1]) - dy) / mpp + oy)) for point in ring]
            draw.polygon(points, fill=fill, outline=outline, width=width)
    return Image.alpha_composite(canvas, layer).convert("RGB")


def _polygon_area(room):
    try:
        exterior = room.get("polygon", [])
        holes = room.get("holes", [])
        if len(exterior) < 3:
            return 0.0
        return float(Polygon(exterior, holes).area)
    except Exception:
        return float(room.get("area_m2") or 0.0)


def _wall_edge_stats(walls):
    non_axis = total = 0
    for wall in walls:
        for ring in [wall.get("polygon", []), *wall.get("holes", [])]:
            if len(ring) < 2:
                continue
            for start, end in zip(ring, ring[1:] + ring[:1]):
                dx, dy = float(end[0]) - float(start[0]), float(end[1]) - float(start[1])
                if abs(dx) + abs(dy) < 1e-8:
                    continue
                total += 1
                angle = abs(np.degrees(np.arctan2(dy, dx))) % 90
                if min(angle, 90 - angle) > 1.0:
                    non_axis += 1
    return non_axis, total


def _floor_mismatch(rooms):
    by_floor = {}
    for room in rooms:
        floor = int(room.get("floorIndex", room.get("level", 0)) or 0)
        points = room.get("polygon", [])
        if len(points) >= 3:
            by_floor.setdefault(floor, []).extend(points)
    if len(by_floor) < 2:
        return 0.0
    bounds = []
    for points in by_floor.values():
        xs, ys = [float(point[0]) for point in points], [float(point[1]) for point in points]
        bounds.append((min(xs), min(ys), max(xs), max(ys)))
    reference = bounds[0]
    ref_dims = (max(reference[2] - reference[0], 1e-6), max(reference[3] - reference[1], 1e-6))
    mismatches = []
    for candidate in bounds[1:]:
        dims = (candidate[2] - candidate[0], candidate[3] - candidate[1])
        mismatches.append(max(abs(dims[0] - ref_dims[0]) / ref_dims[0], abs(dims[1] - ref_dims[1]) / ref_dims[1]))
    return 100 * max(mismatches, default=0.0)


def _footprint_mismatch_from_story_metrics(story_metrics):
    bounds = []
    for item in sorted(story_metrics or [], key=lambda value: value.get("floorIndex", 0)):
        pixel_bounds = item.get("footprint_bounds_px")
        scale = float(item.get("meters_per_pixel") or 0)
        if not pixel_bounds or len(pixel_bounds) != 4 or scale <= 0:
            continue
        x0, y0, x1, y1 = map(float, pixel_bounds)
        bounds.append((max(0.0, x1 - x0) * scale, max(0.0, y1 - y0) * scale))
    if len(bounds) < 2:
        return 0.0
    reference = bounds[0]
    return 100 * max(
        max(abs(candidate[index] - reference[index]) / max(candidate[index], reference[index], 1e-6) for index in (0, 1))
        for candidate in bounds[1:]
    )


def _expected_entry(expected, path):
    for key in (path.name, path.stem, str(path), str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else ""):
        if key and isinstance(expected.get(key), dict):
            return expected[key]
    return {}


def _sanity(summary, expected):
    failures = []
    if summary.get("review_required"):
        failures.extend(summary.get("review_issues", []) or ["scene is held for manual review"])
    area = summary["total_area_m2"]
    if not 20 <= area <= 1500:
        failures.append(f"building area {area:.1f} m2 is outside 20-1500 m2")
    bad_rooms = [room for room in summary["room_areas"] if not 1.5 <= room <= 300]
    if bad_rooms:
        failures.append(f"{len(bad_rooms)} room area(s) outside 1.5-300 m2")
    openings = summary["detected_doors"] + summary["detected_windows"]
    dropped = summary["dropped_doors"] + summary["dropped_windows"]
    if openings and dropped / openings > 0.40:
        failures.append(f"{dropped}/{openings} openings dropped (>40 percent)")
    if summary["detected_windows"] > 6 * max(summary["detected_doors"], 1):
        failures.append("windows exceed 6x detected doors")
    wanted_floors = expected.get("floors")
    if wanted_floors is not None and summary["stories"] != int(wanted_floors):
        failures.append(f"expected {wanted_floors} floor(s), found {summary['stories']}")
    wanted_rooms = expected.get("rooms")
    if wanted_rooms is not None and abs(summary["room_count"] - float(wanted_rooms)) > max(1, 0.35 * float(wanted_rooms)):
        failures.append(f"rough expected room count {wanted_rooms}, found {summary['room_count']}")
    wanted_area = expected.get("area_m2")
    if wanted_area is not None and float(wanted_area) > 0 and abs(area - float(wanted_area)) / float(wanted_area) > 0.50:
        failures.append(f"rough expected area {wanted_area} m2 differs by >50 percent")
    return failures


def _make_overlays(plan, original, capture, payload, summary, output_root):
    directory = output_root / _safe_name(plan)
    directory.mkdir(parents=True, exist_ok=True)
    prepared_by_story = capture.get("prepared_by_story") or {}
    if prepared_by_story:
        for story_index, prepared in sorted(prepared_by_story.items()):
            label = f"01 — EXACT PREPARED IMAGE SENT TO SAM · FLOOR {int(story_index) + 1}"
            _banner(prepared, label).save(directory / f"01_prepared_floor_{int(story_index) + 1}.png")
        first_story = min(prepared_by_story)
        _banner(prepared_by_story[first_story], "01 — EXACT PREPARED IMAGE SENT TO SAM · FLOOR 1").save(directory / "01_prepared.png")
    else:
        _banner(original, "01 — ORIGINAL IMAGE (SAM NOT RUN)").save(directory / "01_prepared.png")

    for concept in CONCEPTS:
        requested_sam = capture.get("requested_mode") == "sam"
        masks = capture.get("sam_masks", {}).get(concept, []) if requested_sam else capture.get("local_masks", {}).get(concept, [])
        mode = "SAM RESPONSE" if requested_sam else "LOCAL OPENCV"
        _mask_overlay(original, masks, f"02 — {mode} MASK: {concept.upper()}", (35, 175, 225)).save(directory / f"02_sam_{concept}.png")

    masks = {}
    for concept in CONCEPTS:
        masks[concept] = capture.get("sam_masks", {}).get(concept, []) or capture.get("local_masks", {}).get(concept, [])
    _mask_overlay(original, masks.get("wall", []), "03 — WALL SEGMENTATION", (40, 45, 50)).save(directory / "03_walls.png")
    _mask_overlay(original, masks.get("room", []), "04 — ROOM SEGMENTATION", (60, 140, 220)).save(directory / "04_rooms.png")

    scene = payload.get("scene", {})
    opening_plan = original.convert("RGB").copy()
    plan_draw = ImageDraw.Draw(opening_plan)
    font = _load_font(13)
    mpp = summary["mpp"] or 0.02
    drawn_openings = []
    legend_entries = []

    def add_opening_marker(kind, x, y, color, identifier, reason, rejected=False):
        marker_number = len(legend_entries) + 1
        radius = 8 if rejected else 7
        if rejected:
            plan_draw.ellipse((x-radius, y-radius, x+radius, y+radius), outline=color, width=3)
            plan_draw.line((x-radius, y, x+radius, y), fill=color, width=2)
            plan_draw.line((x, y-radius, x, y+radius), fill=color, width=2)
        else:
            plan_draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=color, outline="white", width=1)
        plan_draw.text((x - 5, y - 6), str(marker_number), fill="white", font=_load_font(10),
                       stroke_width=1, stroke_fill=(20, 25, 35))
        legend_entries.append({
            "number": marker_number,
            "kind": kind,
            "identifier": identifier,
            "reason": reason,
            "color": color,
        })

    for item in capture.get("opening_candidates", []):
        collection = item.get("collection", "door")
        kept_ids = set(item.get("kept_ids", []))
        dropped_reasons = item.get("dropped_reasons", {})
        for entry in item.get("candidates", []):
            center = entry.get("center", [])
            if len(center) != 2:
                continue
            item_mpp = float(item.get("mpp") or mpp)
            origin_x, origin_y = item.get("origin", (0, 0))
            x = int(round(float(center[0]) / item_mpp + origin_x))
            y = int(round(float(center[1]) / item_mpp + origin_y))
            if not (0 <= x < opening_plan.width and 0 <= y < opening_plan.height):
                continue
            identifier = str(entry.get("id", "opening"))
            is_kept = identifier in kept_ids
            is_dropped = identifier in dropped_reasons
            color = (245, 55, 55) if is_dropped else (40, 190, 95) if collection == "door" else (40, 120, 240)
            display_kind = {
                "swing": "Door",
                "double": "Double door",
                "open-doorway": "Open doorway",
            }.get(str(entry.get("kind") or ""), collection.title())
            add_opening_marker(
                display_kind, x, y, color, identifier,
                dropped_reasons.get(identifier, "kept" if is_kept else "candidate"),
                rejected=is_dropped,
            )
            drawn_openings.append((collection, x, y))

    # Keep candidates rejected before wall snapping visible too. The API stores
    # these points in original-upload pixel coordinates (including split-story
    # origins), so no scale conversion is needed here.
    for item in scene.get("meta", {}).get("openingDiagnostics", []):
        if item.get("accepted") is not False:
            continue
        center = item.get("pixelCenter")
        if not isinstance(center, (list, tuple)) or len(center) != 2:
            continue
        try:
            x, y = (int(round(float(value))) for value in center)
        except (TypeError, ValueError):
            continue
        if not (0 <= x < opening_plan.width and 0 <= y < opening_plan.height):
            continue
        kind = str(item.get("kind") or "opening").lower()
        if any(old_kind == kind and math.hypot(x - old_x, y - old_y) <= 4 for old_kind, old_x, old_y in drawn_openings):
            continue
        reason = " ".join(str(item.get("reason") or "rejected").split())
        identifier = str(item.get("candidate") or "candidate")
        add_opening_marker(kind, x, y, (210, 35, 35), identifier, reason, rejected=True)
        drawn_openings.append((kind, x, y))

    panel_width = 390
    row_layout = []
    for entry in legend_entries:
        wrapped = textwrap.wrap(
            f"{entry['kind'].title()} {entry['identifier']}: {entry['reason']}",
            width=48,
        ) or [entry["identifier"]]
        wrapped = wrapped[:4]
        row_layout.append((entry, wrapped, 20 + 14 * len(wrapped)))
    panel_height = max(opening_plan.height, 54 + sum(row[2] for row in row_layout) + 12)
    openings = Image.new("RGB", (opening_plan.width + panel_width, panel_height), (241, 244, 248))
    openings.paste(opening_plan, (0, 0))
    draw = ImageDraw.Draw(openings)
    draw.rectangle((0, 0, openings.width, 30), fill=(25, 35, 55))
    draw.text((8, 6), "05 — OPENING DETECTIONS · NUMBERED MARKERS MATCH THE REVIEW LIST", fill="white", font=_load_font(15))
    panel_left = opening_plan.width
    draw.rectangle((panel_left, 30, openings.width, panel_height), fill=(247, 248, 250))
    draw.text((panel_left + 12, 42), "CANDIDATES AND REJECTION REASONS", fill=(25, 35, 55), font=_load_font(14))
    draw.text((panel_left + 12, 62), "Green: kept door   Blue: kept window   Red: rejected", fill=(75, 85, 100), font=_load_font(11))
    y_cursor = 84
    for entry, wrapped, row_height in row_layout:
        draw.ellipse((panel_left + 12, y_cursor + 2, panel_left + 26, y_cursor + 16), fill=entry["color"])
        draw.text((panel_left + 33, y_cursor), f"{entry['number']}. {wrapped[0]}", fill=(30, 35, 45), font=font)
        for line_index, line in enumerate(wrapped[1:], start=1):
            draw.text((panel_left + 50, y_cursor + line_index * 14), line, fill=(75, 85, 95), font=font)
        y_cursor += row_height
    openings.save(directory / "05_openings.png")

    final = original.convert("RGB").copy()
    offsets = {int(item.get("floorIndex", item.get("level", 0)) or 0): (float(item.get("dx") or 0), float(item.get("dy") or 0)) for item in scene.get("meta", {}).get("storyOffsets", [])}
    origins = capture.get("story_origins", {0: (0, 0)})
    final = _draw_story_entities(final, scene.get("walls", []), mpp, origins, offsets, (35, 40, 48, 100), (30, 35, 42, 230), 2)
    final = _draw_story_entities(final, scene.get("rooms", []), mpp, origins, offsets, (55, 150, 225, 55), (20, 85, 145, 220), 2)
    _banner(final, "06 — FINAL SCENE GEOMETRY").save(directory / "06_final_plan.png")
    return directory


def _run_one(path, mode, args, expected):
    original_bytes = path.read_bytes()
    with Image.open(io.BytesIO(original_bytes)) as image:
        original = image.convert("RGB")
        size = image.size

    capture = {
        "sam_masks": {}, "local_masks": {}, "sam_concepts": set(),
        "opening_candidates": [], "detector_rejections": [],
        "requested_mode": mode, "prepared_by_story": {},
        "prepared_contexts": {}, "story_by_image_key": {},
        "story_metrics": [], "scale_decisions": [],
    }
    original_processing_mode = app_module._processing_mode
    original_sam_ready = app_module.sam_ready
    original_labeling_ready = app_module.labeling_ready
    original_prepare = app_module.prepare_segmentation
    original_segment = app_module.segment_prepared_concept
    original_query = app_module.query_sam_concept
    original_choose_scale = app_module.choose_scale
    original_detect_openings = app_module.detect_doors_and_windows_geometrically
    original_snap = app_module.snap_openings_and_cut_walls
    original_process_story = app_module._process_story_slice
    try:
        import meta_sam_service
        original_sam_prepare = meta_sam_service._prepare_image
    except Exception:
        meta_sam_service = None
        original_sam_prepare = None

    try:
        if mode == "opencv":
            app_module._processing_mode = lambda: "LOCAL"
            app_module.sam_ready = lambda: False
        elif mode == "sam":
            app_module._processing_mode = lambda: "LIVE"
            app_module.sam_ready = lambda: True
        if not args.with_muse_labeling:
            app_module.labeling_ready = lambda: False

        def capture_prepare(*call_args, **call_kwargs):
            prepared = original_prepare(*call_args, **call_kwargs)
            image_size = call_args[1] if len(call_args) > 1 else call_kwargs.get("image_size", (prepared.get("width", 0), prepared.get("height", 0)))
            context = {
                "floorIndex": int(getattr(STORY_CONTEXT, "story_index", 0) or 0),
                "origin": getattr(STORY_CONTEXT, "origin", (0, 0)),
                "bounds": (0, 0, int(image_size[0]), int(image_size[1])),
            }
            capture["prepared_contexts"][id(prepared)] = context
            return prepared

        def capture_segment(prepared, concept):
            result = original_segment(prepared, concept)
            context = capture["prepared_contexts"].get(id(prepared), {"origin": (0, 0), "bounds": None})
            with CAPTURE_LOCK:
                capture["local_masks"].setdefault(concept, []).extend(
                    {"mask": mask, "origin": context["origin"], "bounds": context["bounds"]}
                    for mask in result
                )
            return result

        def capture_query(image_bytes, concept, image_size, **call_kwargs):
            result = original_query(image_bytes, concept, image_size, **call_kwargs)
            masks = result[0] if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], dict) else result
            context = capture["story_by_image_key"].get(_image_key(image_bytes), {"floorIndex": 0, "origin": (0, 0)})
            tagged = [
                {"mask": mask, "origin": context["origin"], "bounds": (0, 0, int(image_size[0]), int(image_size[1]))}
                for mask in masks
            ]
            with CAPTURE_LOCK:
                capture["sam_masks"].setdefault(concept, []).extend(tagged)
                if masks:
                    capture["sam_concepts"].add(concept)
            return result

        def capture_opening_detection(*call_args, **call_kwargs):
            result = original_detect_openings(*call_args, **call_kwargs)
            if len(result) > 3:
                capture["detector_rejections"].extend(
                    {**item, "floorIndex": int(getattr(STORY_CONTEXT, "story_index", 0) or 0)}
                    for item in result[3] if not item.get("accepted")
                )
            return result

        expected_entry = _expected_entry(expected, path)
        floor_count = int(expected_entry.get("floor_count", 1))
        split_orientation = str(expected_entry.get("split_orientation", "vertical"))
        split_positions = expected_entry.get("split_positions")
        try:
            if floor_count > 1:
                plan_crops = app_module.split_image_at_user_dividers(
                    original_bytes, floor_count, split_orientation, split_positions
                )
            else:
                plan_crops = [(original_bytes, (0, 0, size[0], size[1]))]
            capture["story_origins"] = {
                index: (int(bbox[0]), int(bbox[1]))
                for index, (_crop, bbox) in enumerate(plan_crops)
            }
        except Exception:
            capture["story_origins"] = {0: (0, 0)}

        def capture_process_story(*call_args, **call_kwargs):
            story_index = int(call_kwargs.get("story_index", 0) or 0)
            source_mpp = float(call_args[2] if len(call_args) > 2 else call_kwargs.get("meters_per_pixel", app_module.DEFAULT_METERS_PER_PIXEL))
            image_bytes = call_args[0] if call_args else call_kwargs.get("image_bytes", b"")
            STORY_CONTEXT.story_index = story_index
            STORY_CONTEXT.mpp = source_mpp
            STORY_CONTEXT.origin = capture.get("story_origins", {}).get(story_index, (0, 0))
            if image_bytes:
                capture["story_by_image_key"][_image_key(image_bytes)] = {
                    "floorIndex": story_index,
                    "origin": STORY_CONTEXT.origin,
                }
            try:
                result = original_process_story(*call_args, **call_kwargs)
                capture["story_metrics"].append({
                    "floorIndex": story_index,
                    "meters_per_pixel": result.get("meters_per_pixel"),
                    "scale_source": result.get("scale_source"),
                    "door_widths_px_for_scale": result.get("door_widths_px_for_scale", []),
                    "door_width_source": result.get("door_width_source"),
                    "door_swing_radii_px": result.get("door_swing_radii_px", []),
                    "wall_stroke_thickness_px": result.get("wall_stroke_thickness_px"),
                    "wall_band_thickness_px": result.get("wall_band_thickness_px"),
                    "snap_tolerance_px": result.get("snap_tolerance_px"),
                    "wall_thickness_px": result.get("wall_thickness_px"),
                    "room_footprint_coverage": result.get("room_footprint_coverage"),
                    "footprint_bounds_px": result.get("footprint_bounds_px"),
                    "footprint_contour_area_px": result.get("footprint_contour_area_px"),
                })
                return result
            finally:
                STORY_CONTEXT.story_index = 0
                STORY_CONTEXT.mpp = None
                STORY_CONTEXT.origin = (0, 0)

        if meta_sam_service is not None:
            def capture_sam_prepare(image_bytes, *call_args, **call_kwargs):
                result = original_sam_prepare(image_bytes, *call_args, **call_kwargs)
                prepared_image = _decode_data_url(result[1])
                if prepared_image is not None:
                    context = capture["story_by_image_key"].get(_image_key(image_bytes), {"floorIndex": 0})
                    capture["prepared_by_story"][context["floorIndex"]] = prepared_image
                return result
            meta_sam_service._prepare_image = capture_sam_prepare

        def capture_snap(walls, doors, windows, *call_args, **call_kwargs):
            result = original_snap(walls, doors, windows, *call_args, **call_kwargs)
            kept_doors, kept_windows, dropped_messages = result[1], result[2], result[3]
            reason_map = {}
            for message in dropped_messages:
                match = re.search(r"(?:Door|Window)\s+(\S+)\s+dropped\s*\((.*?)\)", message, re.I)
                if match:
                    reason_map[match.group(1)] = match.group(2)
            with CAPTURE_LOCK:
                if doors:
                    capture["opening_candidates"].append({"collection": "door", "candidates": [dict(item) for item in doors], "kept_ids": [item.get("id") for item in kept_doors], "dropped_reasons": reason_map, "mpp": getattr(STORY_CONTEXT, "mpp", None), "origin": getattr(STORY_CONTEXT, "origin", (0, 0))})
                if windows:
                    capture["opening_candidates"].append({"collection": "window", "candidates": [dict(item) for item in windows], "kept_ids": [item.get("id") for item in kept_windows], "dropped_reasons": reason_map, "mpp": getattr(STORY_CONTEXT, "mpp", None), "origin": getattr(STORY_CONTEXT, "origin", (0, 0))})
            return result

        def capture_choose_scale(*call_args, **call_kwargs):
            result = original_choose_scale(*call_args, **call_kwargs)
            capture["scale_decisions"].append({
                "floorIndex": int(getattr(STORY_CONTEXT, "story_index", 0) or 0),
                "inputs": {
                    key: value.tolist() if isinstance(value, np.ndarray) else value
                    for key, value in call_kwargs.items()
                },
                "result": dict(result),
            })
            try:
                STORY_CONTEXT.mpp = float(result.get("meters_per_pixel") or STORY_CONTEXT.mpp)
            except (AttributeError, TypeError, ValueError):
                pass
            return result

        app_module.prepare_segmentation = capture_prepare
        app_module.segment_prepared_concept = capture_segment
        app_module.query_sam_concept = capture_query
        app_module.detect_doors_and_windows_geometrically = capture_opening_detection
        app_module.choose_scale = capture_choose_scale
        app_module.snap_openings_and_cut_walls = capture_snap
        app_module._process_story_slice = capture_process_story

        payload = app_module._build_scene(
            original_bytes, size, path.name,
            float(app_module.DEFAULT_METERS_PER_PIXEL),
            float(app_module.DEFAULT_WALL_HEIGHT),
            float(app_module.DEFAULT_WALL_THICKNESS),
            not args.no_auto_scale,
            lambda *_values: None,
            floor_count=floor_count,
            split_orientation=split_orientation,
            split_positions=split_positions,
        )
        scene = payload["scene"]
        meta = scene.get("meta", {})
        rooms = scene.get("rooms", [])
        walls = scene.get("walls", [])
        doors = scene.get("doors", [])
        windows = scene.get("windows", [])
        warnings = meta.get("warnings", [])
        dropped_door_msgs = [warning for warning in warnings if re.search(r"\bdoor\b.*\bdropped\b", warning, re.I)]
        dropped_window_msgs = [warning for warning in warnings if re.search(r"\bwindow\b.*\bdropped\b", warning, re.I)]
        door_candidates = sum(len(item["candidates"]) for item in capture["opening_candidates"] if item["collection"] == "door")
        window_candidates = sum(len(item["candidates"]) for item in capture["opening_candidates"] if item["collection"] == "window")
        detected_doors = max(len(doors) + len(dropped_door_msgs), door_candidates)
        detected_windows = max(len(windows) + len(dropped_window_msgs), window_candidates)
        room_areas = [_polygon_area(room) for room in rooms]
        stories = len({int(room.get("floorIndex", room.get("level", 0)) or 0) for room in rooms})
        non_axis, all_edges = _wall_edge_stats(walls)
        mpp = float(meta.get("metersPerPixel") or app_module.DEFAULT_METERS_PER_PIXEL)
        summary = {
            "image_size": size,
            "mode": meta.get("segmentation") or ("OPENCV ONLY" if mode == "opencv" else "SAM REQUESTED; CHECK STATUS"),
            "mpp": mpp,
            "scale_source": meta.get("scaleSource") or meta.get("scaleMethod", "unknown"),
            "room_count": len(rooms),
            "room_areas": room_areas,
            "total_area_m2": sum(room_areas),
            "largest_area_m2": max(room_areas, default=0.0),
            "wall_count": len(walls),
            "detected_doors": detected_doors,
            "kept_doors": len(doors),
            "dropped_doors": max(detected_doors - len(doors), len(dropped_door_msgs)),
            "dropped_door_reasons": dropped_door_msgs,
            "detected_windows": detected_windows,
            "kept_windows": len(windows),
            "dropped_windows": max(detected_windows - len(windows), len(dropped_window_msgs)),
            "dropped_window_reasons": dropped_window_msgs,
            "stories": stories or int(meta.get("levelCount") or 1),
            "review_required": bool(meta.get("needsReview")),
            "review_issues": list(meta.get("reviewIssues") or []),
            "footprint_mismatch_pct": _footprint_mismatch_from_story_metrics(capture["story_metrics"]) or _floor_mismatch(rooms),
            "non_axis_wall_edges": non_axis,
            "wall_edge_count": all_edges,
            "warnings": warnings,
            "room_polygons": rooms,
            "opening_candidate_rejections": capture["detector_rejections"],
            "sam_concepts": meta.get("samConcepts", []),
            "story_metrics": sorted(capture["story_metrics"], key=lambda item: item["floorIndex"]),
            "scale_decisions": capture["scale_decisions"],
        }
        failures = _sanity(summary, _expected_entry(expected, path))
        summary["failures"] = failures

        output_dir = _make_overlays(path, original, capture, payload, summary, ROOT / args.output)
        summary["debug_dir"] = str(output_dir.relative_to(ROOT))
        return summary
    finally:
        app_module._processing_mode = original_processing_mode
        app_module.sam_ready = original_sam_ready
        app_module.labeling_ready = original_labeling_ready
        app_module.prepare_segmentation = original_prepare
        app_module.segment_prepared_concept = original_segment
        app_module.query_sam_concept = original_query
        app_module.detect_doors_and_windows_geometrically = original_detect_openings
        app_module.choose_scale = original_choose_scale
        app_module.snap_openings_and_cut_walls = original_snap
        app_module._process_story_slice = original_process_story
        if meta_sam_service is not None and original_sam_prepare is not None:
            meta_sam_service._prepare_image = original_sam_prepare


def _format_row(item):
    source = str(item.get("scale_source", "unknown"))
    if "median detected door width" in source:
        source = "door-median"
    elif "manual" in source.lower():
        source = "manual/default"
    return [
        Path(item["plan"]).name,
        f"{item['image_size'][0]}x{item['image_size'][1]}",
        item["mode"],
        f"{item['mpp']:.5f} ({source})",
        str(item["room_count"]),
        f"{item['total_area_m2']:.1f} / {item['largest_area_m2']:.1f}",
        str(item["wall_count"]),
        f"{item['detected_doors']}/{item['kept_doors']}/{item['dropped_doors']}",
        f"{item['detected_windows']}/{item['kept_windows']}/{item['dropped_windows']}",
        str(item["stories"]),
        f"{item['footprint_mismatch_pct']:.1f}%",
        f"{item['non_axis_wall_edges']}/{item['wall_edge_count']}",
        str(len(item.get("dropped_door_reasons", [])) + len(item.get("dropped_window_reasons", []))),
        str(len(item.get("warnings", []))),
        ", ".join(item.get("failures", [])) or "PASS",
    ]


def _print_table(rows):
    headers = ["plan", "image", "mode", "m/px (source)", "rooms", "area total/largest m2", "walls", "doors D/K/X", "windows D/K/X", "stories", "footprint mismatch", "non-axis edges", "dropped", "warnings", "sanity"]
    widths = [min(max(len(headers[index]), *(len(row[index]) for row in rows)), 46) for index in range(len(headers))]
    print(" | ".join(headers[i].ljust(widths[i]) for i in range(len(headers))))
    print("-+-".join("-" * width for width in widths))
    for row in rows:
        print(" | ".join(row[i][:widths[i]].ljust(widths[i]) for i in range(len(headers))))


def _print_details(items):
    for item in items:
        if item.get("story_metrics"):
            print(f"\n{Path(item['plan']).name} - scale and pixel-space audit:")
            for metric in item["story_metrics"]:
                print(
                    f"  Floor {metric['floorIndex'] + 1}: scale={metric.get('meters_per_pixel')} m/px "
                    f"({metric.get('scale_source')}); wall stroke={metric.get('wall_stroke_thickness_px')} px; "
                    f"solid band={metric.get('wall_band_thickness_px')} px; "
                    f"snap tolerance={metric.get('snap_tolerance_px')} px; "
                    f"door widths used for scale={metric.get('door_widths_px_for_scale')} "
                    f"from {metric.get('door_width_source')}; "
                    f"door swing arc measurements={metric.get('door_swing_radii_px')}; "
                    f"room/footprint coverage={metric.get('room_footprint_coverage')}; "
                    f"outer bounds px={metric.get('footprint_bounds_px')}; "
                    f"outer contour area px={metric.get('footprint_contour_area_px')}"
                )
            print(f"  Room areas m2: {[round(area, 2) for area in item.get('room_areas', [])]}")
        print(f"\n{Path(item['plan']).name} - dropped openings:")
        reasons = item.get("dropped_door_reasons", []) + item.get("dropped_window_reasons", [])
        if reasons:
            for reason in reasons:
                print(f"  - {reason}")
        else:
            print("  - none")
        print("  Warnings:")
        for warning in item.get("warnings", []) or ["none"]:
            print(f"  - {warning}")
        if item.get("failures"):
            print("  Sanity failures:")
            for failure in item["failures"]:
                print(f"  - {failure}")
        rejections = item.get("opening_candidate_rejections", [])
        if rejections:
            print("  Opening candidates rejected by geometry:")
            for rejection in rejections:
                print(f"  - floor {int(rejection.get('floorIndex', 0)) + 1} {rejection.get('kind', 'opening')} {rejection.get('candidate', '?')}: {rejection.get('reason', 'rejected')}")
        if item.get("sam_concepts"):
            print("  SAM concept results:")
            for result in item["sam_concepts"]:
                print(f"  - {result.get('concept')}: {result.get('status')}; used={bool(result.get('used'))}; prompt={result.get('prompt') or 'none'}; category={result.get('category') or 'none'}")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("current", "opencv", "sam"), default="current")
    parser.add_argument("--eval-dir", default="samples/eval")
    parser.add_argument("--images", nargs="*", help="Optional explicit image paths, useful before samples/eval is populated.")
    parser.add_argument("--expected", default="samples/eval/expected.json")
    parser.add_argument("--output", default="out/debug")
    parser.add_argument("--no-auto-scale", action="store_true")
    parser.add_argument("--with-muse-labeling", action="store_true", help="Allow optional Muse room labeling; may call the provider.")
    args = parser.parse_args()

    expected_path = ROOT / args.expected
    expected = json.loads(expected_path.read_text(encoding="utf-8")) if expected_path.is_file() else {}
    if args.images:
        image_paths = [Path(value).resolve() for value in args.images]
    else:
        search_dir = ROOT / args.eval_dir
        image_paths = sorted(
            path for path in search_dir.rglob("*")
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
        ) if search_dir.exists() else []
        # Keep fixtures in the usual samples/ directory when expected.json is
        # under samples/eval/. This also makes the documented default command
        # work without duplicating several copies of each binary plan.
        if not image_paths and expected:
            candidate_roots = [search_dir.parent, ROOT]
            for entry in expected:
                expected_item = expected[entry]
                declared = expected_item.get("image") if isinstance(expected_item, dict) else None
                candidates = [ROOT / declared] if declared else []
                candidates.extend(root / entry for root in candidate_roots)
                image_path = next((path.resolve() for path in candidates if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS), None)
                if image_path and image_path not in image_paths:
                    image_paths.append(image_path)
    if not image_paths:
        print(f"No evaluation images found in {ROOT / args.eval_dir} or the configured expected-plan paths.")
        print("Add representative plans and expected counts, or pass image paths with --images.")
        return 2

    results = []
    for path in image_paths:
        try:
            summary = _run_one(path, args.mode, args, expected)
            summary["plan"] = str(path)
            results.append(summary)
        except Exception as exc:
            results.append({
                "plan": str(path), "image_size": (0, 0), "mode": args.mode,
                "mpp": 0, "scale_source": "pipeline error", "room_count": 0,
                "total_area_m2": 0, "largest_area_m2": 0, "wall_count": 0,
                "detected_doors": 0, "kept_doors": 0, "dropped_doors": 0,
                "detected_windows": 0, "kept_windows": 0, "dropped_windows": 0,
                "stories": 0, "footprint_mismatch_pct": 0,
                "non_axis_wall_edges": 0, "wall_edge_count": 0,
                "review_required": True, "review_issues": [],
                "warnings": [], "story_metrics": [], "scale_decisions": [],
                "failures": [f"pipeline error: {type(exc).__name__}: {exc}"],
            })

    _print_table([_format_row(item) for item in results])
    _print_details(results)
    (ROOT / args.output).mkdir(parents=True, exist_ok=True)
    (ROOT / args.output / "evaluation.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    failed = [item for item in results if item.get("failures")]
    print(f"\n{len(results) - len(failed)}/{len(results)} plans pass the sanity checks.")
    print(f"Debug overlays: {ROOT / args.output}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
