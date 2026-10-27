import cv2
import numpy as np

from geometry_processor import (
    build_walls_from_rooms,
    estimate_meters_per_pixel_from_doors,
    mask_to_polygons_with_holes,
)


def test_estimate_scale_from_door_width():
    mask = np.zeros((80, 80), dtype=np.uint8)
    cv2.rectangle(mask, (10, 20), (29, 25), 255, thickness=-1)

    scale = estimate_meters_per_pixel_from_doors([mask], target_width_m=1.0)

    assert scale is not None
    assert 0.045 <= scale <= 0.055


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
