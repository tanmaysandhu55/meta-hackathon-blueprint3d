"""
FloorPlan3D - SAM 3.1 & Model Gateway
Routes inference requests through partner cloud endpoints:
1. SAM 3.1 Image Segmentation -> Baseten API Endpoint (BASETEN_API_KEY)
2. Meta Llama 3 Text/NLP Generation -> Fireworks API Endpoint (FIREWORKS_API_KEY)
3. Meta Muse Spark -> Modal Serverless Endpoint (MODAL_API_KEY)
"""

import os
import json
import base64
import cv2
import numpy as np
from PIL import Image
import io
from dotenv import load_dotenv

# Import partner cloud endpoint handlers
from cloud_services import (
    get_baseten_config,
    query_baseten_sam,
    get_fireworks_client,
    generate_with_fireworks_llama,
    get_modal_config,
    label_rooms_with_modal_muse_spark
)

load_dotenv()


def query_sam_concept(b64_data_url, concept, image_size):
    """
    Queries SAM 3.1 for an architectural concept ('room', 'wall', 'door', 'window').
    Prioritizes the Baseten API endpoint as instructed.
    """
    baseten_cfg = get_baseten_config()
    
    if baseten_cfg["is_configured"]:
        return query_baseten_sam(b64_data_url, concept, image_size)
    
    # Fallback to direct Meta API if MODEL_API_KEY is configured
    meta_api_key = os.environ.get("MODEL_API_KEY", "").strip()
    if meta_api_key:
        from openai import OpenAI
        try:
            from meta_sam_parser import (
                image_segmentation_format,
                decode_mask_to_raster,
                CompletedOutcome,
                SegmentationMaskRecord
            )
            client = OpenAI(
                base_url=os.environ.get("MODEL_BASE_URL", "https://api.meta.ai/v1"),
                api_key=meta_api_key
            )
            accumulated_text = ""
            with client.responses.stream(
                model=os.environ.get("SAM_MODEL", "sam-3.1"),
                input=[{
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": concept},
                        {"type": "input_image", "image_url": b64_data_url}
                    ]
                }]
            ) as stream:
                for event in stream:
                    if hasattr(event, "type") and event.type == "response.output_text.delta":
                        accumulated_text += event.delta
                    elif hasattr(event, "delta") and isinstance(event.delta, str):
                        accumulated_text += event.delta

            if not accumulated_text.strip():
                return []

            parser = image_segmentation_format().create_parser()
            parser.push(accumulated_text)
            finish = parser.finish(CompletedOutcome())
            
            img_w, img_h = image_size
            masks = []
            for record in finish.result.records:
                if isinstance(record, SegmentationMaskRecord):
                    raster_bytes = decode_mask_to_raster(record.mask)
                    mh, mw = record.mask.height, record.mask.width
                    lmask = np.frombuffer(raster_bytes, dtype=np.uint8).reshape((mh, mw)) * 255
                    canvas = np.zeros((img_h, img_w), dtype=np.uint8)
                    if hasattr(record, "bounds") and record.bounds:
                        b = record.bounds
                        x1 = max(0, min(img_w, int(round(b.left))))
                        y1 = max(0, min(img_h, int(round(b.top))))
                        x2 = max(0, min(img_w, int(round(b.right))))
                        y2 = max(0, min(img_h, int(round(b.bottom))))
                        bw, bh = x2 - x1, y2 - y1
                        if bw > 0 and bh > 0:
                            if (bh, bw) != lmask.shape:
                                lmask = cv2.resize(lmask, (bw, bh), interpolation=cv2.INTER_NEAREST)
                            canvas[y1:y2, x1:x2] = lmask
                    else:
                        canvas = cv2.resize(lmask, (img_w, img_h), interpolation=cv2.INTER_NEAREST)
                    masks.append(canvas)
            return masks
        except Exception as e:
            print(f"Warning: Direct Meta API query failed: {e}")

    raise ValueError(
        "No SAM 3.1 endpoint configured. Please set BASETEN_API_KEY and BASETEN_SAM_URL in .env."
    )


def label_rooms(b64_data_url, room_candidates):
    """
    Labels each detected room candidate.
    Uses Modal serverless endpoint for Muse Spark,
    and Fireworks API for Meta Llama 3.
    """
    return label_rooms_with_modal_muse_spark(b64_data_url, room_candidates)
