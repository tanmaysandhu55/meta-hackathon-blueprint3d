"""
FloorPlan3D - Partner Cloud Endpoints Service
Implements external REST API integrations for Meta models without any local GPU libraries:

1. Meta SAM 3.1 (Image Segmentation):
   - Provider: Baseten API Endpoint
   - Auth: BASETEN_API_KEY (.env)
   - Route: standard production prediction endpoint (/production/predict)

2. Meta Llama 3 (Text/NLP Generation):
   - Provider: Fireworks API Endpoint
   - Auth: FIREWORKS_API_KEY (.env)
   - Model: accounts/fireworks/models/llama-v3p1-70b-instruct

3. Meta Muse Spark (Region Labeling & Multimodal Classification):
   - Provider: Modal Serverless Endpoint
   - Auth: MODAL_API_KEY (.env)
   - Route: Modal OpenAI-compatible chat completions endpoint
"""

import os
import json
import urllib.request
import urllib.error
import cv2
import numpy as np
from dotenv import load_dotenv
from openai import OpenAI

# Load configuration from .env
load_dotenv()


def is_configured_value(value):
    """Treat documentation placeholders as missing configuration."""
    normalized = (value or "").strip()
    return bool(normalized and "<" not in normalized and "your_" not in normalized.lower() and "your-" not in normalized.lower())


# =====================================================================
# 1. Baseten API Endpoint: Meta SAM 3.1 (Image Segmentation)
# =====================================================================

def get_baseten_config():
    """
    Reads Baseten credentials from .env.
    """
    api_key = os.environ.get("BASETEN_API_KEY", "").strip()
    model_id = os.environ.get("BASETEN_MODEL_ID", "").strip()
    
    # Baseten's standard custom-model synchronous prediction URL.
    default_url = f"https://model-{model_id}.api.baseten.co/production/predict" if model_id else ""
    # An explicitly present but blank .env value should still fall back to the
    # standard production URL derived from BASETEN_MODEL_ID.
    endpoint_url = os.environ.get("BASETEN_SAM_URL", "").strip() or default_url
    
    return {
        "api_key": api_key,
        "endpoint_url": endpoint_url,
        "is_configured": is_configured_value(api_key) and is_configured_value(endpoint_url)
    }


def query_baseten_sam(b64_data_url, concept, image_size):
    """
    Sends the floor plan image and a concept noun phrase (e.g. 'room', 'wall', 'door', 'window')
    to the configured Baseten production prediction URL for SAM 3.1.
    
    Returns:
      List of 2D binary numpy arrays (uint8, values 0 or 255) for each detected instance.
    """
    config = get_baseten_config()
    if not config["is_configured"]:
        raise ValueError(
            "Baseten SAM 3.1 is not fully configured. Please set BASETEN_API_KEY and "
            "BASETEN_SAM_URL (or BASETEN_MODEL_ID) in your .env file."
        )

    img_w, img_h = image_size

    # Baseten inference payload
    payload = {
        "image": b64_data_url,
        "prompt": concept,
        "parameters": {
            "multimask_output": True,
            "concept": concept
        }
    }

    req_data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        config["endpoint_url"],
        data=req_data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Api-Key {config['api_key']}",
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            res_body = response.read().decode("utf-8")
            data = json.loads(res_body)
    except urllib.error.HTTPError as http_err:
        err_msg = http_err.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Baseten SAM API error (HTTP {http_err.code}): {err_msg}")
    except Exception as e:
        raise RuntimeError(f"Failed to query Baseten SAM 3.1: {str(e)}")

    # Parse masks from Baseten response
    masks_list = []

    # Format 1: Direct list of masks (2D arrays or binary grids)
    raw_masks = data.get("masks", []) or data.get("predictions", []) or data.get("output", [])
    if isinstance(raw_masks, list):
        for item in raw_masks:
            try:
                if isinstance(item, list):
                    # 2D array of 0s and 1s
                    arr = np.array(item, dtype=np.uint8)
                    if arr.ndim == 2:
                        if arr.shape != (img_h, img_w):
                            arr = cv2.resize(arr, (img_w, img_h), interpolation=cv2.INTER_NEAREST)
                        masks_list.append((arr > 0).astype(np.uint8) * 255)
                elif isinstance(item, dict):
                    # Polygon coordinates or bounding box
                    if "polygon" in item:
                        pts = np.array(item["polygon"], dtype=np.int32)
                        canvas = np.zeros((img_h, img_w), dtype=np.uint8)
                        cv2.fillPoly(canvas, [pts], 255)
                        masks_list.append(canvas)
                    elif "box" in item:
                        b = item["box"] # [x1, y1, x2, y2]
                        canvas = np.zeros((img_h, img_w), dtype=np.uint8)
                        cv2.rectangle(canvas, (int(b[0]), int(b[1])), (int(b[2]), int(b[3])), 255, -1)
                        masks_list.append(canvas)
            except Exception as parse_err:
                print(f"Warning: Could not parse mask from Baseten: {parse_err}")

    return masks_list


