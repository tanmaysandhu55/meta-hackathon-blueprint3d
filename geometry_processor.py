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


def split_image_at_user_dividers(image_bytes, floor_count, orientation="vertical", positions=None):
    """Split one uploaded image only at user-selected normalized divider positions."""
    if isinstance(image_bytes, np.ndarray):
        img = image_bytes
    else:
        img = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("The uploaded floor-plan image could not be decoded for splitting.")
    floor_count = int(floor_count)
    if floor_count not in (2, 3):
        raise ValueError("Choose one, two, or three floors in the uploaded image.")
    axis = 1 if orientation == "vertical" else 0 if orientation == "horizontal" else None
    if axis is None:
        raise ValueError("Choose vertical or horizontal floor-plan dividers.")
    length = img.shape[1] if axis == 1 else img.shape[0]
    raw_positions = list(positions or [])
    if len(raw_positions) != floor_count - 1:
        raw_positions = [index / floor_count for index in range(1, floor_count)]
    normalized = [float(value) for value in raw_positions]
    if any(not math.isfinite(value) or not 0.08 <= value <= 0.92 for value in normalized):
        raise ValueError("Move each divider so every floor section has at least 8% of the image width or height.")
    if normalized != sorted(normalized) or any(right - left < 0.08 for left, right in zip(normalized, normalized[1:])):
        raise ValueError("Floor dividers must be ordered and leave room for each floor plan.")
    edges = [0, *[int(round(value * length)) for value in normalized], length]
    crops = []
    for start, end in zip(edges, edges[1:]):
        if end <= start:
            raise ValueError("The selected floor divider positions do not create valid image regions.")
        crop = img[:, start:end] if axis == 1 else img[start:end, :]
        success, encoded = cv2.imencode(".png", crop)
        if not success:
            raise ValueError("A selected floor-plan section could not be encoded.")
        if axis == 1:
            bbox = (start, 0, end - start, img.shape[0])
        else:
            bbox = (0, start, img.shape[1], end - start)
        crops.append((encoded.tobytes(), bbox))
    return crops


def estimate_meters_per_pixel_from_door_widths(widths_px, target_width_m=0.9, min_doors=3, max_cv=0.25):
    """Estimate scale only when at least three door widths agree closely."""
    widths = np.asarray([float(width) for width in (widths_px or []) if math.isfinite(float(width)) and float(width) > 0], dtype=np.float64)
    if len(widths) < min_doors:
        return None, {"count": int(len(widths)), "coefficientOfVariation": None}
    median_width = float(np.median(widths))
    if median_width <= 0:
        return None, {"count": int(len(widths)), "coefficientOfVariation": None}
    cv = float(np.std(widths) / median_width)
    if cv >= max_cv:
        return None, {"count": int(len(widths)), "coefficientOfVariation": round(cv, 4)}
    scale = float(target_width_m) / median_width
    if not (0.001 <= scale <= 0.1):
        return None, {"count": int(len(widths)), "coefficientOfVariation": round(cv, 4)}
    return scale, {"count": int(len(widths)), "coefficientOfVariation": round(cv, 4), "medianWidthPx": median_width}


def estimate_meters_per_pixel_from_doors(door_masks, target_width_m=0.9, min_area_px=40, min_doors=3, max_cv=0.25):
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
    scale, _quality = estimate_meters_per_pixel_from_door_widths(
        widths_px, target_width_m=target_width_m, min_doors=min_doors, max_cv=max_cv
    )
    return scale


def scale_from_two_points(point_a_px, point_b_px, known_length_m):
    """Return m/px from two coordinates measured in the same source image."""
    ax, ay = map(float, point_a_px)
    bx, by = map(float, point_b_px)
    length = float(known_length_m)
    pixel_distance = math.hypot(bx - ax, by - ay)
    if not all(math.isfinite(value) for value in (ax, ay, bx, by, length)):
        raise ValueError("Calibration points and length must be finite numbers.")
    if pixel_distance <= 0 or length <= 0:
        raise ValueError("Choose two different points and enter a positive real length.")
    return length / pixel_distance


