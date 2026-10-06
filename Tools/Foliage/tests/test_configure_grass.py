"""Offline checks for Tools/Foliage/configure_grass.py (world sprint, Task V3).

    python -m pytest Tools/Foliage/tests -q

configure_grass.py is sent to the live editor through Hayba python_run
(node Tools/Foliage/run_foliage.mjs py Tools/Foliage/configure_grass.py), so it
must survive the python_run policy. Its TYPES table is a plain literal, and these
tests hold it to the brief's numbers (task-V3-brief.md, "Produces"):

    near grass  cull 3000/5000 cm, 12 per m2, no dynamic shadow
    dry tufts   cull 6000/10000 cm, 2 per m2, no dynamic shadow
    reeds       cull 5000/8000 cm, 1.5 per m2, dynamic shadow
    all         contact shadow off, random rotation, scale 0.8-1.3, align to surface,
                (grass.DensityScale scales every variety in UE 5.8; there is no
                per-variety switch to set)

Ruling R25: grass types take static meshes only, so the reeds must not use the
skinned Megaplant reeds (SK_/SKM_ assets). Ruling R21: no T_Gaea_* anywhere.
"""
import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "Tools" / "Foliage" / "configure_grass.py"
FOLIAGE = "/Game/SaskartaGaea/Foliage/"

BRIEF = {
    "LGT_Saskarta_NearGrass": dict(start=3000, end=5000, per_m2=12.0, shadow=False),
    "LGT_Saskarta_DryGrass": dict(start=6000, end=10000, per_m2=2.0, shadow=False),
    "LGT_Saskarta_Reeds": dict(start=5000, end=8000, per_m2=1.5, shadow=True),
}


def literal(name):
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"no top-level {name} = <literal> in {SCRIPT}")


def types():
    return {pathlib.PurePosixPath(t["path"]).name: t for t in literal("TYPES")}


def test_script_survives_python_run():
    text = SCRIPT.read_text(encoding="utf-8")
    text.encode("ascii")
    for bad in ["try", "getattr", "open(", ".replace(", "new_level(", "import time", "T_Gaea_"]:
        assert bad not in text, bad


def test_the_three_types_and_their_paths():
    t = types()
    assert set(t) == set(BRIEF)
    for name, spec in t.items():
        assert spec["path"] == FOLIAGE + name


def test_cull_distances_match_the_brief():
    for name, spec in types().items():
        assert (spec["start_cull_cm"], spec["end_cull_cm"]) == (BRIEF[name]["start"], BRIEF[name]["end"]), name


def test_only_reeds_cast_dynamic_shadow_and_every_type_casts_contact_shadow():
    # PERF2 correction (user): keep grass shadows cheaply near the camera: contact shadows on every type,
    # the VSM only on the sparse reeds.
    for name, spec in types().items():
        assert spec["cast_dynamic_shadow"] is BRIEF[name]["shadow"], name
    assert literal("CAST_CONTACT_SHADOW") is True


def test_density_per_square_metre_is_split_by_shares():
    # GrassDensity measured as instances per 100 m2 in this editor (task-V3-report.md).
    assert literal("UNITS_PER_M2") == 100.0
    for name, spec in types().items():
        assert spec["per_m2"] == BRIEF[name]["per_m2"], name
        assert len(spec["shares"]) == len(spec["meshes"]) >= 1, name
        assert all(s > 0 for s in spec["shares"]), name
        per_variety = [spec["per_m2"] * 100.0 * s / sum(spec["shares"]) for s in spec["shares"]]
        assert abs(sum(per_variety) / 100.0 - BRIEF[name]["per_m2"]) < 1e-9, name


def test_no_glTF_default_material_meshes():
    # The Pallbearer tufts' material parent is the glTF importer's M_Default, which is
    # not usable with instanced static meshes: as grass they render nothing.
    for spec in types().values():
        for mesh in spec["meshes"]:
            assert "/Pallbearer/" not in mesh, mesh


def test_placement_rules():
    assert literal("SCALE_RANGE") == (0.8, 1.3)
    assert literal("RANDOM_ROTATION") is True
    assert literal("ALIGN_TO_SURFACE") is True


