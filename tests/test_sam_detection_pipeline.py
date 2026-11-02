import math
import cv2
import numpy as np
import pytest
import shapely.geometry

from meta_sam_service import (
    SamEmptyOutcome,
    SamFailedOutcome,
    query_sam_concept,
    _execute_sam_call,
)
from geometry_processor import (
    detect_doors_and_windows_geometrically,
    snap_openings_and_cut_walls,
    snap_polygon_orthogonal,
    reconstruct_walls_room_first,
)


def _create_synthetic_cad_plan():
    """Generates a clean synthetic 2D CAD floor plan with black lines on white background:
    - 2 rooms separated by an interior wall
    - A 40px doorway gap with a quarter-circle door swing arc
    - An exterior entrance doorway gap
    - Parallel-line window symbols on exterior walls
    """
    img = np.full((600, 800), 255, dtype=np.uint8)

    # Outer wall boundary: rectangle from (100, 100) to (700, 500)
    # Double lines for wall (thickness 10 px)
    cv2.rectangle(img, (100, 100), (700, 500), 0, 2)
    cv2.rectangle(img, (110, 110), (690, 490), 0, 2)

    # Interior dividing wall at x = 400 from y = 110 to y = 490
    cv2.line(img, (395, 110), (395, 490), 0, 2)
    cv2.line(img, (405, 110), (405, 490), 0, 2)

    # Cut an interior door gap in dividing wall at y = 280 to 330 (gap width 50 px)
    img[280:330, 390:410] = 255

    # Draw door swing arc: quarter circle from (405, 280) curving down to (455, 330)
    cv2.ellipse(img, (405, 280), (50, 50), 0, 0, 90, 0, 1)

    # Cut an exterior entrance door gap at bottom wall: x = 220 to 270, y = 485 to 505
    img[485:505, 220:270] = 255

    # Exterior window symbol on top wall: x = 500 to 580 (double thin lines in gap)
    img[95:115, 500:580] = 255
    cv2.line(img, (500, 100), (580, 100), 0, 1)
    cv2.line(img, (500, 105), (580, 105), 0, 1)
    cv2.line(img, (500, 110), (580, 110), 0, 1)

    _, png_bytes = cv2.imencode(".png", img)
    return png_bytes.tobytes(), img


def test_sam_error_vs_empty_distinction(monkeypatch):
    """Verifies that SAM distinguishes empty responses (HTTP 200 with 0 masks)
    from API errors (HTTP 4xx/5xx or exceptions) without hiding errors.
    """
    # 1. Empty outcome
    empty = SamEmptyOutcome("door", prompt_text="door")
    assert empty.outcome == "EMPTY"
    assert "SAM found no 'door'" in empty.reason

    # 2. Failed outcome
    failed = SamFailedOutcome("door", "429 rate limit exceeded", status_code=429, retries=3)
    assert failed.outcome == "FAILED"
    assert "429" in failed.reason
    assert failed.status_code == 429
    assert failed.retries == 3

    # 3. Verify _execute_sam_call raises SamEmptyOutcome when API returns 0 tokens
    class MockClient:
        def with_options(self, **kwargs):
            return self
        class responses:
            @staticmethod
            def create(**kwargs):
                class MockResp:
                    output_text = ""
                return MockResp()

    import time
    deadline = time.monotonic() + 5.0
    with pytest.raises(SamEmptyOutcome) as exc_info:
        _execute_sam_call(
            MockClient(), "sam-3.1", "door", "door", "data:image/png;base64,fake",
            (100, 100), (100, 100), deadline
        )
    assert exc_info.value.outcome == "EMPTY"


def test_sam_retry_logic_on_simulated_errors(monkeypatch):
    """Verifies exponential backoff retry on simulated 429 and 500 errors."""
    calls = []

    class Mock429Error(RuntimeError):
        status_code = 429

    class MockRetryClient:
        def with_options(self, **kwargs):
            return self
        class responses:
            @staticmethod
            def create(**kwargs):
                calls.append(len(calls) + 1)
                if len(calls) < 3:
                    raise Mock429Error("429 rate limit exceeded")
                class MockResp:
                    output_text = ""
                return MockResp()

    monkeypatch.setattr("time.sleep", lambda s: None)

    import time
    deadline = time.monotonic() + 5.0
    with pytest.raises(SamEmptyOutcome):
        _execute_sam_call(
            MockRetryClient(), "sam-3.1", "door", "door", "data:image/png;base64,fake",
            (100, 100), (100, 100), deadline
        )
    # Succeeded on 3rd attempt after 2 retries
    assert len(calls) == 3