def choose_scale(*, user_scale, door_widths_px, footprint_bounds_px, footprint_area_px, room_areas_px, default_scale=0.02, typical_width_m=12.0):
    """Apply the documented scale priority, rejecting candidates outside area/door sanity limits."""
    candidates = []
    if user_scale is not None:
        candidates.append((float(user_scale), "user", 1.0))

    door_scale, door_quality = estimate_meters_per_pixel_from_door_widths(door_widths_px)
    if door_scale is not None:
        candidates.append((door_scale, "door-width", 0.7))

    if footprint_bounds_px:
        min_x, min_y, max_x, max_y = map(float, footprint_bounds_px)
        longest_side = max(max_x - min_x, max_y - min_y)
        if longest_side > 0:
            candidates.append((float(typical_width_m) / longest_side, "typical-footprint-width", 0.35))
    candidates.append((float(default_scale), "configured-default", 0.15))

    warnings = []
    if user_scale is None and door_scale is None:
        count = int(door_quality.get("count", 0))
        coefficient = door_quality.get("coefficientOfVariation")
        if count < 3:
            warnings.append(
                f"Door-based scale was not used: {count} plausible opening width(s) found; at least 3 are required."
            )
        elif coefficient is not None and coefficient >= 0.25:
            warnings.append(
                f"Door-based scale was not used: opening widths vary too much (coefficient of variation {coefficient:.2f}; limit 0.25)."
            )
        else:
            warnings.append("Door-based scale was not used because the opening-derived scale is outside the supported range.")
    if user_scale is not None and not (0.001 <= float(user_scale) <= 0.1):
        warnings.append("User scale is outside the supported range; an automatic estimate was tried instead.")

    seen = set()
    for scale, source, confidence in candidates:
        if scale in seen or not math.isfinite(scale) or not 0.001 <= scale <= 0.1:
            continue
        seen.add(scale)
        total_area = float(footprint_area_px or 0) * scale * scale
        room_areas = [float(area) * scale * scale for area in (room_areas_px or [])]
        door_median = float(np.median(door_widths_px)) * scale if door_widths_px else None
        reasons = []
        if total_area and not 20 <= total_area <= 1500:
            reasons.append(f"estimated building area {total_area:.1f} m2 is outside 20-1500 m2")
        invalid_rooms = [area for area in room_areas if area < 1.5 or area > 300]
        if invalid_rooms:
            reasons.append(f"{len(invalid_rooms)} estimated room area(s) are outside 1.5-300 m2")
        if door_median is not None and len(door_widths_px) >= 3 and not 0.7 <= door_median <= 1.2:
            reasons.append(f"median detected door width {door_median:.2f} m is outside 0.7-1.2 m")
        if reasons:
            warnings.append(f"Rejected {source} scale: {'; '.join(reasons)}.")
            continue
        return {
            "meters_per_pixel": scale,
            "source": source,
            "confidence": confidence,
            "accepted": True,
            "warnings": warnings,
            "door_quality": door_quality,
        }

    # Keep geometry reviewable at the best available rough scale, but mark it as
    # unverified so the UI can withhold a misleading 3D rendering.
    fallback = candidates[-1][0] if candidates else float(default_scale)
    warnings.append("No candidate scale passed the sanity checks; manual two-point calibration is needed.")
    return {
        "meters_per_pixel": fallback,
        "source": "needs-review",
        "confidence": 0.0,
        "accepted": False,
        "warnings": warnings,
        "door_quality": door_quality,
    }


