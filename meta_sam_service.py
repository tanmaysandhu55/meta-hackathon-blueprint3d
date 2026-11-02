"""Meta Model API integration for Segment Anything Model 3.1."""

import base64
import logging
import os
import time
from io import BytesIO

import cv2
import numpy as np
from openai import APIConnectionError, APITimeoutError, OpenAI
from PIL import Image

logger = logging.getLogger(__name__)

# Concept wording experiments run automatically in order per Part 3 specification
CONCEPT_WORDING_EXPERIMENTS = {
    "door": ["door", "door swing arc", "doorway", "opening in wall"],
    "window": ["window", "window symbol"],
    "room": ["room", "floor plan room", "enclosed room"],
    "wall": ["wall", "black wall line"],
    "staircase": ["staircase", "stairs"],
    "elevator": ["elevator"],
    "corridor": ["corridor", "hallway"],
    "toilet": ["toilet", "bathroom"],
}

CONCEPT_PROMPTS = {k: v[0] for k, v in CONCEPT_WORDING_EXPERIMENTS.items()}
CONCEPT_FALLBACK_PROMPTS = {}


class SamMaskList(list):
    """List of segmentation masks carrying metadata such as concept_used."""
    def __init__(self, iterable=(), concept_used=None):
        super().__init__(iterable)
        self.concept_used = concept_used


class SamOutcomeError(Exception):
    """Base error for SAM outcome classification."""
    pass


class SamEmptyOutcome(ValueError, SamOutcomeError):
    """SAM returned 200 OK with zero matching regions."""
    def __init__(self, concept, prompt_text=""):
        super().__init__(f"SAM found no '{concept}'.")
        self.concept = concept
        self.prompt_text = prompt_text
        self.outcome = "EMPTY"
        self.safe_category = "no_matches"
        self.reason = f"SAM found no '{concept}'"


class SamFailedOutcome(SamOutcomeError):
    """SAM call failed due to API error, rate limit, timeout, or parsing failure."""
    def __init__(self, concept, reason, status_code=None, retries=0):
        super().__init__(f"SAM failed for '{concept}': {reason}")
        self.concept = concept
        self.reason = reason
        self.status_code = status_code
        self.retries = retries
        self.outcome = "FAILED"
        self.safe_category = "unavailable"


def is_sam_configured():
    api_key = os.getenv("MODEL_API_KEY", "").strip() or os.getenv("META_API_KEY", "").strip()
    return bool(
        api_key
        and os.getenv("SAM_MODEL", "sam-3.1").strip()
    )


def _prepare_image(image_bytes, min_side=1024, max_side=1500):
    """Convert to high-contrast line drawing with 5% border padding and coordinate mapping."""
    np_arr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    if img is None:
        with Image.open(BytesIO(image_bytes)) as source:
            img = cv2.cvtColor(np.array(source.convert("RGB")), cv2.COLOR_RGB2BGR)

    orig_h, orig_w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Clean high contrast: thicken thin lines slightly on light backgrounds
    if gray.mean() > 127:
        _, binary = cv2.threshold(gray, 220, 255, cv2.THRESH_BINARY)
        inv = 255 - binary
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        thickened = cv2.dilate(inv, kernel, iterations=1)
        clean = 255 - thickened
    else:
        _, binary = cv2.threshold(gray, 40, 255, cv2.THRESH_BINARY)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        clean = cv2.dilate(binary, kernel, iterations=1)

    # 5% white border padding
    pad_y = max(4, int(orig_h * 0.05))
    pad_x = max(4, int(orig_w * 0.05))
    padded = cv2.copyMakeBorder(clean, pad_y, pad_y, pad_x, pad_x, cv2.BORDER_CONSTANT, value=255)
    pad_h, pad_w = padded.shape[:2]

    # Resize so longest side is between 1024 and 1500 px
    longest = max(pad_w, pad_h)
    if longest > max_side:
        scale = max_side / float(longest)
    elif longest < min_side:
        scale = min_side / float(longest)
    else:
        scale = 1.0

    sent_w = int(round(pad_w * scale))
    sent_h = int(round(pad_h * scale))
    if scale != 1.0:
        interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LANCZOS4
        prepared = cv2.resize(padded, (sent_w, sent_h), interpolation=interp)
    else:
        prepared = padded

    prepared_rgb = cv2.cvtColor(prepared, cv2.COLOR_GRAY2RGB)
    success, encoded_buf = cv2.imencode(".png", prepared_rgb)
    if not success:
        output = BytesIO()
        Image.fromarray(prepared_rgb).save(output, format="PNG", optimize=True)
        encoded_bytes = output.getvalue()
    else:
        encoded_bytes = encoded_buf.tobytes()

    encoded = base64.b64encode(encoded_bytes).decode("ascii")
    data_url = f"data:image/png;base64,{encoded}"

    mapping = {
        "orig_size": (orig_w, orig_h),
        "pad_y": pad_y,
        "pad_x": pad_x,
        "pad_size": (pad_w, pad_h),
        "sent_size": (sent_w, sent_h),
        "scale": scale,
    }
    return (sent_w, sent_h), data_url, mapping


