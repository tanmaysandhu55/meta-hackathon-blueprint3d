"""
FloorPlan3D - Geometry Processor
Uses OpenCV, NumPy, and Shapely to convert raw binary segmentation masks
into clean, simplified architectural polygons scaled to real-world meters.
"""

import cv2
import numpy as np
import shapely.geometry
from shapely.validation import make_valid


def clean_mask(mask_uint8, kernel_size=5):
    """
    Cleans noisy raster masks using morphological operations:
    1. Closing: bridges small pixel gaps in walls/rooms.
    2. Opening: removes isolated salt-and-pepper noise pixels.
    """
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_size, kernel_size))
    # Close small internal gaps
    closed = cv2.morphologyEx(mask_uint8, cv2.MORPH_CLOSE, kernel)
    # Remove small specks
    opened = cv2.morphologyEx(closed, cv2.MORPH_OPEN, kernel)
    return opened


def estimate_meters_per_pixel_from_doors(door_masks, target_width_m=0.9, min_area_px=40):
    """Estimate plan scale from the median pixel width of detected doors.

    Returns None when there are too few usable door masks; callers should then
    keep their manually selected/default scale and explain that fallback.
    """
    widths_px = []
    for mask in door_masks or []:
        cleaned = clean_mask(mask, kernel_size=3)
        contours, _ = cv2.findContours(cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            if cv2.contourArea(contour) < min_area_px:
                continue
            (_center_x, _center_y), (width, height), _angle = cv2.minAreaRect(contour)
            pixel_width = max(width, height)
            if pixel_width > 0:
                widths_px.append(pixel_width)
    if not widths_px:
        return None
    median_width_px = float(np.median(widths_px))
    if median_width_px <= 0:
        return None
    return target_width_m / median_width_px


def mask_to_polygons_with_holes(mask_uint8, meters_per_pixel, min_area_px=150, simplify_meters=0.04):
    """
    Converts a binary mask into clean polygons with outer boundaries and holes.
    
    Parameters:
      mask_uint8: 2D numpy array (values 0 or 255)
      meters_per_pixel: scale factor (e.g., 0.02)
      min_area_px: minimum contour area in pixels to ignore noise
      simplify_meters: tolerance in meters for Douglas-Peucker simplification

    Returns:
      List of dicts: [
        {
          "polygon": [[x1, y1], [x2, y2], ...],
          "holes": [[[hx1, hy1], ...], ...],
          "centroid": [cx, cy],
          "area_m2": float
        }
      ]
    """
    cleaned = clean_mask(mask_uint8)
    h, w = cleaned.shape[:2]

    # Find two-level hierarchy contours: RETR_CCOMP
    # External boundaries are root contours (hierarchy[i][3] == -1)
    # Holes are children of external contours (hierarchy[i][3] != -1)
    contours, hierarchy = cv2.findContours(cleaned, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)

    if contours is None or len(contours) == 0 or hierarchy is None:
        return []

    hierarchy = hierarchy[0]
    results = []

    for i, cnt in enumerate(contours):
        # Only process external (outer) boundaries
        if hierarchy[i][3] != -1:
            continue

        area_px = cv2.contourArea(cnt)
        if area_px < min_area_px:
            continue

        # Douglas-Peucker polygon approximation for outer contour
        # Snaps zigzag pixel steps into straight architectural lines
        arc_len = cv2.arcLength(cnt, True)
        epsilon = max(1.5, 0.005 * arc_len)
        approx_exterior = cv2.approxPolyDP(cnt, epsilon, True)

        if len(approx_exterior) < 3:
            continue

        exterior_coords = [
            [round(pt[0][0] * meters_per_pixel, 3), round(pt[0][1] * meters_per_pixel, 3)]
            for pt in approx_exterior
        ]

        # Gather any hole contours that belong to this exterior contour
        holes_coords_list = []
        child_idx = hierarchy[i][2] # first child index
        while child_idx != -1:
            child_cnt = contours[child_idx]
            child_area = cv2.contourArea(child_cnt)
            # Only keep significant holes (e.g. at least 100 pixels)
            if child_area >= 100:
                child_arc = cv2.arcLength(child_cnt, True)
                child_eps = max(1.5, 0.005 * child_arc)
                approx_child = cv2.approxPolyDP(child_cnt, child_eps, True)
                if len(approx_child) >= 3:
                    hole_coords = [
                        [round(pt[0][0] * meters_per_pixel, 3), round(pt[0][1] * meters_per_pixel, 3)]
                        for pt in approx_child
                    ]
                    holes_coords_list.append(hole_coords)
            child_idx = hierarchy[child_idx][0] # next sibling

        # Validate and clean polygon geometry using Shapely
        try:
            poly = shapely.geometry.Polygon(exterior_coords, holes_coords_list)
            if not poly.is_valid:
                poly = make_valid(poly)

            # If make_valid produced a MultiPolygon, take the largest piece
            if poly.geom_type == "MultiPolygon":
                poly = max(poly.geoms, key=lambda p: p.area)

            if poly.geom_type != "Polygon" or poly.is_empty:
                continue

            # Simplify to eliminate redundant collinear vertices
            poly = poly.simplify(simplify_meters, preserve_topology=True)
            if poly.is_empty or len(poly.exterior.coords) < 3:
                continue

            # Cleaned exterior coords (omit repeating last point in GeoJSON/contract style)
            ext_pts = [[round(x, 3), round(y, 3)] for x, y in list(poly.exterior.coords)[:-1]]
            
            # Cleaned holes
            cleaned_holes = []
            for interior in poly.interiors:
                if len(interior.coords) >= 3:
                    h_pts = [[round(x, 3), round(y, 3)] for x, y in list(interior.coords)[:-1]]
                    cleaned_holes.append(h_pts)

            centroid = [round(poly.centroid.x, 3), round(poly.centroid.y, 3)]

            results.append({
                "polygon": ext_pts,
                "holes": cleaned_holes,
                "centroid": centroid,
                "area_m2": round(poly.area, 2),
                "shapely_poly": poly
            })
        except Exception:
            # Fallback to approximated contour directly if Shapely fails
            results.append({
                "polygon": exterior_coords,
                "holes": holes_coords_list,
                "centroid": [round(np.mean([p[0] for p in exterior_coords]), 3),
                             round(np.mean([p[1] for p in exterior_coords]), 3)],
                "area_m2": round(area_px * (meters_per_pixel ** 2), 2),
                "shapely_poly": None
            })

    return results


def extract_doors(door_masks, rooms_list, meters_per_pixel, min_area_px=40):
    """
    Extracts door center points and widths, and determines which rooms each door connects.
    
    scene.json contract:
    {"id": "d1", "center": [x, y], "width": 0.9, "connects": ["r1", "c1"]}
    """
    doors = []
    door_id_counter = 1

    # Pre-build Shapely polygons for each room
    room_geoms = []
    for r in rooms_list:
        try:
            poly = shapely.geometry.Polygon(r["polygon"])
            room_geoms.append((r["id"], poly))
        except Exception:
            pass

    for mask in door_masks:
        cleaned = clean_mask(mask, kernel_size=3)
        contours, _ = cv2.findContours(cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            continue

        for cnt in contours:
            if cv2.contourArea(cnt) < min_area_px:
                continue

            # Rotated bounding box to find center and door width
            rect = cv2.minAreaRect(cnt)
            (cx_px, cy_px), (w_px, h_px), angle = rect

            cx_m = round(cx_px * meters_per_pixel, 3)
            cy_m = round(cy_px * meters_per_pixel, 3)
            # Door width is the larger dimension of the door mask (typically 0.7m - 1.2m)
            width_m = round(max(w_px, h_px) * meters_per_pixel, 3)
            if width_m < 0.6:
                width_m = 0.8
            elif width_m > 2.0:
                width_m = 1.0 # clamp realistic single door width

            # Find nearby room polygons using a bounded margin around this door.
            door_pt = shapely.geometry.Point(cx_m, cy_m)
            connection_radius = min(0.75, max(0.35, width_m / 2.0 + 0.2))
            connected = []
            for room_id, r_poly in room_geoms:
                distance = r_poly.distance(door_pt)
                if distance <= connection_radius:
                    connected.append((distance, room_id))
            connected.sort(key=lambda candidate: candidate[0])
            connected = [room_id for _distance, room_id in connected[:2]]

            if len(connected) == 0:
                connected = ["outside"]
            elif len(connected) == 1:
                connected.append("outside")

            doors.append({
                "id": f"d{door_id_counter}",
                "center": [cx_m, cy_m],
                "width": width_m,
                "connects": connected[:2]
            })
            door_id_counter += 1

    return doors


def extract_windows(window_masks, meters_per_pixel, min_area_px=40):
    """
    Extracts window center points and widths.
    
    scene.json contract:
    {"id": "win1", "center": [x, y], "width": 1.2}
    """
    windows = []
    win_id_counter = 1

    for mask in window_masks:
        cleaned = clean_mask(mask, kernel_size=3)
        contours, _ = cv2.findContours(cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            continue

        for cnt in contours:
            if cv2.contourArea(cnt) < min_area_px:
                continue

            rect = cv2.minAreaRect(cnt)
            (cx_px, cy_px), (w_px, h_px), angle = rect

            cx_m = round(cx_px * meters_per_pixel, 3)
            cy_m = round(cy_px * meters_per_pixel, 3)
            width_m = round(max(w_px, h_px) * meters_per_pixel, 3)
            if width_m < 0.6:
                width_m = 1.0

            windows.append({
                "id": f"win{win_id_counter}",
                "center": [cx_m, cy_m],
                "width": width_m
            })
            win_id_counter += 1

    return windows


def build_walls_from_rooms(rooms_list, meters_per_pixel, image_size, wall_thickness_m=0.2):
    """
    Fallback wall generator: If SAM 3.1 returns 0 wall matches,
    synthesizes architectural wall outlines from room boundary outlines.
    Ensures scene.json always has valid 3D walls!
    """
    walls = []
    wall_id = 1

    for r in rooms_list:
        poly_coords = r.get("polygon", [])
        if len(poly_coords) < 3:
            continue

        try:
            poly = shapely.geometry.Polygon(poly_coords)
            # Create a hollow wall band by buffering the exterior outline
            exterior_line = poly.exterior
            buffered_wall = exterior_line.buffer(wall_thickness_m / 2.0, cap_style=3, join_style=2)
            
            if buffered_wall.geom_type == "Polygon":
                ext = [[round(x, 3), round(y, 3)] for x, y in list(buffered_wall.exterior.coords)[:-1]]
                holes = []
                for interior in buffered_wall.interiors:
                    holes.append([[round(x, 3), round(y, 3)] for x, y in list(interior.coords)[:-1]])
                walls.append({
                    "id": f"w{wall_id}",
                    "polygon": ext,
                    "holes": holes
                })
                wall_id += 1
        except Exception:
            continue

    return walls
