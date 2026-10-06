"""Offline tests for the V5 tree graph specs (build_pcg_trees.py). No editor needed."""
import ast
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import build_pcg_trees as b  # noqa: E402

ORIGIN, EXTENT = b.mask_mapping(b.ROOT / "Tools" / "Terrain" / "MASKS.md")
SPECS = [b.sub_spec(ORIGIN, EXTENT), b.trees_spec()]
BANNED = [r"\btry\b", r"\bgetattr\b", r"import time", r"open\(", r"\.replace\(", r"new_level\(", r"\beval\("]


def test_edges_reference_defined_nodes():
    for spec in SPECS:
        ids = {n["id"] for n in spec.nodes} | {"IN", "OUT"}
        for a, _, c, _ in spec.edges:
            assert a in ids and c in ids


def test_compiled_code_parses_and_obeys_python_run_rules():
    for spec in SPECS:
        code = b.compile_spec(spec)
        ast.parse(code)
        for pattern in BANNED:
            assert not re.search(pattern, code), (spec.path, pattern)


def test_never_uses_stale_gaea_masks():
    for spec in SPECS:
        assert "T_Gaea" not in b.compile_spec(spec)


def test_texture_mapping_comes_from_masks_md():
    code = b.compile_spec(SPECS[0])
    half = EXTENT / 2.0
    assert f"unreal.Vector({ORIGIN[0] + half!r}, {ORIGIN[1] + half!r}, 0.0)" in code
    assert f"unreal.Vector({half!r}, {half!r}, 1.0)" in code


def test_r39_static_only_with_culls_and_near_wind():
    spec = SPECS[1]
    classes = [n["cls"] for n in spec.nodes]
    assert "PCGSkinnedMeshSpawnerSettings" not in classes          # R39: never skinned trees
    assert classes.count("PCGStaticMeshSpawnerSettings") == 1
    code = b.compile_spec(spec)
    assert "Skinned" not in code and "DWD_" not in code and "Megaplant_Library" not in code
    assert "'instance_min_draw_distance': lambda c: 0.0" in code
    assert "'instance_start_cull_distance': lambda c: 25000.0, 'instance_end_cull_distance': lambda c: 30000.0" in code
    assert "'world_position_offset_disable_distance': lambda c: 6000" in code


def test_b_plus_density_threshold():
    assert b.FP_THRESHOLD == 1.0


def test_b_plus_numbers():
    assert abs(b.PARENTS_PER_M2 - 0.0056) < 1e-9
    assert abs(b.SIGMA_CM - 1170.0) < 1e-9
    # the sum of two uniform +-a offsets has sd a*sqrt(2/3); it must equal sigma
    assert abs(b.CHILD_HALF_CM * (2.0 / 3.0) ** 0.5 - b.SIGMA_CM) < 1e-6
    # 1.2 - r/(2.5 sigma) meets the 0.25 floor at PATCH_ZERO_R_CM
    assert abs(1.2 - b.PATCH_ZERO_R_CM / (2.5 * b.SIGMA_CM) - 0.25) < 1e-9


def test_every_species_has_a_static_stand_in():
    code = b.compile_spec(SPECS[1])
    for name in b.SPECIES:
        path = b.far_mesh(name)
        assert b.obj_path(path) in code
        # static meshes only (R39): the project's stand-ins or the MedievalVillage pines (LANE4)
        assert "/SM_Saskarta_TreeFar_" in path or "/MedievalVillage/Demo/StaticMesh/Trees/" in path
    assert all(b.far_mesh(n).endswith(("SM_PineTree_01", "SM_PineTree_02")) for n in b.SPECIES if n.startswith("Ginkgo"))


def test_saturating_remaps_keep_output_in_unit_range():
    # Remap's clamp_to_unit_range clamps the OUTPUT to [0, 1] (measured in the editor), so a
    # remap with an output range outside [0, 1] must not set it.
    for spec in SPECS:
        for n in spec.nodes:
            if n["cls"] == "PCGAttributeRemapSettings" and n["props"]["clamp_to_unit_range"]:
                lo, hi = n["props"]["out_range_min"], n["props"]["out_range_max"]
                assert 0.0 <= min(lo, hi) and max(lo, hi) <= 1.0, n
