import io
import urllib.error

import cloud_services


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return b'{"masks": [[[0, 1], [1, 0]]]}'


def test_baseten_retries_server_errors_twice_then_succeeds(monkeypatch):
    monkeypatch.setenv("BASETEN_API_KEY", "test-key")
    monkeypatch.setenv("BASETEN_SAM_URL", "https://example.invalid/predict")
    monkeypatch.delenv("REPLAY_SAM_RESPONSES", raising=False)
    monkeypatch.delenv("RECORD_SAM_RESPONSES", raising=False)
    attempts = []

    def fake_urlopen(_request, timeout):
        attempts.append(timeout)
        if len(attempts) < 3:
            raise urllib.error.HTTPError("https://example.invalid/predict", 503, "down", {}, io.BytesIO())
        return FakeResponse()

    monkeypatch.setattr(cloud_services.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(cloud_services.time, "sleep", lambda _seconds: None)

    masks = cloud_services.query_baseten_sam("data:image/png;base64,ZmFrZQ==", "room", (2, 2), timeout=10)

    assert len(attempts) == 3
    assert len(masks) == 1
    assert masks[0].shape == (2, 2)