def test_meshes_are_static_and_reeds_are_not_the_skinned_megaplant():
    for name, spec in types().items():
        for mesh in spec["meshes"]:
            leaf = mesh.rsplit("/", 1)[-1]
            assert mesh.startswith("/Game/") and "." not in leaf, mesh
            assert not leaf.startswith(("SK_", "SKM_")), mesh
    for mesh in types()["LGT_Saskarta_Reeds"]["meshes"]:
        assert "Plant_Dry_Common_Reeds" not in mesh, mesh


def test_per_quality_twins_are_set_to_the_same_values():
    text = SCRIPT.read_text(encoding="utf-8")
    for prop in ["grass_density_quality", "start_cull_distance_quality", "end_cull_distance_quality"]:
        assert f"'{prop}'" in text, prop


def test_wpo_disable_distance_is_the_spec_60_m():
    assert literal("WPO_DISABLE_CM") == 6000


def test_min_weight_keeps_the_maintained_core_and_crown_empty():
    """Review Focus 3: the weight floor must cut the soft core edge and, with the LOOK2
    crown term core * saturate((neglect - 0.8) / 0.2) * 0.15, keep the crown empty below
    neglect ~0.84, without cutting ordinary verge grass."""
    w = literal("MIN_WEIGHT")
    assert (1 - 0.8) * 0.15 < w                 # edge band at core 0.8, lushest base 1.0
    crown = lambda n: min(max((n - 0.8) / 0.2, 0.0), 1.0) * 0.15
    assert crown(0.84) >= w * 0.99              # crown only from neglect ~0.84 up
    assert crown(0.83) < w
    assert 0.25 * 0.15 > w                      # an unexposed, dry verge (base 0.25) at neglect 0 survives
    assert "'allowed_density_range'" in SCRIPT.read_text(encoding="utf-8")


# ---- LOOK2: colour instances ----------------------------------------------------------
def _hue(c):
    r, g, b = c
    mx, mn = max(c), min(c)
    if mx - mn < 1e-9:
        return None
    if mx == r:
        return 60.0 * (((g - b) / (mx - mn)) % 6.0)
    if mx == g:
        return 60.0 * ((b - r) / (mx - mn) + 2.0)
    return 60.0 * ((r - g) / (mx - mn) + 4.0)


def test_every_mesh_has_a_project_owned_colour_instance():
    mats = literal("MATERIALS")
    for name, spec in types().items():
        assert len(spec["materials"]) == len(spec["meshes"]), name
        for mi in spec["materials"]:
            assert mi in mats and mi.startswith("MI_Saskarta_"), mi
    assert literal("MI_DIR").startswith("/Game/SaskartaGaea/")
    text = SCRIPT.read_text(encoding="utf-8")
    assert "'override_materials'" in text


def test_grass_is_dry_and_dull():
    # LANE4: no pale/white and no bright green type: every tint's chroma (max - min) at most 0.35,
    # and none brighter than 0.8 in any channel
    for name, (parent, vecs, scals) in literal("MATERIALS").items():
        for k, v in vecs.items():
            assert max(v) <= 0.8 and max(v) - min(v) <= 0.36, (name, k, v)
        for k, v in scals.items():
            if k == 'Local Random Color Variation':
                assert v <= 0.5, (name, v)


def test_grass_colours_are_earth_and_green_never_pink():
    # the RoadVis captures showed pink reeds (MI_TallGrass 00_BaseColorTint 1.0, 0.55, 0.59)
    # and a magenta third colour on the blades (0.53, 0.16, 0.22)
    hues = []
    for name, (parent, vecs, scals) in literal("MATERIALS").items():
        # the parents are the project's _GB copies of the pack MIs (the ground blend, LANE4)
        assert parent.startswith("/Game/SaskartaGaea/Foliage/Materials/Masters/") and parent.endswith("_GB"), parent
        for k, v in vecs.items():
            if k == "00_ColorRandomizationControls":
                continue                                    # a control vector, not a colour
            h = _hue(v)
            if h is not None:
                assert 15.0 <= h <= 110.0, (name, k, v, h)     # rust .. ochre .. straw .. green
                hues.append(h)
    # LANE4 (user 2026-09-28: "more uniform", "the white and green grass vary too much"): a little
    # spread (dead brown .. dull olive), no longer LOOK2's rust-to-green > 40 deg
    assert 15.0 < max(hues) - min(hues) <= 35.0


def test_dry_tufts_differ_from_each_other():
    tints = [literal("MATERIALS")[m][1]["Tint"] for m in types()["LGT_Saskarta_DryGrass"]["materials"]]
    assert len(set(tints)) == 4
