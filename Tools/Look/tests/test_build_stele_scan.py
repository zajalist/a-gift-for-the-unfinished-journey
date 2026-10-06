"""Offline tests for Tools/Look/build_stele_scan.py, run against fake `unreal` modules.

1. Script text: every editor script compiles, has none of python_run's banned words (no "try" anywhere),
   and the material is split into calls of at most NODE_CHUNK nodes / LINK_CHUNK links.
2. The material graph: the create / node / link / compile scripts are executed in order against a fake
   MaterialEditingLibrary that finds nodes by their `desc` key, as the editor scripts do. A small model
   of the HLSL translator then checks the graph: input and output names resolve the way
   MaterialEditingLibrary.cpp resolves them (an empty input name is input 0; ParallaxOcclusionMapping's
   input names are the ones in the UE 5.8 asset), component counts match (UVs float2, the height
   channel float4, a texture object into the texture input, a static bool into Render Shadows), every
   node reaches a material output, and the Custom Primitive Data indices are the documented layout.
3. The level steps: cpd then save then verify run on a fake World Partition level in which only
   modify() and set_editor_property dirty a package (set_default_custom_primitive_data_float does not).
   Without the modify() calls the save writes nothing and cpd reports the clean packages.
4. The runner's pass conditions: a compile error, a bad link, a missing stele or a verify problem stops it.

These model UE 5.8 from its source; they are not the engine. The editor steps are still untested
until they run there.

Run: python -m pytest Tools/Look/tests/test_build_stele_scan.py -q -p no:cacheprovider
"""
import pathlib
import sys
import types

import pytest

LOOK = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LOOK))

import build_stele_scan as bss  # noqa: E402
from apply_look import BANNED  # noqa: E402

# the input names of /Engine/Functions/Engine_MaterialFunctions01/Texturing/ParallaxOcclusionMapping
# (UE 5.8 asset name table) and what each one takes
POM_INPUTS = {"Heightmap Texture": "tex", "Height Ratio": 1, "Min Steps": 1, "Max Steps": 1, "UVs": 2,
              "Heightmap Channel": 4, "Reference Plane": 1, "Render Shadows (Occlusion Mapping)": "sbool",
              "Light Vector": 3, "Shadow Steps": 1, "Shadow Penumbra": 1, "Specify Manual Texture Size": "sbool",
              "Manual Texture Size": 2, "Use World Coordinates": "sbool"}
POM_REQUIRED = ("Heightmap Texture", "Height Ratio", "Min Steps", "Max Steps", "UVs", "Heightmap Channel")
POM_OUTPUTS = {"Parallax UVs": 2, "Offset Only": 2, "Pixel Depth Offset": 1, "Shadow": 1}


# ------------------------------------------------------------------------------------------------ 1
def test_every_script_is_python_run_safe():
    labels = []
    for label, s in bss.all_scripts():
        labels.append(label)
        compile(s, label, "exec")
        hits = [w for w in BANNED if w in s]
        assert not hits, f"{label}: banned {hits}"
        assert "try" not in s.lower(), label                   # geometry, entry, registry ... all banned
    assert labels[0] == "create" and "compile" in labels


