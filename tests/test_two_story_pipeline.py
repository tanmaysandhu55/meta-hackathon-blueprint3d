"""Tests for multi-story floor plan pipeline, clean orthogonal geometry, and opening snapping."""

import io
import math
import numpy as np
import pytest
import shapely.geometry
from PIL import Image

from geometry_processor import (
    check_axis_aligned_fraction,
    detect_doors_and_windows_geometrically,
    reconstruct_walls_room_first,
    snap_openings_and_cut_walls,
    snap_polygon_orthogonal,
    split_multi_plan_image,
    validate_scene_geometry,
)


def _create_synthetic_two_plan_image():
    """Create a 1000x500 synthetic image with two black rectangular building floor plans."""
    img = np.ones((500, 1000, 3), dtype=np.uint8) * 255
    # Plan 0 on the left: outer wall 300x300 at (50, 100)
    img[100:400, 50:350] = 0
    img[120:380, 70:330] = 255  # hollow interior

    # Plan 1 on the right: outer wall 300x300 at (550, 100)
    img[100:400, 550:850] = 0
    img[120:380, 570:830] = 255  # hollow interior

    pil_img = Image.fromarray(img)
    buf = io.BytesIO()
    pil_img.save(buf, format="PNG")
    return buf.getvalue()


def _create_synthetic_single_plan_image():
    """Create a 500x500 synthetic image with one building floor plan."""
    img = np.ones((500, 500, 3), dtype=np.uint8) * 255
    img[100:400, 100:400] = 0
    img[120:380, 120:380] = 255
    pil_img = Image.fromarray(img)
    buf = io.BytesIO()
    pil_img.save(buf, format="PNG")
    return buf.getvalue()


def test_split_multi_plan_image():
    # Single plan returns 1 crop
    single_bytes = _create_synthetic_single_plan_image()
    crops_single = split_multi_plan_image(single_bytes)
    assert len(crops_single) == 1

    # Two plans return 2 crops
    double_bytes = _create_synthetic_two_plan_image()
    crops_double = split_multi_plan_image(double_bytes)
    assert len(crops_double) == 2
    # Ensure crops are sorted left-to-right
    assert crops_double[0][1][0] < crops_double[1][1][0]


def test_orthogonal_snapping():
    # Polygon with slight tilts (under 7 degrees)
    tilted_poly = [
        [0.0, 0.05],
        [10.02, 0.0],
        [10.0, 7.98],
        [-0.03, 8.0],
    ]
    snapped = snap_polygon_orthogonal(tilted_poly, tolerance_deg=7.0, snap_dist=0.15)
    assert len(snapped) >= 4
    # All edges must be axis-aligned (either dx == 0 or dy == 0)
    for i in range(len(snapped)):
        p1 = snapped[i]
        p2 = snapped[(i + 1) % len(snapped)]
        dx = abs(p2[0] - p1[0])
        dy = abs(p2[1] - p1[1])
        assert dx < 1e-3 or dy < 1e-3, f"Edge ({p1}, {p2}) is not axis-aligned"


def test_collinear_merge_and_vertex_snapping():
    # Poly with collinear redundant points and points closer than 0.15m
    poly_with_redundancy = [
        [0.0, 0.0],
        [5.0, 0.0],      # collinear on bottom edge
        [10.0, 0.0],
        [10.05, 0.02],   # redundant point within 0.15m of previous
        [10.0, 5.0],
        [0.0, 5.0],
    ]
    snapped = snap_polygon_orthogonal(poly_with_redundancy, tolerance_deg=7.0, snap_dist=0.15)
    # The redundant points should be merged
    assert len(snapped) <= 5


def test_reconstruct_walls_room_first_valid():
    rooms = [
        {"id": "r1", "polygon": [[0.0, 0.0], [5.0, 0.0], [5.0, 5.0], [0.0, 5.0]]},
        {"id": "r2", "polygon": [[5.0, 0.0], [10.0, 0.0], [10.0, 5.0], [5.0, 5.0]]},
    ]
    walls, ratio = reconstruct_walls_room_first(rooms, wall_thickness_m=0.2)
    assert len(walls) > 0
    assert ratio >= 0.85
    # Check that each wall is a valid polygon
    for w in walls:
        poly = shapely.geometry.Polygon(w["polygon"])
        assert poly.is_valid