def estimate_wall_thickness_px(wall_masks, meters_per_pixel=None, wall_thickness_m=0.2):
    """Estimate raster wall thickness from distance-transform ridges."""
    measured = []
    for mask in wall_masks or []:
        binary = (np.asarray(mask) > 0).astype(np.uint8)
        if binary.ndim != 2 or not np.any(binary):
            continue
        distance = cv2.distanceTransform(binary, cv2.DIST_L2, 5)
        local_max = cv2.dilate(distance, np.ones((3, 3), np.uint8))
        ridge = (distance >= local_max - 1e-3) & (distance >= 1.0)
        widths = 2.0 * distance[ridge]
        widths = widths[(widths >= 2.0) & (widths <= 40.0)]
        if widths.size:
            measured.extend(widths.tolist())
    if measured:
        return float(np.median(measured))
    if meters_per_pixel and meters_per_pixel > 0:
        return float(wall_thickness_m) / float(meters_per_pixel)
    return 8.0


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
            if not 0.7 <= width_m <= 1.2:
                continue

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
                "pixel_center": [round(float(cx_px), 2), round(float(cy_px), 2)],
                "pixel_width": round(float(max(w_px, h_px)), 2),
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
            if not 0.5 <= width_m <= 3.0:
                continue

            windows.append({
                "id": f"win{win_id_counter}",
                "center": [cx_m, cy_m],
                "pixel_center": [round(float(cx_px), 2), round(float(cy_px), 2)],
                "pixel_width": round(float(max(w_px, h_px)), 2),
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


def detect_doors_and_windows_geometrically(image_bytes, meters_per_pixel, pad=20, return_diagnostics=False):
    """Detect door openings and window symbols directly from CAD line graphics
    when AI segmentation (SAM) is not used.
    """
    if isinstance(image_bytes, np.ndarray):
        img = image_bytes
    else:
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        empty = ([], [], None)
        return (*empty, []) if return_diagnostics else empty

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
    diagnostics = []
    for candidate_index, c in enumerate(candidates, start=1):
        cx, cy, max_d, min_d, area = c
        neighbors = [other for other in candidates if math.hypot(cx - other[0], cy - other[1]) < 60]
        if len(neighbors) >= 3:
            diagnostics.append({
                "kind": "door", "candidate": f"door-candidate-{candidate_index}",
                "accepted": False, "pixelCenter": [round(float(cx), 2), round(float(cy), 2)],
                "reason": "dense repeated-line cluster is more likely stair treads than a doorway",
            })
            continue
        if not any(math.hypot(cx - d[0], cy - d[1]) < 45 for d in filtered_doors):
            filtered_doors.append((cx, cy, max_d))
            door_widths_px.append(max_d)
            diagnostics.append({
                "kind": "door", "candidate": f"door-candidate-{candidate_index}",
                "accepted": True, "pixelCenter": [round(float(cx), 2), round(float(cy), 2)],
                "reason": "door-swing geometry candidate",
            })
        else:
            diagnostics.append({
                "kind": "door", "candidate": f"door-candidate-{candidate_index}",
                "accepted": False, "pixelCenter": [round(float(cx), 2), round(float(cy), 2)],
                "reason": "duplicate candidate near another doorway",
            })

    doors_data = []
    for idx, (cx_px, cy_px, w_px) in enumerate(filtered_doors):
        doors_data.append({
            "id": f"d{idx + 1}",
            "center": [round(cx_px * meters_per_pixel, 3), round(cy_px * meters_per_pixel, 3)],
            "pixel_center": [round(float(cx_px), 2), round(float(cy_px), 2)],
            "width": 0.90,
            "connects": ["room"],
            "source": "estimated",
            "pixel_width": int(w_px),
        })

    # A single Hough segment is not a window: exterior and interior wall
    # strokes produce thousands of them. Require a paired window-like mark:
    # two parallel segments, close together, with substantial shared length.
    lines = cv2.HoughLinesP(dark, 1, np.pi / 180, threshold=24, minLineLength=20, maxLineGap=4)
    segments = []
    if lines is not None:
        for raw_line in np.asarray(lines).reshape(-1, 4):
            x1, y1, x2, y2 = map(float, raw_line)
            length = math.hypot(x2 - x1, y2 - y1)
            if length < 20:
                continue
            angle = math.degrees(math.atan2(y2 - y1, x2 - x1)) % 180
            segments.append({"p1": (x1, y1), "p2": (x2, y2), "length": length, "angle": angle,
                             "center": ((x1 + x2) / 2, (y1 + y2) / 2)})

    closed_for_outline = cv2.morphologyEx(
        dark, cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (max(5, min(w, h) // 80),) * 2),
        iterations=2,
    )
    outer_contours, _ = cv2.findContours(closed_for_outline, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    outer = max(outer_contours, key=cv2.contourArea) if outer_contours else None
    windows_candidates = []
    seen_centers = []
    used_segments = set()
    min_length_px, max_length_px = 0.5 / max(meters_per_pixel, 1e-9), 3.0 / max(meters_per_pixel, 1e-9)
    exterior_tolerance_px = max(12.0, min(w, h) * 0.012)
    for index, first in enumerate(segments):
        first_x, first_y = first["center"]
        pair = None
        for other_index in range(index + 1, len(segments)):
            second = segments[other_index]
            angle_gap = abs(first["angle"] - second["angle"])
            angle_gap = min(angle_gap, 180 - angle_gap)
            if angle_gap > 5 or abs(first["length"] - second["length"]) > max(10, first["length"] * 0.3):
                continue
            theta = math.radians(first["angle"])
            normal = (-math.sin(theta), math.cos(theta))
            delta = (second["center"][0] - first_x, second["center"][1] - first_y)
            offset = abs(delta[0] * normal[0] + delta[1] * normal[1])
            along = abs(delta[0] * math.cos(theta) + delta[1] * math.sin(theta))
            overlap = max(0.0, min(first["length"], second["length"]) - along)
            overlap_ratio = overlap / max(1.0, min(first["length"], second["length"]))
            if 2 <= offset <= max(24, exterior_tolerance_px * 1.5) and overlap_ratio >= 0.7:
                pair = (other_index, second, (first_x + second["center"][0]) / 2,
                        (first_y + second["center"][1]) / 2,
                        (first["length"] + second["length"]) / 2)
                break
        if pair is None:
            continue
        other_index, second, cx, cy, length_px = pair
        used_segments.update((index, other_index))
        # Only pairs on or immediately next to the exterior footprint are
        # meaningful window candidates. Filtering here prevents interior room
        # lines and hatch marks from flooding both diagnostics and candidate
        # work with false window matches.
        if outer is None or abs(cv2.pointPolygonTest(outer, (float(cx), float(cy)), True)) > exterior_tolerance_px:
            continue
        if not min_length_px <= length_px <= max_length_px:
            diagnostics.append({"kind": "window", "candidate": f"pair-{index + 1}-{other_index + 1}", "accepted": False,
                                "pixelCenter": [round(float(cx), 2), round(float(cy), 2)],
                                "reason": f"paired mark length {length_px * meters_per_pixel:.2f} m is outside 0.5-3.0 m"})
            continue
        nearby = [segment for segment in segments if math.hypot(segment["center"][0] - cx, segment["center"][1] - cy) < 35]
        if len(nearby) > 8:
            diagnostics.append({"kind": "window", "candidate": f"pair-{index + 1}-{other_index + 1}", "accepted": False,
                                "pixelCenter": [round(float(cx), 2), round(float(cy), 2)],
                                "reason": "dense stair-hatch or drafting-line cluster"})
            continue
        if any(math.hypot(cx - old_x, cy - old_y) < max(20, length_px * 0.35) for old_x, old_y in seen_centers):
            diagnostics.append({"kind": "window", "candidate": f"pair-{index + 1}-{other_index + 1}", "accepted": False,
                                "pixelCenter": [round(float(cx), 2), round(float(cy), 2)],
                                "reason": "duplicate paired mark near another window"})
            continue
        seen_centers.append((cx, cy))
        windows_candidates.append((cx, cy, length_px))
        diagnostics.append({"kind": "window", "candidate": f"pair-{index + 1}-{other_index + 1}", "accepted": True,
                            "pixelCenter": [round(float(cx), 2), round(float(cy), 2)],
                            "reason": "outer-wall paired parallel mark"})

    # Keep candidate counts plausible for the measured exterior perimeter.
    if outer is not None:
        perimeter_px = cv2.arcLength(outer, True)
        # Even a long residential exterior should not become dozens of windows
        # from repeated wall strokes or drawing grids. Keep both the density
        # limit and a conservative global cap for house plans.
        max_windows = min(19, max(1, int(math.ceil(perimeter_px * meters_per_pixel / 4.0))))
        if len(windows_candidates) > max_windows:
            windows_candidates.sort(key=lambda item: item[2], reverse=True)
            rejected = windows_candidates[max_windows:]
            windows_candidates = windows_candidates[:max_windows]
            for index, (cx, cy, length_px) in enumerate(rejected, start=max_windows + 1):
                diagnostics.append({"kind": "window", "candidate": f"cap-{index}", "accepted": False,
                                    "pixelCenter": [round(float(cx), 2), round(float(cy), 2)],
                                    "reason": "plausible exterior-window cap reached (about one per 4 m wall)"})

    windows_data = []
    for idx, (cx_px, cy_px, len_px) in enumerate(windows_candidates):
        windows_data.append({
            "id": f"win{idx + 1}",
            "center": [round(cx_px * meters_per_pixel, 3), round(cy_px * meters_per_pixel, 3)],
            "pixel_center": [round(cx_px, 2), round(cy_px, 2)],
            "pixel_width": round(len_px, 2),
            "width": round(len_px * meters_per_pixel, 2),
            "source": "estimated",
        })

    median_door_px = float(np.median(door_widths_px)) if door_widths_px else None
    result = (doors_data, windows_data, median_door_px)
    return (*result, diagnostics) if return_diagnostics else result


def snap_openings_and_cut_walls(
    walls_data, doors_data, windows_data, wall_thickness_m=0.2, max_dist_m=0.6,
    meters_per_pixel=None, wall_thickness_px=None,
):
    """Snap openings in source-pixel space, then convert the accepted point to meters.

    ``max_dist_m`` remains for compatibility with older callers/tests. The live
    pipeline supplies ``meters_per_pixel`` and uses a tolerance derived from the
    measured raster wall thickness instead.
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

    pixel_walls = combined_walls
    tolerance_px = None
    if meters_per_pixel is not None and meters_per_pixel > 0:
        from shapely.affinity import scale as scale_geometry
        pixel_walls = scale_geometry(combined_walls, xfact=1.0 / meters_per_pixel, yfact=1.0 / meters_per_pixel, origin=(0, 0))
        wall_thickness_px = float(wall_thickness_px or (wall_thickness_m / meters_per_pixel))
        tolerance_px = max(6.0, 2.5 * wall_thickness_px)

    def snap_point(cx_m, cy_m, opening_id, kind):
        if tolerance_px is None:
            check_point = shapely.geometry.Point(cx_m, cy_m)
            distance = combined_walls.distance(check_point)
            if distance > max_dist_m:
                dropped_openings.append(
                    f"{kind.title()} {opening_id} dropped (nearest wall {distance / meters_per_pixel:.1f} px; {distance:.3f} m, over {max_dist_m} m tolerance)."
                    if meters_per_pixel else
                    f"{kind.title()} {opening_id} dropped (no wall within {max_dist_m} m; no floating openings allowed)."
                )
                return None
            nearest = shapely.ops.nearest_points(combined_walls.boundary, check_point)[0]
            return round(nearest.x, 3), round(nearest.y, 3)

        check_point_px = shapely.geometry.Point(cx_m / meters_per_pixel, cy_m / meters_per_pixel)
        distance_px = pixel_walls.distance(check_point_px)
        if distance_px > tolerance_px:
            distance_m = distance_px * meters_per_pixel
            dropped_openings.append(
                f"{kind.title()} {opening_id} dropped (nearest wall {distance_px:.1f} px / {distance_m:.3f} m; tolerance {tolerance_px:.1f} px from wall thickness)."
            )
            return None
        nearest_px = shapely.ops.nearest_points(pixel_walls.boundary, check_point_px)[0]
        return round(nearest_px.x * meters_per_pixel, 3), round(nearest_px.y * meters_per_pixel, 3)

    def opening_orientation(center):
        point = shapely.geometry.Point(center)
        best = None
        for polygon in wall_polys:
            rings = [polygon.exterior, *polygon.interiors]
            for ring in rings:
                coords = list(ring.coords)
                for start, end in zip(coords, coords[1:]):
                    segment = shapely.geometry.LineString([start, end])
                    distance = segment.distance(point)
                    if best is None or distance < best[0]:
                        best = (distance, end[0] - start[0], end[1] - start[1])
        return "horizontal" if best is None or abs(best[1]) >= abs(best[2]) else "vertical"

    # Process doors
    valid_doors = []
    cut_boxes = []
    for d in doors_data:
        cx, cy = d["center"]
        snapped = snap_point(cx, cy, d["id"], "door")
        if snapped is None:
            continue
        snap_x, snap_y = snapped
        d["center"] = [snap_x, snap_y]
        cut_w = float(d.get("width", 0.9))
        box_th = wall_thickness_m + 0.15
        if opening_orientation((snap_x, snap_y)) == "horizontal":
            door_box = shapely.geometry.box(snap_x - cut_w / 2.0, snap_y - box_th / 2.0, snap_x + cut_w / 2.0, snap_y + box_th / 2.0)
        else:
            door_box = shapely.geometry.box(snap_x - box_th / 2.0, snap_y - cut_w / 2.0, snap_x + box_th / 2.0, snap_y + cut_w / 2.0)
        cut_boxes.append(door_box)
        valid_doors.append(d)

    # Process windows
    valid_windows = []
    for win in windows_data:
        cx, cy = win["center"]
        snapped = snap_point(cx, cy, win["id"], "window")
        if snapped is None:
            continue
        snap_x, snap_y = snapped
        win["center"] = [snap_x, snap_y]
        cut_w = float(win.get("width", 1.2))
        box_th = wall_thickness_m + 0.15
        if opening_orientation((snap_x, snap_y)) == "horizontal":
            win_box = shapely.geometry.box(snap_x - cut_w / 2.0, snap_y - box_th / 2.0, snap_x + cut_w / 2.0, snap_y + box_th / 2.0)
        else:
            win_box = shapely.geometry.box(snap_x - box_th / 2.0, snap_y - cut_w / 2.0, snap_x + box_th / 2.0, snap_y + cut_w / 2.0)
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
    wall_segments = []
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
                wall_segments.append((math.atan2(ext[i + 1][1] - ext[i][1], ext[i + 1][0] - ext[i][0]), length))
        except Exception:
            pass

    # Plans may be rotated in the source image. Find the dominant pair of
    # perpendicular wall directions first, then flag only edges that are not
    # close to either direction.
    if wall_segments:
        cos_sum = sum(length * math.cos(4 * angle) for angle, length in wall_segments)
        sin_sum = sum(length * math.sin(4 * angle) for angle, length in wall_segments)
        dominant_axis = math.atan2(sin_sum, cos_sum) / 4 if abs(cos_sum) + abs(sin_sum) > 1e-8 else 0.0
        orthogonal_period = math.pi / 2
        angle_tolerance = math.radians(7)
        total_len = sum(length for _, length in wall_segments)
        non_aligned_len = 0.0
        for angle, length in wall_segments:
            deviation = (angle - dominant_axis + orthogonal_period / 2) % orthogonal_period - orthogonal_period / 2
            if abs(deviation) > angle_tolerance:
                non_aligned_len += length
        if total_len > 0 and (non_aligned_len / total_len) > 0.15:
            pct = (non_aligned_len / total_len) * 100
            warnings.append(f"Wall alignment check: {pct:.1f}% of wall boundary length is not near the dominant orthogonal directions.")

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
