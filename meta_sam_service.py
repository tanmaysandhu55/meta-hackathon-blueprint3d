"""Meta Model API integration for Segment Anything Model 3.1."""

import base64
import logging
import os
import time
import threading
from io import BytesIO
from pathlib import Path

import cv2
import numpy as np
from openai import APIConnectionError, APITimeoutError, OpenAI
from PIL import Image

logger = logging.getLogger(__name__)
_TRACE_LOCK = threading.Lock()

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

CONCEPT_FALLBACK_PROMPTS = {
    "door": ("door swing arc", "doorway"),
    "window": ("window symbol",),
    "wall": ("black wall line",),
    "room": ("enclosed room",),
}


def is_sam_configured():
    api_key = os.getenv("MODEL_API_KEY", "").strip() or os.getenv("META_API_KEY", "").strip()
    return bool(
        api_key
        and os.getenv("SAM_MODEL", "sam-3.1").strip()
    )


def _prepare_image(image_bytes, max_side=1280, return_transform=False):
    """Prepare architectural line art and retain an exact inverse pixel map.

    SAM sees a denoised, lightly thickened, high-contrast plan with a 5% white
    margin. Its returned bounds are relative to this padded raster, so callers
    must use the returned transform to put masks back on the uploaded image.
    """
    with Image.open(BytesIO(image_bytes)) as source:
        rgb = np.asarray(source.convert("RGB"))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    gray = cv2.medianBlur(gray, 3)
    # Adaptive threshold keeps thin dark drafting strokes while removing paper
    # texture and scan noise. A single 2x2 dilation restores slightly faded ink.
    ink = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 8
    )
    ink = cv2.dilate(ink, cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2)), iterations=1)
    prepared = cv2.cvtColor(cv2.bitwise_not(ink), cv2.COLOR_GRAY2RGB)
    original_height, original_width = gray.shape
    scale = min(1.0, float(max_side) / max(original_width, original_height))
    resized_width = max(1, int(round(original_width * scale)))
    resized_height = max(1, int(round(original_height * scale)))
    if (resized_width, resized_height) != (original_width, original_height):
        prepared = cv2.resize(prepared, (resized_width, resized_height), interpolation=cv2.INTER_AREA)
    pad_x = max(1, int(round(resized_width * 0.05)))
    pad_y = max(1, int(round(resized_height * 0.05)))
    padded = cv2.copyMakeBorder(
        prepared, pad_y, pad_y, pad_x, pad_x,
        borderType=cv2.BORDER_CONSTANT, value=(255, 255, 255),
    )
    image = Image.fromarray(padded, mode="RGB")
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    encoded = base64.b64encode(output.getvalue()).decode("ascii")
    result = (image.size, f"data:image/png;base64,{encoded}")
    if return_transform:
        transform = {
            "original_size": (original_width, original_height),
            "resized_size": (resized_width, resized_height),
            "padding": (pad_x, pad_y),
        }
        return (*result, transform)
    return result


def _restore_prepared_mask(mask, transform):
    """Remove SAM's prep border and resize its mask to uploaded-image pixels."""
    original_width, original_height = transform["original_size"]
    resized_width, resized_height = transform["resized_size"]
    pad_x, pad_y = transform["padding"]
    unpadded = np.asarray(mask, dtype=np.uint8)[pad_y:pad_y + resized_height, pad_x:pad_x + resized_width]
    if unpadded.size == 0:
        return np.zeros((original_height, original_width), dtype=np.uint8)
    if unpadded.shape != (original_height, original_width):
        unpadded = cv2.resize(unpadded, (original_width, original_height), interpolation=cv2.INTER_NEAREST)
    return np.ascontiguousarray((unpadded > 0).astype(np.uint8) * 255)


def _safe_category(exc):
    if isinstance(exc, ValueError) and "detected no matching regions" in str(exc).lower():
        return "no_matches"
    status = getattr(exc, "status_code", None)
    if status in (401, 403):
        return "auth"
    if isinstance(exc, (APITimeoutError, TimeoutError)):
        return "timeout"
    if status in (400, 404, 422) or isinstance(exc, ValueError):
        return "bad_response"
    return "unavailable"


def _write_sam_trace(prompt, status, error_type, raw_text):
    """Write a short response diagnostic without request headers or secrets."""
    try:
        trace_path = Path(__file__).resolve().parent / "out" / "debug" / "sam_raw.txt"
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        excerpt = str(raw_text or "")[:500].replace("\r", " ").replace("\n", " ")
        record = (
            f"prompt={prompt!r} status={status} error_type={error_type or 'none'}\n"
            f"raw_first_500={excerpt}\n---\n"
        )
        with _TRACE_LOCK, trace_path.open("a", encoding="utf-8") as trace_file:
            trace_file.write(record)
    except OSError:
        logger.debug("Could not write local SAM diagnostic trace.")