def test_material_calls_are_small():
    nodes, links, props = bss.graph()
    scripts = bss.material_scripts()
    assert len([s for lb, s in scripts if lb.startswith("nodes")]) == -(-len(nodes) // bss.NODE_CHUNK)
    assert len([s for lb, s in scripts if lb.startswith("links")]) == -(-len(links) // bss.LINK_CHUNK)
    assert bss.NODE_CHUNK <= 40 and bss.LINK_CHUNK <= 100
    keys = [n[0] for n in nodes]
    assert len(keys) == len(set(keys))


# ------------------------------------------------------------------------------------------------ fakes
class Any:
    def __init__(self, name="any"):
        self._n = name

    def __getattr__(self, k):
        if k.startswith("__"):
            raise AttributeError(k)
        return Any(self._n + "." + k)

    def __call__(self, *a, **kw):
        return Any(self._n + "()")

    def __eq__(self, other):
        return isinstance(other, Any) and other._n == self._n

    def __hash__(self):
        return hash(self._n)


class FakeUnreal(types.ModuleType):
    def __init__(self, **attrs):
        super().__init__("unreal")
        self.__dict__.update(attrs)

    def __getattr__(self, k):
        if k.startswith("__"):
            raise AttributeError(k)
        return Any(k)


class ExprClass:
    def __init__(self, name):
        self.name = name


class Node:
    def __init__(self, cls):
        self.cls, self.props, self.inputs = cls, {}, {}

    def set_editor_property(self, k, v):
        self.props[k] = v

    def get_editor_property(self, k):
        return self.props.get(k, "")


OUT4 = {"": 3, "RGB": 3, "R": 1, "G": 1, "B": 1, "A": 1, "RGBA": 4}
OUTPUTS = {
    "MaterialExpressionTextureCoordinate": {"": 2},
    "MaterialExpressionScalarParameter": {"": 1},
    "MaterialExpressionConstant": {"": 1},
    "MaterialExpressionConstant2Vector": {"": 2, "R": 1, "G": 1},
    "MaterialExpressionConstant3Vector": {"": 3, "R": 1, "G": 1, "B": 1},
    "MaterialExpressionConstant4Vector": {"": 4, "R": 1, "G": 1, "B": 1, "A": 1},
    "MaterialExpressionVectorParameter": OUT4,
    "MaterialExpressionTextureSampleParameter2D": OUT4,
    "MaterialExpressionTextureObjectParameter": {"": "tex"},
    "MaterialExpressionStaticBool": {"": "sbool"},
    "MaterialExpressionPixelDepth": {"": 1},
    "MaterialExpressionVertexNormalWS": {"": 3},
    "MaterialExpressionCameraVectorWS": {"": 3},
    "MaterialExpressionTime": {"": 1},
    "MaterialExpressionNoise": {"": 1},
    "MaterialExpressionVertexColor": {"": 3, "R": 1, "G": 1, "B": 1, "A": 1},
}
BINARY = {"Multiply", "Add", "Subtract", "Divide", "Max", "Min", "Fmod", "DotProduct"}
UNARY = {"OneMinus", "Abs", "Saturate", "Normalize", "Floor", "ComponentMask"}
INPUTS = {f"MaterialExpression{c}": ["A", "B"] for c in BINARY}
INPUTS.update({f"MaterialExpression{c}": ["Input"] for c in UNARY})
INPUTS.update({"MaterialExpressionLinearInterpolate": ["A", "B", "Alpha"],
               "MaterialExpressionAppendVector": ["A", "B"],
               "MaterialExpressionClamp": ["Input", "Min", "Max"],
               "MaterialExpressionStaticSwitchParameter": ["True", "False"],
               "MaterialExpressionTextureSampleParameter2D": ["UVs"],
               "MaterialExpressionNoise": ["Position", "FilterWidth"]})
PROPERTY_SIZES = {"MP_BASE_COLOR": (1, 3), "MP_NORMAL": (3,), "MP_ROUGHNESS": (1,), "MP_AMBIENT_OCCLUSION": (1,),
                  "MP_EMISSIVE_COLOR": (1, 3)}


class FakeMEL:
    def __init__(self):
        self.nodes, self.props, self.compiled = [], [], 0

    def set_base_material_usage(self, *a):
        return None

    def has_material_usage(self, *a):
        return True

    def delete_all_material_expressions(self, mat):
        self.nodes.clear()

    def get_num_material_expressions(self, mat):
        return len(self.nodes)

    def get_material_expressions(self, mat):
        return list(self.nodes)

    def create_material_expression(self, mat, cls, x, y):
        n = Node(cls.name)
        self.nodes.append(n)
        return n

    def connect_material_expressions(self, a, ao, b, bi):
        if a.cls == "MaterialExpressionMaterialFunctionCall":
            outs = POM_OUTPUTS if a.props.get("material_function") == bss.POM_FN else {}
        else:
            outs = OUTPUTS.get(a.cls, {"": 1})
        if ao not in outs:
            return False
        if b.cls == "MaterialExpressionMaterialFunctionCall":
            ins = list(POM_INPUTS) if b.props.get("material_function") == bss.POM_FN else []
        else:
            ins = INPUTS.get(b.cls, [])
        key = ins[0] if (bi == "" and ins) else bi
        if key not in ins:
            return False
        b.inputs[key] = (a, ao)
        return True

    def get_material_expression_input_names(self, n):
        return list(POM_INPUTS)

    def connect_material_property(self, n, out, prop):
        self.props.append((n, out, prop._n.split(".")[-1]))
        return True

    def recompile_material(self, mat):
        self.compiled += 1
        return []


class AssetPath(str):
    """A loaded asset: compares equal to its path, takes editor properties."""

    def set_editor_property(self, k, v):
        pass


class FakeEAL:
    def does_asset_exist(self, p):
        return True

    def load_asset(self, p):
        return AssetPath(p)

    def save_loaded_asset(self, a, only_dirty=True):
        return True


class FakeMaterialUnreal(FakeUnreal):
    def __getattr__(self, k):
        if k.startswith("MaterialExpression"):
            return ExprClass(k)
        return super().__getattr__(k)


def run_script(monkeypatch, fake, script):
    monkeypatch.setitem(sys.modules, "unreal", fake)
    exec(compile(script, "editor_script", "exec"), {"__name__": "editor_script"})


def build_material(monkeypatch, capsys):
    mel = FakeMEL()
    fake = FakeMaterialUnreal(MaterialEditingLibrary=mel, EditorAssetLibrary=FakeEAL(), LinearColor=lambda *c: tuple(c))
    outs = []
    for _label, s in bss.material_scripts():
        run_script(monkeypatch, fake, s)
        outs.append(capsys.readouterr().out)
    return mel, outs


def translate(mel):
    errors, memo = [], {}

    def size(node, out):
        k = (id(node), out)
        if k in memo:
            return memo[k]
        cls = node.cls
        if cls == "MaterialExpressionMaterialFunctionCall":
            for name in POM_REQUIRED:
                if name not in node.inputs:
                    errors.append(f"POM: {name} not connected")
            for name, want in POM_INPUTS.items():
                if name in node.inputs:
                    got = size(*node.inputs[name])
                    if got != want and not (want in (1, 2, 3, 4) and got == 1 and want == 1):
                        errors.append(f"POM {name}: got {got}, wants {want}")
            w = POM_OUTPUTS[out]
        elif cls in OUTPUTS:
            w = OUTPUTS[cls][out]
            if "UVs" in node.inputs and size(*node.inputs["UVs"]) != 2:
                errors.append(f"{cls}: UVs must be float2")
        else:
            def inp(name, required=False):
                if name in node.inputs:
                    return size(*node.inputs[name])
                if required:
                    errors.append(f"{cls}: missing input {name}")
                return 1

            short = cls[len("MaterialExpression"):]
            if short in BINARY or short == "LinearInterpolate":
                req = short in ("Fmod", "DotProduct")
                a, b = inp("A", req), inp("B", req)
                if a != b and 1 not in (a, b):
                    errors.append(f"{cls}: float{a} with float{b}")
                w = 1 if short == "DotProduct" else max(a, b)
                if short == "LinearInterpolate":
                    t = inp("Alpha")
                    if t not in (1, w):
                        errors.append(f"{cls}: alpha float{t} for float{w}")
            elif short == "ComponentMask":
                src = inp("Input", True)
                flags = [bool(node.props.get(c)) for c in "rgba"]
                if any(f and i >= src for i, f in enumerate(flags)):
                    errors.append("ComponentMask: not enough components in float%d" % src)
                w = sum(flags)
            elif short == "Clamp":
                w = inp("Input", True)
                for m in ("Min", "Max"):
                    if m in node.inputs and inp(m) not in (1, w):
                        errors.append(f"Clamp {m}: size")
            elif short in UNARY:
                w = inp("Input", True)
            elif short == "AppendVector":
                w = inp("A", True) + inp("B", True)
            elif short == "StaticSwitchParameter":
                a, b = inp("True", True), inp("False", True)
                if a != b:
                    errors.append("StaticSwitch: True and False differ")
                w = a
            else:
                raise AssertionError(f"no model for {cls}")
        if not isinstance(w, int) and cls not in ("MaterialExpressionTextureObjectParameter", "MaterialExpressionStaticBool"):
            errors.append(f"{cls}: non-numeric {w}")
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
    unused = [n.get_editor_property("desc") for n in mel.nodes if id(n) not in reached]
    return errors, unused


# ------------------------------------------------------------------------------------------------ 2
def test_material_graph_translates(monkeypatch, capsys):
    mel, outs = build_material(monkeypatch, capsys)
    assert "nodes=0 " in outs[0]
    for o in outs:
        if "links chunk" in o:
            assert "bad=[]" in o, o
    assert "props=[True, True, True, True, True]" in outs[-1] and "errors=0 " in outs[-1], outs[-1]
    errors, unused = translate(mel)
    assert errors == [], errors
    assert unused == [], unused
    assert sorted(p for _, _, p in mel.props) == sorted(PROPERTY_SIZES)


def test_pom_is_wired_as_the_design_says(monkeypatch, capsys):
    mel, _ = build_material(monkeypatch, capsys)
    by = {n.get_editor_property("desc"): n for n in mel.nodes}
    pom = by["pom"]
    assert pom.props["material_function"] == bss.POM_FN
    assert pom.inputs["Heightmap Texture"][0].props["texture"] == bss.TEX_H
    assert pom.inputs["Heightmap Channel"][0].props["constant"] == (1.0, 0.0, 0.0, 0.0)   # G8 samples into R
    assert pom.inputs["Render Shadows (Occlusion Mapping)"][0].props["value"] is False
    assert pom.inputs["Reference Plane"][0].props["r"] == 1.0
    assert by["usepom"].inputs["True"][0] is by["pclamp"]      # parallax UVs, clamped to the cell
    for t in ("hs", "hb", "ns"):
        assert by[t].inputs["UVs"][0] is by["usepom"]
    assert by["hb"].props["mip_value_mode"]._n == "TextureMipValueMode.TMVM_MIP_BIAS"


def test_custom_primitive_data_layout(monkeypatch, capsys):
    mel, _ = build_material(monkeypatch, capsys)
    cpd = {n.props["parameter_name"]: n.props["primitive_data_index"] for n in mel.nodes
           if n.props.get("use_custom_primitive_data")}
    assert cpd == {"Wear": 0, "Cell": 1, "ScanStart": 2, "ScanMode": 3, "CellRect": 4, "GlowHoldS": 8}
    names = [n.props.get("parameter_name") for n in mel.nodes if n.props.get("parameter_name")]
    assert len(names) == len(set(names)), "duplicate parameter names"


# ------------------------------------------------------------------------------------------------ 3
class Pkg:
    def __init__(self, name):
        self.name, self.dirty = name, False

    def get_name(self):
        return self.name


class Named:
    def __init__(self, n):
        self.n = n

    def get_name(self):
        return self.n


class FakeComp:
    def __init__(self, actor):
        self.actor, self.cpd = actor, [actor.wear]

    def modify(self, always=True):
        self.actor.pkg.dirty = True

    def set_default_custom_primitive_data_float(self, i, v):   # no Modify: does not dirty the package
        while len(self.cpd) <= i:
            self.cpd.append(0.0)
        self.cpd[i] = v

    def get_editor_property(self, k):
        assert k == "custom_primitive_data"
        return types.SimpleNamespace(get_editor_property=lambda _k: list(self.cpd))

    def get_num_materials(self):
        return 2

    def get_material(self, i):
        return Named(["MI_Stele_Body", self.actor.face][i])


class FakeActor:
    def __init__(self, label, wear, face="MI_SteleFace"):
        self.label, self.wear, self.face = label, wear, face
        self.pkg = Pkg("/Game/__ExternalActors__/" + label)
        self.tags = ["OtherTag"]
        self.static_mesh_component = FakeComp(self)
        self.saved = None

    def get_actor_label(self):
        return self.label

    def get_package(self):
        return self.pkg

    def modify(self, always=True):
        self.pkg.dirty = True

    def get_editor_property(self, k):
        assert k == "tags"
        return list(self.tags)

    def set_editor_property(self, k, v):                     # PreEditChange -> Modify: dirties
        assert k == "tags"
        self.pkg.dirty = True
        self.tags = [str(t) for t in v]


class FakeLevel:
    def __init__(self, data):
        self.actors = [FakeActor(s["id"], s["wear"]) for s in data["steles"]]
        self.actors += [FakeActor(s["id"] + "_Glyph", 0.0) for s in data["steles"][:3]]
        self.disk = {}

    def get_all_level_actors(self):
        return list(self.actors)

    def get_dirty_map_packages(self):
        return [a.pkg for a in self.actors if a.pkg.dirty]

    def save_packages(self, pkgs, only_dirty):
        for p in pkgs:
            if p.dirty or not only_dirty:
                a = next(x for x in self.actors if x.pkg is p)
                self.disk[a.label] = (list(a.tags), list(a.static_mesh_component.cpd))
                p.dirty = False
        return True

    def reload(self):
        for a in self.actors:
            if a.label in self.disk:
                a.tags, a.static_mesh_component.cpd = [list(x) for x in self.disk[a.label]]
            else:
                a.tags, a.static_mesh_component.cpd = ["OtherTag"], [a.wear]
            a.pkg.dirty = False


def level_unreal(level):
    return FakeUnreal(get_editor_subsystem=lambda cls: level, EditorActorSubsystem=Any("EAS"),
                      EditorLoadingAndSavingUtils=level, Name=str)


def run_level_steps(monkeypatch, capsys, level, script_filter=lambda s: s):
    items = bss.cpd_items()
    fake = level_unreal(level)
    outs = []
    for i in range(0, len(items), bss.CPD_CHUNK):
        run_script(monkeypatch, fake, script_filter(bss.fill(bss.CPD, ITEMS=repr(items[i:i + bss.CPD_CHUNK]))))
        outs.append(capsys.readouterr().out)
    for chunk in range(2):
        run_script(monkeypatch, fake, bss.fill(bss.SAVE, CHUNK=chunk, SIZE=bss.SAVE_CHUNK))
        outs.append(capsys.readouterr().out)
    level.reload()
    run_script(monkeypatch, fake, bss.fill(bss.VERIFY, ITEMS=repr(items), FACE=bss.MI_NAME))
    outs.append(capsys.readouterr().out)
    return outs


def test_cpd_save_verify_round_trip(monkeypatch, capsys):
    level = FakeLevel(bss.load_data())
    outs = run_level_steps(monkeypatch, capsys, level)
    assert all("missing=[] not_dirty=[]" in o for o in outs[:3]), outs[:3]
    assert "SAVE total=36 " in outs[3] and "left_dirty=[]" in outs[3]
    assert "VERIFY count=36 problems=0" in outs[-1], outs[-1]
    glyph = next(a for a in level.actors if a.label.endswith("_Glyph"))
    assert glyph.label not in level.disk                      # the old decals are never touched
    a = next(a for a in level.actors if a.label == "Stele_WayStone_12")
    assert a.tags == ["OtherTag", "Stele", "Stele_WayStone_12"]
    assert len(a.static_mesh_component.cpd) == bss.CPD_COUNT


def test_without_modify_the_save_writes_nothing(monkeypatch, capsys):
    level = FakeLevel(bss.load_data())
    strip = lambda s: s.replace("    s.modify()\n    c.modify()\n", "").replace(  # noqa: E731
        '    s.set_editor_property("tags", keep + [unreal.Name(t) for t in it["tags"]])\n', "")
    outs = run_level_steps(monkeypatch, capsys, level, strip)
    assert "not_dirty=[]" not in outs[0]
    assert "VERIFY count=36 problems=0" not in outs[-1]


def test_cpd_items_follow_the_data():
    items = bss.cpd_items()
    data = bss.load_data()
    assert len(items) == 36
    by = {s["id"]: s for s in data["steles"]}
    cells = {r["id"]: r["atlas_cell"] for r in data["inscriptions"]}
    for it in items:
        s = by[it["id"]]
        assert len(it["cpd"]) == bss.CPD_COUNT
        assert it["cpd"][0] == s["wear"] and it["cpd"][1] == cells[s["inscription"]]
        assert it["cpd"][4:8] == data["meshes"][s["mesh"]]["cell_rect_uv1"]
        assert it["cpd"][2] == it["cpd"][3] == it["cpd"][8] == 0.0   # runtime slots start idle


# ------------------------------------------------------------------------------------------------ 4
def test_runner_pass_conditions(monkeypatch):
    replies = []
    monkeypatch.setattr(bss, "python_run", lambda s: (True, replies.pop(0), ""))
    monkeypatch.setattr(bss, "refuse_readonly", lambda *a: None)
    ok_material = (["SCANMAT create nodes=0 nanite=True"] + ["SCANMAT nodes chunk=0 made=1 total=1"] * 5
                   + ["SCANMAT links chunk=0 n=1 bad=[] pom_inputs=[]"] * 3
                   + ["SCANMAT compile nodes=170 props=[True, True, True, True, True] errors=0 first_errors=[] saved=True"])
    replies[:] = list(ok_material)
    assert bss.main(["material"]) == 0
    replies[:] = ok_material[:-1] + [ok_material[-1].replace("errors=0", "errors=2")]
    with pytest.raises(SystemExit, match="errors=0"):
        bss.main(["material"])
    replies[:] = ok_material[:6] + ["SCANMAT links chunk=0 n=1 bad=['pom>pclamp.'] pom_inputs=[]"] + ok_material[7:]
    with pytest.raises(SystemExit, match="bad="):
        bss.main(["material"])
    replies[:] = ["CPD done=11 missing=['Stele_WayStone_3'] not_dirty=[]"]
    with pytest.raises(SystemExit, match="missing"):
        bss.main(["cpd"])
    replies[:] = ["RESIDENT loaded=0 dirty=0 dirty_labels=[]", "LOAD steles descs=36 loaded_now=24",
                  "LOAD steles descs=36 loaded_now=12", "VERIFY count=36 problems=1 first=['x']", "UNLOAD 36"]
    with pytest.raises(SystemExit, match="verify"):
        bss.main(["verify"])
