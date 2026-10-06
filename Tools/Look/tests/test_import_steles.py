"""Offline tests for the editor scripts in Tools/Look/import_steles.py, run against fake `unreal` modules.

1. MATERIAL: the script is executed with a fake MaterialEditingLibrary that records the graph, then a
   small model of the HLSL translator checks it: output and input names resolve the way
   MaterialEditingLibrary.cpp resolves them (an empty output name is output 0), component counts
   follow the outputs' masks (VectorParameter output 0 is "RGB", a float3), a ComponentMask may not
   ask for a component its input lacks, arithmetic needs equal sizes or a scalar, and every node
   reaches a material property. The old GlyphRect wiring ("" into the .zw mask) must fail it.
2. SWAP / SAVE / RESIDENT / VERIFY: executed against a fake World Partition level whose setters
   dirty the actor's package only where the engine does (set_editor_property and modify(); not
   set_visibility, set_actor_hidden_in_game, set_static_mesh or the transform setters), and whose
   save_packages(only_dirty=True) writes only dirty packages. After swap, save, unload and reload,
   verify must pass; without the modify() calls the hidden decals must come back and verify must
   say so.

These model the engine from its source (UE 5.8); they are not the engine. What the editor really
does is still untested until the steps run there.

Run: python -m pytest Tools/Look/tests/test_import_steles.py -q -p no:cacheprovider
"""
import copy
import pathlib
import sys
import types

import pytest

LOOK = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LOOK))

import import_steles as ist  # noqa: E402


class Any:
    """Enums, structs, helpers the scripts only pass along: any attribute or call gives another Any."""

    def __init__(self, name="any"):
        self._n = name

    def __getattr__(self, k):
        if k.startswith("__"):
            raise AttributeError(k)
        return Any(self._n + "." + k)

    def __call__(self, *a, **kw):
        return Any(self._n + "()")


class FakeUnreal(types.ModuleType):
    """`import unreal`: explicit fakes first, any other name is an Any (or a class stand-in)."""

    def __init__(self, **attrs):
        super().__init__("unreal")
        self.__dict__.update(attrs)

    def __getattr__(self, k):
        if k.startswith("__"):
            raise AttributeError(k)
        return Any(k)


def run_script(monkeypatch, fake, script):
    monkeypatch.setitem(sys.modules, "unreal", fake)
    exec(compile(script, "editor_script", "exec"), {"__name__": "editor_script"})


# ------------------------------------------------------------------------------------------------
# 1. the material graph
# ------------------------------------------------------------------------------------------------
TEX_OUT = [("RGB", 3), ("R", 1), ("G", 1), ("B", 1), ("A", 1), ("RGBA", 4)]
OUTPUTS = {                                    # output 0 first (MaterialExpressions.cpp constructors)
    "MaterialExpressionTextureCoordinate": [("", 2)],
    "MaterialExpressionScalarParameter": [("", 1)],
    "MaterialExpressionConstant": [("", 1)],
    "MaterialExpressionNoise": [("", 1)],
    "MaterialExpressionVectorParameter": TEX_OUT,
    "MaterialExpressionTextureSampleParameter2D": TEX_OUT,
    "MaterialExpressionConstant3Vector": [("", 3), ("R", 1), ("G", 1), ("B", 1)],
    "MaterialExpressionVertexColor": [("", 3), ("R", 1), ("G", 1), ("B", 1), ("A", 1)],
}
BINARY = {"MaterialExpressionMultiply", "MaterialExpressionAdd", "MaterialExpressionSubtract",
          "MaterialExpressionDivide"}
UNARY = {"MaterialExpressionOneMinus", "MaterialExpressionAbs", "MaterialExpressionSaturate",
         "MaterialExpressionNormalize", "MaterialExpressionComponentMask"}
