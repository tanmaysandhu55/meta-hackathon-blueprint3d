"""Local OpenCV heuristics for floor-plan room and opening segmentation."""

import cv2
import numpy as np


def prepare_segmentation(image_bytes, image_size):
    """Decode and preprocess an image once for the parallel concept workers."""
    width, height = map(int, image_size)
    if width <= 0 or height <= 0:
        raise ValueError("Floor plan image dimensions must be positive.")

    if isinstance(image_bytes, np.ndarray):
        color = image_bytes
        if color.ndim == 2:
            gray = color
            color = cv2.cvtColor(color, cv2.COLOR_GRAY2BGR)
        elif color.ndim == 3 and color.shape[2] == 4:
            gray = cv2.cvtColor(color, cv2.COLOR_BGRA2GRAY)
            color = cv2.cvtColor(color, cv2.COLOR_BGRA2BGR)
        elif color.ndim == 3 and color.shape[2] == 3:
            gray = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)
        else:
            raise ValueError("Floor plan image is empty or invalid.")
    else:
        encoded = np.frombuffer(image_bytes, dtype=np.uint8)
        color = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        if color is None:
            raise ValueError("Could not decode floor plan image for local segmentation.")
        gray = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)

    if gray.ndim != 2 or not gray.size:
        raise ValueError("Floor plan image is empty or invalid.")
    if gray.shape != (height, width):
        gray = cv2.resize(gray, (width, height), interpolation=cv2.INTER_AREA)
        color = cv2.resize(color, (width, height), interpolation=cv2.INTER_AREA)

    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    _, otsu = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    adaptive = cv2.adaptiveThreshold(
        blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 9
    )
    dark = cv2.bitwise_or(otsu, adaptive)
    kernel_size = max(3, int(round(min(width, height) / 250)) | 1)
    wall_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT, (kernel_size * 3, kernel_size * 3)
    )
    walls = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, wall_kernel, iterations=2)
    walls = cv2.morphologyEx(
        walls,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_size, kernel_size)),
    )
    return {
        "width": width,
        "height": height,
        "kernel_size": kernel_size,
        "walls": walls,
        # Keep the unclosed line drawing for measuring wall stroke thickness;
        # the connected wall mask above is intentionally morphologically filled.
        "dark": dark,
        "hsv": cv2.cvtColor(color, cv2.COLOR_BGR2HSV),
    }


def _component_masks(binary, min_area, max_area=None):
    count, labels, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
    masks = []
    for index in range(1, count):
        area = int(stats[index, cv2.CC_STAT_AREA])
        if area < min_area or (max_area is not None and area > max_area):
            continue
        masks.append(np.where(labels == index, 255, 0).astype(np.uint8))
    return masks


def segment_prepared_concept(prepared, concept):
    """Extract one concept from the preprocessed image without decoding it again."""
    width = prepared["width"]
    height = prepared["height"]
    walls = prepared["walls"]

    if concept == "wall":
        return [walls] if cv2.countNonZero(walls) else []

    if concept == "room":
        min_area = max(100, int(width * height * 0.002))
        max_area = int(width * height * 0.75)

        def enclosed_regions(closed_walls):
            free = cv2.bitwise_not(closed_walls)
            count, labels, stats, _ = cv2.connectedComponentsWithStats(free, 8)
            border_labels = set(
                np.unique(np.concatenate((labels[0], labels[-1], labels[:, 0], labels[:, -1])))
            )
            masks = []
            for index in range(1, count):
                area = int(stats[index, cv2.CC_STAT_AREA])
                if index in border_labels or area < min_area or area > max_area:
                    continue
                masks.append(np.where(labels == index, 255, 0).astype(np.uint8))
            return masks

        # Door swings leave openings of very different sizes in scanned and
        # generated plans. One aggressive close can merge several rooms into a
        # single region; evaluate a scale range and prefer stable region counts,
        # while rejecting candidates dominated by one leaking region.
        shorter_side = min(width, height)
        fractions = (0.008, 0.012, 0.016, 0.020, 0.024, 0.028, 0.032, 0.040,
                     0.050, 0.060, 0.080, 0.100, 0.120, 0.140)
        kernel_sizes = sorted({max(3, int(round(shorter_side * fraction)) | 1) for fraction in fractions})
        candidates = []
        for close_size in kernel_sizes:
            adaptive_kernel = cv2.getStructuringElement(
                cv2.MORPH_RECT, (close_size, close_size)
            )
            candidate_closed = cv2.morphologyEx(walls, cv2.MORPH_CLOSE, adaptive_kernel, iterations=1)
            candidate_masks = enclosed_regions(candidate_closed)
            areas = [cv2.countNonZero(mask) for mask in candidate_masks]
            total_area = sum(areas)
            largest_share = max(areas, default=0) / max(total_area, 1)
            # A tiny collection of door-swing slivers can look like several
            # "stable" components at small kernels. Keep candidates that cover
            # a meaningful part of the image and are not dominated by one
            # leaking room. This is especially important on split multi-floor
            # uploads, where a stair hatch otherwise wins the count-only score.
            coverage = total_area / max(width * height, 1)
            if candidate_masks and coverage >= 0.10 and largest_share <= 0.68:
                candidates.append({
                    "kernel_size": close_size,
                    "masks": candidate_masks,
                    "count": len(candidate_masks),
                    "largest_share": largest_share,
                    "coverage": coverage,
                    "areas": sorted(areas, reverse=True),
                })

        if not candidates:
            return []

        # Repeated counts across nearby kernel sizes are a stability signal.
        for candidate in candidates:
            support = sum(
                other["count"] == candidate["count"]
                and abs(other["kernel_size"] - candidate["kernel_size"]) <= max(4, shorter_side * 0.025)
                for other in candidates
            )
            # Prefer stable, well-distributed interior regions. Coverage is a
            # modest tie-breaker rather than a goal by itself so a merged
            # whole-building component cannot beat several rooms.
            candidate["score"] = (
                candidate["count"]
                + 1.5 * support
                + min(candidate["coverage"], 0.75)
                - candidate["largest_share"]
            )

        best = max(candidates, key=lambda item: (item["score"], item["count"], -item["largest_share"], -item["kernel_size"]))
        if best["count"] > 1:
            prepared["adaptive_room_closing"] = {
                "kernel_size": best["kernel_size"],
                "room_count": best["count"],
                "stability_score": round(float(best["score"]), 3),
                "coverage": round(float(best["coverage"]), 4),
                "component_areas_px": best["areas"],
            }
        return best["masks"]

    if concept in ("door", "window"):
        # Prepared plans mark these details with colored drafting lines.
        if concept == "door":
            lower = np.array([3, 65, 70])
            upper = np.array([28, 255, 255])
        else:
            lower = np.array([88, 45, 70])
            upper = np.array([140, 255, 255])
        candidate = cv2.inRange(prepared["hsv"], lower, upper)
        candidate = cv2.morphologyEx(
            candidate,
            cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)),
        )
        min_area = max(5, int(width * height * 0.000008))
        max_area = int(width * height * 0.015)
        return _component_masks(candidate, min_area, max_area)

    raise ValueError(f"Unknown segmentation concept: {concept}")


def segment_concept(image_bytes, concept, image_size):
    """Return binary uint8 masks at original image dimensions (width, height)."""
    return segment_prepared_concept(prepare_segmentation(image_bytes, image_size), concept)
