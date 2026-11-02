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
    snapped = [p[:] for p in pts]
    for _pass in range(2):
        for i in range(n):
            p1 = snapped[i]
            next_idx = (i + 1) % n
            p2 = snapped[next_idx]
            dx = p2[0] - p1[0]
            dy = p2[1] - p1[1]
            length = math.hypot(dx, dy)
            if length < 1e-4:
                continue
            angle = math.degrees(math.atan2(dy, dx)) % 360
            near_h = min(abs(angle - 0), abs(angle - 180), abs(angle - 360)) <= tolerance_deg
            near_v = min(abs(angle - 90), abs(angle - 270)) <= tolerance_deg
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
    if len(merged) < 3:
        return pts
    try:
        poly_check = shapely.geometry.Polygon(merged)
        if not poly_check.is_valid:
            valid_p = make_valid(poly_check)
            if valid_p.geom_type == 'Polygon' and len(valid_p.exterior.coords) >= 4:
                merged = [[round(pt[0], 3), round(pt[1], 3)] for pt in list(valid_p.exterior.coords)[:-1]]
            elif valid_p.geom_type == 'MultiPolygon':
                largest = max(valid_p.geoms, key=lambda g: g.area)
                if len(largest.exterior.coords) >= 4:
                    merged = [[round(pt[0], 3), round(pt[1], 3)] for pt in list(largest.exterior.coords)[:-1]]
    except Exception:
        pass
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



def _find_wall_segment_orientation(combined_walls, pt):
    """Find the orientation (tangent u and normal n) of the wall boundary nearest to pt."""
    boundary = combined_walls.boundary
    best_dist = float("inf")
    best_u = (1.0, 0.0)
    best_n = (0.0, 1.0)
    best_nearest = pt

    lines = []
    if boundary.geom_type == "LineString":
        lines = [boundary]
    elif boundary.geom_type in ("MultiLineString", "GeometryCollection"):
        lines = [g for g in boundary.geoms if g.geom_type == "LineString"]

    for line in lines:
        coords = list(line.coords)
        for i in range(len(coords) - 1):
            p1 = coords[i]
            p2 = coords[i + 1]
            seg = shapely.geometry.LineString([p1, p2])
            d = seg.distance(pt)
            if d < best_dist:
                best_dist = d
                n_pt = shapely.ops.nearest_points(seg, pt)[0]
                best_nearest = n_pt
                dx = p2[0] - p1[0]
                dy = p2[1] - p1[1]
                L = math.hypot(dx, dy)
                if L > 1e-4:
                    best_u = (dx / L, dy / L)
                    best_n = (-dy / L, dx / L)

    return best_nearest, best_u, best_n


def _oriented_opening_box(center_x, center_y, u, n, width, thickness):
    """Create an oriented rectangular polygon along tangent u and normal n."""
    half_w = width / 2.0
    half_t = thickness / 2.0
    c1 = (center_x + u[0] * half_w + n[0] * half_t, center_y + u[1] * half_w + n[1] * half_t)
    c2 = (center_x - u[0] * half_w + n[0] * half_t, center_y - u[1] * half_w + n[1] * half_t)
    c3 = (center_x - u[0] * half_w - n[0] * half_t, center_y - u[1] * half_w - n[1] * half_t)
    c4 = (center_x + u[0] * half_w - n[0] * half_t, center_y + u[1] * half_w - n[1] * half_t)
    return shapely.geometry.Polygon([c1, c2, c3, c4])


