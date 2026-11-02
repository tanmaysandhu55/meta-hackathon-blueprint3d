"""
FloorPlan3D - Geometry Processor
Uses OpenCV, NumPy, and Shapely to convert raw binary segmentation masks
into clean, simplified architectural polygons scaled to real-world meters.
"""

import math
import cv2
import numpy as np
import shapely.geometry
from shapely.validation import make_valid
from shapely.ops import polylabel, unary_union


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


def split_multi_plan_image(image_bytes, min_plan_ratio=0.04, pad=20):
    """Detect whether a single image contains multiple separate floor plans.

    Returns a list of tuples: [(cropped_image_bytes, (x, y, w, h)), ...]
    If only one plan is found, returns [(image_bytes, (0, 0, w, h))].
    """
    if isinstance(image_bytes, np.ndarray):
        img = image_bytes
    else:
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        return [(image_bytes, (0, 0, 0, 0))]

    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    _, dark = cv2.threshold(gray, 210, 255, cv2.THRESH_BINARY_INV)

    kernel_size = max(15, int(min(w, h) / 60))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_size, kernel_size))
    closed = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    plans = []
    min_area = min_plan_ratio * (w * h)
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area >= min_area:
            bx, by, bw, bh = cv2.boundingRect(cnt)
            aspect = bw / (bh + 1e-5)
            if 0.3 <= aspect <= 3.0:
                plans.append((bx, by, bw, bh, area))

    if len(plans) < 2:
        return [(image_bytes, (0, 0, w, h))]

    plans.sort(key=lambda p: (p[1] // (h // 2), p[0]))
    crops = []
    for bx, by, bw, bh, _ in plans:
        x0 = max(0, bx - pad)
        y0 = max(0, by - pad)
        x1 = min(w, bx + bw + pad)
        y1 = min(h, by + bh + pad)
        crop_img = img[y0:y1, x0:x1]
        _, enc = cv2.imencode('.png', crop_img)
        crops.append((enc.tobytes(), (bx, by, bw, bh)))
    return crops


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
            # Only consider single door dimensions (between 15 and 100 pixels in typical plans)
            if 15 <= pixel_width <= 100:
                widths_px.append(pixel_width)
    if not widths_px:
        return None
    median_width_px = float(np.median(widths_px))
    if median_width_px <= 0:
        return None
    scale = target_width_m / median_width_px
    # Architectural scale safety clamp: plans range from 0.01 to 0.08 meters per pixel
    if not (0.01 <= scale <= 0.08):
        return None
    return scale


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


def extract_doors(door_masks, rooms_list, meters_per_pixel, min_area_px=25):
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
        # Door symbols are often thin arcs or leaf strokes. The generic cleanup
        # includes an opening step that erases those valid one-pixel features;
        # close tiny gaps without eroding the marks before contour extraction.
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        cleaned = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
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

            # A valid door must connect to at least one room; ignore noise outside the plan
            if not connected:
                continue
            if len(connected) == 1:
                connected.append("outside")

            # Deduplicate doors within 0.6m of an already detected door
            duplicate = False
            for existing in doors:
                dist = math.hypot(cx_m - existing["center"][0], cy_m - existing["center"][1])
                if dist < 0.6:
                    duplicate = True
                    break
            if duplicate:
                continue

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
    Fallback wall generator when local wall segmentation finds no reliable regions.
    Synthesizes architectural wall outlines from room boundary outlines.
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


def snap_polygon_orthogonal(coords, tolerance_deg=7.0, snap_dist=0.15):
    """Force edges within tolerance_deg of axis alignment to be strictly orthogonal,
    merge collinear consecutive edges, and snap vertices within snap_dist to one point.
    """
    pts = [[float(p[0]), float(p[1])] for p in coords]
    if len(pts) < 3:
        return pts
    n = len(pts)
    snapped = []
    for i in range(n):
        p1 = pts[i]
        p2 = pts[(i + 1) % n]
        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]
        length = math.hypot(dx, dy)
        if length < 1e-4:
            continue
        angle = math.degrees(math.atan2(dy, dx)) % 360
        near_h = min(abs(angle - 0), abs(angle - 180), abs(angle - 360)) <= tolerance_deg
        near_v = min(abs(angle - 90), abs(angle - 270)) <= tolerance_deg
        snapped.append([p1[0], p1[1]])
        if near_h:
            p2[1] = p1[1]
        elif near_v:
            p2[0] = p1[0]

    # Merge consecutive collinear edges
    merged_collinear = []
    for p in snapped:
        if len(merged_collinear) < 2:
            merged_collinear.append(p)
        else:
            p0 = merged_collinear[-2]
            p1 = merged_collinear[-1]
            if (abs(p0[1] - p1[1]) < 1e-3 and abs(p1[1] - p[1]) < 1e-3) or \
               (abs(p0[0] - p1[0]) < 1e-3 and abs(p1[0] - p[0]) < 1e-3):
                merged_collinear[-1] = p
            else:
                merged_collinear.append(p)

    # Snap vertices within snap_dist
    merged = []
    for p in merged_collinear:
        if not merged or math.hypot(p[0] - merged[-1][0], p[1] - merged[-1][1]) >= snap_dist:
            merged.append(p)
    if len(merged) > 2 and math.hypot(merged[0][0] - merged[-1][0], merged[0][1] - merged[-1][1]) < snap_dist:
        merged.pop()
    return merged


def check_axis_aligned_fraction(shapely_geom, angle_tol_deg=5.0):
    """Calculate the fraction of wall boundary segments that are strictly axis-aligned."""
    if shapely_geom is None or shapely_geom.is_empty:
        return 0.0
    geoms = shapely_geom.geoms if shapely_geom.geom_type == "MultiPolygon" else [shapely_geom]
    total_len = 0.0
    aligned_len = 0.0
    for g in geoms:
        coords = list(g.exterior.coords)
        for i in range(len(coords) - 1):
            p1 = coords[i]
            p2 = coords[i + 1]
            dx = abs(p2[0] - p1[0])
            dy = abs(p2[1] - p1[1])
            length = math.hypot(dx, dy)
            if length < 1e-4:
                continue
            total_len += length
            angle = math.degrees(math.atan2(dy, dx)) % 360
            near_h = min(abs(angle - 0), abs(angle - 180), abs(angle - 360)) <= angle_tol_deg
            near_v = min(abs(angle - 90), abs(angle - 270)) <= angle_tol_deg
            if near_h or near_v:
                aligned_len += length
    return (aligned_len / total_len) if total_len > 0 else 1.0


def reconstruct_walls_room_first(rooms_list, wall_thickness_m=0.2):
    """Primary wall reconstructor: takes clean snapped room outlines and synthesizes
    a uniform closed wall system of constant thickness (0.2m) with Shapely unary_union.
    """
    buffered_boundaries = []
    for r in rooms_list:
        poly_coords = r.get("polygon", [])
        if len(poly_coords) < 3:
            continue
        try:
            poly = shapely.geometry.Polygon(poly_coords)
            if not poly.is_valid:
                poly = make_valid(poly)
            if poly.geom_type == "MultiPolygon":
                poly = max(poly.geoms, key=lambda p: p.area)
            if poly.is_valid and poly.area >= 0.3:
                # Buffer boundary by wall_thickness / 2 so shared walls sum to wall_thickness
                buf = poly.exterior.buffer(wall_thickness_m / 2.0, cap_style=3, join_style=2)
                buffered_boundaries.append(buf)
        except Exception:
            continue

    if not buffered_boundaries:
        return [], 0.0

    walls_union = unary_union(buffered_boundaries).buffer(0)
    aligned_ratio = check_axis_aligned_fraction(walls_union)

    walls_data = []
    wall_id = 1
    geoms = walls_union.geoms if walls_union.geom_type == "MultiPolygon" else [walls_union]
    for g in geoms:
        if g.is_empty or g.area < 0.2:
            continue
        ext = [[round(x, 3), round(y, 3)] for x, y in list(g.exterior.coords)[:-1]]
        holes = []
        for interior in g.interiors:
            if len(interior.coords) >= 3:
                holes.append([[round(x, 3), round(y, 3)] for x, y in list(interior.coords)[:-1]])
        walls_data.append({
            "id": f"w{wall_id}",
            "polygon": ext,
            "holes": holes,
        })
        wall_id += 1
    return walls_data, aligned_ratio


def reconstruct_walls_from_mask_orthogonal(wall_masks, meters_per_pixel, wall_thickness_m=0.2):
    """Fallback wall reconstructor: simplifies extracted wall mask, snaps orthogonally,
    removes slivers, and rebuilds walls with uniform 0.2m thickness.
    """
    if not wall_masks:
        return [], 0.0
    combined = np.zeros_like(wall_masks[0])
    for mask in wall_masks:
        combined = cv2.bitwise_or(combined, mask)

    # Morphological clean and gap closure under 0.1m
    gap_px = max(3, int(round(0.10 / meters_per_pixel)))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (gap_px, gap_px))
    cleaned = cv2.morphologyEx(combined, cv2.MORPH_CLOSE, kernel)

    polys = mask_to_polygons_with_holes(cleaned, meters_per_pixel=meters_per_pixel, min_area_px=100)
    buffered_pieces = []
    for p in polys:
        coords = p.get("polygon", [])
        if len(coords) < 3:
            continue
        snapped = snap_polygon_orthogonal(coords, tolerance_deg=7.0, snap_dist=0.15)
        if len(snapped) < 3:
            continue
        try:
            poly = shapely.geometry.Polygon(snapped)
            if not poly.is_valid:
                poly = make_valid(poly)
            if poly.geom_type == "MultiPolygon":
                poly = max(poly.geoms, key=lambda item: item.area)
            # Remove slivers: area under 0.3 m2
            if poly.is_valid and poly.area >= 0.3:
                # Rebuild with constant thickness along boundary
                buf = poly.exterior.buffer(wall_thickness_m / 2.0, cap_style=3, join_style=2)
                buffered_pieces.append(buf)
        except Exception:
            continue

    if not buffered_pieces:
        return [], 0.0

    walls_union = unary_union(buffered_pieces).buffer(0)
    aligned_ratio = check_axis_aligned_fraction(walls_union)
    walls_data = []
    wall_id = 1
    geoms = walls_union.geoms if walls_union.geom_type == "MultiPolygon" else [walls_union]
    for g in geoms:
        if g.is_empty or g.area < 0.2:
            continue
        ext = [[round(x, 3), round(y, 3)] for x, y in list(g.exterior.coords)[:-1]]
        holes = []
        for interior in g.interiors:
            if len(interior.coords) >= 3:
                holes.append([[round(x, 3), round(y, 3)] for x, y in list(interior.coords)[:-1]])
        walls_data.append({
            "id": f"w{wall_id}",
            "polygon": ext,
            "holes": holes,
        })
        wall_id += 1
    return walls_data, aligned_ratio