def test_synthetic_cad_opening_detection():
    """Verifies geometric detection of door swing arcs, wall gaps, and window symbols."""
    b, _ = _create_synthetic_cad_plan()
    doors, windows, med_w = detect_doors_and_windows_geometrically(b, meters_per_pixel=0.02)

    assert len(doors) >= 1
    assert any(d.get("has_arc") for d in doors)
    assert all(d.get("source") == "estimated" for d in doors)
    assert med_w is not None and 20 <= med_w <= 80


def test_snapping_and_opening_cutting():
    """Verifies snapping of doors and windows to walls within 0.6m and rectangular wall cutting."""
    # Create horizontal wall from x = 1 to 10 at y = 5 with thickness 0.2m
    # Polygon is a rectangle: [[1, 4.9], [10, 4.9], [10, 5.1], [1, 5.1]]
    wall = {
        "id": "w1",
        "polygon": [[1.0, 4.9], [10.0, 4.9], [10.0, 5.1], [1.0, 5.1]]
    }

    # Door near wall (0.1m away from centerline at x = 5.0, y = 5.1)
    near_door = {
        "id": "d1",
        "center": [5.0, 5.1],
        "width": 0.9,
        "source": "estimated"
    }

    # Far door (1.5m away from wall) -> should be dropped
    far_door = {
        "id": "d2",
        "center": [5.0, 7.0],
        "width": 0.9,
        "source": "estimated"
    }

    cut_walls, snapped_doors, snapped_windows, dropped = snap_openings_and_cut_walls(
        [wall], [near_door, far_door], [], wall_thickness_m=0.2, max_dist_m=0.6
    )

    # Near door is kept and snapped to centerline y = 5.0 (within thickness)
    assert len(snapped_doors) == 1
    assert snapped_doors[0]["id"] == "d1"
    assert abs(snapped_doors[0]["center"][1] - 5.0) <= 0.15
    assert snapped_doors[0]["angle"] == 0.0

    # Far door is dropped with warning
    assert len(dropped) == 1
    assert "d2" in dropped[0]

    # Wall has opening cut at door location (point at 5.0, 5.0 is now cut out of wall)
    assert len(cut_walls) >= 1
    cut_poly = shapely.geometry.Polygon(cut_walls[0]["polygon"])
    assert not cut_poly.contains(shapely.geometry.Point(5.0, 5.0))


def test_room_connectivity():
    """Verifies that snapped openings identify connects: [roomA, roomB]."""
    # Room 1 on left (x: 1 to 5, y: 1 to 5)
    room1 = {
        "id": "r1",
        "polygon": [[1.0, 1.0], [5.0, 1.0], [5.0, 5.0], [1.0, 5.0]]
    }
    # Room 2 on right (x: 5 to 9, y: 1 to 5)
    room2 = {
        "id": "r2",
        "polygon": [[5.0, 1.0], [9.0, 1.0], [9.0, 5.0], [5.0, 5.0]]
    }
    # Dividing wall at x = 5
    wall = {
        "id": "w1",
        "polygon": [[4.9, 1.0], [5.1, 1.0], [5.1, 5.0], [4.9, 5.0]]
    }
    door = {
        "id": "d1",
        "center": [5.0, 3.0],
        "width": 0.9,
        "source": "estimated"
    }

    _, snapped_doors, _, _ = snap_openings_and_cut_walls(
        [wall], [door], [], wall_thickness_m=0.2, cleaned_rooms=[room1, room2]
    )

    assert len(snapped_doors) == 1
    connects = snapped_doors[0].get("connects", [])
    assert "r1" in connects and "r2" in connects


def test_source_tags_preservation():
    """Verifies that source tags ('sam', 'estimated', 'manual') are strictly preserved."""
    door_sam = {"id": "d1", "center": [2.0, 2.0], "width": 0.9, "source": "sam"}
    door_est = {"id": "d2", "center": [4.0, 2.0], "width": 0.9, "source": "estimated"}
    door_man = {"id": "d3", "center": [6.0, 2.0], "width": 0.9, "source": "manual"}

    wall = {"id": "w1", "polygon": [[1.0, 1.9], [8.0, 1.9], [8.0, 2.1], [1.0, 2.1]]}

    _, snapped, _, _ = snap_openings_and_cut_walls([wall], [door_sam, door_est, door_man], [])
    assert len(snapped) == 3
    sources = {d["id"]: d.get("source") for d in snapped}
    assert sources["d1"] == "sam"
    assert sources["d2"] == "estimated"
    assert sources["d3"] == "manual"
