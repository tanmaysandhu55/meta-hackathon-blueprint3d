import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Load .env if present; if not present, app falls back cleanly to MOCK_AI=1
env_path = Path(__file__).resolve().parent / ".env"
if "PYTEST_CURRENT_TEST" not in os.environ:
    try:
        from dotenv import load_dotenv
        if env_path.is_file():
            load_dotenv(dotenv_path=env_path, override=True)
        else:
            load_dotenv(override=True)
    except ImportError:
        # Manual fallback parser for minimal environments without python-dotenv
        if env_path.is_file():
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    os.environ[k.strip()] = v.strip().strip("'\"")

# Unified API Key & Base URL
if os.getenv("META_API_KEY") and not os.getenv("MODEL_API_KEY"):
    logger.warning("META_API_KEY is deprecated. Please update your environment to MODEL_API_KEY.")

MODEL_API_KEY = (os.getenv("MODEL_API_KEY") or os.getenv("META_API_KEY") or "").strip()
MODEL_BASE_URL = os.getenv("MODEL_BASE_URL", "https://api.meta.ai/v1").strip()

# Model Identifiers
SAM_MODEL = os.getenv("SAM_MODEL", "sam-3.1").strip()

# Muse Spark Model ID (Verified Standard Tier per Meta dev docs: muse-spark-1.3)
# Privacy guard: Contributor tier models are strictly rejected to prevent training on private blueprints
_raw_muse = (os.getenv("MUSE_MODEL") or os.getenv("BASETEN_MUSE_MODEL") or "muse-spark-1.3").strip()
if "contributor" in _raw_muse.lower():
    raise ValueError(
        f"MUSE_MODEL '{_raw_muse}' contains 'contributor'. "
        "FloorPlan3D strictly requires Standard-tier models (e.g. 'muse-spark-1.3') "
        "to guarantee user architectural blueprints are never used for model training."
    )
MUSE_MODEL = _raw_muse

MUSE_IMAGE_MODEL = os.getenv("MUSE_IMAGE_MODEL", "muse-image-1.0").strip()
MUSE_VOICE_MODEL = os.getenv("MUSE_VOICE_MODEL", "muse-voice-transcribe-1.0").strip()

# Mock Mode Logic:
# Default to 1 (mock mode) until a key is present and MOCK_AI is explicitly set to 0
_mock_raw = os.getenv("MOCK_AI", os.getenv("MOCK_MODE", "")).strip().lower()
if _mock_raw in ("0", "false", "no", "off"):
    if not MODEL_API_KEY:
        logger.warning("MOCK_AI=0 requested but MODEL_API_KEY is unset; falling back to MOCK_AI=1.")
        MOCK_AI = 1
    else:
        MOCK_AI = 0
else:
    MOCK_AI = 1

# Segmentation Concepts (Official singular noun phrases)
SAM_CONCEPTS = [
    "room",
    "door",
    "window",
    "wall",
    "staircase",
    "elevator",
    "corridor",
    "toilet",
]

# Budgets, Timeouts & Limits
MAX_IMAGE_SIDE = int(os.getenv("MAX_IMAGE_SIDE", "1500"))
SAM_TIMEOUT = int(os.getenv("SAM_TIMEOUT", "75"))
MUSE_TIMEOUT = int(os.getenv("MUSE_TIMEOUT", "30"))
MAX_PARALLEL = int(os.getenv("MAX_PARALLEL", "4"))
MAX_SAM_CALLS_PER_UPLOAD = int(os.getenv("MAX_SAM_CALLS_PER_UPLOAD", "12"))
DEFAULT_METERS_PER_PIXEL = float(os.getenv("DEFAULT_METERS_PER_PIXEL", "0.02"))
DEFAULT_WALL_HEIGHT = float(os.getenv("DEFAULT_WALL_HEIGHT", "3.0"))
DEFAULT_WALL_THICKNESS = float(os.getenv("DEFAULT_WALL_THICKNESS", "0.2"))


def is_live_ready():
    """True if live AI calls can be made (key is configured and MOCK_AI=0)."""
    return bool(MODEL_API_KEY and MOCK_AI == 0)


def get_config_status():
    """Returns safe, non-secret configuration status metadata for the frontend."""
    reasons = []
    if not MODEL_API_KEY:
        reasons.append("MODEL_API_KEY is not configured in .env")
    if MOCK_AI == 1:
        reasons.append("MOCK_AI=1 is enabled (running prepared/local pipelines)")

    return {
        "live_ready": is_live_ready(),
        "mock_mode": bool(MOCK_AI == 1),
        "key_configured": bool(MODEL_API_KEY),
        "sam_model": SAM_MODEL,
        "muse_model": MUSE_MODEL,
        "reasons": reasons,
    }
