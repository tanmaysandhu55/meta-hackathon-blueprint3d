"""
FloorPlan3D - Meta SAM 3.1 & Muse Spark API Service
Handles communication with Meta Model API (https://api.meta.ai/v1) using the OpenAI SDK.
Includes SAM 3.1 segmentation via Responses API, meta-sam-parser mask decoding,
and Muse Spark structured room classification.
"""

import os
import json
import base64
import cv2
import numpy as np
from PIL import Image
import io
from dotenv import load_dotenv
from openai import OpenAI

# Load environment variables from .env
load_dotenv()

# Meta's official SAM 3.1 parser
try:
    from meta_sam_parser import (
        image_segmentation_format,
        decode_mask_to_raster,
        CompletedOutcome,
        SegmentationMaskRecord,
        SegmentationBoxRecord
    )
    HAS_META_SAM_PARSER = True
except ImportError:
    HAS_META_SAM_PARSER = False


def get_meta_client():
    """
    Initializes and returns an OpenAI client configured for the Meta Model API.
    Reads MODEL_API_KEY from the environment (loaded via python-dotenv).
    Never hardcodes the API key.
    """
    api_key = os.environ.get("MODEL_API_KEY", "").strip()
    if not api_key:
        raise ValueError(
            "MODEL_API_KEY is not set. Please add your Meta Model API key to the .env file. "
            "Get your key at https://dev.meta.ai/."
        )

    base_url = os.environ.get("MODEL_BASE_URL", "https://api.meta.ai/v1").strip()
    return OpenAI(base_url=base_url, api_key=api_key)


def image_to_base64_data_url(image_bytes):
    """
    Converts raw image bytes to a data URL string suitable for Meta Model API.
    """
    b64_str = base64.b64encode(image_bytes).decode("utf-8")
    return f"data:image/png;base64,{b64_str}"


def query_sam_concept(client, concept_noun_phrase, b64_data_url, image_size):
    """
    Queries Meta SAM 3.1 for a single architectural concept.
    
    META API RULES:
    - SAM 3.1 = model 'sam-3.1' via the Responses API.
    - Input: ONE short noun phrase (e.g. 'room', 'wall', 'door', 'window') plus an image.
    - Lists ('door, window') and commands ('segment doors') do NOT work.
    - Zero matches is a normal result, not an error.
    - Stream responses and collect text tokens.
    - Output text format: <0f>0<|box;...|><|mask;...|>
    
    Returns:
      List of full-canvas 2D numpy arrays (uint8, values 0 or 255) for each detected instance.
    """
    sam_model = os.environ.get("SAM_MODEL", "sam-3.1").strip()
    img_w, img_h = image_size
    accumulated_text = ""

    # Streaming call via OpenAI SDK Responses API
    with client.responses.stream(
        model=sam_model,
        input=[{
            "type": "message",
            "role": "user",
            "content": [
                {"type": "input_text", "text": concept_noun_phrase},
                {"type": "input_image", "image_url": b64_data_url}
            ]
        }]
    ) as stream:
        for event in stream:
            if hasattr(event, "type") and event.type == "response.output_text.delta":
                accumulated_text += event.delta
            elif hasattr(event, "delta") and isinstance(event.delta, str):
                accumulated_text += event.delta

    # If SAM returned no tokens or no matches, return empty list (normal result)
    if not accumulated_text.strip():
        return []

    # Decode masks using Meta's official meta-sam-parser package
    masks_list = []
    if HAS_META_SAM_PARSER:
        parser = image_segmentation_format().create_parser()
        parser.push(accumulated_text)
        finish = parser.finish(CompletedOutcome())
        
        for record in finish.result.records:
            if isinstance(record, SegmentationMaskRecord):
                try:
                    # Decode compressed payload into row-major binary bytes
                    raster_bytes = decode_mask_to_raster(record.mask)
                    mask_h = record.mask.height
                    mask_w = record.mask.width
                    
                    # Convert to 2D numpy array (values 0 and 255)
                    local_mask = np.frombuffer(raster_bytes, dtype=np.uint8).reshape((mask_h, mask_w)) * 255

                    # Place onto full image canvas using bounds coordinates
                    full_canvas_mask = np.zeros((img_h, img_w), dtype=np.uint8)
                    
                    if hasattr(record, "bounds") and record.bounds:
                        b = record.bounds
                        x1 = max(0, min(img_w, int(round(b.left))))
                        y1 = max(0, min(img_h, int(round(b.top))))
                        x2 = max(0, min(img_w, int(round(b.right))))
                        y2 = max(0, min(img_h, int(round(b.bottom))))
                        
                        # Resize or crop local mask if slight rounding mismatch
                        bw = x2 - x1
                        bh = y2 - y1
                        if bw > 0 and bh > 0:
                            if (bh, bw) != local_mask.shape:
                                local_resized = cv2.resize(local_mask, (bw, bh), interpolation=cv2.INTER_NEAREST)
                            else:
                                local_resized = local_mask
                            full_canvas_mask[y1:y2, x1:x2] = local_resized
                    else:
                        # Full image mask
                        if local_mask.shape == (img_h, img_w):
                            full_canvas_mask = local_mask
                        else:
                            full_canvas_mask = cv2.resize(local_mask, (img_w, img_h), interpolation=cv2.INTER_NEAREST)

                    masks_list.append(full_canvas_mask)
                except Exception as decode_err:
                    print(f"Warning: Failed to decode SAM mask record: {decode_err}")
    else:
        print("Warning: meta-sam-parser package not installed. Skipping mask decoding.")

    return masks_list


