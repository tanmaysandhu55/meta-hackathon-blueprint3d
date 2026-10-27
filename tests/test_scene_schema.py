import copy

import pytest

from app import validate_scene_contract
from demo_data import get_sample_scene_json, get_two_story_sample_scene_json


@pytest.mark.parametrize("scene_factory", [get_sample_scene_json, get_two_story_sample_scene_json])
def test_prepared_scenes_meet_contract(scene_factory):
    scene = scene_factory()
    scene["meta"]["processingMode"] = "DEMO"
    assert validate_scene_contract(scene) is scene


def test_scene_contract_rejects_invalid_polygon():
    scene = copy.deepcopy(get_sample_scene_json())
    scene["rooms"][0]["polygon"] = [[0, 0], [1, 1]]

    with pytest.raises(RuntimeError, match="rooms.0.polygon"):
        validate_scene_contract(scene)