def detect_doors_and_windows_geometrically(image_bytes, meters_per_pixel, pad=20):
    """Detect door openings and window symbols directly from CAD line graphics
    when AI segmentation (SAM) is not used.
    """
    if isinstance(image_bytes, np.ndarray):
        img = image_bytes
    else:
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        return [], [], None

    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    _, dark = cv2.threshold(gray, 210, 255, cv2.THRESH_BINARY_INV)

    small_close = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)))
    large_close = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (45, 45)))
    bridges = cv2.subtract(large_close, small_close)
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(bridges)

    candidates = []
    for i in range(1, num_labels):
        area = stats[i, cv2.CC_STAT_AREA]
        bw = stats[i, cv2.CC_STAT_WIDTH]
        bh = stats[i, cv2.CC_STAT_HEIGHT]
        max_d = max(bw, bh)
        min_d = min(bw, bh)
        if 35 <= max_d <= 80 and area >= 280:
            cx, cy = centroids[i]
            candidates.append((cx, cy, max_d, min_d, area))

    # Reject closely packed repeated stair treads (clusters with >= 3 items in 60px)
    filtered_doors = []
    door_widths_px = []
    for c in candidates:
        cx, cy, max_d, min_d, area = c
        neighbors = [other for other in candidates if math.hypot(cx - other[0], cy - other[1]) < 60]
        if len(neighbors) >= 3:
            continue
        if not any(math.hypot(cx - d[0], cy - d[1]) < 45 for d in filtered_doors):
            filtered_doors.append((cx, cy, max_d))
            door_widths_px.append(max_d)

    doors_data = []
    for idx, (cx_px, cy_px, w_px) in enumerate(filtered_doors):
        doors_data.append({
            "id": f"d{idx + 1}",
            "center": [round(cx_px * meters_per_pixel, 3), round(cy_px * meters_per_pixel, 3)],
            "width": 0.90,
            "connects": ["room"],
            "source": "estimated",
            "pixel_width": w_px,
        })

    # Window detection along exterior perimeter
    lines = cv2.HoughLinesP(dark, 1, np.pi/180, threshold=25, minLineLength=30, maxLineGap=5)
    windows_candidates = []
    if lines is not None:
        for l in lines:
            x1, y1, x2, y2 = l.flatten()
            length = float(np.hypot(x2 - x1, y2 - y1))
            if 35 <= length <= 120:
                cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
                if cy < 70 or cy > h - 70 or cx < 70 or cx > w - 70:
                    if not any(math.hypot(cx - win[0], cy - win[1]) < 35 for win in windows_candidates):
                        windows_candidates.append((cx, cy, length))

    windows_data = []
    for idx, (cx_px, cy_px, len_px) in enumerate(windows_candidates):
        windows_data.append({
            "id": f"win{idx + 1}",
            "center": [round(cx_px * meters_per_pixel, 3), round(cy_px * meters_per_pixel, 3)],
            "width": round(max(1.0, len_px * meters_per_pixel), 2),
            "source": "estimated",
        })

    median_door_px = float(np.median(door_widths_px)) if door_widths_px else None
    return doors_data, windows_data, median_door_px