def _restore_masks(masks, mapping, target_size):
    """Restore SAM masks from prepared padded coordinates back to target image size."""
    orig_w, orig_h = mapping["orig_size"]
    pad_y, pad_x = mapping["pad_y"], mapping["pad_x"]
    pad_w, pad_h = mapping["pad_size"]
    target_w, target_h = target_size

    restored = []
    for mask in masks:
        if (mask.shape[1], mask.shape[0]) != (pad_w, pad_h):
            mask = cv2.resize(mask, (pad_w, pad_h), interpolation=cv2.INTER_NEAREST)
        unpadded = mask[pad_y : pad_y + orig_h, pad_x : pad_x + orig_w]
        if (unpadded.shape[1], unpadded.shape[0]) != (target_w, target_h):
            unpadded = cv2.resize(unpadded, (target_w, target_h), interpolation=cv2.INTER_NEAREST)
        restored.append(np.ascontiguousarray(unpadded, dtype=np.uint8))
    return restored


def _safe_category(exc):
    if isinstance(exc, ValueError) and "detected no matching regions" in str(exc).lower():
        return "no_matches"
    status = getattr(exc, "status_code", None)
    if status in (401, 403):
        return "auth"
    if isinstance(exc, APITimeoutError):
        return "timeout"
    if status in (400, 404, 422):
        return "bad_response"
    return "unavailable"


def _decode_masks(output_text, expected_size):
    """Decode Meta's SAM token response into the app's 0/255 mask contract."""
    from meta_sam_parser import CompletedOutcome, decode_mask_to_raster, image_segmentation_format

    parser = image_segmentation_format().create_parser()
    parser.push(output_text)
    result = parser.finish(CompletedOutcome()).result
    if result.outcome.status != "completed":
        raise ValueError("SAM returned an incomplete segmentation response.")
    if any(getattr(item.severity, "value", item.severity) == "error" for item in result.diagnostics):
        raise ValueError("SAM returned a malformed mask payload.")

    output_width, output_height = expected_size
    masks = []
    for record in result.records:
        if getattr(record, "kind", None) != "mask":
            continue
        mask_data = record.mask
        width, height = int(mask_data.width), int(mask_data.height)
        if width <= 0 or height <= 0 or width * height > 20_000_000:
            raise ValueError("SAM returned invalid mask dimensions.")
        raster = np.frombuffer(decode_mask_to_raster(mask_data), dtype=np.uint8)
        if raster.size != width * height:
            raise ValueError("SAM returned a mask with an invalid size.")
        mask = raster.reshape((height, width)) * 255
        if (width, height) != (output_width, output_height):
            mask = cv2.resize(mask, (output_width, output_height), interpolation=cv2.INTER_NEAREST)
        masks.append(np.ascontiguousarray(mask, dtype=np.uint8))
    return masks