def label_rooms_with_muse_spark(client, b64_data_url, room_candidates):
    """
    Labels each detected room region using Meta Muse Spark.
    
    META API RULES:
    - Base URL: https://api.meta.ai/v1.
    - Model: Muse Spark standard tier (e.g. 'muse-spark-1.3'), NEVER '-contributor'.
    - Supports image input and JSON structured output.
    - Allowed room types:
      room, classroom, lab, corridor, stairs, elevator, restroom, entrance, other.
    
    Parameters:
      client: OpenAI client configured for Meta API
      b64_data_url: floor plan image data URL
      room_candidates: list of dicts with 'id', 'centroid', 'area_m2', 'polygon'
    
    Returns:
      Dict mapping room_id -> {"type": str, "label": str, "confidence": float}
    """
    muse_model = os.environ.get("MUSE_MODEL", "muse-spark-1.3").strip()
    
    # Do not call if no room candidates were found
    if not room_candidates:
        return {}

    # Format room candidate metadata for Muse Spark prompt
    candidates_desc = []
    for r in room_candidates:
        candidates_desc.append({
            "id": r["id"],
            "approx_center_meters": r.get("centroid", [0, 0]),
            "approx_area_sq_meters": r.get("area_m2", 0.0),
        })

    prompt_text = (
        "You are an architectural floor plan classifier. Analyze this 2D floor plan image.\n"
        "SAM 3.1 detected the following room regions at these coordinates:\n"
        f"{json.dumps(candidates_desc, indent=2)}\n\n"
        "TASK:\n"
        "1. Inspect the image for printed room numbers, names (e.g. 'Room 101', 'LAB', 'WC', 'STAIRS', 'OFFICE'), "
        "and architectural layout features (plumbing for restrooms, large open long spaces for corridors).\n"
        "2. Classify each room ID into EXACTLY ONE of the allowed room types:\n"
        "   ['room', 'classroom', 'lab', 'corridor', 'stairs', 'elevator', 'restroom', 'entrance', 'other']\n"
        "3. Provide a clear, natural architectural label (e.g. 'Room 101', 'Computer Lab', 'Main Corridor', 'Restroom').\n"
        "4. Assign a confidence score between 0.50 and 1.00.\n\n"
        "Return a strictly valid JSON object matching this schema:\n"
        "{\n"
        '  "rooms": [\n'
        '    {"id": "r1", "type": "classroom", "label": "Room 101", "confidence": 0.95},\n'
        '    {"id": "r2", "type": "lab", "label": "Science Lab", "confidence": 0.92}\n'
        "  ]\n"
        "}"
    )

    try:
        response = client.chat.completions.create(
            model=muse_model,
            messages=[
                {
                    "role": "system",
                    "content": "You are a professional architectural AI assistant. Always respond with pure valid JSON."
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt_text},
                        {"type": "image_url", "image_url": {"url": b64_data_url}}
                    ]
                }
            ],
            response_format={"type": "json_object"}
        )

        response_content = response.choices[0].message.content
        data = json.loads(response_content)
        labeled_rooms = {}

        allowed_types = {
            "room", "classroom", "lab", "corridor", "stairs", 
            "elevator", "restroom", "entrance", "other"
        }

        for item in data.get("rooms", []):
            rid = item.get("id")
            rtype = item.get("type", "room").lower().strip()
            if rtype not in allowed_types:
                rtype = "room"
            label = item.get("label", f"Room {rid}")
            conf = float(item.get("confidence", 0.9))
            labeled_rooms[rid] = {
                "type": rtype,
                "label": label,
                "confidence": round(min(1.0, max(0.1, conf)), 2)
            }

        return labeled_rooms
    except Exception as muse_err:
        print(f"Warning: Muse Spark labeling encountered an error: {muse_err}. Using sensible defaults.")
        # Provide fallback labels if Muse Spark has an issue
        fallbacks = {}
        for r in room_candidates:
            rid = r["id"]
            # Largest elongated room defaults to corridor, otherwise classroom/room
            area = r.get("area_m2", 0)
            if area > 40:
                fallbacks[rid] = {"type": "corridor", "label": f"Corridor {rid}", "confidence": 0.85}
            else:
                fallbacks[rid] = {"type": "room", "label": f"Room {rid}", "confidence": 0.88}
        return fallbacks
