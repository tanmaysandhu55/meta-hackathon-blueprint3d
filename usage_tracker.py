"""Thread-safe local usage totals for provider responses that report token counts."""
import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)
_LOCK = threading.Lock()
_USAGE_FILE = Path(__file__).resolve().parent / "local_data" / "baseten_usage.json"


def _empty_usage():
    return {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "by_operation": {}}


def _read_usage():
    try:
        data = json.loads(_USAGE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict) and all(isinstance(data.get(key, 0), int) for key in ("calls", "prompt_tokens", "completion_tokens", "total_tokens")):
            data.setdefault("by_operation", {})
            return data
    except (OSError, ValueError, TypeError):
        pass
    return _empty_usage()


def record_provider_usage(response, operation):
    """Persist usage metadata only; never store prompts, responses, or credentials."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return
    if hasattr(usage, "model_dump"):
        usage = usage.model_dump()
    elif not isinstance(usage, dict):
        usage = {name: getattr(usage, name, None) for name in ("prompt_tokens", "completion_tokens", "total_tokens")}
    prompt = usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0
    completion = usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0
    total = usage.get("total_tokens") or (prompt + completion)
    try:
        prompt, completion, total = (max(0, int(value)) for value in (prompt, completion, total))
    except (TypeError, ValueError):
        logger.warning("Provider returned malformed usage metadata; token totals were not updated")
        return
    with _LOCK:
        data = _read_usage()
        data["calls"] += 1
        data["prompt_tokens"] += prompt
        data["completion_tokens"] += completion
        data["total_tokens"] += total
        entry = data["by_operation"].setdefault(operation, {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
        for key, value in (("calls", 1), ("prompt_tokens", prompt), ("completion_tokens", completion), ("total_tokens", total)):
            entry[key] += value
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        try:
            _USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
            temporary = _USAGE_FILE.with_suffix(".tmp")
            temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
            os.replace(temporary, _USAGE_FILE)
        except OSError as exc:
            logger.warning("Could not persist provider usage totals (%s)", type(exc).__name__)


def get_provider_usage():
    with _LOCK:
        return _read_usage()
