import hashlib
import json
import tempfile
from pathlib import Path

from cloud_services import _read_recorded_sam_response, _record_sam_response


def test_sam_response_record_and_replay_roundtrip(monkeypatch):
    image_data = "data:image/png;base64,ZmFrZQ=="
    raw_response = json.dumps({"masks": [[[0, 255], [255, 0]]]})
    with tempfile.TemporaryDirectory(prefix="sam-record-", dir=Path(__file__).parent) as temp_dir:
        monkeypatch.setenv("SAM_RESPONSE_DIR", temp_dir)
        monkeypatch.setenv("RECORD_SAM_RESPONSES", "1")

        _record_sam_response(image_data, "room", raw_response)

        digest = hashlib.sha256(image_data.encode("utf-8")).hexdigest()
        recorded_file = Path(temp_dir) / f"{digest}_room.json"
        assert recorded_file.read_text(encoding="utf-8") == raw_response
        monkeypatch.setenv("REPLAY_SAM_RESPONSES", "1")
        assert _read_recorded_sam_response(image_data, "room") == raw_response
