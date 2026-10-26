"""
FloorPlan3D - SAM 3.1 & Model Gateway
Routes inference requests through partner cloud endpoints:
1. SAM 3.1 Image Segmentation -> Baseten API Endpoint (BASETEN_API_KEY)
2. Meta Llama 3 Text/NLP Generation -> Fireworks API Endpoint (FIREWORKS_API_KEY)
3. Meta Muse Spark -> Modal Serverless Endpoint (MODAL_API_KEY)
"""

# Import partner cloud endpoint handlers
from cloud_services import (
    get_baseten_config,
    query_baseten_sam,
    label_rooms_with_modal_muse_spark
)


def query_sam_concept(b64_data_url, concept, image_size):
    """
    Queries SAM 3.1 for an architectural concept ('room', 'wall', 'door', 'window').
    Calls only the configured Baseten SAM endpoint.
    """
    baseten_cfg = get_baseten_config()
    if not baseten_cfg["is_configured"]:
        raise ValueError(
            "Baseten SAM 3.1 is not configured. Set BASETEN_API_KEY and BASETEN_SAM_URL "
            "(or BASETEN_MODEL_ID) in .env."
        )
    return query_baseten_sam(b64_data_url, concept, image_size)


def label_rooms(b64_data_url, room_candidates):
    """
    Labels each detected room candidate.
    Uses Modal serverless endpoint for Muse Spark,
    and Fireworks API for Meta Llama 3.
    """
    return label_rooms_with_modal_muse_spark(b64_data_url, room_candidates)
