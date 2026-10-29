import base64
import io
from pathlib import Path

import numpy as np
from PIL import Image

from geometry_processor import extract_doors, mask_to_polygons_with_holes
import baseten_service
from baseten_service import validate_room_labels
from segmentation_service import prepare_segmentation, segment_concept, segment_prepared_concept


def _image_data_url(size=(16, 16)):
    output = io.BytesIO()
    Image.new("RGB", size, "white").save(output, format="PNG")
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")


def test_local_segmentation_finds_sample_rooms_at_source_size():
    path = Path(__file__).parents[1] / "samples" / "sample_floorplan.png"
    image_bytes = path.read_bytes()
    size = Image.open(io.BytesIO(image_bytes)).size
    rooms = segment_concept(image_bytes, "room", size)
    doors = segment_concept(image_bytes, "door", size)
    windows = segment_concept(image_bytes, "window", size)
    assert rooms
    assert doors
    assert windows
    assert 5 <= len(rooms) <= 14
    assert len(doors) <= 100
    assert len(windows) <= 200
    assert all(mask.dtype == np.uint8 and mask.shape == (size[1], size[0]) for mask in rooms)
    assert all(set(np.unique(mask)).issubset({0, 255}) for mask in rooms)


def test_sample_geometry_keeps_thin_door_strokes():
    path = Path(__file__).parents[1] / "samples" / "sample_floorplan.png"
    image_bytes = path.read_bytes()
    size = Image.open(io.BytesIO(image_bytes)).size
    room_candidates = []
    for mask in segment_concept(image_bytes, "room", size):
        for polygon in mask_to_polygons_with_holes(mask, meters_per_pixel=0.02, min_area_px=200):
            room_candidates.append({"id": f"r{len(room_candidates) + 1}", "polygon": polygon["polygon"]})
    doors = extract_doors(segment_concept(image_bytes, "door", size), room_candidates, meters_per_pixel=0.02)
    assert len(doors) >= 3


def test_prepared_segmentation_matches_single_concept_contract():
    path = Path(__file__).parents[1] / "samples" / "sample_floorplan.png"
    image_bytes = path.read_bytes()
    size = Image.open(io.BytesIO(image_bytes)).size
    prepared = prepare_segmentation(image_bytes, size)
    for concept in ("room", "wall", "door", "window"):
        expected = segment_concept(image_bytes, concept, size)
        actual = segment_prepared_concept(prepared, concept)
        assert len(actual) == len(expected)
        assert all(np.array_equal(left, right) for left, right in zip(actual, expected))


def test_room_label_validation_accepts_valid_ids_and_clamps_confidence():
    candidates = [{"id": "r1"}]
    labels = validate_room_labels('{"rooms":[{"id":"r1","type":"lab","label":"Chem Lab","confidence":4}]}', candidates)
    assert labels["r1"] == {"type": "lab", "label": "Chem Lab", "confidence": 1.0}


def test_room_label_validation_treats_non_finite_confidence_as_zero():
    labels = validate_room_labels(
        '{"rooms":[{"id":"r1","type":"room","label":"Room A","confidence":NaN}]}',
        [{"id": "r1"}],
    )
    assert labels["r1"]["confidence"] == 0.0


def test_room_label_validation_handles_text_and_rejects_unknown_ids():
    candidates = [{"id": "r1"}]
    wrapped = 'Result: {"rooms":[{"id":"r1","type":"classroom","label":"Room A","confidence":0.7},{"id":"x","label":"ignore"}]}'
    assert set(validate_room_labels(wrapped, candidates)) == {"r1"}
    assert validate_room_labels("not json", candidates) == {}


def test_muse_retries_transient_server_error(monkeypatch):
    monkeypatch.setenv("BASETEN_API_KEY", "test-only")
    monkeypatch.setenv("BASETEN_MUSE_MODEL", "meta-models/muse-spark-open-1026")
    attempts = []

    class TransientError(Exception):
        status_code = 503

    class Client:
        def __init__(self, **_kwargs):
            self.chat = self
            self.completions = self

        def with_options(self, **_kwargs):
            return self

        def create(self, **_kwargs):
            attempts.append(1)
            if len(attempts) < 3:
                raise TransientError("temporary failure")
            class Message:
                content = '{"rooms":[{"id":"r1","type":"room","label":"Room A","confidence":0.8}]}'
            class Choice:
                message = Message()
            class Result:
                choices = [Choice()]
            return Result()

    monkeypatch.setattr(baseten_service, "OpenAI", Client)
    monkeypatch.setattr(baseten_service.time, "sleep", lambda _delay: None)
    assert baseten_service.label_rooms(_image_data_url(), [{"id": "r1"}])
    assert len(attempts) == 3


def test_muse_image_payload_is_downscaled_to_2048_pixels():
    resized_url = baseten_service._image_data_url(_image_data_url((2400, 1000)))
    _, encoded = resized_url.split(",", 1)
    with Image.open(io.BytesIO(base64.b64decode(encoded))) as image:
        assert max(image.size) == 2048


def test_invalid_muse_image_uses_generic_label_fallback(monkeypatch):
    monkeypatch.setenv("BASETEN_API_KEY", "test-only")
    monkeypatch.setenv("BASETEN_MUSE_MODEL", "meta-models/muse-spark-open-1026")
    monkeypatch.setattr(
        baseten_service,
        "OpenAI",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("API client must not be created")),
    )
    assert baseten_service.label_rooms("not an image", [{"id": "r1"}]) == {}
    assert baseten_service.last_error_category() == "bad_response"


def test_baseten_map_answer_uses_grounded_facts_and_exact_hackathon_model(monkeypatch):
    monkeypatch.setenv("BASETEN_API_KEY", "test-only")
    seen = []

    class Client:
        def __init__(self, **kwargs):
            seen.append(("client", kwargs))
            self.chat = self
            self.completions = self

        def with_options(self, **_kwargs):
            return self

        def create(self, **kwargs):
            seen.append(("request", kwargs))
            class Message:
                content = "The Computer Lab is on Level 1."
            class Choice:
                message = Message()
            class Result:
                choices = [Choice()]
            return Result()

    monkeypatch.setattr(baseten_service, "OpenAI", Client)
    result = baseten_service.answer_scene_question("Where is the Computer Lab?", {"rooms": [{"label": "Computer Lab"}]})

    assert result == "The Computer Lab is on Level 1."
    assert next(item[1]["base_url"] for item in seen if item[0] == "client") == "https://inference.baseten.co/v1"
    request = next(item[1] for item in seen if item[0] == "request")
    assert request["model"] == "meta-models/muse-spark-open-1026"
    assert request["max_tokens"] == 4096
    assert "Scene facts" in request["messages"][1]["content"]


def test_repository_has_no_removed_provider_references():
    root = Path(__file__).parents[1]
    needles = ("mo" + "dal", "fire" + "works")
    for path in root.rglob("*"):
        if not path.is_file() or any(part in {".git", ".venv", "__pycache__", ".pytest_cache"} for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8").lower()
        except (UnicodeDecodeError, OSError):
            continue
        assert not any(needle in text for needle in needles), f"Removed provider reference remains in {path}"

