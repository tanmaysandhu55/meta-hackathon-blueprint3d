"""
FloorPlan3D - Partner Cloud Endpoints Service
Implements external REST API integrations for Meta models without any local GPU libraries:

1. Meta SAM 3.1 (Image Segmentation):
   - Provider: Baseten API Endpoint
   - Auth: BASETEN_API_KEY (.env)
   - Route: Baseten sync inference endpoint

2. Meta Llama 3 (Text/NLP Generation):
   - Provider: Fireworks API Endpoint
   - Auth: FIREWORKS_API_KEY (.env)
   - Model: accounts/fireworks/models/llama-v3p1-70b-instruct

3. Meta Muse Spark (Region Labeling & Multimodal Classification):
   - Provider: Modal Serverless Endpoint
   - Auth: MODAL_API_KEY (.env)
   - Route: Modal serverless web endpoint
"""

import os
import json
import base64
import urllib.request
import urllib.error
import cv2
import numpy as np
from dotenv import load_dotenv
from openai import OpenAI

# Load configuration from .env
load_dotenv()


# =====================================================================
# 1. Baseten API Endpoint: Meta SAM 3.1 (Image Segmentation)
# =====================================================================

def get_baseten_config():
    """
    Reads Baseten credentials from .env.
    """
    api_key = os.environ.get("BASETEN_API_KEY", "").strip()
    model_id = os.environ.get("BASETEN_MODEL_ID", "").strip()
    
    # Standard Baseten model inference URL
    default_url = f"https://model-{model_id}.api.baseten.co/environments/production/sync/v1" if model_id else ""
    endpoint_url = os.environ.get("BASETEN_SAM_URL", default_url).strip()
    
    return {
        "api_key": api_key,
        "endpoint_url": endpoint_url,
        "is_configured": bool(api_key and endpoint_url)
    }


def query_baseten_sam(b64_data_url, concept, image_size):
    """
    Sends the floor plan image and a concept noun phrase (e.g. 'room', 'wall', 'door', 'window')
    to Baseten's standard inference URL for SAM 3.1.
    
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
            "Api-Key": config["api_key"]
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
    if not api_key:
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
    Reads Modal serverless endpoint configuration from .env.
    """
    api_key = os.environ.get("MODAL_API_KEY", "").strip()
    endpoint_url = os.environ.get("MODAL_MUSE_SPARK_URL", "").strip()
    return {
        "api_key": api_key,
        "endpoint_url": endpoint_url,
        "is_configured": bool(endpoint_url)
    }


def label_rooms_with_modal_muse_spark(b64_data_url, room_candidates):
    """
    Calls the Modal serverless endpoint for Meta Muse Spark to classify and label room regions.
    Fallback: Uses Fireworks Meta Llama 3 if Modal endpoint is not deployed.
    
    Allowed room types:
      room, classroom, lab, corridor, stairs, elevator, restroom, entrance, other
    """
    if not room_candidates:
        return {}

    allowed_types = {
        "room", "classroom", "lab", "corridor", "stairs", 
        "elevator", "restroom", "entrance", "other"
    }

    modal_cfg = get_modal_config()

    # If Modal endpoint is configured, send HTTP POST to the serverless function
    if modal_cfg["is_configured"]:
        payload = {
            "image": b64_data_url,
            "room_candidates": [
                {
                    "id": r["id"],
                    "centroid": r.get("centroid", [0, 0]),
                    "area_m2": r.get("area_m2", 0.0),
                    "bounds": r.get("bounds", [])
                }
                for r in room_candidates
            ],
            "allowed_types": list(allowed_types)
        }

        req_data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if modal_cfg["api_key"]:
            headers["Authorization"] = f"Bearer {modal_cfg['api_key']}"
            headers["X-Modal-Key"] = modal_cfg["api_key"]

        req = urllib.request.Request(
            modal_cfg["endpoint_url"],
            data=req_data,
            headers=headers,
            method="POST"
        )

        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                labeled_rooms = {}
                for item in data.get("rooms", []):
                    rid = item.get("id")
                    rtype = item.get("type", "room").lower().strip()
                    if rtype not in allowed_types:
                        rtype = "room"
                    labeled_rooms[rid] = {
                        "type": rtype,
                        "label": item.get("label", f"Room {rid}"),
                        "confidence": round(float(item.get("confidence", 0.9)), 2)
                    }
                return labeled_rooms
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
            labeled_rooms = {}
            for item in data.get("rooms", []):
                rid = item.get("id")
                rtype = item.get("type", "room").lower().strip()
                if rtype not in allowed_types:
                    rtype = "room"
                labeled_rooms[rid] = {
                    "type": rtype,
                    "label": item.get("label", f"Room {rid}"),
                    "confidence": round(float(item.get("confidence", 0.9)), 2)
                }
            return labeled_rooms
        except Exception as fw_err:
            print(f"Warning: Fireworks Llama 3 classification error: {fw_err}")

    # Sensible geometric fallback if no external endpoint returned
    fallbacks = {}
    for r in room_candidates:
        rid = r["id"]
        area = r.get("area_m2", 0)
        if area > 45:
            fallbacks[rid] = {"type": "corridor", "label": f"Corridor {rid}", "confidence": 0.88}
        elif area < 12:
            fallbacks[rid] = {"type": "restroom", "label": f"Restroom {rid}", "confidence": 0.85}
        else:
            fallbacks[rid] = {"type": "classroom", "label": f"Room {rid}", "confidence": 0.90}
    return fallbacks
