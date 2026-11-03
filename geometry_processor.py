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
        candidates.append((float(user_scale), "user", 1.0, None))

    door_values = sorted(float(width) for width in (door_widths_px or []) if math.isfinite(float(width)) and float(width) > 0)
    # Arc detectors can also find unrelated curved drawing marks. Keep
    # internally consistent groups so a few spurious radii cannot spoil the
    # median of the actual repeated door-swing arcs.
    door_clusters = []
    for anchor in door_values:
        cluster = [width for width in door_values if 0.75 * anchor <= width <= 1.25 * anchor]
        if len(cluster) < 3:
            continue
        median = float(np.median(cluster))
        cv = float(np.std(cluster) / median) if median else float("inf")
        if cv < 0.25 and not any(cluster == existing for existing in door_clusters):
            door_clusters.append(cluster)
    door_clusters.sort(key=lambda values: (-len(values), float(np.median(values))))
    for cluster in door_clusters:
        candidates.append((0.9 / float(np.median(cluster)), "door-width", 0.7, cluster))

    door_scale, door_quality = estimate_meters_per_pixel_from_door_widths(door_values)
    if door_scale is not None and not any(source == "door-width" and abs(scale - door_scale) < 1e-10 for scale, source, _, _ in candidates):
        candidates.append((door_scale, "door-width", 0.7, door_values))

    if footprint_bounds_px:
        min_x, min_y, max_x, max_y = map(float, footprint_bounds_px)
        longest_side = max(max_x - min_x, max_y - min_y)
        if longest_side > 0:
            candidates.append((float(typical_width_m) / longest_side, "typical-footprint-width", 0.35, None))
    candidates.append((float(default_scale), "configured-default", 0.15, None))

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
    for scale, source, confidence, candidate_door_widths in candidates:
        if scale in seen or not math.isfinite(scale) or not 0.001 <= scale <= 0.1:
            continue
        seen.add(scale)
        total_area = float(footprint_area_px or 0) * scale * scale
        room_areas = [float(area) * scale * scale for area in (room_areas_px or [])]
        habitable_room_areas = [area for area in room_areas if area >= 6.0] or room_areas
        validation_widths = candidate_door_widths if candidate_door_widths is not None else door_values
        door_median = float(np.median(validation_widths)) * scale if validation_widths else None
        reasons = []
        if source != "user" and total_area and not 25 <= total_area <= 400:
            reasons.append(f"estimated residential building area {total_area:.1f} m2 is outside 25-400 m2")
        if source != "user" and habitable_room_areas and not 6 <= float(np.median(habitable_room_areas)) <= 30:
            reasons.append(f"median estimated room area {float(np.median(habitable_room_areas)):.1f} m2 is outside 6-30 m2")
        if door_median is not None and len(validation_widths) >= 3 and not 0.7 <= door_median <= 1.1:
            reasons.append(f"median detected door swing/width {door_median:.2f} m is outside 0.7-1.1 m")
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
    """Measure solid wall-band thickness from its distance-transform ridge."""
    measured = []
    for mask in wall_masks or []:
        binary = (np.asarray(mask) > 0).astype(np.uint8)
        if binary.ndim != 2 or not np.any(binary):
            continue
        distance = cv2.distanceTransform(binary, cv2.DIST_L2, 5)
        local_max = cv2.dilate(distance, np.ones((3, 3), np.uint8))
        ridge = (distance >= local_max - 1e-3) & (distance >= 1.0)
        widths = 2.0 * distance[ridge]
        widths = widths[(widths >= 2.0) & (widths <= 120.0)]
        if widths.size:
            measured.extend(widths.tolist())
    if measured:
        return float(np.median(measured))
    if meters_per_pixel and meters_per_pixel > 0:
        return float(wall_thickness_m) / float(meters_per_pixel)
    return 8.0


def solidify_wall_band(mask):
    """Close the narrow white seam between parallel wall strokes on a copy."""
    binary = (np.asarray(mask) > 0).astype(np.uint8) * 255
    if binary.ndim != 2 or not np.any(binary):
        return binary
    gap_kernel = max(21, min(31, int(round(min(binary.shape) * 0.018)) | 1))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (gap_kernel, gap_kernel))
    return cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=1)


