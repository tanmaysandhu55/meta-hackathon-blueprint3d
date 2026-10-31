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
    "room": "rooms",
    "wall": "walls",
    "door": "doors",
    "window": "windows",
}


def is_sam_configured():
    api_key = os.getenv("META_API_KEY", "").strip() or os.getenv("MODEL_API_KEY", "").strip()
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
    api_key = os.getenv("META_API_KEY", "").strip() or os.getenv("MODEL_API_KEY", "").strip()
    client = OpenAI(
        api_key=api_key,
        base_url=os.getenv("META_API_BASE_URL", os.getenv("MODEL_BASE_URL", "https://api.meta.ai/v1")).strip(),
        timeout=timeout,
        max_retries=0,
    )

    for attempt in range(3):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("SAM request exceeded its processing time budget.")
        try:
            output_text = ""
            stream_fn = getattr(client.responses, "stream", None)
            if callable(stream_fn):
                try:
                    with client.with_options(timeout=remaining).responses.stream(
                        model=model,
                        input=[{"type": "message", "role": "user", "content": [
                            {"type": "input_text", "text": prompt},
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
                        {"type": "input_text", "text": prompt},
                        {"type": "input_image", "image_url": data_url},
                    ]}],
                    metadata={"mask_encoding": "one_bit", "include_confidence": "true"},
                )
                output_text = getattr(response, "output_text", "") or ""
            masks = _decode_masks(output_text, size)
            if not masks:
                raise ValueError("SAM returned no masks for this prompt.")
            original_size = tuple(map(int, image_size))
            if size != original_size:
                masks = [
                    cv2.resize(mask, original_size, interpolation=cv2.INTER_NEAREST)
                    for mask in masks
                ]
            return masks
        except Exception as exc:
            category = _safe_category(exc)
            retryable = isinstance(exc, (APIConnectionError, APITimeoutError)) or (
                getattr(exc, "status_code", 0) or 0
            ) >= 500
            logger.warning("SAM segmentation failed (category=%s, concept=%s)", category, concept)
            delay = 0.4 * (2 ** attempt)
            if not retryable or attempt == 2 or time.monotonic() + delay >= deadline:
                exc.safe_category = category
                raise
            time.sleep(delay)

    raise TimeoutError("SAM request exceeded its processing time budget.")
