"""Tests for multi-story floor plan pipeline, clean orthogonal geometry, and opening snapping."""

import io
import math
import numpy as np
import pytest
import shapely.geometry
from PIL import Image
import app as app_module

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


def test_geometry_validator_accepts_rotated_orthogonal_walls():
    angle = math.radians(27)
    cosine, sine = math.cos(angle), math.sin(angle)
    def rotate(x, y):
        return [round(x * cosine - y * sine, 4), round(x * sine + y * cosine, 4)]

    polygon = [rotate(x, y) for x, y in ((0, 0), (8, 0), (8, 4), (0, 4))]
    warnings = validate_scene_geometry({
        "meta": {},
        "rooms": [],
        "walls": [{"id": "rotated-wall", "polygon": polygon}],
        "doors": [],
        "windows": [],
    })
    assert not any("Wall alignment check" in warning for warning in warnings)


def test_story_rescaling_keeps_holes_and_metric_geometry_consistent():
    result = {
        "meters_per_pixel": 0.02,
        "rooms": [{
            "polygon": [[0, 0], [4, 0], [4, 3], [0, 3]],
            "holes": [[[1, 1], [2, 1], [2, 2], [1, 2]]],
            "centroid": [2, 1.5],
            "area_m2": 11,
        }],
        "walls": [{
            "polygon": [[0, 0], [4, 0], [4, 0.2], [0, 0.2]],
            "holes": [[[1, 0], [2, 0], [2, 0.2], [1, 0.2]]],
        }],
        "doors": [{"center": [2, 0], "width": 0.9}],
        "windows": [{"center": [3, 0], "width": 1.2}],
    }

    app_module._rescale_story_result(result, 0.04)

    assert result["meters_per_pixel"] == 0.04
    assert result["rooms"][0]["polygon"][1] == [8.0, 0.0]
    assert result["rooms"][0]["holes"][0][2] == [4.0, 4.0]
    assert result["rooms"][0]["area_m2"] == 44
    assert result["walls"][0]["holes"][0][1] == [4.0, 0.0]
    assert result["doors"][0]["center"] == [4.0, 0.0]
    assert result["doors"][0]["width"] == 1.8


def test_two_story_alignment_uses_matching_stair_centroids():
    ground = {"rooms": [{
        "id": "r-stair", "type": "stairs", "area_m2": 4,
        "polygon": [[10, 10], [12, 10], [12, 12], [10, 12]], "centroid": [11, 11],
    }]}
    upper = {
        "rooms": [{
            "id": "u-stair", "type": "stairs", "area_m2": 4,
            "polygon": [[2, 3], [4, 3], [4, 5], [2, 5]], "holes": [[[2.5, 3.5], [3, 3.5], [3, 4], [2.5, 4]]],
            "centroid": [3, 4],
        }],
        "walls": [{"polygon": [[2, 3], [4, 3], [4, 3.2], [2, 3.2]], "holes": []}],
        "doors": [{"center": [3, 3], "width": 0.9}],
        "windows": [],
    }

    dx, dy, ground_connector, upper_connector = app_module._align_upper_story(ground, upper)

    assert (dx, dy) == (8, 7)
    assert ground_connector["id"] == "r-stair"
    assert upper_connector["centroid"] == [11, 11]
    assert upper["rooms"][0]["holes"][0][0] == [10.5, 10.5]
    assert upper["walls"][0]["polygon"][0] == [10.0, 10.0]
    assert upper["doors"][0]["center"] == [11.0, 10.0]


def test_two_story_scene_harmonizes_scale_and_links_stairs(monkeypatch):
    image = Image.new("RGB", (20, 20), "white")
    output = io.BytesIO()
    image.save(output, format="PNG")
    image_bytes = output.getvalue()
    monkeypatch.setattr(app_module, "_processing_mode", lambda: "LOCAL")
    monkeypatch.setattr(app_module, "sam_ready", lambda: False)
    monkeypatch.setattr(app_module, "split_image_at_user_dividers", lambda _data, *_args: [
        (image_bytes, (0, 0, 20, 20)),
        (image_bytes, (0, 0, 20, 20)),
    ])

    def make_room(points, scale, room_id, room_type="classroom", label="Room"):
        polygon = [[round((x + points[0]) * scale, 3), round((y + points[1]) * scale, 3)] for x, y in points[2]]
        return {
            "id": room_id,
            "type": room_type,
            "label": label,
            "confidence": 0.9,
            "polygon": polygon,
            "holes": [],
            "centroid": [round(sum(point[0] for point in polygon) / len(polygon), 3), round(sum(point[1] for point in polygon) / len(polygon), 3)],
            "area_m2": round(abs(shapely.geometry.Polygon(polygon).area), 2),
        }

    def fake_process(_image_bytes, _image_size, _mpp, _wall_height, _wall_thickness, _calibrate, _progress, _deadline, _use_sam, _mode, _url, story_index=0, **_kwargs):
        scale = 0.02 if story_index == 0 else 0.04
        offset = (0, 0) if story_index == 0 else (100, 80)
        main = make_room((offset[0], offset[1], [[0, 0], [200, 0], [200, 200], [0, 200]]), scale, f"r{story_index + 1}")
        stair = make_room((offset[0], offset[1], [[80, 80], [120, 80], [120, 120], [80, 120]]), scale, f"s{story_index + 1}", "stairs", "Stairwell")
        return {
            "rooms": [main, stair], "walls": [], "doors": [], "windows": [], "warnings": [],
            "meters_per_pixel": scale, "scale_method": "median detected door width (assumed 0.9 m)",
                "scale_source": "door-width", "scale_confidence": 0.7, "scale_accepted": True,
                "scale_quality_issues": [],
            "segmentation_backend": "opencv-fallback", "wall_method": "room-boundary-reconstruction",
        }

    monkeypatch.setattr(app_module, "_process_story_slice", fake_process)
    result = app_module._build_scene(image_bytes, image.size, "two-story.png", 0.02, 3.0, 0.2, True, lambda *_args: None, floor_count=2, split_positions=[0.5])
    scene = result["scene"]
    ground_stairs = next(room for room in scene["rooms"] if room["id"] == "s1")
    upper_stairs = next(room for room in scene["rooms"] if room["id"] == "s2")

    assert ground_stairs["connectsTo"] == upper_stairs["id"]
    assert upper_stairs["connectsTo"] == ground_stairs["id"]
    assert ground_stairs["centroid"] == pytest.approx(upper_stairs["centroid"], abs=0.002)
    assert scene["meta"]["metersPerPixel"] == scene["meta"]["levels"][1]["metersPerPixel"]
    assert not any("footprint differs" in warning for warning in scene["meta"]["warnings"])
    assert not any("stairs not aligned" in warning for warning in scene["meta"]["warnings"])
