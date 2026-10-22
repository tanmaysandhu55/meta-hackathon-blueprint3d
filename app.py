"""
FloorPlan3D - Flask Application
Serves the 3D Viewer frontend and provides REST API endpoints using partner cloud endpoints:
- Baseten API for SAM 3.1
- Fireworks API for Meta Llama 3
- Modal Serverless Endpoint for Meta Muse Spark
"""

import os
import io
import json
import base64
from flask import Flask, request, jsonify, render_template, send_from_directory, send_file
from flask_cors import CORS
from dotenv import load_dotenv
from PIL import Image

# Local FloorPlan3D modules
from sam_service import query_sam_concept, label_rooms
from cloud_services import get_baseten_config, get_fireworks_client, get_modal_config
from geometry_processor import mask_to_polygons_with_holes, extract_doors, extract_windows, build_walls_from_rooms
from demo_data import generate_sample_floorplan_image, get_sample_scene_json, get_sample_mask_overlays

# Load environment configuration from .env
load_dotenv()

app = Flask(__name__, template_folder="templates", static_folder="static")
CORS(app)

# Ensure sample image exists on startup
SAMPLE_IMG_PATH = os.path.join(app.root_path, "samples", "sample_floorplan.png")
if not os.path.exists(SAMPLE_IMG_PATH):
    generate_sample_floorplan_image(SAMPLE_IMG_PATH)


@app.route("/")
def index():
    """Serves the main FloorPlan3D user interface with endpoint indicators."""
    baseten_cfg = get_baseten_config()
    fireworks_client = get_fireworks_client()
    modal_cfg = get_modal_config()
    meta_key = bool(os.environ.get("MODEL_API_KEY", "").strip())

    any_api_ready = baseten_cfg["is_configured"] or bool(fireworks_client) or modal_cfg["is_configured"] or meta_key

    return render_template(
        "index.html",
        api_key_configured=any_api_ready,
        baseten_ready=baseten_cfg["is_configured"],
        fireworks_ready=bool(fireworks_client),
        modal_ready=modal_cfg["is_configured"],
        sam_model="Baseten SAM 3.1",
        muse_model="Modal Muse Spark / Fireworks Llama 3"
    )


@app.route("/api/health", methods=["GET"])
def health():
    """Returns endpoint connectivity status for all partner cloud endpoints."""
    baseten_cfg = get_baseten_config()
    fireworks_client = get_fireworks_client()
    modal_cfg = get_modal_config()

    return jsonify({
        "status": "online",
        "service": "FloorPlan3D",
        "partner_endpoints": {
            "baseten_sam": {
                "configured": baseten_cfg["is_configured"],
                "url": baseten_cfg["endpoint_url"] or "Not configured"
            },
            "fireworks_llama": {
                "configured": bool(fireworks_client),
                "model": os.environ.get("FIREWORKS_LLAMA_MODEL", "accounts/fireworks/models/llama-v3p1-70b-instruct")
            },
            "modal_muse_spark": {
                "configured": modal_cfg["is_configured"],
                "url": modal_cfg["endpoint_url"] or "Not configured"
            }
        }
    })