def _decode_masks(output_text, expected_size):
    """Decode box-local SAM rasters into full-frame 0/255 masks.

    SAM's mask raster is local to its source-image bounding box. Resizing each
    raster to the full frame (the old behavior) moved every detected object to
    the whole-plan scale and made otherwise valid results unusable.
    """
    from meta_sam_parser import CompletedOutcome, decode_mask_to_raster, image_segmentation_format

    output_width, output_height = map(int, expected_size)
    if output_width <= 0 or output_height <= 0:
        raise ValueError("SAM expected image dimensions are invalid.")
    if not str(output_text or "").strip():
        return []

    parser = image_segmentation_format().create_parser()
    parser.push(output_text)
    result = parser.finish(CompletedOutcome()).result
    if result.outcome.status != "completed":
        raise ValueError("SAM returned an incomplete segmentation response.")
    if any(getattr(item.severity, "value", item.severity) == "error" for item in result.diagnostics):
        raise ValueError("SAM returned a malformed mask payload.")

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
        local_mask = raster.reshape((height, width)) * 255
        bounds = getattr(record, "bounds", None)
        if bounds is None:
            if (width, height) != (output_width, output_height):
                raise ValueError("SAM returned a cropped mask without source-image bounds.")
            left, top, right, bottom = 0, 0, output_width, output_height
        else:
            left = int(np.floor(float(bounds.left)))
            top = int(np.floor(float(bounds.top)))
            right = int(np.ceil(float(bounds.right)))
            bottom = int(np.ceil(float(bounds.bottom)))
        if right <= left or bottom <= top:
            raise ValueError("SAM returned invalid mask bounds.")
        clipped_left, clipped_top = max(0, left), max(0, top)
        clipped_right, clipped_bottom = min(output_width, right), min(output_height, bottom)
        if clipped_right <= clipped_left or clipped_bottom <= clipped_top:
            continue
        target_width, target_height = right - left, bottom - top
        if target_width <= 0 or target_height <= 0 or target_width * target_height > 20_000_000:
            raise ValueError("SAM returned mask bounds that are too large.")
        local_mask = cv2.resize(local_mask, (target_width, target_height), interpolation=cv2.INTER_NEAREST)
        source_left, source_top = clipped_left - left, clipped_top - top
        source_right, source_bottom = source_left + (clipped_right - clipped_left), source_top + (clipped_bottom - clipped_top)
        full_frame = np.zeros((output_height, output_width), dtype=np.uint8)
        full_frame[clipped_top:clipped_bottom, clipped_left:clipped_right] = local_mask[source_top:source_bottom, source_left:source_right]
        if np.any(full_frame):
            masks.append(np.ascontiguousarray(full_frame, dtype=np.uint8))
    return masks


def _execute_sam_call(client, model, prompt_text, data_url, size, image_size, deadline):
    for attempt in range(3):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("SAM request exceeded its processing time budget.")
        try:
            output_text = ""
            stream_fn = getattr(client.responses, "stream", None)
            if callable(stream_fn):
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
                _write_sam_trace(prompt_text, "completed", "", output_text)
            else:
                response = client.with_options(timeout=remaining).responses.create(
                    model=model,
                    input=[{"type": "message", "role": "user", "content": [
                        {"type": "input_text", "text": prompt_text},
                        {"type": "input_image", "image_url": data_url},
                    ]}],
                    metadata={"mask_encoding": "one_bit", "include_confidence": "true"},
                )
                output_text = getattr(response, "output_text", "") or ""
                _write_sam_trace(prompt_text, getattr(response, "status", "completed"), "", output_text)
            masks = _decode_masks(output_text, size)
            if not masks:
                raise ValueError(f"SAM 3.1 detected no matching regions for '{prompt_text}'.")
            original_size = tuple(map(int, image_size))
            if size != original_size:
                masks = [
                    cv2.resize(mask, original_size, interpolation=cv2.INTER_NEAREST)
                    for mask in masks
                ]
            return masks
        except Exception as exc:
            category = _safe_category(exc)
            _write_sam_trace(prompt_text, getattr(exc, "status_code", "unknown"), type(exc).__name__, "")
            if category == "no_matches":
                exc.safe_category = "no_matches"
                raise
            retryable = isinstance(exc, (APIConnectionError, APITimeoutError)) or (
                getattr(exc, "status_code", 0) or 0
            ) >= 500
            logger.warning("SAM segmentation failed (category=%s, prompt=%s)", category, prompt_text)
            delay = 0.4 * (2 ** attempt)
            if not retryable or attempt == 2 or time.monotonic() + delay >= deadline:
                exc.safe_category = category
                raise
            time.sleep(delay)

    raise TimeoutError("SAM request exceeded its processing time budget.")


def query_sam_concept(image_bytes, concept, image_size, timeout=75, return_status=False):
    """Meta SAM 3.1 integration point: return concept masks in source-image pixels."""
    if concept not in CONCEPT_PROMPTS:
        raise ValueError(f"Unknown segmentation concept: {concept}")
    if not is_sam_configured():
        raise RuntimeError("Meta API key is not configured.")

    model = os.getenv("SAM_MODEL", "sam-3.1").strip()
    if not model:
        raise ValueError("SAM_MODEL is empty.")
    prompt = CONCEPT_PROMPTS[concept]
    size, data_url, transform = _prepare_image(image_bytes, return_transform=True)
    deadline = time.monotonic() + timeout
    api_key = os.getenv("MODEL_API_KEY", "").strip() or os.getenv("META_API_KEY", "").strip()
    client = OpenAI(
        api_key=api_key,
        base_url=os.getenv("META_API_BASE_URL", os.getenv("MODEL_BASE_URL", "https://api.meta.ai/v1")).strip(),
        timeout=timeout,
        max_retries=0,
    )

    prompts = [prompt, *CONCEPT_FALLBACK_PROMPTS.get(concept, ())]

    for current_prompt in prompts:
        try:
            masks = _execute_sam_call(client, model, current_prompt, data_url, size, size, deadline)
            masks = [_restore_prepared_mask(mask, transform) for mask in masks]
            if return_status:
                return masks, {"status": "OK", "prompt": current_prompt, "category": None}
            return masks
        except ValueError as exc:
            if getattr(exc, "safe_category", None) == "no_matches" and current_prompt != prompts[-1]:
                continue
            raise