INPUTS = {c: ["A", "B"] for c in BINARY}
INPUTS.update({c: ["Input"] for c in UNARY})
INPUTS.update({"MaterialExpressionLinearInterpolate": ["A", "B", "Alpha"],
               "MaterialExpressionAppendVector": ["A", "B"],
               "MaterialExpressionTextureSampleParameter2D": ["UVs"],
               "MaterialExpressionNoise": ["Position", "FilterWidth"]})
PROPERTY_SIZES = {"MP_BASE_COLOR": (1, 3), "MP_NORMAL": (3,), "MP_ROUGHNESS": (1,), "MP_AMBIENT_OCCLUSION": (1,)}


class Node:
    def __init__(self, cls):
        self.cls, self.props, self.inputs = cls, {}, {}

    def set_editor_property(self, k, v):
        self.props[k] = v

    def get_editor_property(self, k):
        return self.props.get(k)


class ExprClass:
    def __init__(self, name):
        self.name = name


class FakeMaterialUnreal(FakeUnreal):
    def __getattr__(self, k):
        if k.startswith("MaterialExpression"):
            return ExprClass(k)
        return super().__getattr__(k)


class FakeMEL:
    def __init__(self):
        self.nodes, self.props = [], []

    def set_material_usage(self, *a):
        return True

    def get_material_expressions(self, mat):
        return list(self.nodes)

    def delete_material_expression(self, mat, n):
        self.nodes.remove(n)

    def create_material_expression(self, mat, cls, x, y):
        n = Node(cls.name)
        self.nodes.append(n)
        return n

    def connect_material_expressions(self, a, ao, b, bi):
        outs = OUTPUTS.get(a.cls, [("", 0)])
        if ao and ao not in [o for o, _ in outs]:
            return False                       # MaterialEditingLibrary: no output by that name
        ins = INPUTS.get(b.cls, [])
        key = ins[0] if (bi == "" and ins) else bi
        if key not in ins:
            return False
        b.inputs[key] = (a, ao)
        return True

    def connect_material_property(self, n, out, prop):
        self.props.append((n, out, prop._n.split(".")[-1]))
        return True

    def recompile_material(self, mat):
        return []


class FakeEAL:
    def does_asset_exist(self, p):
        return True

    def does_directory_exist(self, p):
        return True

    def load_asset(self, p):
        return Any(p)

    def save_loaded_asset(self, a, only_dirty=True):
        return True


def translate(mel):
    """Component counts through the graph, the way FHLSLMaterialTranslator would size them."""
    errors, memo = [], {}

    def size(node, out):
        k = (id(node), out)
        if k in memo:
            return memo[k]
        cls = node.cls
        if cls in OUTPUTS:                     # fixed output sizes; their inputs are optional
            outs = OUTPUTS[cls]
            w = outs[0][1] if out == "" else dict(outs)[out]
            if "UVs" in node.inputs and size(*node.inputs["UVs"]) != 2:
                errors.append(f"{cls}: UVs must be float2")
        else:
            def inp(name, required):
                if name in node.inputs:
                    return size(*node.inputs[name])
                if required:
                    errors.append(f"{cls}: missing input {name}")
                return 1

            if cls in BINARY or cls == "MaterialExpressionLinearInterpolate":
                a, b = inp("A", False), inp("B", False)
                if a != b and 1 not in (a, b):
                    errors.append(f"{cls}: float{a} with float{b}")
                w = max(a, b)
                if cls == "MaterialExpressionLinearInterpolate":
                    t = inp("Alpha", False)
                    if t not in (1, w):
                        errors.append(f"{cls}: alpha float{t} for float{w}")
            elif cls == "MaterialExpressionComponentMask":
                src = inp("Input", True)
                flags = [bool(node.props.get(c)) for c in "rgba"]
                if any(f and i >= src for i, f in enumerate(flags)):
                    errors.append("ComponentMask: not enough components in float%d for component mask %s"
                                  % (src, "".join("1" if f else "0" for f in flags)))
                w = sum(flags)
            elif cls in UNARY:
                w = inp("Input", True)
            elif cls == "MaterialExpressionAppendVector":
                w = inp("A", True) + inp("B", True)
            else:
                raise AssertionError(f"no model for {cls}")
        memo[k] = w
        return w

    for n, out, prop in mel.props:
        w = size(n, out)
        if w not in PROPERTY_SIZES[prop]:
            errors.append(f"{prop}: float{w}")
    reached, stack = set(), [n for n, _, _ in mel.props]
    while stack:
        n = stack.pop()
        if id(n) not in reached:
            reached.add(id(n))
            stack += [a for a, _ in n.inputs.values()]
    unused = [n.cls for n in mel.nodes if id(n) not in reached]
    return errors, unused


