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
import io
import json
import re
import sys
import threading
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
        for mask in masks:
            if mask is None:
                continue
            resized = cv2.resize(np.asarray(mask, dtype=np.uint8), (canvas.shape[1], canvas.shape[0]), interpolation=cv2.INTER_NEAREST)
            combined = cv2.bitwise_or(combined, resized)
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


def _expected_entry(expected, path):
    for key in (path.name, path.stem, str(path), str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else ""):
        if key and isinstance(expected.get(key), dict):
            return expected[key]
    return {}


def _sanity(summary, expected):
    failures = []
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
    prepared = capture.get("prepared_image") or original
    _banner(prepared, "01 — PREPARED IMAGE SENT TO SAM" if capture.get("prepared_image") else "01 — ORIGINAL IMAGE (SAM NOT RUN)").save(directory / "01_prepared.png")

    for concept in CONCEPTS:
        masks = capture.get("masks", {}).get(concept, [])
        mode = "SAM" if concept in capture.get("sam_concepts", set()) else "OPENCV / NONE"
        _mask_overlay(original, masks, f"02 — {mode} MASK: {concept.upper()}", (35, 175, 225)).save(directory / f"02_sam_{concept}.png")

    masks = capture.get("masks", {})
    _mask_overlay(original, masks.get("wall", []), "03 — WALL SEGMENTATION", (40, 45, 50)).save(directory / "03_walls.png")
    _mask_overlay(original, masks.get("room", []), "04 — ROOM SEGMENTATION", (60, 140, 220)).save(directory / "04_rooms.png")

    openings = original.convert("RGB").copy()
    draw = ImageDraw.Draw(openings)
    font = _load_font(13)
    mpp = summary["mpp"] or 0.02
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
            identifier = str(entry.get("id", "opening"))
            is_kept = identifier in kept_ids
            is_dropped = identifier in dropped_reasons
            color = (245, 55, 55) if is_dropped else (40, 190, 95) if collection == "door" else (40, 120, 240)
            radius = 7
            draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=color, outline="white", width=1)
            draw.text((x + 8, y - 8), f"{identifier}: {dropped_reasons.get(identifier, 'kept' if is_kept else 'candidate')}", fill=color, font=font)
    draw.rectangle((0, 0, openings.width, 30), fill=(25, 35, 55))
    draw.text((8, 6), "05 — OPENINGS: DOORS GREEN · WINDOWS BLUE · DROPPED RED", fill="white", font=_load_font(15))
    openings.save(directory / "05_openings.png")

    scene = payload.get("scene", {})
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

    capture = {"masks": {}, "sam_concepts": set(), "opening_candidates": []}
    original_processing_mode = app_module._processing_mode
    original_sam_ready = app_module.sam_ready
    original_labeling_ready = app_module.labeling_ready
    original_prepare = app_module.prepare_segmentation
    original_segment = app_module.segment_prepared_concept
    original_query = app_module.query_sam_concept
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
            capture["prepared"] = prepared
            return prepared

        def capture_segment(prepared, concept):
            result = original_segment(prepared, concept)
            with CAPTURE_LOCK:
                capture["masks"].setdefault(concept, []).extend(result)
            return result

        def capture_query(image_bytes, concept, image_size, **call_kwargs):
            result = original_query(image_bytes, concept, image_size, **call_kwargs)
            with CAPTURE_LOCK:
                capture["masks"].setdefault(concept, []).extend(result)
                capture["sam_concepts"].add(concept)
            return result

        try:
            plan_crops = app_module.split_multi_plan_image(original_bytes)
            capture["story_origins"] = {
                index: (max(0, int(bbox[0]) - 20), max(0, int(bbox[1]) - 20))
                for index, (_crop, bbox) in enumerate(plan_crops)
            } if len(plan_crops) > 1 else {0: (0, 0)}
        except Exception:
            capture["story_origins"] = {0: (0, 0)}

        def capture_process_story(*call_args, **call_kwargs):
            story_index = int(call_kwargs.get("story_index", 0) or 0)
            source_mpp = float(call_args[2] if len(call_args) > 2 else call_kwargs.get("meters_per_pixel", app_module.DEFAULT_METERS_PER_PIXEL))
            STORY_CONTEXT.story_index = story_index
            STORY_CONTEXT.mpp = source_mpp
            STORY_CONTEXT.origin = capture.get("story_origins", {}).get(story_index, (0, 0))
            try:
                return original_process_story(*call_args, **call_kwargs)
            finally:
                STORY_CONTEXT.story_index = 0
                STORY_CONTEXT.mpp = None
                STORY_CONTEXT.origin = (0, 0)

        if meta_sam_service is not None:
            def capture_sam_prepare(image_bytes, *call_args, **call_kwargs):
                result = original_sam_prepare(image_bytes, *call_args, **call_kwargs)
                prepared_image = _decode_data_url(result[1])
                if prepared_image is not None:
                    capture["prepared_image"] = prepared_image
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

        app_module.prepare_segmentation = capture_prepare
        app_module.segment_prepared_concept = capture_segment
        app_module.query_sam_concept = capture_query
        app_module.snap_openings_and_cut_walls = capture_snap
        app_module._process_story_slice = capture_process_story

        payload = app_module._build_scene(
            original_bytes, size, path.name,
            float(app_module.DEFAULT_METERS_PER_PIXEL),
            float(app_module.DEFAULT_WALL_HEIGHT),
            float(app_module.DEFAULT_WALL_THICKNESS),
            not args.no_auto_scale,
            lambda *_values: None,
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
            "mode": mode,
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
            "footprint_mismatch_pct": _floor_mismatch(rooms),
            "non_axis_wall_edges": non_axis,
            "wall_edge_count": all_edges,
            "warnings": warnings,
            "room_polygons": rooms,
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

    image_paths = [Path(value).resolve() for value in args.images] if args.images else sorted(
        path for path in (ROOT / args.eval_dir).rglob("*") if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    ) if (ROOT / args.eval_dir).exists() else []
    if not image_paths:
        print(f"No evaluation images found in {ROOT / args.eval_dir}.")
        print("Add the representative plans and samples/eval/expected.json, or pass image paths with --images.")
        return 2

    expected_path = ROOT / args.expected
    expected = json.loads(expected_path.read_text(encoding="utf-8")) if expected_path.is_file() else {}
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
                "warnings": [], "failures": [f"pipeline error: {type(exc).__name__}: {exc}"],
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
