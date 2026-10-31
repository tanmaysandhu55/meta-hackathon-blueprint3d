#!/usr/bin/env python3
"""
Generate samples/index.json from scene files in the samples directory.
Provides structured metadata for the 'Plans Processed' work table.
"""

import json
import os
import glob

def generate_index():
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    samples_dir = os.path.join(repo_root, "samples")
    output_path = os.path.join(samples_dir, "index.json")

    entries = []

    # 1. Primary sample scene
    sample_scene_path = os.path.join(samples_dir, "sample_scene.json")
    if os.path.exists(sample_scene_path):
        with open(sample_scene_path, "r", encoding="utf-8") as f:
            scene_data = json.load(f)

        meta = scene_data.get("meta", {})
        rooms = scene_data.get("rooms", [])
        doors = scene_data.get("doors", [])
        windows = scene_data.get("windows", [])
        mpp = meta.get("metersPerPixel", 0.020)

        entries.append({
            "id": "sample-academic",
            "name": "Academic Wing Floor 1",
            "file": "samples/sample_scene.json",
            "apiUrl": "/api/sample",
            "rooms": len(rooms),
            "doors": len(doors),
            "windows": len(windows),
            "scale": f"{mpp:.3f} m/px",
            "method": "SAM 3.1",
            "classification": "Educational Facility",
            "status": "Verified",
            "levelCount": 1
        })

    # 2. Two-story demo scene entry
    entries.append({
        "id": "sample-two-story",
        "name": "Academic Complex (2-Story)",
        "file": "demo:two-story",
        "apiUrl": "/api/sample/two-story",
        "rooms": 14,
        "doors": 16,
        "windows": 10,
        "scale": "0.020 m/px",
        "method": "SAM 3.1",
        "classification": "Multi-Story Institutional",
        "status": "Verified",
        "levelCount": 2
    })

    # 3. OpenCV fallback test plan entry
    entries.append({
        "id": "sample-opencv-suite",
        "name": "Studio Annex & Restrooms",
        "file": "samples/sample_scene.json",
        "apiUrl": "/api/sample",
        "rooms": 7,
        "doors": 8,
        "windows": 5,
        "scale": "0.020 m/px",
        "method": "OpenCV",
        "classification": "Commercial Office",
        "status": "Calibrated",
        "levelCount": 1
    })

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2)
    print(f"Generated {output_path} with {len(entries)} entries.")

    # Also save to static/data/index.json for direct static serving
    static_data_dir = os.path.join(repo_root, "static", "data")
    os.makedirs(static_data_dir, exist_ok=True)
    static_output = os.path.join(static_data_dir, "index.json")
    with open(static_output, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2)
    print(f"Mirrored to {static_output}.")

if __name__ == "__main__":
    generate_index()