def material_script(glyph_rect_out="RGBA"):
    s = dict(ist.scripts_for_check())["material"]
    if glyph_rect_out != "RGBA":
        old = '(rect, "RGBA", rxy, ""), (rect, "RGBA", rzw, "")'
        assert old in s
        s = s.replace(old, f'(rect, "{glyph_rect_out}", rxy, ""), (rect, "{glyph_rect_out}", rzw, "")')
    return s


def run_material(monkeypatch, script):
    mel = FakeMEL()
    run_script(monkeypatch, FakeMaterialUnreal(MaterialEditingLibrary=mel, EditorAssetLibrary=FakeEAL()), script)
    return mel


def test_material_graph_translates(monkeypatch, capsys):
    mel = run_material(monkeypatch, material_script())
    out = capsys.readouterr().out
    assert "bad_links=[]" in out and "props=[True, True, True, True]" in out and "errors=0 " in out, out
    errors, unused = translate(mel)
    assert errors == [], errors
    assert unused == [], unused
    assert sorted(p for _, _, p in mel.props) == sorted(PROPERTY_SIZES)


def test_old_glyph_rect_wiring_is_caught(monkeypatch, capsys):
    """The previous script read GlyphRect through output 0 (RGB, float3) and masked .zw from it."""
    mel = run_material(monkeypatch, material_script(glyph_rect_out=""))
    errors, _ = translate(mel)
    assert any("component mask 0011" in e for e in errors), errors


def test_material_step_fails_on_compile_errors(monkeypatch):
    """The runner's pass condition is errors=0, not bad_links=[] alone."""
    line = "STELEMAT nodes=80 bad_links=[] props=[True, True, True, True] errors=1 first_errors=['x'] saved=True"
    monkeypatch.setattr(ist, "python_run", lambda s: (True, line, ""))
    with pytest.raises(SystemExit, match="errors=0"):
        ist.main(["material"])
    monkeypatch.setattr(ist, "python_run", lambda s: (True, line.replace("errors=1", "errors=0"), ""))
    assert ist.main(["material"]) == 0


# ------------------------------------------------------------------------------------------------
# 2. the level: swap, save, unload, reload, verify
# ------------------------------------------------------------------------------------------------
class Named:
    def __init__(self, name):
        self.name = name

    def get_name(self):
        return self.name


class Vec:
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x, self.y, self.z = x, y, z


class Pkg:
    def __init__(self, name):
        self.name, self.dirty = name, False

    def get_name(self):
        return self.name


def mesh_slots(mesh):
    if mesh.startswith("SM_Stele_"):
        return ["MI_Stele_Body", "MI_Stele_Face_" + mesh[len("SM_Stele_"):]]
    return ["MI_Rock_01"]


class Comp:
    def __init__(self, actor):
        self.actor = actor

    @property
    def st(self):
        return self.actor.st

    def modify(self, always_mark_dirty=True):
        self.actor.pkg.dirty = True
        return True


