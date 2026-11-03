import cv2
import numpy as np

from geometry_processor import (
    build_walls_from_rooms,
    choose_scale,
    estimate_wall_thickness_px,
    estimate_meters_per_pixel_from_doors,
    estimate_meters_per_pixel_from_door_widths,
    mask_to_polygons_with_holes,
    scale_from_two_points,
)


def test_estimate_scale_from_door_width():
    mask = np.zeros((80, 80), dtype=np.uint8)
    cv2.rectangle(mask, (5, 10), (24, 15), 255, thickness=-1)
    cv2.rectangle(mask, (30, 30), (49, 35), 255, thickness=-1)
    cv2.rectangle(mask, (55, 50), (74, 55), 255, thickness=-1)

    scale = estimate_meters_per_pixel_from_doors([mask], target_width_m=1.0)

    assert scale is not None
    assert 0.045 <= scale <= 0.055


def test_scale_calibration_is_invariant_to_image_resizing():
    source_points = ((100, 80), (500, 80))
    expected = 4.0 / 400.0
    for factor in (0.5, 2.0):
        resized = tuple((x * factor, y * factor) for x, y in source_points)
        assert scale_from_two_points(*resized, known_length_m=4.0) == expected / factor
        # The m/px value changes with raster resolution, while the converted
        # physical distance remains exactly the same.
        distance_px = 400 * factor
        scale = scale_from_two_points(*resized, known_length_m=4.0)
        assert abs(distance_px * scale - 4.0) < 1e-9


def test_scale_sanity_rejects_implausible_user_scale_then_uses_footprint():
    result = choose_scale(
        user_scale=0.05,
        door_widths_px=[100, 102, 98],
        footprint_bounds_px=(0, 0, 2000, 1000),
        footprint_area_px=1_000_000,
        room_areas_px=[100_000, 100_000],
        default_scale=0.02,
    )
    assert result["accepted"] is True
    assert result["source"] == "door-width"
    assert 20 <= 1_000_000 * result["meters_per_pixel"] ** 2 <= 1500
    assert any("Rejected user scale" in warning for warning in result["warnings"])


def test_door_scale_requires_three_consistent_door_openings():
    scale, quality = estimate_meters_per_pixel_from_door_widths([48, 50])
    assert scale is None
    assert quality["count"] == 2

    scale, quality = estimate_meters_per_pixel_from_door_widths([40, 50, 80])
    assert scale is None
    assert quality["coefficientOfVariation"] >= 0.25

    result = choose_scale(
        user_scale=None,
        door_widths_px=[48, 50],
        footprint_bounds_px=(0, 0, 600, 400),
        footprint_area_px=180_000,
        room_areas_px=[80_000, 70_000],
        default_scale=0.02,
    )
    assert result["source"] == "typical-footprint-width"


def test_scale_needs_review_when_every_candidate_fails_sanity():
    result = choose_scale(
        user_scale=0.001,
        door_widths_px=[],
        footprint_bounds_px=(0, 0, 100, 100),
        footprint_area_px=100,
        room_areas_px=[100],
        default_scale=0.002,
    )
    assert result["accepted"] is False
    assert result["source"] == "needs-review"


def test_wall_thickness_estimate_and_pixel_space_snapping():
    wall_mask = np.zeros((120, 160), dtype=np.uint8)
    cv2.rectangle(wall_mask, (10, 50), (150, 55), 255, thickness=-1)
    measured = estimate_wall_thickness_px([wall_mask])
    assert 4 <= measured <= 8

    # The same 4 px offset is accepted at both image scales because the check
    # happens in source pixels, not via a fixed 0.6 m distance.
    from geometry_processor import snap_openings_and_cut_walls
    for mpp in (0.01, 0.04):
        wall = {"id": "w1", "polygon": [[0, -0.1*mpp], [100*mpp, -0.1*mpp], [100*mpp, 0.1*mpp], [0, 0.1*mpp]]}
        door = {"id": "d1", "center": [50*mpp, 4*mpp], "width": 0.9}
        _walls, kept, _windows, dropped = snap_openings_and_cut_walls(
            [wall], [door], [], wall_thickness_m=0.2, meters_per_pixel=mpp, wall_thickness_px=4,
        )
        assert len(kept) == 1
        assert not dropped


def test_estimate_scale_returns_none_when_door_masks_are_empty():
    assert estimate_meters_per_pixel_from_doors([]) is None
    assert estimate_meters_per_pixel_from_doors([np.zeros((32, 32), dtype=np.uint8)]) is None


def test_mask_conversion_returns_scaled_polygon_and_area():
    mask = np.zeros((100, 120), dtype=np.uint8)
    cv2.rectangle(mask, (10, 20), (89, 79), 255, thickness=-1)

    polygons = mask_to_polygons_with_holes(mask, meters_per_pixel=0.1, min_area_px=10)

    assert len(polygons) == 1
    polygon = polygons[0]
    assert len(polygon["polygon"]) >= 4
    assert polygon["area_m2"] > 30
    assert all(len(point) == 2 for point in polygon["polygon"])


def test_wall_fallback_creates_thin_hollow_boundary_strips():
    rooms = [{"id": "r1", "polygon": [[0, 0], [5, 0], [5, 4], [0, 4]]}]

    walls = build_walls_from_rooms(rooms, meters_per_pixel=0.02, image_size=(500, 400), wall_thickness_m=0.2)

    assert len(walls) == 1
    assert len(walls[0]["polygon"]) >= 4
    assert len(walls[0]["holes"]) == 1
    assert len(walls[0]["holes"][0]) >= 4
