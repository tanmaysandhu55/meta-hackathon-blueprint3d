"""
FloorPlan3D - SAM 3.1 & Model Gateway
Routes inference requests through partner cloud endpoints:
1. SAM 3.1 Image Segmentation -> Baseten API Endpoint (BASETEN_API_KEY)
2. Meta Llama 3 Text/NLP Generation -> Fireworks API Endpoint (FIREWORKS_API_KEY)
3. Meta Muse Spark -> Modal Serverless Endpoint (MODAL_API_KEY)
"""

import cv2
import numpy as np

from cloud_services import (
    get_baseten_config,
    is_mock_sam_enabled,
    is_sam_replay_enabled,
    query_baseten_sam,
    label_rooms_with_modal_muse_spark
)
from demo_data import get_sample_scene_json


def _mock_masks(concept, image_size):
    """Build deterministic binary masks from the prepared sample scene."""
    width, height = image_size
    scene = get_sample_scene_json()
    base_width, base_height = scene["meta"]["imageSize"]
    scale_x, scale_y = width / base_width, height / base_height
    scene_scale = scene["meta"]["metersPerPixel"]
    collection = {"room": "rooms", "wall": "walls", "door": "doors", "window": "windows"}.get(concept)
    if not collection:
        return []

    masks = []
    for item in scene.get(collection, []):
        mask = np.zeros((height, width), dtype=np.uint8)
        if concept in ("room", "wall"):
            polygon = item.get("polygon", [])
            if len(polygon) < 3:
                continue
            points = np.array([[round(x / scene_scale * scale_x),
                                round(y / scene_scale * scale_y)]
                               for x, y in polygon], dtype=np.int32)
            cv2.fillPoly(mask, [points], 255)
            for hole in item.get("holes", []):
                hole_points = np.array([[round(x / scene_scale * scale_x),
                                         round(y / scene_scale * scale_y)]
                                        for x, y in hole], dtype=np.int32)
                cv2.fillPoly(mask, [hole_points], 0)
        else:
            center = item.get("center", [0, 0])
            cx = round(center[0] / scene_scale * scale_x)
            cy = round(center[1] / scene_scale * scale_y)
            long_axis = max(8, round(float(item.get("width", 0.9)) / scene_scale * min(scale_x, scale_y)))
            thickness = max(4, round(0.2 / scene_scale * min(scale_x, scale_y)))
            nearest_wall = min(scene.get("walls", []), key=lambda wall: (
                sum(point[0] for point in wall.get("polygon", [])) / max(1, len(wall.get("polygon", []))) - center[0]
            ) ** 2 + (
                sum(point[1] for point in wall.get("polygon", [])) / max(1, len(wall.get("polygon", []))) - center[1]
            ) ** 2, default=None)
            wall_polygon = nearest_wall.get("polygon", []) if nearest_wall else []
            is_vertical = bool(wall_polygon) and (
                max(point[1] for point in wall_polygon) - min(point[1] for point in wall_polygon)
                > max(point[0] for point in wall_polygon) - min(point[0] for point in wall_polygon)
            )
            x_radius, y_radius = ((thickness // 2, long_axis // 2) if is_vertical
                                  else (long_axis // 2, thickness // 2))
            x1, y1, x2, y2 = cx - x_radius, cy - y_radius, cx + x_radius, cy + y_radius
            cv2.rectangle(mask, (x1, y1), (x2, y2), 255, thickness=-1)
        if cv2.countNonZero(mask):
            masks.append(mask)
    return masks


def _mock_room_labels(room_candidates):
    """Assign sample room labels to the nearest same-position candidates."""
    sample_rooms = get_sample_scene_json().get("rooms", [])
    used = set()
    labels = {}

    def centroid(room):
        if room.get("centroid"):
            return room["centroid"]
        polygon = room.get("polygon", [])
        if len(polygon) < 3:
            return [0, 0]
        twice_area = 0
        x_sum = y_sum = 0
        for index, point in enumerate(polygon):
            next_point = polygon[(index + 1) % len(polygon)]
            cross = point[0] * next_point[1] - next_point[0] * point[1]
            twice_area += cross
            x_sum += (point[0] + next_point[0]) * cross
            y_sum += (point[1] + next_point[1]) * cross
        if abs(twice_area) < 1e-8:
            return [sum(point[0] for point in polygon) / len(polygon),
                    sum(point[1] for point in polygon) / len(polygon)]
        return [x_sum / (3 * twice_area), y_sum / (3 * twice_area)]

    for candidate in room_candidates:
        cx, cy = centroid(candidate)
        nearest = min(
            (room for room in sample_rooms if room["id"] not in used),
            key=lambda room: (centroid(room)[0] - cx) ** 2 + (centroid(room)[1] - cy) ** 2,
            default=None,
        )
        if nearest is None:
            labels[candidate["id"]] = {"type": "room", "label": f"Mock Room {candidate['id']}", "confidence": 0.75}
        else:
            used.add(nearest["id"])
            labels[candidate["id"]] = {
                "type": nearest.get("type", "room"),
                "label": nearest.get("label", f"Mock Room {candidate['id']}"),
                "confidence": nearest.get("confidence", 0.9),
            }
    return labels


def query_sam_concept(b64_data_url, concept, image_size, timeout=60):
    """
    Queries SAM 3.1 for an architectural concept ('room', 'wall', 'door', 'window').
    Calls only the configured Baseten SAM endpoint.
    """
    if is_mock_sam_enabled():
        return _mock_masks(concept, image_size)
    baseten_cfg = get_baseten_config()
    if not is_sam_replay_enabled() and not baseten_cfg["is_configured"]:
        raise ValueError(
            "Baseten SAM 3.1 is not configured. Set BASETEN_API_KEY and BASETEN_SAM_URL "
            "(or BASETEN_MODEL_ID) in .env, or enable MOCK_SAM/REPLAY_SAM_RESPONSES."
        )
    return query_baseten_sam(b64_data_url, concept, image_size, timeout=timeout)


def label_rooms(b64_data_url, room_candidates, warnings=None, timeout=60):
    """
    Labels each detected room candidate.
    Uses Modal serverless endpoint for Muse Spark,
    and Fireworks API for Meta Llama 3.
    """
    if is_mock_sam_enabled():
        return _mock_room_labels(room_candidates)
    if is_sam_replay_enabled():
        if warnings is not None:
            warnings.append("Room labels use local replay fallback; no NLP provider was called.")
        return {candidate["id"]: {
            "type": "room",
            "label": f"Replay Room {index + 1}",
            "confidence": 0.0,
        } for index, candidate in enumerate(room_candidates)}
    return label_rooms_with_modal_muse_spark(
        b64_data_url, room_candidates, warnings=warnings, timeout=timeout
    )
