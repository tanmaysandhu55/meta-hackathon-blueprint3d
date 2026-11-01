"""Test fixtures and isolation configuration for FloorPlan3D."""

import pytest


@pytest.fixture(autouse=True)
def isolate_test_environment(monkeypatch):
    """Ensure local .env credentials do not bleed into mocked offline unit tests."""
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("META_API_KEY", raising=False)
    monkeypatch.setenv("MOCK_AI", "1")
    monkeypatch.setenv("MOCK_MODE", "1")