def _execute_sam_call(client, model, concept, prompt_text, data_url, size, image_size, deadline, mapping=None):
    for attempt in range(3):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            exc = SamFailedOutcome(concept, "timeout (retried 3 times)", status_code=408, retries=attempt)
            exc.safe_category = "timeout"
            raise exc
        try:
            output_text = ""
            stream_fn = getattr(client.responses, "stream", None)
            if callable(stream_fn):
                try:
                    with client.with_options(timeout=remaining).responses.stream(
                        model=model,
                        input=[{"type": "message", "role": "user", "content": [
                            {"type": "input_text", "text": prompt_text},
                            {"type": "input_image", "image_url": data_url},
                        ]}],
                        metadata={"mask_encoding": "one_bit", "include_confidence": "true"},
                    ) as stream:
                        for event in stream:
                            if getattr(event, "type", None) == "response.output_text.delta":
                                output_text += getattr(event, "delta", "")
                except Exception as stream_exc:
                    logger.debug("SAM streaming failed, trying create: %s", stream_exc)
                    output_text = ""
            if not output_text:
                response = client.with_options(timeout=remaining).responses.create(
                    model=model,
                    input=[{"type": "message", "role": "user", "content": [
                        {"type": "input_text", "text": prompt_text},
                        {"type": "input_image", "image_url": data_url},
                    ]}],
                    metadata={"mask_encoding": "one_bit", "include_confidence": "true"},
                )
                output_text = getattr(response, "output_text", "") or ""

            masks = _decode_masks(output_text, size)
            if not masks:
                raise SamEmptyOutcome(concept, prompt_text)

            target_size = tuple(map(int, image_size))
            if mapping:
                masks = _restore_masks(masks, mapping, target_size)
            elif size != target_size:
                masks = [
                    cv2.resize(mask, target_size, interpolation=cv2.INTER_NEAREST)
                    for mask in masks
                ]
            return masks
        except SamEmptyOutcome:
            raise
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            category = _safe_category(exc)
            exc.safe_category = category
            exc.outcome = "FAILED"

            is_429 = (status == 429) or ("rate" in str(exc).lower() and "limit" in str(exc).lower())
            if is_429:
                reason = f"429 rate limit (retried {attempt + 1} times)"
            elif isinstance(exc, APITimeoutError):
                reason = f"timeout (retried {attempt + 1} times)"
            elif isinstance(exc, APIConnectionError):
                reason = f"connection error (retried {attempt + 1} times)"
            elif status in (401, 403):
                reason = "authentication failed"
            elif status and status >= 500:
                reason = f"{status} server error (retried {attempt + 1} times)"
            elif isinstance(exc, ValueError) and "malformed" in str(exc).lower():
                reason = f"parse error: {exc}"
            else:
                reason = f"error ({category}): {str(exc)[:80]}"
            exc.reason = reason

            retryable = is_429 or isinstance(exc, (APIConnectionError, APITimeoutError)) or ((status or 0) >= 500)
            logger.warning("SAM segmentation failed for %s (attempt=%d, reason=%s)", concept, attempt + 1, reason)
            delay = 0.5 * (2 ** attempt)
            if not retryable or attempt == 2 or time.monotonic() + delay >= deadline:
                raise
            time.sleep(delay)

    final_exc = SamFailedOutcome(concept, "processing time budget exceeded", status_code=408, retries=3)
    final_exc.safe_category = "timeout"
    raise final_exc


def query_sam_concept(image_bytes, concept, image_size, timeout=75):
    """Run concept experiments in priority order, stopping at first match."""
    prompts = CONCEPT_WORDING_EXPERIMENTS.get(concept)
    if not prompts:
        if concept in CONCEPT_PROMPTS:
            prompts = [CONCEPT_PROMPTS[concept]]
        else:
            raise ValueError(f"Unknown segmentation concept: {concept}")
    if not is_sam_configured():
        raise RuntimeError("Meta API key is not configured.")

    model = os.getenv("SAM_MODEL", "sam-3.1").strip()
    if not model:
        raise ValueError("SAM_MODEL is empty.")

    size, data_url, mapping = _prepare_image(image_bytes)
    deadline = time.monotonic() + timeout
    api_key = os.getenv("MODEL_API_KEY", "").strip() or os.getenv("META_API_KEY", "").strip()
    client = OpenAI(
        api_key=api_key,
        base_url=os.getenv("META_API_BASE_URL", os.getenv("MODEL_BASE_URL", "https://api.meta.ai/v1")).strip(),
        timeout=timeout,
        max_retries=0,
    )

    last_empty = None
    for current_prompt in prompts:
        try:
            masks = _execute_sam_call(client, model, concept, current_prompt, data_url, size, image_size, deadline, mapping)
            return SamMaskList(masks, concept_used=current_prompt)
        except SamEmptyOutcome as exc:
            last_empty = exc
            continue

    if last_empty is not None:
        raise last_empty
    raise SamEmptyOutcome(concept, prompts[0])
