"""Run coarse, offline regression checks on the bundled floor-plan fixture."""
import concurrent.futures
import json
from pathlib import Path
import sys

import cv2
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from geometry_processor import extract_doors, extract_windows, mask_to_polygons_with_holes
from segmentation_service import segment_concept


SAMPLE = ROOT / "samples" / "sample_floorplan.png"
CONCEPTS = ("room", "wall", "door", "window")


def evaluate_sample():
    image_bytes = SAMPLE.read_bytes()
    with Image.open(SAMPLE) as image:
        size = image.size

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            concept: executor.submit(segment_concept, image_bytes, concept, size)
            for concept in CONCEPTS
        }
        masks = {concept: future.result() for concept, future in futures.items()}

    counts = {
        concept: {
            "mask_count": len(concept_masks),
            "foreground_pixels": sum(cv2.countNonZero(mask) for mask in concept_masks),
        }
        for concept, concept_masks in masks.items()
    }
    room_polygons = [
        polygon
        for mask in masks["room"]
        for polygon in mask_to_polygons_with_holes(mask, meters_per_pixel=0.02, min_area_px=200)
    ]
    rooms = [{"id": f"r{index + 1}", "polygon": polygon["polygon"]} for index, polygon in enumerate(room_polygons)]
    geometry_counts = {
        "room_polygons": len(rooms),
        "doors": len(extract_doors(masks["door"], rooms, meters_per_pixel=0.02)),
        "windows": len(extract_windows(masks["window"], meters_per_pixel=0.02)),
    }
    checks = {
        "room_count_in_expected_fixture_range": 5 <= geometry_counts["room_polygons"] <= 14,
        "wall_mask_detected": counts["wall"]["mask_count"] > 0,
        "door_geometry_detected": geometry_counts["doors"] > 0,
        "window_geometry_detected": geometry_counts["windows"] > 0,
    }
    return {
        "source": str(SAMPLE.relative_to(ROOT)),
        "image_size": list(size),
        "backend": "opencv-heuristic",
        "counts": counts,
        "geometry": geometry_counts,
        "checks": checks,
        "passed": all(checks.values()),
        "note": "Fixture regression guardrails only; passing does not measure accuracy on other plans.",
    }


if __name__ == "__main__":
    result = evaluate_sample()
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 1)
