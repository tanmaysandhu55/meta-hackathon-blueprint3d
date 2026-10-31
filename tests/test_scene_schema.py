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


def test_sample_scene_has_genuine_exterior_exits():
    scene = get_sample_scene_json()
    doors = scene.get("doors", [])
    exterior_doors = [d for d in doors if "outside" in d.get("connects", [])]
    assert len(exterior_doors) >= 2, "Expected at least 2 exterior exit doors"

    # Verify West corridor exit d5
    d5 = next((d for d in doors if d["id"] == "d5"), None)
    assert d5 is not None
    assert "outside" in d5["connects"]
    assert "r3" in d5["connects"]

    # Verify East lobby main entrance exit d8
    d8 = next((d for d in doors if d["id"] == "d8"), None)
    assert d8 is not None
    assert "outside" in d8["connects"]
    assert "r6" in d8["connects"]

    # Verify wall opening for d8 on south perimeter
    walls = scene.get("walls", [])
    wall_ids = {w["id"] for w in walls}
    assert "south_center_east_a" in wall_ids
    assert "south_center_east_b" in wall_ids
