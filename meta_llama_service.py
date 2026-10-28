"""Optional room labeling through Meta's hosted Llama-compatible API."""
import base64
import json
import logging
import math
import os
import time
import threading
from io import BytesIO

from openai import OpenAI
from openai import APIConnectionError, APITimeoutError
from PIL import Image

logger = logging.getLogger(__name__)
_error_state = threading.local()
ALLOWED_TYPES = {"room", "classroom", "lab", "corridor", "stairs", "elevator", "restroom", "entrance", "other"}


def _configured():
    return bool(os.getenv("LLAMA_API_KEY", "").strip() and os.getenv("LLAMA_VISION_MODEL", "").strip())


def is_labeling_configured():
    return _configured()


def last_error_category():
    return getattr(_error_state, "category", None)


def validate_room_labels(raw_text, candidates):
    if not isinstance(raw_text, str):
        return {}
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError:
        start, end = raw_text.find("{"), raw_text.rfind("}")
        if start < 0 or end <= start:
            return {}
        try:
            data = json.loads(raw_text[start:end + 1])
        except json.JSONDecodeError:
            return {}
    ids = {str(room.get("id")) for room in candidates}
    labels = {}
    for row in data.get("rooms", []) if isinstance(data, dict) else []:
        if not isinstance(row, dict) or str(row.get("id")) not in ids:
            continue
        rid = str(row["id"])
        room_type = str(row.get("type", "room")).strip().lower()
        if room_type not in ALLOWED_TYPES:
            room_type = "room"
        label = row.get("label")
        if not isinstance(label, str) or not label.strip():
            label = f"Room {rid[1:]}"
        try:
            confidence = float(row.get("confidence", 0))
            confidence = max(0.0, min(1.0, confidence)) if math.isfinite(confidence) else 0.0
        except (TypeError, ValueError):
            confidence = 0.0
        labels[rid] = {"type": room_type, "label": label.strip()[:100], "confidence": confidence}
    return labels


def _image_data_url(data_url):
    if not isinstance(data_url, str) or "," not in data_url:
        raise ValueError("Invalid image data URL.")
    _, encoded = data_url.split(",", 1)
    raw = base64.b64decode(encoded, validate=True)
    with Image.open(BytesIO(raw)) as source:
        source.load()
        image = source.convert("RGB")
    image.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
    output = BytesIO()
    image.save(output, format="JPEG", quality=88, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(output.getvalue()).decode("ascii")


def label_rooms(b64_data_url, room_candidates, timeout=45):
    """Return validated labels; empty dict triggers the app's generic fallback."""
    _error_state.category = None
    if not room_candidates or not _configured():
        return {}
    try:
        image_url = _image_data_url(b64_data_url)
    except Exception as exc:
        _error_state.category = "bad_response"
        logger.warning("Llama labeling skipped because image preparation failed (%s)", type(exc).__name__)
        return {}

    client = OpenAI(
        api_key=os.environ["LLAMA_API_KEY"].strip(),
        base_url=os.getenv("LLAMA_API_BASE_URL", "https://api.meta.ai/v1").strip(),
        timeout=timeout,
        max_retries=0,
    )
    prompt = (
        "Classify only the supplied floor-plan room regions. Allowed types: "
        + json.dumps(sorted(ALLOWED_TYPES))
        + '. Return JSON only in this form: {"rooms":[{"id":"r1","type":"classroom",'
          '"label":"Classroom 101","confidence":0.9}]}. Keep every candidate ID exactly once. Candidates: '
        + json.dumps(room_candidates, ensure_ascii=False)
    )
    messages = [{"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": image_url}},
    ]}]
    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=os.environ["LLAMA_VISION_MODEL"].strip(), messages=messages,
                temperature=0.1, max_completion_tokens=1600,
            )
            result = validate_room_labels(response.choices[0].message.content or "", room_candidates)
            if not result:
                logger.warning("Llama room-label response had an unsupported JSON shape")
            return result
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            category = "auth" if status in (401, 403) else "timeout" if isinstance(exc, APITimeoutError) else "bad_response" if status in (400, 404, 422) else "unavailable"
            _error_state.category = category
            retryable = isinstance(exc, (APIConnectionError, APITimeoutError)) or (status is not None and status >= 500)
            logger.warning("Llama labeling request failed (category=%s): %s", category, type(exc).__name__)
            if not retryable or attempt == 2:
                return {}
            time.sleep(0.4 * (2 ** attempt))
    return {}