@app.route("/api/sample", methods=["GET"])
def sample_data():
    """
    Returns the precomputed sample floor plan and scene.json.
    Allows instant testing without live cloud API keys.
    """
    try:
        scene = get_sample_scene_json()
        overlays = get_sample_mask_overlays()
        
        with open(SAMPLE_IMG_PATH, "rb") as f:
            img_bytes = f.read()
            b64_image = base64.b64encode(img_bytes).decode("utf-8")
            data_url = f"data:image/png;base64,{b64_image}"

        return jsonify({
            "success": True,
            "scene": scene,
            "overlays": overlays,
            "imageUrl": data_url
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/sample_image", methods=["GET"])
def sample_image():
    """Serves the sample floor plan PNG image."""
    return send_file(SAMPLE_IMG_PATH, mimetype="image/png")


@app.route("/api/process", methods=["POST"])
def process_floorplan():
    """
    Main AI pipeline endpoint:
    1. Sends image to Baseten SAM 3.1 for 'room', 'wall', 'door', 'window'.
    2. Runs OpenCV & Shapely to transform masks to metric polygons.
    3. Sends candidate regions to Modal Muse Spark (or Fireworks Meta Llama 3) for labeling.
    4. Outputs strictly validated scene.json.
    """
    baseten_cfg = get_baseten_config()
    meta_key = os.environ.get("MODEL_API_KEY", "").strip()

    if not baseten_cfg["is_configured"] and not meta_key:
        return jsonify({
            "success": False,
            "error": (
                "Baseten SAM 3.1 endpoint is not configured in .env. "
                "Please set BASETEN_API_KEY and BASETEN_SAM_URL (or BASETEN_MODEL_ID), "
                "or click 'Load Demo Plan' to test the 3D viewer immediately."
            )
        }), 400

    if "file" not in request.files:
        return jsonify({"success": False, "error": "No image file provided in request."}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"success": False, "error": "Empty filename."}), 400

    try:
        mpp = float(request.form.get("metersPerPixel", 0.02))
        wall_height = float(request.form.get("wallHeight", 3.0))
        wall_thickness = float(request.form.get("wallThickness", 0.2))

        # Validate image format and dimensions with PIL
        image_bytes = file.read()
        pil_img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        img_w, img_h = pil_img.size

        # Convert to Base64 Data URL
        b64_str = base64.b64encode(image_bytes).decode("utf-8")
        b64_url = f"data:image/png;base64,{b64_str}"

        # 1. Query SAM 3.1 via Baseten for each concept
        print("Querying SAM 3.1 on Baseten for 'room'...")
        room_masks = query_sam_concept(b64_url, "room", (img_w, img_h))

        print("Querying SAM 3.1 on Baseten for 'wall'...")
        wall_masks = query_sam_concept(b64_url, "wall", (img_w, img_h))

        print("Querying SAM 3.1 on Baseten for 'door'...")
        door_masks = query_sam_concept(b64_url, "door", (img_w, img_h))

        print("Querying SAM 3.1 on Baseten for 'window'...")
        window_masks = query_sam_concept(b64_url, "window", (img_w, img_h))

        # 2. Convert masks to metric polygons in meters
        rooms_data = []
        room_id_counter = 1
        for mask in room_masks:
            polys = mask_to_polygons_with_holes(mask, meters_per_pixel=mpp, min_area_px=200)
            for p in polys:
                rooms_data.append({
                    "id": f"r{room_id_counter}",
                    "type": "room",
                    "label": f"Room {room_id_counter}",
                    "confidence": 0.85,
                    "polygon": p["polygon"],
                    "centroid": p["centroid"],
                    "area_m2": p["area_m2"]
                })
                room_id_counter += 1

        # 3. Label rooms via Modal serverless endpoint (or Fireworks Llama 3)
        if rooms_data:
            print(f"Labeling {len(rooms_data)} rooms via Modal Muse Spark / Fireworks Llama 3...")
            labels = label_rooms(b64_url, rooms_data)
            for r in rooms_data:
                rid = r["id"]
                if rid in labels:
                    r["type"] = labels[rid]["type"]
                    r["label"] = labels[rid]["label"]
                    r["confidence"] = labels[rid]["confidence"]

        cleaned_rooms = [
            {
                "id": r["id"],
                "type": r["type"],
                "label": r["label"],
                "confidence": r["confidence"],
                "polygon": r["polygon"]
            }
            for r in rooms_data
        ]

        # 4. Extract walls
        walls_data = []
        wall_id_counter = 1
        for mask in wall_masks:
            wall_polys = mask_to_polygons_with_holes(mask, meters_per_pixel=mpp, min_area_px=100)
            for wp in wall_polys:
                walls_data.append({
                    "id": f"w{wall_id_counter}",
                    "polygon": wp["polygon"],
                    "holes": wp["holes"]
                })
                wall_id_counter += 1

        # Fallback: if SAM found rooms but zero walls, synthesize from room perimeters
        if not walls_data and cleaned_rooms:
            walls_data = build_walls_from_rooms(cleaned_rooms, mpp, (img_w, img_h), wall_thickness)

        # 5. Extract doors and windows
        doors_data = extract_doors(door_masks, cleaned_rooms, meters_per_pixel=mpp)
        windows_data = extract_windows(window_masks, meters_per_pixel=mpp)

        # 6. Assemble scene.json contract
        scene_json = {
            "meta": {
                "source": file.filename,
                "imageSize": [img_w, img_h],
                "metersPerPixel": mpp,
                "wallHeight": wall_height,
                "wallThickness": wall_thickness
            },
            "rooms": cleaned_rooms,
            "walls": walls_data,
            "doors": doors_data,
            "windows": windows_data
        }

        overlays = {
            "room": [{"id": r["id"], "label": r["label"], "polygon": r["polygon"]} for r in cleaned_rooms],
            "wall": [{"id": w["id"], "polygon": w["polygon"]} for w in walls_data],
            "door": [{"id": d["id"], "center": d["center"], "width": d["width"]} for d in doors_data],
            "window": [{"id": win["id"], "center": win["center"], "width": win["width"]} for win in windows_data]
        }

        return jsonify({
            "success": True,
            "scene": scene_json,
            "overlays": overlays,
            "imageUrl": b64_url
        })

    except Exception as e:
        print(f"Error processing floor plan: {e}")
        return jsonify({
            "success": False,
            "error": f"Cloud inference pipeline error: {str(e)}"
        }), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = bool(int(os.environ.get("FLASK_DEBUG", 1)))
    print(f"Starting FloorPlan3D server at http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port, debug=debug)