def _determine_opening_connects(snap_x, snap_y, n, cleaned_rooms):
    """Determine which two rooms an opening connects based on normal offsets."""
    if not cleaned_rooms:
        return ["room", "room"]
    p_a = shapely.geometry.Point(snap_x + n[0] * 0.35, snap_y + n[1] * 0.35)
    p_b = shapely.geometry.Point(snap_x - n[0] * 0.35, snap_y - n[1] * 0.35)
    room_a = "outside"
    room_b = "outside"
    for r in cleaned_rooms:
        poly_coords = r.get("polygon", [])
        if len(poly_coords) >= 3:
            try:
                poly = shapely.geometry.Polygon(poly_coords)
                if poly.contains(p_a):
                    room_a = r.get("id", "room")
                if poly.contains(p_b):
                    room_b = r.get("id", "room")
            except Exception:
                pass
    if room_a == "outside" and room_b == "outside":
        return ["room", "outside"]
    if room_a == room_b:
        return [room_a, "outside"]
    return [room_a, room_b]

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

    # 1. Door swing arcs (quarter-circle curved contours)
    contours, _ = cv2.findContours(dark, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    arcs = []
    for cnt in contours:
        length = cv2.arcLength(cnt, False)
        area = cv2.contourArea(cnt)
        if 45 <= length <= 350 and area < 400:
            (cx, cy), radius = cv2.minEnclosingCircle(cnt)
            if 20 <= radius <= 70:
                arcs.append((float(cx), float(cy), float(radius)))

    # 2. Wall breaks / gaps via morphological differences
    small_close = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)))
    large_close = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (45, 45)))
    bridges = cv2.subtract(large_close, small_close)
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(bridges)

    gap_candidates = []
    for i in range(1, num_labels):
        area = stats[i, cv2.CC_STAT_AREA]
        bw = stats[i, cv2.CC_STAT_WIDTH]
        bh = stats[i, cv2.CC_STAT_HEIGHT]
        max_d = max(bw, bh)
        min_d = min(bw, bh)
        if 25 <= max_d <= 80 and area >= 180:
            cx, cy = centroids[i]
            gap_candidates.append((float(cx), float(cy), float(max_d), float(min_d), area))

    # Reject closely packed repeated stair treads
    filtered_gaps = []
    for c in gap_candidates:
        cx, cy, max_d, min_d, area = c
        neighbors = [other for other in gap_candidates if math.hypot(cx - other[0], cy - other[1]) < 60]
        if len(neighbors) >= 4:
            continue
        filtered_gaps.append((cx, cy, max_d))

    final_doors = []
    door_widths_px = []

    # First add arcs: each arc defines a door
    for arc_cx, arc_cy, arc_r in arcs:
        matching_gap = None
        min_gap_dist = 50.0
        for gap in filtered_gaps:
            d = math.hypot(arc_cx - gap[0], arc_cy - gap[1])
            if d < min_gap_dist:
                min_gap_dist = d
                matching_gap = gap

        if matching_gap:
            door_cx = matching_gap[0]
            door_cy = matching_gap[1]
            door_w = matching_gap[2]
        else:
            door_cx = arc_cx
            door_cy = arc_cy
            door_w = arc_r * 1.414

        if not any(math.hypot(door_cx - d[0], door_cy - d[1]) < 35 for d in final_doors):
            final_doors.append((door_cx, door_cy, door_w, True))
            door_widths_px.append(door_w)

    # Second add gaps that are not covered by any arc (e.g. open entrance doorway)
    for gap in filtered_gaps:
        cx, cy, max_d = gap
        if not any(math.hypot(cx - d[0], cy - d[1]) < 70 for d in final_doors):
            final_doors.append((cx, cy, max_d, False))
            door_widths_px.append(max_d)

    doors_data = []
    for idx, (cx_px, cy_px, w_px, has_arc) in enumerate(final_doors):
        doors_data.append({
            "id": f"d{idx + 1}",
            "center": [round(cx_px * meters_per_pixel, 3), round(cy_px * meters_per_pixel, 3)],
            "pixel_center": [cx_px, cy_px],
            "width": 0.90,
            "connects": ["room"],
            "source": "estimated",
            "has_arc": has_arc,
            "pixel_width": w_px,
        })

    # 3. Window detection
    lines = cv2.HoughLinesP(dark, 1, np.pi/180, threshold=25, minLineLength=25, maxLineGap=10)
    windows_candidates = []
    if lines is not None:
        h_lines = []
        v_lines = []
        for l in lines:
            x1, y1, x2, y2 = l.flatten()
            length = float(np.hypot(x2 - x1, y2 - y1))
            if 25 <= length <= 140:
                angle = float(np.degrees(np.arctan2(abs(y2 - y1), abs(x2 - x1))))
                if angle < 15:
                    h_lines.append((min(x1, x2), max(x1, x2), (y1 + y2)/2.0, length))
                elif angle > 75:
                    v_lines.append((min(y1, y2), max(y1, y2), (x1 + x2)/2.0, length))

        for i in range(len(h_lines)):
            for j in range(i + 1, len(h_lines)):
                l1, l2 = h_lines[i], h_lines[j]
                overlap = min(l1[1], l2[1]) - max(l1[0], l2[0])
                y_dist = abs(l1[2] - l2[2])
                if overlap > 25 and 6 <= y_dist <= 25:
                    cx = (max(l1[0], l2[0]) + min(l1[1], l2[1])) / 2.0
                    cy = (l1[2] + l2[2]) / 2.0
                    if not any(math.hypot(cx - d[0], cy - d[1]) < 40 for d in final_doors):
                        windows_candidates.append((cx, cy, overlap))

        for i in range(len(v_lines)):
            for j in range(i + 1, len(v_lines)):
                l1, l2 = v_lines[i], v_lines[j]
                overlap = min(l1[1], l2[1]) - max(l1[0], l2[0])
                x_dist = abs(l1[2] - l2[2])
                if overlap > 25 and 6 <= x_dist <= 25:
                    cy = (max(l1[0], l2[0]) + min(l1[1], l2[1])) / 2.0
                    cx = (l1[2] + l2[2]) / 2.0
                    if not any(math.hypot(cx - d[0], cy - d[1]) < 40 for d in final_doors):
                        windows_candidates.append((cx, cy, overlap))

    filtered_windows = []
    for win in windows_candidates:
        if not any(math.hypot(win[0] - w_item[0], win[1] - w_item[1]) < 35 for w_item in filtered_windows):
            filtered_windows.append(win)

    windows_data = []
    for idx, (cx_px, cy_px, len_px) in enumerate(filtered_windows):
        windows_data.append({
            "id": f"win{idx + 1}",
            "center": [round(cx_px * meters_per_pixel, 3), round(cy_px * meters_per_pixel, 3)],
            "pixel_center": [cx_px, cy_px],
            "width": round(max(1.0, min(2.0, len_px * meters_per_pixel)), 2),
            "source": "estimated",
        })

    median_door_px = float(np.median(door_widths_px)) if door_widths_px else None
    return doors_data, windows_data, median_door_px


