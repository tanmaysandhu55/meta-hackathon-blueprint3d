import cv2
import numpy as np

from geometry_processor import detect_doors_and_windows_geometrically


def _encoded(image):
    ok, data = cv2.imencode(".png", image)
    assert ok
    return data.tobytes()


def test_window_pair_inside_wall_band_is_detected_but_detached_pair_is_ignored(monkeypatch):
    image = np.full((360, 520, 3), 255, dtype=np.uint8)
    cv2.rectangle(image, (40, 80), (480, 140), (0, 0, 0), -1)
    # Supply deterministic line proposals from a synthetic paired-mark image;
    # the detector still applies its wall-band and geometry filters.
    monkeypatch.setattr(cv2, "HoughLinesP", lambda *_args, **_kwargs: np.array([
        [[170, 100, 255, 100]], [[170, 120, 255, 120]],
        [[170, 210, 255, 210]], [[170, 223, 255, 223]],
    ], dtype=np.int32))

    _, windows, _, diagnostics = detect_doors_and_windows_geometrically(
        _encoded(image), 0.01, return_diagnostics=True
    )

    assert windows
    assert all(78 <= item["pixel_center"][1] <= 142 for item in windows)
    assert not any(item.get("pixel_center", [0, 0])[1] > 180 for item in windows)
    assert any(item["accepted"] for item in diagnostics if item["kind"] == "window")


def test_unmarked_wall_gap_is_an_open_doorway_not_a_window():
    image = np.full((300, 520, 3), 255, dtype=np.uint8)
    # The 90px (0.9m) break is an entrance in an otherwise continuous wall.
    cv2.line(image, (30, 120), (180, 120), (0, 0, 0), 8)
    cv2.line(image, (270, 120), (490, 120), (0, 0, 0), 8)
    cv2.line(image, (30, 128), (180, 128), (0, 0, 0), 3)
    cv2.line(image, (270, 128), (490, 128), (0, 0, 0), 3)

    doors, windows, _, _ = detect_doors_and_windows_geometrically(
        _encoded(image), 0.01, return_diagnostics=True
    )

    assert any(item["kind"] == "open-doorway" for item in doors)
    assert windows == []


def test_facing_door_arcs_count_as_one_double_door():
    image = np.full((360, 520, 3), 255, dtype=np.uint8)
    cv2.line(image, (40, 150), (480, 150), (0, 0, 0), 5)
    # Two facing 90-degree swing arcs with 1.8m between hinge centers.
    from geometry_processor import detect_door_swing_radii_px
    import geometry_processor

    cv2.ellipse(image, (170, 150), (90, 90), 0, 180, 270, (0, 0, 0), 2)
    cv2.ellipse(image, (350, 150), (90, 90), 0, 270, 360, (0, 0, 0), 2)
    original_detector = geometry_processor.detect_door_swing_radii_px
    geometry_processor.detect_door_swing_radii_px = lambda *_args, **_kwargs: [
        {"center": [170.0, 150.0], "radius": 90.0, "arc_span": 90.0},
        {"center": [350.0, 150.0], "radius": 90.0, "arc_span": 90.0},
    ]
    try:
        doors, _, _, _ = detect_doors_and_windows_geometrically(
            _encoded(image), 0.01, return_diagnostics=True
        )
    finally:
        geometry_processor.detect_door_swing_radii_px = original_detector

    assert sum(item["kind"] == "double" for item in doors) == 1