# =====================================================================
# 2. Fireworks API Endpoint: Meta Llama 3 (Text/NLP Generation)
# =====================================================================

def get_fireworks_client():
    """
    Initializes an OpenAI-compatible client for Fireworks API.
    Reads FIREWORKS_API_KEY from .env.
    """
    api_key = os.environ.get("FIREWORKS_API_KEY", "").strip()
    if not is_configured_value(api_key):
        return None

    base_url = os.environ.get("FIREWORKS_BASE_URL", "https://api.fireworks.ai/inference/v1").strip()
    return OpenAI(base_url=base_url, api_key=api_key)


def generate_with_fireworks_llama(prompt, system_prompt=None, response_format=None):
    """
    Generates text or structured JSON using Meta Llama 3 via Fireworks API.
    Default model: accounts/fireworks/models/llama-v3p1-70b-instruct
    """
    client = get_fireworks_client()
    if not client:
        raise ValueError(
            "FIREWORKS_API_KEY is not set in .env. Please configure your Fireworks key for Meta Llama 3."
        )

    model_name = os.environ.get(
        "FIREWORKS_LLAMA_MODEL",
        "accounts/fireworks/models/llama-v3p1-70b-instruct"
    ).strip()

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    kwargs = {
        "model": model_name,
        "messages": messages,
        "temperature": 0.2
    }
    if response_format:
        kwargs["response_format"] = response_format

    response = client.chat.completions.create(**kwargs)
    return response.choices[0].message.content


# =====================================================================
# 3. Modal Serverless Endpoint: Meta Muse Spark
# =====================================================================

def get_modal_config():
    """
    Reads the Modal OpenAI-compatible endpoint configuration from .env.
    """
    api_key = os.environ.get("MODAL_API_KEY", "").strip()
    endpoint_url = os.environ.get("MODAL_MUSE_SPARK_URL", "").strip()
    model_name = os.environ.get("MODAL_MUSE_SPARK_MODEL", "").strip()
    token_parts = api_key.split(".", 1)
    has_proxy_token = (
        len(token_parts) == 2
        and token_parts[0].startswith("wk-")
        and token_parts[1].startswith("ws-")
    )
    return {
        "api_key": api_key,
        "endpoint_url": endpoint_url,
        "model_name": model_name,
        "is_configured": is_configured_value(endpoint_url) and is_configured_value(model_name) and has_proxy_token,
    }


