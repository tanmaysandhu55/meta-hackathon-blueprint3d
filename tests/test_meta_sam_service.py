import base64
import io
import types

import numpy as np
import pytest
from PIL import Image

import meta_sam_service


def _png_bytes(size=(80, 60)):
    output = io.BytesIO()
    Image.new("RGB", size, "white").save(output, format="PNG")
    return output.getvalue()


def test_sam_request_uses_meta_model_api_and_restores_original_mask_size(monkeypatch):
    monkeypatch.setenv("META_API_KEY", "test-only")
    calls = []

    class Client:
        def __init__(self, **kwargs):
            calls.append(("client", kwargs))
            self.responses = self

        def with_options(self, **_kwargs):
            return self

        def create(self, **kwargs):
            calls.append(("request", kwargs))
            return types.SimpleNamespace(output_text="structured mask output")

    monkeypatch.setattr(meta_sam_service, "OpenAI", Client)
    monkeypatch.setattr(
        meta_sam_service,
        "_decode_masks",
        lambda _text, size: [np.full((size[1], size[0]), 255, dtype=np.uint8)],
    )
    image = _png_bytes((2400, 1000))
    masks = meta_sam_service.query_sam_concept(image, "room", (2400, 1000))

    assert len(masks) == 1
    assert masks[0].shape == (1000, 2400)
    request = next(item[1] for item in calls if item[0] == "request")
    assert request["model"] == "sam-3.1"
    assert request["metadata"]["mask_encoding"] == "one_bit"
    content = request["input"][0]["content"]
    assert content[0]["type"] == "input_text"
    assert "room" in content[0]["text"]
    data_url = content[1]["image_url"]
    with Image.open(io.BytesIO(base64.b64decode(data_url.split(",", 1)[1]))) as sent_image:
        # The longest prepared side is capped before requests reach the API.
        assert max(sent_image.size) <= 1500


def test_sam_retries_temporary_server_errors(monkeypatch):
    monkeypatch.setenv("META_API_KEY", "test-only")
    attempts = []

    class ServerError(Exception):
        status_code = 503

    class Client:
        def __init__(self, **_kwargs):
            self.responses = self

        def with_options(self, **_kwargs):
            return self

        def create(self, **_kwargs):
            attempts.append(1)
            raise ServerError("private provider detail")

    monkeypatch.setattr(meta_sam_service, "OpenAI", Client)
    monkeypatch.setattr(meta_sam_service.time, "sleep", lambda _delay: None)
    with pytest.raises(ServerError) as error:
        meta_sam_service.query_sam_concept(_png_bytes(), "wall", (80, 60))
    assert error.value.safe_category == "unavailable"
    assert len(attempts) == 3


def test_sam_mask_decoder_places_box_local_mask_at_source_bounds(monkeypatch):
    fake_mask = types.SimpleNamespace(width=3, height=2)
    fake_bounds = types.SimpleNamespace(left=2, top=1, right=5, bottom=3)
    FakeRecord = type("FakeRecord", (), {"kind": "mask", "mask": fake_mask, "bounds": fake_bounds})

    class FakeResult:
        records = (FakeRecord(),)
        diagnostics = ()
        outcome = types.SimpleNamespace(status="completed")

    class FakeParser:
        def push(self, _text):
            return ()

        def finish(self, _outcome):
            return types.SimpleNamespace(result=FakeResult())

    fake_library = types.ModuleType("meta_sam_parser")
    fake_library.CompletedOutcome = lambda: object()
    fake_library.decode_mask_to_raster = lambda _mask: bytes([0, 1, 0, 1, 1, 0])
    fake_library.image_segmentation_format = lambda: types.SimpleNamespace(create_parser=FakeParser)
    monkeypatch.setitem(__import__("sys").modules, "meta_sam_parser", fake_library)

    masks = meta_sam_service._decode_masks("wire output", (8, 6))
    assert masks[0].shape == (6, 8)
    assert set(np.unique(masks[0])).issubset({0, 255})
    assert np.count_nonzero(masks[0]) == 3
    assert not np.any(masks[0][:1, :])
    assert not np.any(masks[0][:, :2])
    assert np.array_equal(masks[0][1:3, 2:5], np.array([[0, 255, 0], [255, 255, 0]], dtype=np.uint8))


def test_sam_decoder_accepts_documented_mask_payload():
    payload = "<0f>0<|box;x1=0;y1=0;x2=4;y2=4;w=5;h=5|><|mask;x=0;y=0;data=5,5,!!!!!(QO(0lu8?|>"
    masks = meta_sam_service._decode_masks(payload, (5, 5))
    assert len(masks) == 1
    assert masks[0].shape == (5, 5)
    assert set(np.unique(masks[0])).issubset({0, 255})
