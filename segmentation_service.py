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
    kernel_size = prepared["kernel_size"]

    if concept == "wall":
        return [walls] if cv2.countNonZero(walls) else []

    if concept == "room":
        # Close likely door gaps before extracting enclosed room regions.
        close_kernel = cv2.getStructuringElement(
            cv2.MORPH_RECT, (kernel_size * 7, kernel_size * 7)
        )
        closed = cv2.morphologyEx(walls, cv2.MORPH_CLOSE, close_kernel, iterations=2)
        free = cv2.bitwise_not(closed)
        count, labels, stats, _ = cv2.connectedComponentsWithStats(free, 8)
        border_labels = set(
            np.unique(np.concatenate((labels[0], labels[-1], labels[:, 0], labels[:, -1])))
        )
        min_area = max(100, int(width * height * 0.002))
        masks = []
        for index in range(1, count):
            if index in border_labels or stats[index, cv2.CC_STAT_AREA] < min_area:
                continue
            masks.append(np.where(labels == index, 255, 0).astype(np.uint8))
        return masks

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