def label_rooms_with_modal_muse_spark(b64_data_url, room_candidates):
    """
    Calls the configured Modal classifier, then Fireworks if Modal is unavailable.
    Returns only validated model results; the pipeline owns the explicit generic fallback.
    
    Allowed room types:
      room, classroom, lab, corridor, stairs, elevator, restroom, entrance, other
    """
    if not room_candidates:
        return {}

    allowed_types = {
        "room", "classroom", "lab", "corridor", "stairs", 
        "elevator", "restroom", "entrance", "other"
    }

    expected_ids = {room["id"] for room in room_candidates}

    def validated_labels(raw_rooms):
        labels = {}
        for item in raw_rooms if isinstance(raw_rooms, list) else []:
            if not isinstance(item, dict):
                continue
            rid = item.get("id")
            if rid not in expected_ids:
                continue
            rtype = str(item.get("type", "room")).lower().strip()
            if rtype not in allowed_types:
                rtype = "room"
            label = item.get("label")
            if not isinstance(label, str) or not label.strip():
                label = f"Room {rid[1:]}"
            try:
                confidence = float(item.get("confidence", 0.0))
            except (TypeError, ValueError):
                confidence = 0.0
            if not np.isfinite(confidence):
                confidence = 0.0
            labels[rid] = {
                "type": rtype,
                "label": label.strip()[:100],
                "confidence": round(min(1.0, max(0.0, confidence)), 2),
            }
        return labels

    modal_cfg = get_modal_config()

    # Modal Shared/Dedicated Endpoints expose OpenAI-compatible chat completions.
    if modal_cfg["is_configured"]:
        try:
            base_url = modal_cfg["endpoint_url"].rstrip("/")
            for suffix in ("/v1/chat/completions", "/chat/completions"):
                if base_url.endswith(suffix):
                    base_url = base_url[:-len(suffix)]
                    break
            if not base_url.endswith("/v1"):
                base_url += "/v1"
            client = OpenAI(base_url=base_url, api_key=modal_cfg["api_key"], timeout=60)
            candidate_json = json.dumps([
                {
                    "id": room["id"],
                    "centroid": room.get("centroid", [0, 0]),
                    "area_m2": room.get("area_m2", 0.0),
                    "bounds": room.get("bounds", []),
                }
                for room in room_candidates
            ], indent=2)
            prompt = (
                "Inspect this floor-plan image and classify only the listed room candidates. "
                f"Allowed types: {json.dumps(sorted(allowed_types))}. "
                "Return one JSON object with a rooms array. Each item must contain id, type, label, "
                "and confidence from 0 to 1. Do not add or omit candidate IDs.\n"
                f"Candidates:\n{candidate_json}\n"
                'Required shape: {"rooms":[{"id":"r1","type":"classroom","label":"Classroom 101","confidence":0.95}]}'
            )
            response = client.chat.completions.create(
                model=modal_cfg["model_name"],
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": b64_data_url}},
                    ],
                }],
                temperature=0.1,
                max_tokens=1200,
            )
            raw_text = response.choices[0].message.content or ""
            try:
                data = json.loads(raw_text)
            except json.JSONDecodeError:
                start, end = raw_text.find("{"), raw_text.rfind("}")
                if start < 0 or end <= start:
                    raise ValueError("Modal Muse Spark returned no JSON object.")
                data = json.loads(raw_text[start:end + 1])
            return validated_labels(data.get("rooms", []))
        except Exception as modal_err:
            print(f"Warning: Modal endpoint returned error ({modal_err}). Falling back to Fireworks Llama 3.")

    # Fireworks Meta Llama 3 NLP fallback for room labeling
    fw_client = get_fireworks_client()
    if fw_client:
        prompt_text = (
            "You are an architectural floor plan classifier. Analyze these room regions detected by SAM:\n"
            f"{json.dumps(room_candidates, indent=2)}\n\n"
            "Classify each room ID into exactly one of these types: "
            "['room', 'classroom', 'lab', 'corridor', 'stairs', 'elevator', 'restroom', 'entrance', 'other'].\n"
            "Provide an architectural label (e.g. 'Classroom 101', 'Computer Lab', 'Main Corridor', 'Restroom') "
            "and a confidence score between 0.5 and 1.0.\n"
            "Return valid JSON matching this schema:\n"
            '{"rooms": [{"id": "r1", "type": "classroom", "label": "Classroom 101", "confidence": 0.95}]}'
        )
        try:
            raw_json = generate_with_fireworks_llama(
                prompt=prompt_text,
                system_prompt="You are a professional architectural AI assistant. Respond strictly in JSON.",
                response_format={"type": "json_object"}
            )
            data = json.loads(raw_json)
            return validated_labels(data.get("rooms", []))
        except Exception as fw_err:
            print(f"Warning: Fireworks Llama 3 classification error: {fw_err}")

    # The caller adds explicit generic labels and a scene warning. Do not infer
    # room types from area alone: that would make a fallback look like a model result.
    return {}