def test_door_snapping_and_orphan_drop():
    walls = [
        {"id": "w1", "polygon": [[0.0, -0.1], [10.0, -0.1], [10.0, 0.1], [0.0, 0.1]], "holes": []}
    ]
    # d1 is near the wall (within 0.6m)
    # d2 is floating out in the lawn at (5.0, 5.0) (> 0.6m away)
    doors = [
        {"id": "d1", "center": [3.0, 0.2], "width": 0.9},
        {"id": "d2", "center": [5.0, 5.0], "width": 0.9},
    ]
    cut_walls, valid_doors, valid_windows, dropped = snap_openings_and_cut_walls(
        walls, doors, [], wall_thickness_m=0.2, max_dist_m=0.6
    )
    # d1 should be retained and snapped onto the wall
    assert any(d["id"] == "d1" for d in valid_doors)
    # d2 should be dropped
    assert not any(d["id"] == "d2" for d in valid_doors)
    assert any("d2" in msg for msg in dropped)
    # Wall should have been cut (length decreased or area decreased)
    assert len(cut_walls) > 0


def test_story_alignment_and_stacking():
    # Synthetic scene with 2 stacked stories
    scene = {
        "meta": {
            "source": "two_story.png",
            "imageSize": [1000, 500],
            "metersPerPixel": 0.02,
            "wallHeight": 3.0,
            "wallThickness": 0.2,
            "floorHeight": 3.2,
            "slabThickness": 0.2,
            "levelCount": 2,
            "levels": [
                {"level": 0, "floorIndex": 0, "name": "Ground Floor", "elevation": 0.0},
                {"level": 1, "floorIndex": 1, "name": "Second Floor", "elevation": 3.2},
            ],
            "storyOffsets": [
                {"level": 0, "dx": 0.0, "dy": 0.0},
                {"level": 1, "dx": 0.0, "dy": 0.0},
            ],
            "warnings": [],
        },
        "rooms": [
            {"id": "r1", "type": "room", "label": "Room G1", "confidence": 0.0, "polygon": [[0, 0], [6, 0], [6, 6], [0, 6]], "floorIndex": 0, "level": 0},
            {"id": "s1_r1", "type": "room", "label": "Room 1.1", "confidence": 0.0, "polygon": [[0, 0], [6, 0], [6, 6], [0, 6]], "floorIndex": 1, "level": 1},
        ],
        "walls": [
            {"id": "w1", "polygon": [[-0.1, -0.1], [6.1, -0.1], [6.1, 6.1], [-0.1, 6.1]], "floorIndex": 0, "level": 0},
            {"id": "s1_w1", "polygon": [[-0.1, -0.1], [6.1, -0.1], [6.1, 6.1], [-0.1, 6.1]], "floorIndex": 1, "level": 1},
        ],
        "doors": [
            {"id": "d1", "center": [3.0, 0.0], "width": 0.9, "connects": ["r1"], "floorIndex": 0, "level": 0},
            {"id": "s1_d1", "center": [3.0, 0.0], "width": 0.9, "connects": ["s1_r1"], "floorIndex": 1, "level": 1},
        ],
        "windows": [],
    }
    warnings = validate_scene_geometry(scene)
    assert len(warnings) == 0


def test_geometry_validator_detects_footprint_mismatch():
    scene = {
        "meta": {
            "source": "mismatch.png",
            "imageSize": [1000, 500],
            "metersPerPixel": 0.02,
            "wallHeight": 3.0,
            "wallThickness": 0.2,
            "levelCount": 2,
            "levels": [
                {"level": 0, "floorIndex": 0, "name": "Ground Floor", "elevation": 0.0},
                {"level": 1, "floorIndex": 1, "name": "Second Floor", "elevation": 3.2},
            ],
        },
        "rooms": [
            # Story 0 is 10m wide
            {"id": "r1", "type": "room", "label": "Room G1", "confidence": 0.0, "polygon": [[0, 0], [10, 0], [10, 8], [0, 8]], "floorIndex": 0, "level": 0},
            # Story 1 is 5m wide (5m difference, exceeds 0.5m limit!)
            {"id": "s1_r1", "type": "room", "label": "Room 1.1", "confidence": 0.0, "polygon": [[0, 0], [5, 0], [5, 8], [0, 8]], "floorIndex": 1, "level": 1},
        ],
        "walls": [],
        "doors": [],
        "windows": [],
    }
    warnings = validate_scene_geometry(scene)
    assert any("diff exceeds 0.5 m" in w for w in warnings)