class FakeSMC(Comp):
    def set_static_mesh(self, m):             # UStaticMeshComponent::SetStaticMesh: no Modify
        self.st["mesh"] = m.get_name()
        return True

    def set_editor_property(self, k, v):      # PreEditChange -> Modify: dirties the package
        assert k == "override_materials"
        self.actor.pkg.dirty = True
        self.st["overrides"] = [x.get_name() if x else None for x in v]

    def get_editor_property(self, k):
        if k == "static_mesh":
            return Named(self.st["mesh"])
        if k == "override_materials":
            return [Named(x) if x else None for x in self.st["overrides"]]
        if k == "custom_primitive_data":
            return types.SimpleNamespace(get_editor_property=lambda _k: list(self.st["cpd"]))
        raise KeyError(k)

    def set_custom_primitive_data_float(self, i, v):
        # Runtime CPD mirrors UPrimitiveComponent's Transient CustomPrimitiveDataInternal.
        cpd = self.st.setdefault("runtime_cpd", [])
        cpd += [0.0] * (i + 1 - len(cpd))
        cpd[i] = v

    def set_default_custom_primitive_data_float(self, i, v):
        # This is the serialized CustomPrimitiveData default read by the reload verifier.
        cpd = self.st["cpd"]
        cpd += [0.0] * (i + 1 - len(cpd))
        cpd[i] = v

    def set_material(self, i, m):             # no Modify
        ov = self.st["overrides"]
        ov += [None] * (i + 1 - len(ov))
        ov[i] = m.get_name()

    def get_num_materials(self):
        return max(len(mesh_slots(self.st["mesh"])), len(self.st["overrides"]))

    def get_material(self, i):
        ov = self.st["overrides"]
        if i < len(ov) and ov[i]:
            return Named(ov[i])
        slots = mesh_slots(self.st["mesh"])
        return Named(slots[i]) if i < len(slots) else None


class FakeDecal(Comp):
    def get_editor_property(self, k):
        assert k == "decal_color"
        return types.SimpleNamespace(a=self.st["wear"])

    def set_editor_property(self, k, v):
        self.actor.pkg.dirty = True
        self.st[k] = (v.x, v.y, v.z)

    def set_visibility(self, v, propagate):  # SetVisibility: render state only, no Modify
        self.st["visible"] = v

    def is_visible(self):
        return self.st["visible"]


class FakeActor:
    def __init__(self, label, st):
        self.label, self.st, self.pkg = label, st, Pkg("/Game/__ExternalActors__/level/Saskarta_WP/" + label)
        if label.endswith("_Glyph"):
            self.decal = FakeDecal(self)
        else:
            self.static_mesh_component = FakeSMC(self)

    def get_actor_label(self):
        return self.label

    def get_package(self):
        return self.pkg

    def modify(self, always_mark_dirty=True):
        self.pkg.dirty = True
        return True

    def set_actor_scale3d(self, v):           # no Modify
        self.st["scale"] = v.x

    def get_actor_scale3d(self):
        return Vec(self.st["scale"], self.st["scale"], self.st["scale"])

    def set_actor_hidden_in_game(self, b):    # SetHidden: push-model macro only, no Modify
        self.st["hidden"] = b

    def get_editor_property(self, k):
        assert k == "hidden"
        return self.st["hidden"]

    def get_actor_transform(self):
        return Any("transform")

    def get_actor_rotation(self):
        return Any("rotator")

    def set_actor_location(self, *a):
        self.st["moved"] = True

    def set_actor_rotation(self, *a):
        self.st["turned"] = True


