"""
FloorPlan3D - Flask Application
Serves the 3D Viewer frontend and provides REST API endpoints for:
1. Health check & configuration status
2. Loading sample hackathon demo floor plan & scene.json
3. Processing user-uploaded 2D floor plans via Meta SAM 3.1 & Muse Spark
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
from sam_service import get_meta_client, image_to_base64_data_url, query_sam_concept, label_rooms_with_muse_spark
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
    """Serves the main FloorPlan3D user interface."""
    api_key_configured = bool(os.environ.get("MODEL_API_KEY", "").strip())
    sam_model = os.environ.get("SAM_MODEL", "sam-3.1")
    muse_model = os.environ.get("MUSE_MODEL", "muse-spark-1.3")
    return render_template(
        "index.html",
        api_key_configured=api_key_configured,
        sam_model=sam_model,
        muse_model=muse_model
    )


@app.route("/api/health", methods=["GET"])
def health():
    """Returns the API status and configuration check."""
    api_key = os.environ.get("MODEL_API_KEY", "").strip()
    return jsonify({
        "status": "online",
        "service": "FloorPlan3D",
        "api_key_configured": bool(api_key),
        "base_url": os.environ.get("MODEL_BASE_URL", "https://api.meta.ai/v1"),
        "sam_model": os.environ.get("SAM_MODEL", "sam-3.1"),
        "muse_model": os.environ.get("MUSE_MODEL", "muse-spark-1.3")
    })


@app.route("/api/sample", methods=["GET"])
def sample_data():
    """
    Returns the precomputed sample floor plan and scene.json.
    Allows testing and presenting the 3D viewer immediately without a live API key.
    """
    try:
        scene = get_sample_scene_json()
        overlays = get_sample_mask_overlays()
        
        # Read the sample image as base64 for immediate rendering
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
    """Serves the raw sample floor plan PNG image."""
    return send_file(SAMPLE_IMG_PATH, mimetype="image/png")


@app.route("/api/process", methods=["POST"])
def process_floorplan():
    """
    Main AI pipeline endpoint:
    1. Receives uploaded 2D floor plan image.
    2. Runs Meta SAM 3.1 to segment 'room', 'wall', 'door', 'window'.
    3. Turns masks into clean polygons in meters using OpenCV & Shapely.
    4. Runs Meta Muse Spark to classify and label each room.
    5. Returns scene.json adhering to the contract.
    """
    api_key = os.environ.get("MODEL_API_KEY", "").strip()
    if not api_key:
        return jsonify({
            "success": False,
            "error": "MODEL_API_KEY is not configured in .env. Please set your key from https://dev.meta.ai/ or click 'Load Demo Plan' to test the 3D viewer."
        }), 400

    # Parse uploaded file
    if "file" not in request.files:
        return jsonify({"success": False, "error": "No image file provided in request."}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"success": False, "error": "Empty filename."}), 400

    try:
        # Read parameters
        mpp = float(request.form.get("metersPerPixel", 0.02))
        wall_height = float(request.form.get("wallHeight", 3.0))
        wall_thickness = float(request.form.get("wallThickness", 0.2))

        # Open image with PIL to validate format and read dimensions
        image_bytes = file.read()
        pil_img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        img_w, img_h = pil_img.size

        # Convert to Base64 Data URL for Meta Model API
        b64_url = image_to_base64_data_url(image_bytes)

        # Initialize OpenAI client with Meta API base_url
        client = get_meta_client()

        # Step 1: Query SAM 3.1 for each concept
        # Rules: ONE short noun phrase per request. Zero matches is normal.
        print("SAM 3.1: Segmenting 'room'...")
        room_masks = query_sam_concept(client, "room", b64_url, (img_w, img_h))

        print("SAM 3.1: Segmenting 'wall'...")
        wall_masks = query_sam_concept(client, "wall", b64_url, (img_w, img_h))

        print("SAM 3.1: Segmenting 'door'...")
        door_masks = query_sam_concept(client, "door", b64_url, (img_w, img_h))

        print("SAM 3.1: Segmenting 'window'...")
        window_masks = query_sam_concept(client, "window", b64_url, (img_w, img_h))

        # Step 2: Convert masks to polygons in meters
        rooms_data = []
        room_id_counter = 1
        for mask in room_masks:
            polys = mask_to_polygons_with_holes(mask, meters_per_pixel=mpp, min_area_px=200)
            for p in polys:
                rooms_data.append({
                    "id": f"r{room_id_counter}",
                    "type": "room", # temporary default before Muse Spark classification
                    "label": f"Room {room_id_counter}",
                    "confidence": 0.85,
                    "polygon": p["polygon"],
                    "centroid": p["centroid"],
                    "area_m2": p["area_m2"]
                })
                room_id_counter += 1

        # Step 3: Muse Spark classification
        if rooms_data:
            print(f"Muse Spark: Classifying {len(rooms_data)} rooms...")
            muse_labels = label_rooms_with_muse_spark(client, b64_url, rooms_data)
            for r in rooms_data:
                rid = r["id"]
                if rid in muse_labels:
                    r["type"] = muse_labels[rid]["type"]
                    r["label"] = muse_labels[rid]["label"]
                    r["confidence"] = muse_labels[rid]["confidence"]

        # Clean room objects to strictly match scene.json contract
        cleaned_rooms = []
        for r in rooms_data:
            cleaned_rooms.append({
                "id": r["id"],
                "type": r["type"],
                "label": r["label"],
                "confidence": r["confidence"],
                "polygon": r["polygon"]
            })

        # Process walls
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

        # Fallback if SAM detected rooms but zero walls:
        if not walls_data and cleaned_rooms:
            print("Note: Synthesizing walls from room perimeters.")
            walls_data = build_walls_from_rooms(cleaned_rooms, mpp, (img_w, img_h), wall_thickness)

        # Process doors
        doors_data = extract_doors(door_masks, cleaned_rooms, meters_per_pixel=mpp)

        # Process windows
        windows_data = extract_windows(window_masks, meters_per_pixel=mpp)

        # Construct final scene.json strictly following contract
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

        # Build mask overlay summary for frontend 2D inspection tab
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
            "error": f"Failed to process floor plan: {str(e)}"
        }), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = bool(int(os.environ.get("FLASK_DEBUG", 1)))
    print(f"Starting FloorPlan3D server at http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port, debug=debug)
