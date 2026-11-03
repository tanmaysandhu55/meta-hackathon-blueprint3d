"""Tests for unified config.py and readiness metadata."""

import importlib
import pytest
from app import app
import config


@pytest.fixture
def test_client():
    app.config.update(TESTING=True)
    return app.test_client()


def test_config_loads_defaults(monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "")
    monkeypatch.setenv("META_API_KEY", "")
    monkeypatch.setenv("MOCK_AI", "1")
    monkeypatch.delenv("MUSE_MODEL", raising=False)
    monkeypatch.delenv("BASETEN_MUSE_MODEL", raising=False)
    reloaded = importlib.reload(config)

    assert reloaded.MODEL_BASE_URL == "https://api.meta.ai/v1"
    assert reloaded.SAM_MODEL == "sam-3.1"
    assert reloaded.MUSE_MODEL == "muse-spark-1.3"
    assert reloaded.MOCK_AI == 1
    assert reloaded.is_live_ready() is False
    assert len(reloaded.SAM_CONCEPTS) == 8


def test_config_mode_logic_requires_key_for_live(monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "")
    monkeypatch.setenv("META_API_KEY", "")
    monkeypatch.setenv("MOCK_AI", "0")
    reloaded = importlib.reload(config)

    # Should fall back to MOCK_AI=1 because no key is present
    assert reloaded.MOCK_AI == 1
    assert reloaded.is_live_ready() is False

    monkeypatch.setenv("MODEL_API_KEY", "meta_test_secret_key_123")
    monkeypatch.setenv("MOCK_AI", "0")
    reloaded_live = importlib.reload(config)
    assert reloaded_live.MOCK_AI == 0
    assert reloaded_live.is_live_ready() is True


def test_config_rejects_contributor_models(monkeypatch):
    monkeypatch.setenv("MUSE_MODEL", "meta-models/muse-spark-contributor-1026")
    with pytest.raises(ValueError, match="strictly requires Standard-tier models"):
        importlib.reload(config)


def test_status_endpoint_never_leaks_api_key(test_client, monkeypatch):
    secret_key = "super_confidential_meta_key_value_9999"
    monkeypatch.setenv("MODEL_API_KEY", secret_key)
    monkeypatch.setenv("MOCK_AI", "0")
    importlib.reload(config)

    response = test_client.get("/api/config/status")
    assert response.status_code == 200
    data = response.get_json()

    assert data["key_configured"] is True
    # The key itself, its prefixes or hashes must NEVER appear anywhere in the response
    assert secret_key not in str(data)
    assert "super_confidential" not in str(data)
    assert data["sam_model"] == "sam-3.1"
    assert data["muse_model"] == "muse-spark-1.3"


def test_budget_guard_limit_configured():
    assert config.MAX_SAM_CALLS_PER_UPLOAD >= 1
    assert config.SAM_TIMEOUT >= 10
    assert config.MUSE_TIMEOUT >= 10