class Level:
    """Disk = the saved state per actor; memory = the loaded actors."""

    def __init__(self):
        self.disk, self.loaded = {}, {}
        for i in range(34):
            self._add(f"Stele_WayStone_{i}", 0.1 + 0.02 * i)
        self._add("Stele_DockPost_A", 0.15)
        self._add("Stele_DockPost_B", 0.6)

    def _add(self, name, wear):
        self.disk[name] = {"mesh": "SM_Pillar_A_01", "overrides": ["MI_Rock_01"], "cpd": [], "scale": 1.0,
                           "hidden": False}
        self.disk[name + "_Glyph"] = {"wear": wear, "visible": True, "hidden": False, "scale": 1.0}

    def load(self):
        for label, st in self.disk.items():
            self.loaded.setdefault(label, FakeActor(label, copy.deepcopy(st)))

    def unload(self):
        self.loaded = {k: a for k, a in self.loaded.items() if a.pkg.dirty}   # dirty ones stay pinned

    def save_packages(self, pkgs, only_dirty):
        by_pkg = {a.pkg.name: a for a in self.loaded.values()}
        for p in pkgs:
            if p.dirty or not only_dirty:
                serialized = copy.deepcopy(by_pkg[p.name].st)
                serialized.pop("runtime_cpd", None)
                self.disk[by_pkg[p.name].label] = serialized
                p.dirty = False
        return True

    def fake(self):
        eas = types.SimpleNamespace(get_all_level_actors=lambda: list(self.loaded.values()))
        els = types.SimpleNamespace(
            get_dirty_map_packages=lambda: [a.pkg for a in self.loaded.values() if a.pkg.dirty],
            save_packages=self.save_packages)
        return FakeUnreal(
            EditorActorSubsystem="EditorActorSubsystem", get_editor_subsystem=lambda cls: eas,
            EditorLoadingAndSavingUtils=els, load_asset=lambda p: Named(p.split("/")[-1]),
            Vector=Vec, MathLibrary=types.SimpleNamespace(transform_location=lambda t, v: v,
                                                          compose_rotators=lambda a, b: a),
            Rotator=lambda **kw: Any("rotator"))


def editor(level, monkeypatch, capsys, script):
    run_script(monkeypatch, level.fake(), ist.check_banned(script))
    return capsys.readouterr().out


def swap_save_reload_verify(level, monkeypatch, capsys, mode, swap_tmpl=None):
    meshes = ist.manifest()
    items = ist.swap_items(meshes, mode)
    level.load()
    swap_out = ""
    for i in range(0, len(items), ist.SWAP_CHUNK):
        swap_out += editor(level, monkeypatch, capsys, ist.fill(swap_tmpl or ist.SWAP, ITEMS=repr(
            items[i:i + ist.SWAP_CHUNK]), MODE=mode, BODY=ist.BODY_MI))
    save_out = ""
    for chunk in range(4):
        save_out += editor(level, monkeypatch, capsys, ist.fill(ist.SAVE, CHUNK=chunk, SIZE=ist.SAVE_CHUNK))
    level.unload()
    resident = editor(level, monkeypatch, capsys, ist.fill(ist.RESIDENT))
    level.load()
    verify = editor(level, monkeypatch, capsys, ist.fill(ist.VERIFY, ITEMS=repr(items), MODE=mode))
    return swap_out, save_out, resident, verify


@pytest.mark.parametrize("mode", ["uv1", "decal"])
def test_swap_persists_through_save_and_reload(monkeypatch, capsys, mode):
    level = Level()
    swap_out, save_out, resident, verify = swap_save_reload_verify(level, monkeypatch, capsys, mode)
    assert swap_out.count("missing=[] not_dirty=[]") == 3, swap_out
    assert save_out.count("left_dirty=[]") == 4 and "SAVE total=72 " in save_out, save_out
    assert "RESIDENT loaded=0 dirty=0" in resident, resident
    assert "VERIFY count=36 problems=0 " in verify, verify
    hidden = [st["hidden"] for k, st in level.disk.items() if k.endswith("_Glyph")]
    assert hidden == [mode == "uv1"] * 36                 # what is on disk, not only what verify says


