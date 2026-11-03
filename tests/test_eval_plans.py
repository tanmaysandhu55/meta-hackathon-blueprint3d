import shutil
from pathlib import Path

from PIL import Image

from scripts.eval_plans import _make_overlays


def test_opening_overlay_marks_rejected_geometry_candidates():
    output_root = Path(__file__).parents[1] / "out" / "test-eval-overlays"
    shutil.rmtree(output_root, ignore_errors=True)
    base = Image.new("RGB", (80, 80), "white")
    payload = {
        "scene": {
            "meta": {
                "openingDiagnostics": [{
                    "kind": "window",
                    "candidate": "pair-3-8",
                    "accepted": False,
                    "pixelCenter": [40, 40],
                    "reason": "paired line is not on an exterior wall",
                }],
                "storyOffsets": [],
            },
            "walls": [],
            "rooms": [],
        }
    }
    summary = {"mpp": 0.02}
    output = _make_overlays(
        Path("plan.png"),
        base,
        {"opening_candidates": [], "story_origins": {0: (0, 0)}},
        payload,
        summary,
        output_root,
    )

    try:
        overlay = Image.open(output / "05_openings.png").convert("RGB")
        # Rejected points use a red cross; the exact center is one of its strokes.
        red, green, blue = overlay.getpixel((32, 40))
        assert red > 180 and green < 100 and blue < 100
    finally:
        shutil.rmtree(output_root, ignore_errors=True)
