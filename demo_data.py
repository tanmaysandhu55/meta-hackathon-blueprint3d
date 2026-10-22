"""
FloorPlan3D - Demo Data Generator
Creates a realistic architectural floor plan image and precomputed scene data
so beginners can test and demo the 3D viewer immediately, even before configuring
their Meta MODEL_API_KEY.
"""

import io
import os
import base64
import numpy as np
from PIL import Image, ImageDraw, ImageFont


def generate_sample_floorplan_image(output_path=None):
    """
    Synthesizes a realistic 2D architectural floor plan (800x600 px).
    Contains:
      - Outer perimeter walls and inner dividing walls
      - 4 distinct rooms: Classroom 101, Computer Lab, Main Corridor, Restroom
      - Door openings with door swing arcs
      - Window openings on exterior walls
      - Architectural dimension lines and labels
    """
    width, height = 800, 600
    img = Image.new("RGB", (width, height), color=(250, 250, 250))
    draw = ImageDraw.Draw(img)

    # 1. Subtle background grid (architectural blueprint graph lines)
    for x in range(0, width, 40):
        draw.line([(x, 0), (x, height)], fill=(235, 238, 242), width=1)
    for y in range(0, height, 40):
        draw.line([(0, y), (width, y)], fill=(235, 238, 242), width=1)

    # Room bounds in pixels
    # Classroom 101: [60, 60, 360, 300]
    # Computer Lab:  [380, 60, 740, 300]
    # Restroom:      [60, 360, 260, 540]
    # Faculty Office:[280, 360, 500, 540]
    # Main Corridor: [60, 300, 740, 360] + east branch [500, 360, 740, 540]

    # Outer wall bounds
    outer_box = [50, 50, 750, 550]
    wall_color = (40, 44, 52)      # Dark slate wall tone
    wall_thick = 12

    # Draw outer perimeter wall
    draw.rectangle(outer_box, outline=wall_color, width=wall_thick)

    # Draw interior dividing walls
    # Horizontal corridor walls
    draw.line([(50, 300), (750, 300)], fill=wall_color, width=wall_thick)
    draw.line([(50, 360), (750, 360)], fill=wall_color, width=wall_thick)

    # Vertical dividing walls
    draw.line([(370, 50), (370, 300)], fill=wall_color, width=wall_thick)   # Classroom vs Lab
    draw.line([(270, 360), (270, 550)], fill=wall_color, width=wall_thick) # Restroom vs Office
    draw.line([(510, 360), (510, 550)], fill=wall_color, width=wall_thick) # Office vs East Wing

    # 2. Door Openings (cleared wall sections with swing arcs)
    door_clearances = [
        # Classroom door to corridor
        {"center": (200, 300), "size": 36, "wall_orient": "H", "swing": (200, 300, 236, 336), "start": 0, "end": 90},
        # Lab door to corridor
        {"center": (550, 300), "size": 36, "wall_orient": "H", "swing": (550, 300, 586, 336), "start": 0, "end": 90},
        # Restroom door to corridor
        {"center": (160, 360), "size": 32, "wall_orient": "H", "swing": (160, 328, 192, 360), "start": 270, "end": 360},
        # Office door to corridor
        {"center": (390, 360), "size": 34, "wall_orient": "H", "swing": (390, 326, 424, 360), "start": 270, "end": 360},
        # Main entrance on West Wall
        {"center": (50, 330),  "size": 44, "wall_orient": "V", "swing": (50, 308, 94, 352), "start": 0, "end": 90},
    ]

    for d in door_clearances:
        cx, cy = d["center"]
        sz = d["size"]
        if d["wall_orient"] == "H":
            draw.rectangle([cx - sz // 2, cy - wall_thick // 2, cx + sz // 2, cy + wall_thick // 2], fill=(250, 250, 250))
            # Draw door line and swing arc
            draw.line([(cx - sz // 2, cy), (cx - sz // 2, cy + (sz if cy == 300 else -sz))], fill=(160, 100, 40), width=2)
            draw.arc(d["swing"], d["start"], d["end"], fill=(180, 130, 80), width=1)
        else:
            draw.rectangle([cx - wall_thick // 2, cy - sz // 2, cx + wall_thick // 2, cy + sz // 2], fill=(250, 250, 250))
            draw.line([(cx, cy - sz // 2), (cx + sz, cy - sz // 2)], fill=(160, 100, 40), width=2)
            draw.arc(d["swing"], d["start"], d["end"], fill=(180, 130, 80), width=1)

    # 3. Windows on Exterior Walls (drawn as parallel blue/glass lines)
    window_openings = [
        # North wall windows (Classroom & Lab)
        (180, 50, 260, 50),
        (520, 50, 620, 50),
        # East wall window (Lab)
        (750, 150, 750, 230),
        # South wall windows (Restroom & Office)
        (130, 550, 190, 550),
        (360, 550, 440, 550),
    ]

    for wx1, wy1, wx2, wy2 in window_openings:
        if wy1 == wy2: # Horizontal
            draw.rectangle([wx1, wy1 - wall_thick // 2, wx2, wy2 + wall_thick // 2], fill=(250, 250, 250))
            draw.line([(wx1, wy1 - 3), (wx2, wy2 - 3)], fill=(59, 130, 246), width=2)
            draw.line([(wx1, wy1 + 3), (wx2, wy2 + 3)], fill=(59, 130, 246), width=2)
        else: # Vertical
            draw.rectangle([wx1 - wall_thick // 2, wy1, wx2 + wall_thick // 2, wy2], fill=(250, 250, 250))
            draw.line([(wx1 - 3, wy1), (wx2 - 3, wy2)], fill=(59, 130, 246), width=2)
            draw.line([(wx1 + 3, wy1), (wx2 + 3, wy2)], fill=(59, 130, 246), width=2)

    # 4. Architectural Room Labels
    room_annotations = [
        {"text": "CLASSROOM 101", "sub": "Area: 48.0 m²", "pos": (150, 160)},
        {"text": "COMPUTER LAB",  "sub": "Area: 57.6 m²", "pos": (500, 160)},
        {"text": "MAIN CORRIDOR", "sub": "Access & Exit", "pos": (350, 322)},
        {"text": "RESTROOM",      "sub": "M / F Facilities", "pos": (110, 440)},
        {"text": "FACULTY OFFICE","sub": "Room 103", "pos": (350, 440)},
        {"text": "EAST LOBBY",    "sub": "Entrance", "pos": (580, 440)},
    ]

    for ann in room_annotations:
        tx, ty = ann["pos"]
        draw.text((tx, ty), ann["text"], fill=(30, 41, 59))
        draw.text((tx, ty + 16), ann["sub"], fill=(100, 116, 139))

    # Save to disk if path requested
    if output_path:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        img.save(output_path, "PNG")

    return img


def get_sample_scene_json():
    """
    Returns a complete, validated scene.json dictionary meeting the hackathon contract.
    Coordinates are in METERS (origin top-left of plan, x right, y down).
    Meters per pixel: 0.02 (1 px = 0.02m; 50px = 1m).
    800x600 px image -> 16.0m x 12.0m floor plan.
    """
    mpp = 0.02 # 0.02 meters per pixel

    # Helper function to convert pixel rect [x1, y1, x2, y2] to polygon in meters
    def rect_to_poly_m(px1, py1, px2, py2):
        return [
            [round(px1 * mpp, 3), round(py1 * mpp, 3)],
            [round(px2 * mpp, 3), round(py1 * mpp, 3)],
            [round(px2 * mpp, 3), round(py2 * mpp, 3)],
            [round(px1 * mpp, 3), round(py2 * mpp, 3)],
        ]

    scene_data = {
        "meta": {
            "source": "sample_floorplan.png",
            "imageSize": [800, 600],
            "metersPerPixel": mpp,
            "wallHeight": 3.0,
            "wallThickness": 0.24,
        },
        "rooms": [
            {
                "id": "r1",
                "type": "classroom",
                "label": "Classroom 101",
                "confidence": 0.96,
                "polygon": rect_to_poly_m(56, 56, 364, 294), # 6.16m x 4.76m
            },
            {
                "id": "r2",
                "type": "lab",
                "label": "Computer Lab",
                "confidence": 0.94,
                "polygon": rect_to_poly_m(376, 56, 744, 294), # 7.36m x 4.76m
            },
            {
                "id": "r3",
                "type": "corridor",
                "label": "Main Corridor",
                "confidence": 0.98,
                "polygon": [
                    [1.12, 6.0], [14.88, 6.0], [14.88, 7.2],
                    [10.2, 7.2], [10.2, 10.88], [14.88, 10.88],
                    [14.88, 11.0], [10.0, 11.0], [10.0, 7.2],
                    [1.12, 7.2]
                ],
            },
            {
                "id": "r4",
                "type": "restroom",
                "label": "Restroom",
                "confidence": 0.91,
                "polygon": rect_to_poly_m(56, 366, 264, 544), # 4.16m x 3.56m
            },
            {
                "id": "r5",
                "type": "room",
                "label": "Faculty Office",
                "confidence": 0.89,
                "polygon": rect_to_poly_m(276, 366, 504, 544), # 4.56m x 3.56m
            },
            {
                "id": "r6",
                "type": "entrance",
                "label": "East Lobby",
                "confidence": 0.93,
                "polygon": rect_to_poly_m(516, 366, 744, 544), # 4.56m x 3.56m
            },
        ],
        "walls": [
            {
                "id": "w1",
                "polygon": [
                    [1.0, 1.0], [15.0, 1.0], [15.0, 11.0], [1.0, 11.0]
                ],
                "holes": [
                    # Inner courtyard / room openings cut out of outer boundary
                    rect_to_poly_m(56, 56, 744, 294),
                    rect_to_poly_m(56, 300, 744, 544)
                ],
            },
            {
                "id": "w2",
                "polygon": [
                    [7.3, 1.0], [7.5, 1.0], [7.5, 6.0], [7.3, 6.0]
                ],
                "holes": [],
            },
            {
                "id": "w3",
                "polygon": [
                    [1.0, 5.9], [15.0, 5.9], [15.0, 6.1], [1.0, 6.1]
                ],
                "holes": [],
            },
            {
                "id": "w4",
                "polygon": [
                    [1.0, 7.1], [15.0, 7.1], [15.0, 7.3], [1.0, 7.3]
                ],
                "holes": [],
            },
            {
                "id": "w5",
                "polygon": [
                    [5.3, 7.2], [5.5, 7.2], [5.5, 11.0], [5.3, 11.0]
                ],
                "holes": [],
            },
            {
                "id": "w6",
                "polygon": [
                    [10.1, 7.2], [10.3, 7.2], [10.3, 11.0], [10.1, 11.0]
                ],
                "holes": [],
            },
        ],
        "doors": [
            {
                "id": "d1",
                "center": [round(200 * mpp, 3), round(300 * mpp, 3)], # [4.0, 6.0]
                "width": round(36 * mpp, 3), # 0.72m
                "connects": ["r1", "r3"],
            },
            {
                "id": "d2",
                "center": [round(550 * mpp, 3), round(300 * mpp, 3)], # [11.0, 6.0]
                "width": round(36 * mpp, 3), # 0.72m
                "connects": ["r2", "r3"],
            },
            {
                "id": "d3",
                "center": [round(160 * mpp, 3), round(360 * mpp, 3)], # [3.2, 7.2]
                "width": round(32 * mpp, 3), # 0.64m
                "connects": ["r4", "r3"],
            },
            {
                "id": "d4",
                "center": [round(390 * mpp, 3), round(360 * mpp, 3)], # [7.8, 7.2]
                "width": round(34 * mpp, 3), # 0.68m
                "connects": ["r5", "r3"],
            },
            {
                "id": "d5",
                "center": [round(50 * mpp, 3), round(330 * mpp, 3)],  # [1.0, 6.6]
                "width": round(44 * mpp, 3), # 0.88m
                "connects": ["r3", "outside"],
            },
        ],
        "windows": [
            {
                "id": "win1",
                "center": [round(220 * mpp, 3), round(50 * mpp, 3)], # [4.4, 1.0]
                "width": round(80 * mpp, 3), # 1.6m
            },
            {
                "id": "win2",
                "center": [round(570 * mpp, 3), round(50 * mpp, 3)], # [11.4, 1.0]
                "width": round(100 * mpp, 3), # 2.0m
            },
            {
                "id": "win3",
                "center": [round(750 * mpp, 3), round(190 * mpp, 3)], # [15.0, 3.8]
                "width": round(80 * mpp, 3), # 1.6m
            },
            {
                "id": "win4",
                "center": [round(160 * mpp, 3), round(550 * mpp, 3)], # [3.2, 11.0]
                "width": round(60 * mpp, 3), # 1.2m
            },
            {
                "id": "win5",
                "center": [round(400 * mpp, 3), round(550 * mpp, 3)], # [8.0, 11.0]
                "width": round(80 * mpp, 3), # 1.6m
            },
        ],
    }

    return scene_data


def get_sample_mask_overlays(image_size=(800, 600)):
    """
    Generates synthetic 2D segmentation masks for the sample plan,
    used to render the '2D AI Segmentation' inspection tab in the frontend.
    Returns a dict mapping concept ('room', 'wall', 'door', 'window')
    to a list of binary raster bounding boxes and contours.
    """
    w, h = image_size
    overlays = {
        "room": [
            {"id": "r1", "label": "Classroom 101", "box": [56, 56, 364, 294], "color": "rgba(96, 165, 250, 0.4)"},
            {"id": "r2", "label": "Computer Lab", "box": [376, 56, 744, 294], "color": "rgba(168, 85, 247, 0.4)"},
            {"id": "r3", "label": "Main Corridor", "box": [56, 300, 744, 360], "color": "rgba(156, 163, 175, 0.4)"},
            {"id": "r4", "label": "Restroom", "box": [56, 366, 264, 544], "color": "rgba(45, 212, 191, 0.4)"},
            {"id": "r5", "label": "Faculty Office", "box": [276, 366, 504, 544], "color": "rgba(148, 163, 184, 0.4)"},
            {"id": "r6", "label": "East Lobby", "box": [516, 366, 744, 544], "color": "rgba(52, 211, 153, 0.4)"},
        ],
        "wall": [
            {"id": "w_outer", "box": [50, 50, 750, 550], "color": "rgba(239, 68, 68, 0.45)"},
            {"id": "w_inner1", "box": [50, 300, 750, 360], "color": "rgba(239, 68, 68, 0.45)"},
        ],
        "door": [
            {"id": "d1", "box": [182, 290, 218, 310], "color": "rgba(245, 158, 11, 0.7)"},
            {"id": "d2", "box": [532, 290, 568, 310], "color": "rgba(245, 158, 11, 0.7)"},
            {"id": "d3", "box": [144, 350, 176, 370], "color": "rgba(245, 158, 11, 0.7)"},
            {"id": "d4", "box": [373, 350, 407, 370], "color": "rgba(245, 158, 11, 0.7)"},
            {"id": "d5", "box": [40, 308, 60, 352], "color": "rgba(245, 158, 11, 0.7)"},
        ],
        "window": [
            {"id": "win1", "box": [180, 44, 260, 56], "color": "rgba(56, 189, 248, 0.7)"},
            {"id": "win2", "box": [520, 44, 620, 56], "color": "rgba(56, 189, 248, 0.7)"},
            {"id": "win3", "box": [744, 150, 756, 230], "color": "rgba(56, 189, 248, 0.7)"},
            {"id": "win4", "box": [130, 544, 190, 556], "color": "rgba(56, 189, 248, 0.7)"},
            {"id": "win5", "box": [360, 544, 440, 556], "color": "rgba(56, 189, 248, 0.7)"},
        ],
    }
    return overlays