def test_runtime_custom_primitive_data_is_lost_after_reload(monkeypatch, capsys):
    """Runtime CPD is transient; the component default setter is required for saved wear."""
    runtime_only_swap = ist.SWAP.replace(
        "set_default_custom_primitive_data_float", "set_custom_primitive_data_float")
    level = Level()
    swap_out, _, _, verify = swap_save_reload_verify(level, monkeypatch, capsys, "uv1",
                                                     swap_tmpl=runtime_only_swap)
    assert "missing=[] not_dirty=[]" in swap_out, swap_out
    assert "wear=[]" in verify and "no wear in custom primitive data" in verify, verify


def test_without_modify_the_decals_come_back(monkeypatch, capsys):
    """The verifier's finding, reproduced in the model: the glyph packages stay clean, save skips them,
    and after the reload the old decals draw again on the new face. Verify must catch it."""
    no_modify = "\n".join(l for l in ist.SWAP.split("\n") if ".modify()" not in l)
    level = Level()
    swap_out, _, _, verify = swap_save_reload_verify(level, monkeypatch, capsys, "uv1", swap_tmpl=no_modify)
    assert "_Glyph" in swap_out.split("not_dirty=")[1]       # swap itself reports the clean packages
    assert "problems=0 " not in verify and "_Glyph visible=True" in verify, verify


def test_verify_refuses_unsaved_state(monkeypatch, capsys):
    """Verify straight after swap (no save) must fail: the packages are dirty."""
    level = Level()
    items = ist.swap_items(ist.manifest(), "uv1")
    level.load()
    for i in range(0, len(items), ist.SWAP_CHUNK):
        editor(level, monkeypatch, capsys, ist.fill(ist.SWAP, ITEMS=repr(items[i:i + ist.SWAP_CHUNK]), MODE="uv1",
                                                    BODY=ist.BODY_MI))
    assert "dirty=72 " in editor(level, monkeypatch, capsys, ist.fill(ist.RESIDENT))
    verify = editor(level, monkeypatch, capsys, ist.fill(ist.VERIFY, ITEMS=repr(items), MODE="uv1"))
    assert "unsaved (package dirty)" in verify and "problems=0 " not in verify


def test_verify_runner_order(monkeypatch):
    """verify = resident, load (chunks), the check, unload: in that order, each its own call."""
    calls = []

    def fake_run(script):
        head = script.strip().split("\n")[-1][:20]
        calls.append(head)
        if "RESIDENT" in script:
            return True, "RESIDENT loaded=0 dirty=0 dirty_labels=[]", ""
        if "LOAD stele" in script:
            return True, "LOAD stele descs=72 loaded_now=24", ""
        if "VERIFY count" in script:
            return True, "VERIFY count=36 problems=0 first=[]", ""
        return True, "UNLOAD 72", ""

    monkeypatch.setattr(ist, "python_run", fake_run)
    assert ist.main(["verify"]) == 0
    kinds = [("RESIDENT" if "RESIDENT" in c else "LOAD" if "LOAD stele" in c else "VERIFY" if "VERIFY" in c
              else "UNLOAD") for c in calls]
    assert kinds == ["RESIDENT", "LOAD", "LOAD", "LOAD", "VERIFY", "UNLOAD"], calls


@pytest.mark.parametrize("change", [None, ("generate_lightmap_u_vs", True),
                                      ("recompute_normals", True), ("use_full_precision_u_vs", False),
                                      ("uv", 1)])
