"""
FloorPlan3D - Demo Data Generator
Creates a realistic architectural floor plan image and precomputed scene data
so beginners can test and demo the 3D viewer immediately, even before configuring
their partner-cloud API keys.
"""

import io
import os
import base64
import copy
import json


def generate_sample_floorplan_image(output_path=None):
    """
    Synthesizes a realistic 2D architectural floor plan (800x600 px).
    Contains:
      - Outer perimeter walls and inner dividing walls
      - 4 distinct rooms: Classroom 101, Computer Lab, Main Corridor, Restroom
      - Door openings with door swing arcs
      - Window openings on exterior walls
      - Architectural dimension lines and labels
      Only samples
    """
    from PIL import Image, ImageDraw

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
    draw.line([(625, 360), (625, 550)], fill=wall_color, width=wall_thick) # East lobby vs stairwell

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
        # East lobby to stairwell
        {"center": (625, 420), "size": 44, "wall_orient": "V", "swing": (625, 398, 669, 442), "start": 0, "end": 90},
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
        {"text": "EAST LOBBY",    "sub": "Entrance", "pos": (525, 440)},
        {"text": "STAIRWELL",     "sub": "Vertical access", "pos": (650, 440)},
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
    Load the offline demo scene contract from samples/sample_scene.json.
    Coordinates are in meters with the origin at the plan's top-left.
    """
    scene_path = os.path.join(os.path.dirname(__file__), "samples", "sample_scene.json")
    with open(scene_path, "r", encoding="utf-8") as scene_file:
        return json.load(scene_file)


def get_two_story_sample_scene_json():
    """Return the prepared sample plan duplicated as a stacked two-story building."""
    scene = copy.deepcopy(get_sample_scene_json())
    scene["meta"].update({
        "source": "two_story_sample_floorplan.png",
        "levelCount": 2,
        "floorHeight": 3.2,
        "levels": [
            {"level": 0, "name": "Ground Floor", "elevation": 0.0},
            {"level": 1, "name": "Second Floor", "elevation": 3.2},
        ],
    })

    upper_room_labels = {
        "r1": ("classroom", "Design Studio"),
        "r2": ("lab", "Robotics Lab"),
        "r3": ("corridor", "Upper Hallway"),
        "r4": ("restroom", "Second Floor Restroom"),
        "r5": ("room", "Faculty Lounge"),
        "r6": ("entrance", "North Lobby"),
        "r7": ("stairs", "Second Floor Stairs"),
    }

    for collection in ("rooms", "walls", "doors", "windows"):
        for item in list(scene.get(collection, [])):
            item["level"] = 0
            upper = copy.deepcopy(item)
            upper["id"] = f"{item['id']}_l2"
            upper["level"] = 1
            if collection == "rooms":
                upper["type"], upper["label"] = upper_room_labels[item["id"]]
            elif collection == "doors":
                upper["connects"] = [f"{room_id}_l2" if room_id != "outside" else room_id
                                     for room_id in item.get("connects", [])]
            scene[collection].append(upper)

    return scene


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
            {"id": "r6", "label": "East Lobby", "box": [516, 366, 619, 544], "color": "rgba(52, 211, 153, 0.4)"},
            {"id": "r7", "label": "Stairwell", "box": [631, 366, 744, 544], "color": "rgba(245, 158, 11, 0.4)"},
        ],
        "wall": [
            {"id": "w_outer", "box": [50, 50, 750, 550], "color": "rgba(239, 68, 68, 0.45)"},
            {"id": "w_inner1", "box": [50, 300, 750, 360], "color": "rgba(239, 68, 68, 0.45)"},
            {"id": "w_stairs", "box": [620, 360, 630, 550], "color": "rgba(239, 68, 68, 0.45)"},
        ],
        "door": [
            {"id": "d1", "box": [182, 290, 218, 310], "color": "rgba(245, 158, 11, 0.7)"},
            {"id": "d2", "box": [532, 290, 568, 310], "color": "rgba(245, 158, 11, 0.7)"},
            {"id": "d3", "box": [144, 350, 176, 370], "color": "rgba(245, 158, 11, 0.7)"},
            {"id": "d4", "box": [373, 350, 407, 370], "color": "rgba(245, 158, 11, 0.7)"},
            {"id": "d5", "box": [40, 308, 60, 352], "color": "rgba(245, 158, 11, 0.7)"},
            {"id": "d6", "box": [615, 398, 635, 442], "color": "rgba(245, 158, 11, 0.7)"},
            {"id": "d7", "box": [545, 350, 590, 370], "color": "rgba(245, 158, 11, 0.7)"},
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