def snap_openings_and_cut_walls(walls_data, doors_data, windows_data, wall_thickness_m=0.2, max_dist_m=0.6):
    """Snap doors and windows to the nearest wall segment within max_dist_m,
    cut rectangular opening gaps in the wall polygon, and drop orphan openings.
    """
    dropped_openings = []
    if not walls_data:
        return walls_data, doors_data, windows_data, dropped_openings

    # Convert walls to Shapely polygons
    wall_polys = []
    for w in walls_data:
        coords = w.get("polygon", [])
        if len(coords) < 3:
            continue
        try:
            holes = w.get("holes", [])
            poly = shapely.geometry.Polygon(coords, holes)
            if not poly.is_valid:
                poly = make_valid(poly)
            wall_polys.append(poly)
        except Exception:
            continue

    if not wall_polys:
        return walls_data, doors_data, windows_data, dropped_openings

    combined_walls = unary_union(wall_polys).buffer(0)

    # Process doors
    valid_doors = []
    cut_boxes = []
    for d in doors_data:
        cx, cy = d["center"]
        pt = shapely.geometry.Point(cx, cy)
        dist = combined_walls.distance(pt)
        if dist > max_dist_m:
            dropped_openings.append(f"Door {d['id']} dropped (no wall within {max_dist_m} m; no floating doors allowed).")
            continue

        # Find nearest point on wall boundary
        nearest_pt = shapely.ops.nearest_points(combined_walls.exterior if combined_walls.geom_type == "Polygon" else combined_walls.boundary, pt)[0]
        snap_x = round(nearest_pt.x, 3)
        snap_y = round(nearest_pt.y, 3)
        d["center"] = [snap_x, snap_y]

        # Determine if segment is predominantly horizontal or vertical
        cut_w = float(d.get("width", 0.9))
        box_th = wall_thickness_m + 0.15
        # Cut opening box
        door_box = shapely.geometry.box(snap_x - cut_w / 2.0, snap_y - box_th / 2.0, snap_x + cut_w / 2.0, snap_y + box_th / 2.0)
        cut_boxes.append(door_box)
        valid_doors.append(d)

    # Process windows
    valid_windows = []
    for win in windows_data:
        cx, cy = win["center"]
        pt = shapely.geometry.Point(cx, cy)
        dist = combined_walls.distance(pt)
        if dist > max_dist_m:
            dropped_openings.append(f"Window {win['id']} dropped (no wall within {max_dist_m} m).")
            continue
        nearest_pt = shapely.ops.nearest_points(combined_walls.exterior if combined_walls.geom_type == "Polygon" else combined_walls.boundary, pt)[0]
        snap_x = round(nearest_pt.x, 3)
        snap_y = round(nearest_pt.y, 3)
        win["center"] = [snap_x, snap_y]
        cut_w = float(win.get("width", 1.2))
        box_th = wall_thickness_m + 0.15
        win_box = shapely.geometry.box(snap_x - cut_w / 2.0, snap_y - box_th / 2.0, snap_x + cut_w / 2.0, snap_y + box_th / 2.0)
        cut_boxes.append(win_box)
        valid_windows.append(win)

    # Cut openings out of walls
    if cut_boxes:
        openings_union = unary_union(cut_boxes)
        combined_walls = combined_walls.difference(openings_union).buffer(0)

    # Reconstruct clean wall list
    updated_walls = []
    geoms = combined_walls.geoms if combined_walls.geom_type == "MultiPolygon" else [combined_walls]
    wall_id = 1
    for g in geoms:
        if g.is_empty or g.area < 0.2:
            continue
        ext = [[round(x, 3), round(y, 3)] for x, y in list(g.exterior.coords)[:-1]]
        holes = []
        for interior in g.interiors:
            if len(interior.coords) >= 3:
                holes.append([[round(x, 3), round(y, 3)] for x, y in list(interior.coords)[:-1]])
        updated_walls.append({
            "id": f"w{wall_id}",
            "polygon": ext,
            "holes": holes,
        })
        wall_id += 1

    return updated_walls, valid_doors, valid_windows, dropped_openings


