import ast
import datetime
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
import prepare_float_followup as followup


def test_packet_is_two_candidate_sites_and_read_only(tmp_path):
    result = followup.prepare(tmp_path)
    assert len(result["scripts"]) == 4
    assert result["editor_executed"] is False
    for row in result["scripts"]:
        script = Path(row["path"]).read_text()
        ast.parse(script)
        for mutation in ("load_actors(", "unload_actors(", "load_asset(", "save_asset(", "set_actor_", "update_instance"):
            assert mutation not in script
    primary = result["candidates"][0]
    assert len([p for p in primary["authored_items"] if p["ism"]]) == 8
    assert {p["key"] for p in primary["authored_items"] if not p["ism"]} == {
        "B01_marker01", "MV_jute_bag_07", "MV_jute_bag_09"}


def test_descriptor_and_loaded_output_budgets_are_explicit():
    assert "len(rows)>24" in followup.descriptor_script("S09_CaravanRoute")
    script = followup.catalog_script("S09_CaravanRoute")
    assert "pending[:6]" in script
    assert "min(count, 8, 16 - used_samples)" in script
    assert "> 18000" in script
    assert "bounds_and_pivots_are_not_contact_proof" in script


class Obj:
    def __init__(self, path):
        self.path = path

    def get_path_name(self):
        return self.path

    def get_name(self):
        return self.path


class ISM:
    def __init__(self, path, count=8):
        self.path, self.count = path, count
        self.static_mesh = SimpleNamespace(get_path_name=lambda: "/Game/Shrub.Shrub",
            get_bounding_box=lambda: SimpleNamespace(min=[-1, -1, 0], max=[1, 1, 3]))

    def get_path_name(self):
        return self.path

    def get_class(self):
        return Obj("InstancedStaticMeshComponent")

    def get_instance_count(self):
        return self.count

    def is_visible(self):
        return True

    def get_editor_property(self, name):
        return False if name == "hidden_in_game" else 0

    def get_collision_enabled(self):
        return "NoCollision"

    def get_num_materials(self):
        return 0


class Actor(Obj):
    tags = []

    def __init__(self, label, components):
        super().__init__("/Game/World." + label)
        self.label, self.components = label, components

    def get_actor_label(self):
        return self.label

    def get_class(self):
        return Obj("StaticMeshActor")

    def get_package(self):
        return Obj("/Game/__ExternalActors__/stub")

    def get_components_by_class(self, _):
        return self.components


def run_catalog(actors, after=""):
    output = []
    namespace = dict(json=json, actors=actors, started=datetime.datetime.now(datetime.timezone.utc),
        expired=lambda: False, path=lambda value: value.get_path_name() if value else None,
        vec=lambda value: value, world=Obj("/Game/World"), print=output.append,
        instance_pose=lambda comp, index: SimpleNamespace(export_text=lambda: f"pose{index}",
            transform_location=lambda vector: [0, 0, index]),
        unreal=SimpleNamespace(StaticMeshComponent=ISM, InstancedStaticMeshComponent=ISM,
            LandscapeProxy=type("LandscapeProxy", (), {}), Vector=lambda: None))
    body = followup.catalog_script("S09_CaravanRoute", after)[len(followup.COMMON):]
    exec(body, namespace)
    return json.loads(output[0].split(" ", 1)[1])


def test_all_eight_primary_shrub_poses_are_reported_and_unrelated_actors_ignored():
    result = run_catalog([Actor("SD_S09_CaravanRoute_ism_shrubs_00_0", [ISM("/Game/World.Shrubs")]),
                          Actor("SD_S10_CrestFort_ism_grass_00_0", [ISM("/Game/World.Grass")])])
    assert result["site_actor_count_loaded"] == 1
    assert [s["instance"] for s in result["rows"][0]["samples"]] == list(range(8))
    assert result["rows"][0]["samples_truncated"] is False
    assert result["contact_measured"] is False


def test_component_continuation_never_silently_drops_a_component():
    actor = Actor("SD_S09_CaravanRoute_001", [ISM(f"/Game/World.Component{i}", 1) for i in range(8)])
    first = run_catalog([actor])
    assert len(first["rows"]) == 6
    second = run_catalog([actor], first["next_after_component"])
    assert len(second["rows"]) == 2
    assert second["next_after_component"] is None
    with pytest.raises(RuntimeError, match="disappeared"):
        run_catalog([actor], "/Game/Missing.Component")


def test_instance_truncation_is_not_a_complete_contact_claim():
    result = run_catalog([Actor("SD_S09_CaravanRoute_ism_shrubs_00_0", [ISM("/Game/World.Shrubs", 40)])])
    assert len(result["rows"][0]["samples"]) == 8
    assert result["rows"][0]["instance_count"] == 40
    assert result["rows"][0]["samples_truncated"] is True

