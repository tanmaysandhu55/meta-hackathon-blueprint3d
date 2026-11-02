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

CONCEPT_PROMPTS = {
    "room": "room",
    "wall": "wall",
    "door": "door",
    "window": "window",
    "staircase": "staircase",
    "elevator": "elevator",
    "corridor": "corridor",
    "toilet": "toilet",
}

# Single noun-phrase concept prompts per Meta SAM 3.1 specification
CONCEPT_FALLBACK_PROMPTS = {}


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


def _prepare_image(image_bytes, max_side=2048):
    with Image.open(BytesIO(image_bytes)) as source:
        image = source.convert("RGB")
    image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    encoded = base64.b64encode(output.getvalue()).decode("ascii")
    return image.size, f"data:image/png;base64,{encoded}"


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


def _execute_sam_call(client, model, concept, prompt_text, data_url, size, image_size, deadline):
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
            original_size = tuple(map(int, image_size))
            if size != original_size:
                masks = [
                    cv2.resize(mask, original_size, interpolation=cv2.INTER_NEAREST)
                    for mask in masks
                ]
            return masks
        except SamEmptyOutcome:
            # Succeeded with 200 OK but 0 masks
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
    """Run one SAM prompt and return masks at the uploaded image's original size."""
    if concept not in CONCEPT_PROMPTS:
        raise ValueError(f"Unknown segmentation concept: {concept}")
    if not is_sam_configured():
        raise RuntimeError("Meta API key is not configured.")

    model = os.getenv("SAM_MODEL", "sam-3.1").strip()
    if not model:
        raise ValueError("SAM_MODEL is empty.")
    prompt = CONCEPT_PROMPTS[concept]
    size, data_url = _prepare_image(image_bytes)
    deadline = time.monotonic() + timeout
    api_key = os.getenv("MODEL_API_KEY", "").strip() or os.getenv("META_API_KEY", "").strip()
    client = OpenAI(
        api_key=api_key,
        base_url=os.getenv("META_API_BASE_URL", os.getenv("MODEL_BASE_URL", "https://api.meta.ai/v1")).strip(),
        timeout=timeout,
        max_retries=0,
    )

    prompts = [prompt]
    if concept in CONCEPT_FALLBACK_PROMPTS:
        prompts.append(CONCEPT_FALLBACK_PROMPTS[concept])

    for current_prompt in prompts:
        try:
            masks = _execute_sam_call(client, model, concept, current_prompt, data_url, size, image_size, deadline)
            # Store concept used as attribute on the masks list
            try:
                masks.concept_used = current_prompt
            except Exception:
                pass
            return masks
        except SamEmptyOutcome as exc:
            if current_prompt != prompts[-1]:
                continue
            raise
        except ValueError as exc:
            if getattr(exc, "safe_category", None) == "no_matches" and current_prompt != prompts[-1]:
                continue
            raise