def test_fixmesh_validates_import_without_rebuilding(monkeypatch, capsys, change):
    """The imported second UV channel is kept without the Hayba-blocked mesh rebuild API."""
    settings = {"generate_lightmap_u_vs": False, "recompute_normals": False,
                "recompute_tangents": True, "use_mikk_t_space": True,
                "use_full_precision_u_vs": True}
    uv = 2
    if change:
        key, value = change
        if key == "uv":
            uv = value
        else:
            settings[key] = value

    class BuildSettings:
        def get_editor_property(self, name):
            return settings[name]

    class Mesh:
        def get_bounding_box(self):
            return types.SimpleNamespace(min="min", max="max")

    class Subsystem:
        def get_lod_build_settings(self, mesh, lod):
            assert lod == 0
            return BuildSettings()

        def get_num_uv_channels(self, mesh, lod):
            assert lod == 0
            return uv

        def get_number_verts(self, mesh, lod):
            return 100

        def set_lod_build_settings(self, *args):
            pytest.fail("the static-mesh rebuild policy was bypassed")

    fake = FakeUnreal(EditorAssetLibrary=types.SimpleNamespace(load_asset=lambda path: Mesh()),
                      StaticMeshEditorSubsystem=object(), get_editor_subsystem=lambda cls: Subsystem())
    script = ist.fill(ist.FIXMESH, DEST=ist.DEST, NAME="SM_Stele_X")
    assert "set_lod_build_settings" not in script
    if change is None:
        run_script(monkeypatch, fake, script)
        assert "settings_ok=True full_uv=True" in capsys.readouterr().out
    else:
        with pytest.raises(RuntimeError, match="import settings"):
            run_script(monkeypatch, fake, script)


def test_import_sets_interchange_options_before_mesh_creation(monkeypatch, capsys):
    """UV1 is protected at import time, since changing LOD build settings later is unsafe."""
    class Props:
        def __init__(self):
            self.values = {}

        def set_editor_property(self, name, value):
            self.values[name] = value

        def get_editor_property(self, name):
            return self.values[name]

    class Pipeline(Props):
        def __init__(self):
            super().__init__()
            self.values["common_meshes_properties"] = Props()
            self.values["mesh_pipeline"] = Props()

    class Override:
        def add_pipeline(self, pipeline):
            self.pipeline = pipeline

    class Task(Props):
        pass

    class Mesh:
        def get_class(self):
            return types.SimpleNamespace(get_name=lambda: "StaticMesh")

        def get_bounding_box(self):
            return types.SimpleNamespace(min="min", max="max")

        def get_editor_property(self, name):
            assert name == "static_materials"
            return [types.SimpleNamespace(material_slot_name=s) for s in ("Stone", "Face")]

    mesh = Mesh()
    received = []

    def import_tasks(tasks):
        task = tasks[0]
        override = task.get_editor_property("options")
        pipeline = override.pipeline
        common = pipeline.get_editor_property("common_meshes_properties").values
        mesh_options = pipeline.get_editor_property("mesh_pipeline").values
        assert common["use_full_precision_u_vs"] is True
        assert common["recompute_normals"] is False
        assert common["recompute_tangents"] is True
        assert common["use_mikk_t_space"] is True
        assert mesh_options["generate_lightmap_u_vs"] is False
        assert mesh_options["build_nanite"] is True
        assert pipeline.get_editor_property("asset_name") == "SM_Stele_X"
        received.append(task)
        task.set_editor_property("imported_object_paths", [f"{ist.DEST}/SM_Stele_X"])

    eal = types.SimpleNamespace(does_directory_exist=lambda path: True,
                                does_asset_exist=lambda path: True,
                                load_asset=lambda path: mesh,
                                save_loaded_asset=lambda asset, only_if_dirty: True)
    ses = types.SimpleNamespace(get_num_uv_channels=lambda asset, lod: 2,
                                has_vertex_colors=lambda asset: True)
    fake = FakeUnreal(EditorAssetLibrary=eal, AssetImportTask=Task,
                      InterchangeGenericAssetsPipeline=Pipeline,
                      InterchangePipelineStackOverride=Override,
                      AssetToolsHelpers=types.SimpleNamespace(get_asset_tools=lambda: types.SimpleNamespace(import_asset_tasks=import_tasks)),
                      StaticMeshEditorSubsystem=object(), get_editor_subsystem=lambda cls: ses)
    run_script(monkeypatch, fake, ist.fill(ist.IMPORT, DEST=ist.DEST, NAME="SM_Stele_X", FILE="D:/x.glb"))
    assert len(received) == 1
    assert "uv=2" in capsys.readouterr().out