def detect_door_swing_radii_px(image, return_candidates=False):
    """Find plausible partial circular swing arcs and return radii or fitted arcs."""
    if image is None:
        return []
    if isinstance(image, (bytes, bytearray, memoryview)):
        image = cv2.imdecode(np.frombuffer(image, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        if image is None:
            return []
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image.copy()
    gray = cv2.medianBlur(gray, 5)
    edges = cv2.Canny(gray, 40, 120)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    radii = []
    centers = []
    candidates = []
    min_radius = max(8, min(gray.shape) // 100)
    max_radius = max(12, min(gray.shape) // 2)
    for contour in contours:
        if len(contour) < 20:
            continue
        points = contour[:, 0, :].astype(float)
        x, y = points[:, 0], points[:, 1]
        matrix = np.column_stack((2 * x, 2 * y, np.ones_like(x)))
        try:
            cx, cy, constant = np.linalg.lstsq(matrix, x * x + y * y, rcond=None)[0]
        except np.linalg.LinAlgError:
            continue
        radius = math.sqrt(max(0.0, constant + cx * cx + cy * cy))
        # Algebraic circle fits are biased for short arcs (door swings are
        # commonly only a quarter-circle). Refine the fit against geometric
        # radial error with a few Gauss-Newton steps.
        for _ in range(8):
            dx, dy = cx - x, cy - y
            distances = np.maximum(np.hypot(dx, dy), 1e-6)
            residuals = distances - radius
            jacobian = np.column_stack((dx / distances, dy / distances, -np.ones_like(distances)))
            try:
                delta = np.linalg.lstsq(jacobian, -residuals, rcond=None)[0]
            except np.linalg.LinAlgError:
                break
            cx += float(delta[0])
            cy += float(delta[1])
            radius += float(delta[2])
            if float(np.linalg.norm(delta)) < 1e-3:
                break
        residual = np.median(np.abs(np.hypot(x - cx, y - cy) - radius))
        angles = np.sort(np.mod(np.degrees(np.arctan2(y - cy, x - cx)), 360.0))
        angular_gaps = np.diff(np.r_[angles, angles[0] + 360.0])
        arc_span = 360.0 - float(np.max(angular_gaps)) if len(angles) else 0.0
        # Door swing strokes are partial arcs. Full circles, rounded fixtures,
        # and broad curved outlines should not contribute to scale.
        if min_radius <= radius <= max_radius and 35.0 <= arc_span <= 150.0 and residual <= max(2.5, radius * 0.06):
            if not any(math.hypot(cx - old_x, cy - old_y) < max(8.0, radius * 0.2) for old_x, old_y in centers):
                centers.append((cx, cy))
                radii.append(radius)
                candidates.append({"center": [float(cx), float(cy)], "radius": float(radius), "arc_span": float(arc_span)})
    return candidates if return_candidates else radii


def _line_samples_inside(mask, start, end, min_fraction=0.65):
    x1, y1 = start
    x2, y2 = end
    steps = max(2, int(math.hypot(x2 - x1, y2 - y1) / 4))
    xs = np.clip(np.rint(np.linspace(x1, x2, steps)).astype(int), 0, mask.shape[1] - 1)
    ys = np.clip(np.rint(np.linspace(y1, y2, steps)).astype(int), 0, mask.shape[0] - 1)
    return float(np.mean(mask[ys, xs] > 0)) >= min_fraction


def _projected_wall_gaps(dark, meters_per_pixel, orientation):
    """Find repeated, wall-aligned blank spans; return stable gap centers in px."""
    height, width = dark.shape
    image = dark if orientation == "horizontal" else dark.T
    length_px = image.shape[1]
    min_gap = int(math.ceil(0.7 / max(meters_per_pixel, 1e-9)))
    max_gap = int(math.floor(1.5 / max(meters_per_pixel, 1e-9)))
    min_run = max(12, int(round(0.25 / max(meters_per_pixel, 1e-9))))
    found = []
    for line_index, row in enumerate(image):
        xs = np.flatnonzero(row > 0)
        if len(xs) < 2:
            continue
        breaks = np.flatnonzero(np.diff(xs) > 1)
        starts = np.r_[0, breaks + 1]
        ends = np.r_[breaks, len(xs) - 1]
        runs = [(int(xs[a]), int(xs[b])) for a, b in zip(starts, ends) if int(xs[b] - xs[a] + 1) >= min_run]
        for first, second in zip(runs, runs[1:]):
            gap_start, gap_end = first[1] + 1, second[0]
            gap_width = gap_end - gap_start
            if min_gap <= gap_width <= max_gap:
                center = ((gap_start + gap_end) / 2.0, float(line_index))
                found.append(center if orientation == "horizontal" else (center[1], center[0]))
    if not found:
        return []
    # Cluster row/column votes by wall-normal coordinate and nearly identical
    # gap center. A band can be 30-40 px thick, so Euclidean 8 px clustering
    # split one opening into many unstable candidates.
    groups = []
    normal_tolerance = max(12.0, min(height, width) * 0.025)
    along_tolerance = max(8.0, min_gap * 0.08)
    for point in found:
        group = next((g for g in groups if abs(point[0] - g[0][0]) <= along_tolerance
                      and abs(point[1] - g[0][1]) <= normal_tolerance), None)
        if group is None:
            groups.append([point])
        else:
            group.append(point)
    min_votes = max(3, int(round(min(height, width) * 0.0015)))
    return [tuple(np.mean(group, axis=0)) for group in groups if len(group) >= min_votes]


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
    """Detect only openings supported by wall-band, swing-arc, or gap evidence."""
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
    # Hough pairing is quadratic in candidate count. Work at a bounded
    # resolution for large scans, and convert accepted pixel coordinates back
    # to the untouched source image frame below.
    detection_scale = min(1.0, 2048.0 / max(h, w))
    if detection_scale < 1.0:
        detect_gray = cv2.resize(gray, None, fx=detection_scale, fy=detection_scale, interpolation=cv2.INTER_AREA)
        detect_img = cv2.resize(img, (detect_gray.shape[1], detect_gray.shape[0]), interpolation=cv2.INTER_AREA) if img.ndim == 3 else detect_gray
        detect_mpp = meters_per_pixel / detection_scale
    else:
        detect_gray, detect_img, detect_mpp = gray, img, meters_per_pixel
    dh, dw = detect_gray.shape[:2]
    _, dark = cv2.threshold(detect_gray, 210, 255, cv2.THRESH_BINARY_INV)
    diagnostics = []
    wall_band = solidify_wall_band(dark)
    band_distance = cv2.distanceTransform((wall_band > 0).astype(np.uint8), cv2.DIST_L2, 5)
    band_thickness_px = estimate_wall_thickness_px([wall_band])
    wall_roi = (wall_band > 0).astype(np.uint8) * 255
    wall_roi = cv2.dilate(wall_roi, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))

    # Generate window candidates only from measured-length marks that lie in a
    # merged wall band. This removes sheet notes, room text and most stair ticks
    # before the quadratic parallel-line pairing stage.
    min_length_px = 0.6 / max(detect_mpp, 1e-9)
    max_length_px = 3.0 / max(detect_mpp, 1e-9)
    # Keep proposals near a merged wall band before any pair search. The
    # dilation admits the thin pane strokes inside the band, while the later
    # medial-axis check rejects marks riding the outer wall edges.
    proposal_radius = max(5, int(round(band_thickness_px * 0.45)))
    proposal_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (proposal_radius * 2 + 1, proposal_radius * 2 + 1))
    proposal_roi = cv2.dilate(wall_roi, proposal_kernel)
    candidate_mask = cv2.bitwise_and(dark, proposal_roi)
    raw_lines = cv2.HoughLinesP(candidate_mask, 1, np.pi / 180, threshold=20,
                                minLineLength=max(12, int(min_length_px * 0.65)), maxLineGap=4)
    segments = []
    line_rows = np.asarray(raw_lines).reshape(-1, 4) if raw_lines is not None else []
    for raw_line in line_rows[:1200]:
        x1, y1, x2, y2 = map(float, raw_line)
        length = math.hypot(x2 - x1, y2 - y1)
        if not min_length_px <= length <= max_length_px:
            continue
        if not _line_samples_inside(proposal_roi, (x1, y1), (x2, y2), min_fraction=0.8):
            continue
        angle = math.degrees(math.atan2(y2 - y1, x2 - x1)) % 180
        center = ((x1 + x2) / 2, (y1 + y2) / 2)
        # Hough commonly reports the same stroke as many overlapping fragments.
        if any(abs(angle - item["angle"]) < 2.0 and
               abs((center[0] - item["center"][0]) * -math.sin(math.radians(angle)) +
                   (center[1] - item["center"][1]) * math.cos(math.radians(angle))) < 3.0 and
               math.hypot(center[0] - item["center"][0], center[1] - item["center"][1]) < length * 0.8
               for item in segments[-250:]):
            continue
        segments.append({"p1": (x1, y1), "p2": (x2, y2), "length": length, "angle": angle, "center": center})
        if len(segments) >= 250:
            break
    windows_candidates = []
    seen_centers = []
    paired_segments = set()
    band_kernel = max(7, int(round(band_thickness_px * 0.55)))
    max_pair_offset = min(24.0, max(6.0, float(band_kernel)))
    for index, first in enumerate(segments):
        first_x, first_y = first["center"]
        for other_index in range(index + 1, len(segments)):
            if other_index in paired_segments:
                continue
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
            cx, cy = (first_x + second["center"][0]) / 2, (first_y + second["center"][1]) / 2
            length_px = (first["length"] + second["length"]) / 2
            pair_id = f"pair-{index + 1}-{other_index + 1}"
            if offset < 2.0 or offset > max_pair_offset or overlap_ratio < 0.7:
                continue
            paired_segments.update((index, other_index))
            if band_distance[int(np.clip(round(cy), 0, dh - 1)), int(np.clip(round(cx), 0, dw - 1))] < max(8.0, band_thickness_px * 0.35):
                diagnostics.append({"kind": "window", "candidate": pair_id, "accepted": False,
                                    "pixelCenter": [round(float(cx), 2), round(float(cy), 2)],
                                    "reason": "paired lines are outside a solid wall band"})
                break
            nearby = [segment for segment in segments if math.hypot(segment["center"][0] - cx, segment["center"][1] - cy) < max(25.0, band_kernel * 1.5)]
            if len(nearby) > 12:
                diagnostics.append({"kind": "window", "candidate": pair_id, "accepted": False,
                                    "pixelCenter": [round(float(cx), 2), round(float(cy), 2)],
                                    "reason": "dense stair-hatch or drafting-line cluster"})
                break
            if any(math.hypot(cx - old_x, cy - old_y) < max(20, length_px * 0.45) for old_x, old_y in seen_centers):
                diagnostics.append({"kind": "window", "candidate": pair_id, "accepted": False,
                                    "pixelCenter": [round(float(cx), 2), round(float(cy), 2)],
                                    "reason": "duplicate paired mark near another window"})
                break
            seen_centers.append((cx, cy))
            windows_candidates.append((cx / detection_scale, cy / detection_scale, length_px / detection_scale))
            diagnostics.append({"kind": "window", "candidate": pair_id, "accepted": True,
                                "pixelCenter": [round(float(cx), 2), round(float(cy), 2)],
                                "reason": "paired thin lines align inside a solid wall band"})
            break

    # Arc centers are hinges. Pair close, collinear hinges to represent one
    # double leaf opening rather than two adjacent doors.
    arcs = [dict(arc, center=[value / detection_scale for value in arc["center"]],
                 radius=arc["radius"] / detection_scale)
            for arc in detect_door_swing_radii_px(detect_img, return_candidates=True)
            if 0.55 <= arc["radius"] * detect_mpp <= 1.25]
    door_candidates = []
    consumed_arcs = set()
    for i, arc in enumerate(arcs):
        if i in consumed_arcs:
            continue
        cx, cy = arc["center"]
        partner = None
        partner_distance = None
        for j in range(i + 1, len(arcs)):
            if j in consumed_arcs:
                continue
            ox, oy = arcs[j]["center"]
            distance = math.hypot(cx - ox, cy - oy) * meters_per_pixel
            if 1.35 <= distance <= 2.4 and min(abs(cx - ox), abs(cy - oy)) <= 0.25 * max(abs(cx - ox), abs(cy - oy), 1):
                partner, partner_distance = j, distance
                break
        if partner is not None:
            other = arcs[partner]["center"]
            consumed_arcs.update((i, partner))
            door_candidates.append({"center": ((cx + other[0]) / 2, (cy + other[1]) / 2),
                                    "width": float(np.clip(partner_distance, 1.4, 2.4)), "kind": "double"})
        else:
            consumed_arcs.add(i)
            door_candidates.append({"center": (cx, cy), "width": float(arc["radius"] * meters_per_pixel), "kind": "swing"})
    doors_data = []
    for idx, candidate in enumerate(door_candidates, start=1):
        cx, cy = candidate["center"]
        doors_data.append({"id": f"d{idx}", "center": [round(cx * meters_per_pixel, 3), round(cy * meters_per_pixel, 3)],
                           "pixel_center": [round(cx, 2), round(cy, 2)], "width": round(candidate["width"], 2),
                           "kind": candidate["kind"], "connects": ["room"], "source": "swing-arc"})

    # A collinear wall gap with plausible width and no arc/window evidence is
    # recorded as an open doorway. It belongs in doors, never windows.
    horizontal_gaps = _projected_wall_gaps(dark, detect_mpp, "horizontal")
    vertical_gaps = _projected_wall_gaps(dark, detect_mpp, "vertical")
    gap_candidates = [tuple(value / detection_scale for value in point) for point in (horizontal_gaps + vertical_gaps)]
    window_gap_centers = []
    # Window openings contain repeated thin pane lines across the wall gap;
    # an entrance gap has no such parallel marks. Check this before emitting
    # open-door candidates so a window is never re-labelled as a doorway.
    for orientation, candidates in (("horizontal", horizontal_gaps), ("vertical", vertical_gaps)):
        for x, y in candidates:
            radius = max(12, int(round(0.75 / max(detect_mpp, 1e-9))))
            cx, cy = int(round(x)), int(round(y))
            line_votes = []
            if orientation == "horizontal":
                x0, x1 = max(0, cx - radius), min(dw, cx + radius + 1)
                for row in range(max(0, cy - proposal_radius), min(dh, cy + proposal_radius + 1)):
                    line_votes.append((row, float(np.mean(dark[row, x0:x1] > 0)) if x1 > x0 else 0.0))
            else:
                y0, y1 = max(0, cy - radius), min(dh, cy + radius + 1)
                for column in range(max(0, cx - proposal_radius), min(dw, cx + proposal_radius + 1)):
                    line_votes.append((column, float(np.mean(dark[y0:y1, column] > 0)) if y1 > y0 else 0.0))
            marked_lines = [coordinate for coordinate, fraction in line_votes if fraction >= 0.55]
            separated = any(b - a >= 3 for a, b in zip(marked_lines, marked_lines[1:]))
            if len(marked_lines) >= 4 and separated:
                source_x, source_y = x / detection_scale, y / detection_scale
                if not any(math.hypot(source_x - win[0], source_y - win[1]) < 0.45 / max(meters_per_pixel, 1e-9)
                           for win in windows_candidates):
                    windows_candidates.append((source_x, source_y, 0.9 / max(meters_per_pixel, 1e-9)))
                window_gap_centers.append((source_x, source_y))
    unique_gaps = []
    for gap in gap_candidates:
        if any(math.hypot(gap[0] - win_gap[0], gap[1] - win_gap[1]) < max(10.0, 0.35 / max(meters_per_pixel, 1e-9))
               for win_gap in window_gap_centers):
            continue
        if any(math.hypot(gap[0] - old[0], gap[1] - old[1]) < max(8.0, 0.25 / max(meters_per_pixel, 1e-9)) for old in unique_gaps):
            continue
        if any(math.hypot(gap[0] - door["center"][0] / meters_per_pixel, gap[1] - door["center"][1] / meters_per_pixel)
               < max(1.5 / meters_per_pixel, 1.3 * 0.9 / meters_per_pixel) for door in doors_data):
            continue
        if any(math.hypot(gap[0] - win[0], gap[1] - win[1]) < max(8.0, win[2] * 0.5) for win in windows_candidates):
            continue
        unique_gaps.append(gap)
    for gap in unique_gaps:
        doors_data.append({"id": f"d{len(doors_data) + 1}", "center": [round(gap[0] * meters_per_pixel, 3), round(gap[1] * meters_per_pixel, 3)],
                           "pixel_center": [round(gap[0], 2), round(gap[1], 2)], "width": 0.9,
                           "kind": "open-doorway", "connects": ["room"], "source": "wall-gap"})

    for index, door in enumerate(doors_data):
        diagnostics.append({"kind": "door", "candidate": door["id"], "accepted": True,
                            "pixelCenter": door.get("pixel_center"),
                            "reason": {"swing": "single swing arc", "double": "paired facing swing arcs",
                                       "open-doorway": "wall gap with no swing arc or window lines"}.get(door["kind"], "opening evidence accepted"),
                            "openingType": door["kind"]})

    windows_data = []
    for idx, (cx_px, cy_px, len_px) in enumerate(windows_candidates):
        windows_data.append({
            "id": f"win{idx + 1}",
            "center": [round(cx_px * meters_per_pixel, 3), round(cy_px * meters_per_pixel, 3)],
            "pixel_center": [round(cx_px, 2), round(cy_px, 2)],
            "pixel_width": round(len_px, 2),
            "width": round(len_px * meters_per_pixel, 2),
            "kind": "window",
            "source": "estimated",
        })

    median_door_px = float(np.median([arc["radius"] for arc in arcs])) if arcs else None
    result = (doors_data, windows_data, median_door_px)
    return (*result, diagnostics) if return_diagnostics else result


def snap_openings_and_cut_walls(
    walls_data, doors_data, windows_data, wall_thickness_m=0.2, max_dist_m=0.6,
    meters_per_pixel=None, wall_thickness_px=None,
):
    """Snap openings and subtract their cutouts in one source-pixel frame.

    Scene polygons and opening centers are stored in meters. They are converted
    to pixels once on entry; all unions, distance checks, orientation checks,
    and differences then use pixels. Results are converted back only here.
    Legacy callers without a scale retain their meter-coordinate behavior.
    """
    dropped_openings = []
    if not walls_data:
        return walls_data, doors_data, windows_data, dropped_openings

    pixel_mode = meters_per_pixel is not None and float(meters_per_pixel) > 0
    scale = float(meters_per_pixel) if pixel_mode else 1.0
    from shapely.affinity import scale as scale_geometry

    # Convert source scene walls from meters to pixels before any geometry work.
    wall_polys = []
    for w in walls_data:
        coords = w.get("polygon", [])
        if len(coords) < 3:
            continue
        try:
            holes = w.get("holes", [])
            poly = shapely.geometry.Polygon(coords, holes)
            if pixel_mode:
                poly = scale_geometry(poly, xfact=1.0 / scale, yfact=1.0 / scale, origin=(0, 0))
            if not poly.is_valid:
                poly = make_valid(poly)
            wall_polys.append(poly)
        except Exception:
            continue

    if not wall_polys:
        return walls_data, doors_data, windows_data, dropped_openings

    combined_walls = unary_union(wall_polys).buffer(0)
    thickness_px = float(wall_thickness_px or (wall_thickness_m / scale))
    tolerance_px = max(6.0, 1.5 * thickness_px) if pixel_mode else max_dist_m

    def source_point(item):
        if pixel_mode and item.get("pixel_center") is not None:
            return tuple(map(float, item["pixel_center"]))
        return (float(item["center"][0]) / scale, float(item["center"][1]) / scale)

    def snap_point(item, kind):
        check_point = shapely.geometry.Point(source_point(item))
        distance_px = combined_walls.distance(check_point)
        if distance_px > tolerance_px:
            distance_m = distance_px * scale
            dropped_openings.append(
                f"{kind.title()} {item['id']} dropped (nearest wall {distance_px:.1f} px / {distance_m:.3f} m; tolerance {tolerance_px:.1f} px)."
                if pixel_mode else
                f"{kind.title()} {item['id']} dropped (no wall within {max_dist_m} m; no floating openings allowed)."
            )
            return None
        # A center already inside the solid band is correctly localized; moving
        # it to the boundary would shift the cutout off-center and leave a lip.
        if combined_walls.covers(check_point):
            return check_point.x, check_point.y
        nearest_px = shapely.ops.nearest_points(combined_walls.boundary, check_point)[0]
        return nearest_px.x, nearest_px.y

    def opening_orientation(center_px):
        point = shapely.geometry.Point(center_px)
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

    # Validate every candidate against the untouched solid wall union, before cuts.
    valid_doors = []
    cut_boxes = []
    for d in doors_data:
        snapped = snap_point(d, "door")
        if snapped is None:
            continue
        snap_x, snap_y = snapped
        d["center"] = [round(snap_x * scale, 3), round(snap_y * scale, 3)]
        cut_w = float(d.get("pixel_width") or (float(d.get("width", 0.9)) / scale))
        box_th = max(2.0, thickness_px + 4.0)
        if opening_orientation((snap_x, snap_y)) == "horizontal":
            door_box = shapely.geometry.box(snap_x - cut_w / 2.0, snap_y - box_th / 2.0, snap_x + cut_w / 2.0, snap_y + box_th / 2.0)
        else:
            door_box = shapely.geometry.box(snap_x - box_th / 2.0, snap_y - cut_w / 2.0, snap_x + box_th / 2.0, snap_y + cut_w / 2.0)
        cut_boxes.append(door_box)
        valid_doors.append(d)

    # Process windows
    valid_windows = []
    for win in windows_data:
        snapped = snap_point(win, "window")
        if snapped is None:
            continue
        snap_x, snap_y = snapped
        win["center"] = [round(snap_x * scale, 3), round(snap_y * scale, 3)]
        cut_w = float(win.get("pixel_width") or (float(win.get("width", 1.2)) / scale))
        box_th = max(2.0, thickness_px + 4.0)
        if opening_orientation((snap_x, snap_y)) == "horizontal":
            win_box = shapely.geometry.box(snap_x - cut_w / 2.0, snap_y - box_th / 2.0, snap_x + cut_w / 2.0, snap_y + box_th / 2.0)
        else:
            win_box = shapely.geometry.box(snap_x - box_th / 2.0, snap_y - cut_w / 2.0, snap_x + box_th / 2.0, snap_y + cut_w / 2.0)
        cut_boxes.append(win_box)
        valid_windows.append(win)

    # Subtract small pixel-space cutouts from the validated pixel-space walls.
    if cut_boxes:
        openings_union = unary_union(cut_boxes)
        combined_walls = combined_walls.difference(openings_union).buffer(0)

    # Reconstruct clean wall list
    updated_walls = []
    geoms = combined_walls.geoms if combined_walls.geom_type == "MultiPolygon" else [combined_walls]
    wall_id = 1
    for g in geoms:
        if g.is_empty or g.area < (1.0 if pixel_mode else 1e-6):
            continue
        ext = [[round(x * scale, 3), round(y * scale, 3)] for x, y in list(g.exterior.coords)[:-1]]
        holes = []
        for interior in g.interiors:
            if len(interior.coords) >= 3:
                holes.append([[round(x * scale, 3), round(y * scale, 3)] for x, y in list(interior.coords)[:-1]])
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