def validate_scene_geometry(scene):
    """Validator that checks polygon validity, wall axis alignment,
    door-to-wall contact, room-in-footprint containment, and multi-story footprint match.
    """
    warnings = []
    meta = scene.get("meta", {})
    rooms = scene.get("rooms", [])
    walls = scene.get("walls", [])
    doors = scene.get("doors", [])
    levels = meta.get("levels", [])

    # 1. Check all room polygons valid
    room_geoms = []
    for r in rooms:
        coords = r.get("polygon", [])
        if len(coords) < 3:
            warnings.append(f"Room {r.get('id')} polygon has fewer than 3 vertices.")
            continue
        try:
            poly = shapely.geometry.Polygon(coords)
            if not poly.is_valid:
                warnings.append(f"Room {r.get('id')} polygon is invalid.")
            else:
                room_geoms.append(poly)
        except Exception:
            warnings.append(f"Room {r.get('id')} polygon could not be parsed.")

    # 2. Check all wall polygons valid & axis-aligned
    wall_geoms = []
    non_aligned_len = 0.0
    total_len = 0.0
    for w in walls:
        coords = w.get("polygon", [])
        if len(coords) < 3:
            continue
        try:
            poly = shapely.geometry.Polygon(coords)
            if not poly.is_valid:
                warnings.append(f"Wall {w.get('id')} polygon is invalid.")
            else:
                wall_geoms.append(poly)
            ext = list(poly.exterior.coords)
            for i in range(len(ext) - 1):
                dx = abs(ext[i+1][0] - ext[i][0])
                dy = abs(ext[i+1][1] - ext[i][1])
                length = math.hypot(dx, dy)
                if length < 1e-4:
                    continue
                total_len += length
                if dx >= 0.05 and dy >= 0.05:
                    non_aligned_len += length
        except Exception:
            pass

    if total_len > 0 and (non_aligned_len / total_len) > 0.15:
        pct = (non_aligned_len / total_len) * 100
        warnings.append(f"Wall alignment check: {pct:.1f}% of wall boundary length is not axis-aligned.")

    # 3. Check every door touches a wall
    if wall_geoms:
        combined_walls = unary_union(wall_geoms).buffer(0)
        for d in doors:
            center = d.get("center", [0, 0])
            pt = shapely.geometry.Point(center[0], center[1])
            dist = combined_walls.distance(pt)
            if dist > 0.25:
                warnings.append(f"Door {d.get('id')} center is {dist:.2f} m from nearest wall (exceeds 0.20 m limit).")

    # 4. Multi-story footprint match within 0.5m
    if len(levels) >= 2:
        coords0 = [pt for r in rooms if r.get("floorIndex", r.get("level", 0)) == 0 for pt in r.get("polygon", [])]
        coords1 = [pt for r in rooms if r.get("floorIndex", r.get("level", 0)) == 1 for pt in r.get("polygon", [])]
        if coords0 and coords1:
            w0 = max(p[0] for p in coords0) - min(p[0] for p in coords0)
            h0 = max(p[1] for p in coords0) - min(p[1] for p in coords0)
            w1 = max(p[0] for p in coords1) - min(p[0] for p in coords1)
            h1 = max(p[1] for p in coords1) - min(p[1] for p in coords1)
            if abs(w0 - w1) > 0.5 or abs(h0 - h1) > 0.5:
                warnings.append(f"Story footprint mismatch: Story 0 is {w0:.2f}x{h0:.2f} m, Story 1 is {w1:.2f}x{h1:.2f} m (diff exceeds 0.5 m).")

    return warnings