def snap_openings_and_cut_walls(walls_data, doors_data, windows_data, wall_thickness_m=0.2, max_dist_m=0.6, cleaned_rooms=None):
    """Snap doors and windows to the nearest wall segment within max_dist_m,
    cut rectangular opening gaps oriented along the wall, and compute room connectivity.
    """
    dropped_openings = []
    if not walls_data:
        return walls_data, doors_data, windows_data, dropped_openings

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

    valid_doors = []
    cut_boxes = []
    for d in doors_data:
        cx, cy = d["center"]
        pt = shapely.geometry.Point(cx, cy)
        dist = combined_walls.distance(pt)
        if dist > max_dist_m:
            dropped_openings.append(f"Door {d['id']} dropped (no wall within {max_dist_m} m; no floating doors allowed).")
            continue

        nearest_pt, u, n = _find_wall_segment_orientation(combined_walls, pt)
        snap_x = round(nearest_pt.x, 3)
        snap_y = round(nearest_pt.y, 3)
        d["center"] = [snap_x, snap_y]

        angle = math.atan2(u[1], u[0])
        # Force strict axis alignment if close to horizontal or vertical
        if abs(math.cos(angle)) >= abs(math.sin(angle)):
            rot = 0.0
        else:
            rot = round(math.pi / 2, 4)
        d["rotation"] = rot
        d["angle"] = rot

        d["connects"] = _determine_opening_connects(snap_x, snap_y, n, cleaned_rooms)
        d.setdefault("source", "estimated")

        cut_w = float(d.get("width", 0.9))
        box_th = wall_thickness_m + 0.15
        door_box = _oriented_opening_box(snap_x, snap_y, u, n, cut_w, box_th)
        cut_boxes.append(door_box)
        valid_doors.append(d)

    valid_windows = []
    for win in windows_data:
        cx, cy = win["center"]
        pt = shapely.geometry.Point(cx, cy)
        dist = combined_walls.distance(pt)
        if dist > max_dist_m:
            dropped_openings.append(f"Window {win['id']} dropped (no wall within {max_dist_m} m).")
            continue

        nearest_pt, u, n = _find_wall_segment_orientation(combined_walls, pt)
        snap_x = round(nearest_pt.x, 3)
        snap_y = round(nearest_pt.y, 3)
        win["center"] = [snap_x, snap_y]

        angle = math.atan2(u[1], u[0])
        if abs(math.cos(angle)) >= abs(math.sin(angle)):
            rot = 0.0
        else:
            rot = round(math.pi / 2, 4)
        win["rotation"] = rot
        win["angle"] = rot

        win["connects"] = _determine_opening_connects(snap_x, snap_y, n, cleaned_rooms)
        win.setdefault("source", "estimated")

        cut_w = float(win.get("width", 1.2))
        box_th = wall_thickness_m + 0.15
        win_box = _oriented_opening_box(snap_x, snap_y, u, n, cut_w, box_th)
        cut_boxes.append(win_box)
        valid_windows.append(win)

    if cut_boxes:
        openings_union = unary_union(cut_boxes)
        combined_walls = combined_walls.difference(openings_union).buffer(0)

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
                valid_p = make_valid(poly)
                polys = [g for g in (valid_p.geoms if hasattr(valid_p, "geoms") else [valid_p]) if g.geom_type == "Polygon"]
                if polys:
                    largest = max(polys, key=lambda g: g.area)
                    r["polygon"] = [[round(pt[0], 3), round(pt[1], 3)] for pt in list(largest.exterior.coords)[:-1]]
                    room_geoms.append(largest)
                else:
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
            door_w = float(d.get("width", 0.9))
            limit = max(1.10, round(door_w + 0.20, 2))
            if dist > limit:
                warnings.append(f"Door {d.get('id')} center is {dist:.2f} m from nearest wall (exceeds {limit:.2f} m limit).")

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
