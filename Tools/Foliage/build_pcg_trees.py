"""Build the tier-1 tree PCG graphs (world sprint, Task V5; rulings R4, R5, R21, R39).

    python Tools/Foliage/build_pcg_trees.py build          # (re)build both graphs in the live editor
    python Tools/Foliage/build_pcg_trees.py spec           # print the graph specs offline (no editor)

Hold the editor gate (Tools/GameFlow/editor_gate.py) for `build`. Nothing is saved here:
save the two graphs with Tools/Foliage/save_packages.py, by explicit list.

Two assets in /Game/SaskartaGaea/PCG/:

- `PCGSub_TreePoints` (Ruling R4): the deterministic tree points, shared with
  PCG_Ecology_Shrubs (V6) for competition. Output points carry `Species` (string,
  DeadPine_A..E or Ginkgo_A..D), `PatchScale` (0.25-1.4) and `IsParent` (bool).
- `PCG_Ecology_Trees`: runs the subgraph, maps Species to the mesh and spawns every
  point ONCE, through one static spawner (Ruling R39, which replaced R24 after skinned
  DynamicWind trees hung the GPU twice): the static stand-in SM_Saskarta_TreeFar_<Species>
  (Nanite off, LOD0-LOD3) at ALL distances, min draw 0, cull 25000-30000 cm, WPO wind
  (SaskartaWind in the stand-in tree master) within 6000 cm. No skinned spawner. The tree
  points also go to the graph Output, which is the exported TreeCanopy input for V6
  (V6 measures PCG Distance against them).

Pipeline in the subgraph (brief step 2, B+ numbers):
  1. Get Landscape Data -> Surface Sampler, 0.0035 x 1.6 = 0.0056 points/m2, looseness 1
     (jittered grid; stock PCG has no Poisson sampler) -> parent candidates.
  2. Sample Texture T_Saskarta_Ecology and T_Saskarta_RoadInfluence with the MASKS.md
     world mapping (texture data absolute transform centred on the map, scale = half the
     extent; never T_Gaea_*, Ruling R21).
  3. Suitability, all in attribute nodes:
       forestPrior = saturate((moisture + macro - FP_THRESHOLD) / 0.4)   (R21 stand-in for T_Gaea_Forest)
       suit = saturate(0.6 forestPrior + 0.6 moisture - 0.9 exposure) * macro
              * (1 - core) * (1 - 0.85 verge (1 - neglect))
  4. Keep a parent when Roll < suit (Roll = attribute noise 0..1).
  5. 7 children per parent (Copy Points). Offset = the sum of two uniform +-1.225 sigma
     offsets per axis, which has standard deviation sigma = 9 x 1.3 = 11.7 m and a
     triangular falloff with distance (the brief's "+-2 sigma with a density falloff",
     without discarding 64 % of the children). Children are projected onto the landscape.
     PatchScale = clamp(1.2 - r / (2.5 sigma), 0.25, 1.2); parents get 1.4.
  6. Children keep when Roll < saturate(CHILD_GAIN x suit at the child): a grove grows
     only into ground that can hold it (brief step 7, with a gain: suit is 0.05-0.4 in
     good valley ground, so an ungained test would strip the groves back to lone parents).
  7. Self Pruning, large to small by PatchScale, point bounds +-300 cm (radius 3 m): no
     two trunks closer than 6 m, which also keeps the spec's 4 m trunk clearance.
  8. Species: pine probability saturate((exposure + 0.5 zone - moisture + 0.3) / 0.3); dead
     pine on exposed high ground, ginkgo in the moist lowland. The roll is made on the parent
     and inherited, so a grove is mostly one kind. Variants by weight.
  9. Random yaw, scale 0.85-1.15 x (0.5 + 0.45 PatchScale).

The UV mapping is read from Tools/Terrain/MASKS.md (Ruling R5), never hardcoded.
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Tools" / "Road"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from prepare_road_material import mask_mapping  # noqa: E402
import check_pcg_culls  # noqa: E402

PCG_DIR = "/Game/SaskartaGaea/PCG"
SUB_PATH = PCG_DIR + "/PCGSub_TreePoints"
TREES_PATH = PCG_DIR + "/PCG_Ecology_Trees"
TEX_ECO = "/Game/SaskartaGaea/Masks/T_Saskarta_Ecology"
TEX_ROAD = "/Game/SaskartaGaea/Masks/T_Saskarta_RoadInfluence"

# B+ (spec: 1.6x the sketch's parents, 1.3x its spread)
PARENTS_PER_M2 = 0.0035 * 1.6
SIGMA_CM = 900.0 * 1.3
CHILDREN = 7
CHILD_HALF_CM = SIGMA_CM * 1.5 ** 0.5          # two uniform +-a offsets: sd = a * sqrt(2/3) = sigma
PATCH_ZERO_R_CM = (1.2 - 0.25) * 2.5 * SIGMA_CM  # where 1.2 - r/(2.5 sigma) reaches the 0.25 floor
PARENT_PATCH_SCALE = 1.4
PINE_BIAS_LO, PINE_BIAS_HI = -0.3, 0.0   # pine probability = saturate((PB - LO) / (HI - LO)), PB = exposure + 0.5 zone - moisture
FP_THRESHOLD = 1.0          # B+ density (V5 redo): 0.9 gave about 5x sketch B; 1.0 about halves it.
#                            forestPrior = saturate((moisture + macro - FP_THRESHOLD) / 0.4)
CHILD_GAIN = 4.0
PRUNE_HALF_CM = 300.0

# Ruling R39 (cm): the static stand-in is the only tree, near and far.
TREE_MIN_DRAW = 0.0                         # drawn from the camera out
TREE_CULL = (25000.0, 30000.0)              # start, end (spec tier 1: 250-300 m, then HLOD)
TREE_WPO_DISABLE = 6000.0                   # SaskartaWind WPO runs within 60 m only

MEGA = "/Game/Megaplant_Library"
SPECIES = {
    # name: (group, weight, native skeletal mesh, DynamicWind data). Since R39 only the
    # group and weight are used: the mesh is far_mesh(name). The native columns are kept
    # as a record of which Megaplant each stand-in was baked from (Tools/Foliage/convert_to_static.py).
    "DeadPine_A": ("pine", 3, MEGA + "/Tree_Dead_Pine/Tree_Dead_Pine_01/Tree_Dead_Pine_A", "/Game/SaskartaGaea/Foliage/DWD_Tree_Dead_Pine_A"),
    "DeadPine_B": ("pine", 3, MEGA + "/Tree_Dead_Pine/Tree_Dead_Pine_01/Tree_Dead_Pine_B", "/Game/SaskartaGaea/Foliage/DWD_Tree_Dead_Pine_B"),
    "DeadPine_C": ("pine", 3, MEGA + "/Tree_Dead_Pine/Tree_Dead_Pine_01/Tree_Dead_Pine_C", "/Game/SaskartaGaea/Foliage/DWD_Tree_Dead_Pine_C"),
    "DeadPine_D": ("pine", 3, MEGA + "/Tree_Dead_Pine/Tree_Dead_Pine_01/Tree_Dead_Pine_D", "/Game/SaskartaGaea/Foliage/DWD_Tree_Dead_Pine_D"),
    "DeadPine_E": ("pine", 2, MEGA + "/Tree_Dead_Pine/Tree_Dead_Pine_01/Tree_Dead_Pine_E", "/Game/SaskartaGaea/Foliage/DWD_Tree_Dead_Pine_E"),
    "Ginkgo_A": ("ginkgo", 1, MEGA + "/Tree_Ginkgo/Tree_Ginkgo_01/Tree_Ginkgo_01_A", "/Game/SaskartaGaea/Foliage/DWD_Saskarta_Ginkgo_A"),
    "Ginkgo_B": ("ginkgo", 1, MEGA + "/Tree_Ginkgo/Tree_Ginkgo_01/Tree_Ginkgo_01_B", "/Game/SaskartaGaea/Foliage/DWD_Tree_Ginkgo_01_B"),
    "Ginkgo_C": ("ginkgo", 1, MEGA + "/Tree_Ginkgo/Tree_Ginkgo_01/Tree_Ginkgo_01_C", "/Game/SaskartaGaea/Foliage/DWD_Tree_Ginkgo_01_C"),
    "Ginkgo_D": ("ginkgo", 1, MEGA + "/Tree_Ginkgo/Tree_Ginkgo_01/Tree_Ginkgo_01_D", "/Game/SaskartaGaea/Foliage/DWD_Tree_Ginkgo_01_D"),
}


# LANE4 (user-approved 2026-09-28): the ginkgo stand-ins' leaves were conversion quads with no usable
# cut-out ("some trees have very bad looking leaves"), so the ginkgo species draw the MedievalVillage
# pines instead: masked two-sided foliage cards, 2.6k / 4.2k triangles, 4 LODs, instancing-ready.
MESH_OVERRIDE = {
    "Ginkgo_A": "/Game/MedievalVillage/Demo/StaticMesh/Trees/Pine/SM_PineTree_01",
    "Ginkgo_B": "/Game/MedievalVillage/Demo/StaticMesh/Trees/Pine/SM_PineTree_02",
    "Ginkgo_C": "/Game/MedievalVillage/Demo/StaticMesh/Trees/Pine/SM_PineTree_01",
    "Ginkgo_D": "/Game/MedievalVillage/Demo/StaticMesh/Trees/Pine/SM_PineTree_02",
}


def far_mesh(name):
    return MESH_OVERRIDE.get(name, f"/Game/SaskartaGaea/Foliage/Static/SM_Saskarta_TreeFar_{name}")


def obj_path(path):
    """Package path -> full object path, the form the mesh selectors read."""
    return path + "." + path.rsplit("/", 1)[-1]


# ---------------------------------------------------------------- spec helpers
def sel(name):
    return {"sel": name}


def enum(qualified):
    return {"enum": qualified}


def const(kind, value):
    """FPCGMetadataTypesConstantStruct text."""
    if kind == "Double":
        return {"text": f"(Type=Double,DoubleValue={float(value):.6f})"}
    if kind == "Boolean":
        return {"text": f"(Type=Boolean,BoolValue={'True' if value else 'False'})"}
    if kind == "String":
        return {"text": f'(Type=String,StringValue="{value}")'}
    raise ValueError(kind)


class Spec:
    """A graph as data: nodes with property paths, and edges by pin label."""

    def __init__(self, path):
        self.path = path
        self.nodes = []
        self.edges = []
        self.col = {}

    def node(self, cls, props=None, calls=None, lane=0):
        nid = f"n{len(self.nodes)}"
        x = self.col.get(lane, 0)
        self.col[lane] = x + 1
        self.nodes.append({"id": nid, "cls": cls, "props": props or {}, "calls": calls or [], "pos": [x * 320, lane * 260]})
        return nid

    def edge(self, a, apin, b, bpin):
        self.edges.append([a, apin, b, bpin])

    # One-input attribute ops. `src` is the upstream node id; returns the new node id.
    def maths(self, src, op, out, a, b=None, lane=0, pin="Out"):
        props = {"operation": enum("PCGMetadataMathsOperation." + op), "input_source1": sel(a), "output_target": sel(out)}
        if b is not None:
            props["input_source2"] = sel(b)
        n = self.node("PCGMetadataMathsSettings", props, lane=lane)
        if b is None:                       # unary ops (ONE_MINUS ...) have a single "In" pin
            self.edge(src, pin, n, "In")
        else:
            self.edge(src, pin, n, "InA")
            self.edge(src, pin, n, "InB")
        return n

    def copy_attr(self, src, a, out, lane=0, pin="Out"):
        """out = a (Copy Attributes within the same data: both pins fed by src)."""
        n = self.node("PCGCopyAttributesSettings", {"input_source": sel(a), "output_target": sel(out)}, lane=lane)
        self.edge(src, pin, n, "Target")
        self.edge(src, pin, n, "Source")
        return n

    def remap(self, src, a, out, lo, hi, out_lo, out_hi, clamp, lane=0):
        """out = lerp(out_lo, out_hi, (a - lo) / (hi - lo)), extrapolated outside [lo, hi].

        clamp=True clamps the OUTPUT to [0, 1] (that is what Remap's clamp_to_unit_range
        does, measured: it does not clamp the lerp factor). Use it only for saturate()
        with an output range inside [0, 1].
        """
        n = self.node("PCGAttributeRemapSettings", {
            "input_source": sel(a), "output_target": sel(out), "mode": enum("PCGAttributeRemapMode.RANGES"),
            "range_min": lo, "range_max": hi, "out_range_min": out_lo, "out_range_max": out_hi,
            "clamp_to_unit_range": clamp, "ignore_values_outside_input_range": False}, lane=lane)
        self.edge(src, "Out", n, "In")
        return n

    def add_const(self, src, out, kind, value, lane=0):
        n = self.node("PCGAddAttributeSettings", {"output_target": sel(out), "attribute_types": const(kind, value)}, lane=lane)
        self.edge(src, "Out", n, "In")
        return n

    def noise(self, src, out, seed, lane=0):
        n = self.node("PCGAttributeNoiseSettings", {
            "input_source": sel("$Density"), "output_target": sel(out), "mode": enum("PCGAttributeNoiseMode.SET"),
            "noise_min": 0.0, "noise_max": 1.0, "seed": seed}, lane=lane)
        self.edge(src, "Out", n, "In")
        return n

    def keep_positive(self, src, attr, lane=0):
        """Attribute Filter attr > 0 (constant threshold). Returns (node, 'InsideFilter')."""
        n = self.node("PCGAttributeFilteringSettings", {
            "target_attribute": sel(attr), "operator": enum("PCGAttributeFilterOperator.GREATER"),
            "use_constant_threshold": True, "attribute_types": const("Double", 0.0)}, lane=lane)
        self.edge(src, "Out", n, "In")
        return n

    def to_json(self):
        return {"path": self.path, "nodes": self.nodes, "edges": self.edges}


# Sample Texture writes the texel into $Color and leaves $Density alone (IGNORE): the
# default SET/MULTIPLY would write one channel into the density, and the next filter would
# drop every point where that channel is 0 (RoadInfluence alpha is 0 off the paving).
SAMPLE_TEX = {"texture_mapping_method": enum("PCGTextureMappingMethod.PLANAR"),
              "density_merge_function": enum("PCGDensityMergeOperation.IGNORE")}


def suitability(g, src, landscape_free_tex, gain, seed, lane):
    """Sample both masks at the points of `src`, compute Suit, and keep Roll < gain*Suit.

    Returns the id of the Attribute Filter node (keep on its 'InsideFilter' pin).
    """
    eco_tex, road_tex = landscape_free_tex
    s = g.node("PCGSampleTextureSettings", SAMPLE_TEX, lane=lane)
    g.edge(src, "Out", s, "Point")
    g.edge(eco_tex, "Out", s, "BaseTexture")
    n = g.copy_attr(s, "$Color", "Eco", lane=lane)                 # moisture, exposure, zone, macro
    s2 = g.node("PCGSampleTextureSettings", SAMPLE_TEX, lane=lane)
    g.edge(n, "Out", s2, "Point")
    g.edge(road_tex, "Out", s2, "BaseTexture")
    n = g.copy_attr(s2, "$Color", "Road", lane=lane)               # core, verge, neglect, surface
    n = g.maths(n, "ADD", "FP0", "Eco.R", "Eco.A", lane=lane)
    n = g.remap(n, "FP0", "FP", FP_THRESHOLD, FP_THRESHOLD + 0.4, 0.0, 1.0, True, lane=lane)
    n = g.maths(n, "ADD", "SA", "FP", "Eco.R", lane=lane)            # forestPrior + moisture
    n = g.remap(n, "Eco.G", "SB", 0.0, 1.0, 0.0, 1.5, False, lane=lane)     # 1.5 exposure
    n = g.maths(n, "SUBTRACT", "SC", "SA", "SB", lane=lane)
    n = g.remap(n, "SC", "SRaw", 0.0, 1.0 / 0.6, 0.0, 1.0, True, lane=lane)  # saturate(0.6 SC)
    n = g.maths(n, "MULTIPLY", "S1", "SRaw", "Eco.A", lane=lane)      # x macro
    n = g.maths(n, "ONE_MINUS", "R1", "Road.R", lane=lane)             # 1 - core
    n = g.maths(n, "ONE_MINUS", "NN", "Road.B", lane=lane)             # 1 - neglect
    n = g.maths(n, "MULTIPLY", "VN", "Road.G", "NN", lane=lane)       # verge (1 - neglect)
    n = g.remap(n, "VN", "R2", 0.0, 1.0, 1.0, 0.15, False, lane=lane)        # 1 - 0.85 VN
    n = g.maths(n, "MULTIPLY", "S2", "S1", "R1", lane=lane)
    n = g.maths(n, "MULTIPLY", "Suit", "S2", "R2", lane=lane)
    keep_on = "Suit"
    if gain != 1.0:
        n = g.remap(n, "Suit", "SuitG", 0.0, 1.0 / gain, 0.0, 1.0, True, lane=lane)
        keep_on = "SuitG"
    n = g.noise(n, "Roll", seed, lane=lane)
    n = g.maths(n, "SUBTRACT", "Keep", keep_on, "Roll", lane=lane)
    return g.keep_positive(n, "Keep", lane=lane)


def sub_spec(origin, extent):
    g = Spec(SUB_PATH)
    half = extent / 2.0
    xf = {"xf": [[origin[0] + half, origin[1] + half, 0.0], [0.0, 0.0, 0.0], [half, half, 1.0]]}
    tex = []
    for path in (TEX_ECO, TEX_ROAD):
        tex.append(g.node("PCGTextureSamplerSettings", {
            "texture": {"asset": path}, "use_absolute_transform": True, "transform": xf,
            "filter": enum("PCGTextureFilter.BILINEAR"),
            # the texture data's own density is one channel; keep texels where it is 0
            "keep_zero_density_points": True}, lane=4))
    land = g.node("PCGGetLandscapeSettings", {}, lane=0)
    samp = g.node("PCGSurfaceSamplerSettings", {
        "points_per_squared_meter": PARENTS_PER_M2, "looseness": 1.0,
        "point_extents": {"vec": [100.0, 100.0, 100.0]}}, lane=0)
    g.edge(land, "Out", samp, "Surface")
    parents = suitability(g, samp, tex, 1.0, 101, lane=0)
    p = g.copy_attr(parents, "$Position", "ParentPos", lane=0, pin="InsideFilter")
    p = g.noise(p, "SpeciesRoll", 503, lane=0)      # on the parent: its children inherit it, so groves stay one kind
    # children
    tmpl = g.node("PCGCreatePointsSettings", {"points_to_create": {"elem": "PCGPoint", "texts": [
        f"(Transform=(Translation=(X={i + 1}.0,Y=0.0,Z=0.0)),Density=1.000000,Steepness=0.500000,Seed={7919 * (i + 1)})"
        for i in range(CHILDREN)]}}, lane=1)
    cp = g.node("PCGCopyPointsSettings", {
        "attribute_inheritance": enum("PCGCopyPointsMetadataInheritanceMode.TARGET_ONLY")}, lane=1)
    g.edge(tmpl, "Out", cp, "Source")
    g.edge(p, "Out", cp, "Target")
    c = cp
    for seed in (211, 307):
        t = g.node("PCGTransformPointsSettings", {
            "offset_min": {"vec": [-CHILD_HALF_CM, -CHILD_HALF_CM, 0.0]}, "offset_max": {"vec": [CHILD_HALF_CM, CHILD_HALF_CM, 0.0]},
            "absolute_offset": True, "rotation_max": {"rot": [0.0, 0.0, 0.0]},
            "scale_min": {"vec": [1.0, 1.0, 1.0]}, "scale_max": {"vec": [1.0, 1.0, 1.0]}, "seed": seed}, lane=1)
        g.edge(c, "Out", t, "In")
        c = t
    d = g.node("PCGMetadataVectorSettings", {"operation": enum("PCGMetadataVectorOperation.DISTANCE"),
                                             "input_source1": sel("$Position"), "input_source2": sel("ParentPos"),
                                             "output_target": sel("R")}, lane=1)
    g.edge(c, "Out", d, "InA")
    g.edge(c, "Out", d, "InB")
    c = g.remap(d, "R", "PatchT", 0.0, PATCH_ZERO_R_CM, 1.0, 0.0, True, lane=1)     # saturate(1 - r / r0)
    c = g.remap(c, "PatchT", "PatchScale", 0.0, 1.0, 0.25, 1.2, False, lane=1)
    c = g.add_const(c, "IsParent", "Boolean", False, lane=1)
    proj = g.node("PCGProjectionSettings", {"projection_params": {"text": "(bProjectPositions=True,bProjectRotations=False,bProjectScales=False)"}}, lane=1)
    g.edge(c, "Out", proj, "In")
    g.edge(land, "Out", proj, "Projection Target")
    kids = suitability(g, proj, tex, CHILD_GAIN, 409, lane=2)
    # parents' own attributes
    pp = g.add_const(p, "PatchScale", "Double", PARENT_PATCH_SCALE, lane=3)
    pp = g.add_const(pp, "IsParent", "Boolean", True, lane=3)
    merge = g.node("PCGMergeSettings", {}, lane=3)
    g.edge(pp, "Out", merge, "In")
    g.edge(kids, "InsideFilter", merge, "In")
    b = g.node("PCGBoundsModifierSettings", {"mode": enum("PCGBoundsModifierMode.SET"),
                                             "bounds_min": {"vec": [-PRUNE_HALF_CM, -PRUNE_HALF_CM, -100.0]},
                                             "bounds_max": {"vec": [PRUNE_HALF_CM, PRUNE_HALF_CM, 100.0]}}, lane=3)
    g.edge(merge, "Out", b, "In")
    pr = g.node("PCGSelfPruningSettings", {"parameters": {"sub": {
        "pruning_type": enum("PCGSelfPruningType.LARGE_TO_SMALL"), "comparison_source": sel("PatchScale"),
        "radius_similarity_factor": 0.25, "randomized_pruning": True}}}, lane=3)
    g.edge(b, "Out", pr, "In")
    # species: pine probability saturate(2 (exposure + 0.5 zone - moisture))
    n = g.remap(pr, "Eco.B", "HZ", 0.0, 1.0, 0.0, 0.5, False, lane=3)
    n = g.maths(n, "ADD", "PA", "Eco.G", "HZ", lane=3)
    n = g.maths(n, "SUBTRACT", "PB", "PA", "Eco.R", lane=3)
    n = g.remap(n, "PB", "PineP", PINE_BIAS_LO, PINE_BIAS_HI, 0.0, 1.0, True, lane=3)
    n = g.maths(n, "SUBTRACT", "PineKeep", "PineP", "SpeciesRoll", lane=3)
    split = g.keep_positive(n, "PineKeep", lane=3)
    joined = g.node("PCGMergeSettings", {}, lane=5)
    for pin, group in (("InsideFilter", "pine"), ("OutsideFilter", "ginkgo")):
        entries = [f'(Value=(Type=String,StringValue="{name}"),Weight={w})'
                   for name, (grp, w, _, _) in SPECIES.items() if grp == group]
        m = g.node("PCGPointMatchAndSetSettings", {
            "set_target": sel("Species"), "set_target_type": enum("PCGMetadataTypes.STRING"),
            "match_and_set_instance/entries": {"elem": "PCGMatchAndSetWeightedEntry", "texts": entries}},
            calls=[["set_match_and_set_type", {"cls": "PCGMatchAndSetWeighted"}]], lane=5)
        g.edge(split, pin, m, "In")
        g.edge(m, "Out", joined, "In")
    t = g.node("PCGTransformPointsSettings", {
        "rotation_max": {"rot": [0.0, 360.0, 0.0]}, "scale_min": {"vec": [0.85, 0.85, 0.85]},
        "scale_max": {"vec": [1.15, 1.15, 1.15]}, "uniform_scale": True, "seed": 601}, lane=5)
    g.edge(joined, "Out", t, "In")
    n = g.remap(t, "PatchScale", "SizeK", 0.0, PARENT_PATCH_SCALE, 0.5, 0.5 + 0.45 * PARENT_PATCH_SCALE, False, lane=5)
    n = g.maths(n, "MULTIPLY", "$Scale", "$Scale", "SizeK", lane=5)
    g.edge(n, "Out", "OUT", "Out")
    return g


def trees_spec():
    g = Spec(TREES_PATH)
    sub = g.node("PCGSubgraphSettings", {}, calls=[["set_subgraph", {"asset": SUB_PATH}]], lane=0)
    g.edge(sub, "Out", "OUT", "Out")                                    # exported tree points (TreeCanopy for V6)
    entries = [f'(ValueToMatch=(Type=String,StringValue="{k}"),Value=(Type=String,StringValue="{obj_path(far_mesh(k))}"))'
               for k in SPECIES]
    m = g.node("PCGPointMatchAndSetSettings", {
        "set_target": sel("TreeMesh"), "set_target_type": enum("PCGMetadataTypes.STRING"),
        "match_and_set_instance/match_source_attribute": {"name": "Species"},
        "match_and_set_instance/match_source_type": enum("PCGMetadataTypes.STRING"),
        "match_and_set_instance/entries": {"elem": "PCGMatchAndSetByAttributeEntry", "texts": entries}},
        calls=[["set_match_and_set_type", {"cls": "PCGMatchAndSetByAttribute"}]], lane=0)
    g.edge(sub, "Out", m, "In")
    spawn = g.node("PCGStaticMeshSpawnerSettings", {
        "mesh_selector_parameters/attribute_name": {"name": "TreeMesh"},
        "mesh_selector_parameters/template_descriptor": {"sub": {
            "instance_min_draw_distance": TREE_MIN_DRAW,
            "instance_start_cull_distance": TREE_CULL[0], "instance_end_cull_distance": TREE_CULL[1],
            "visible_in_ray_tracing": True, "affect_distance_field_lighting": True, "cast_far_shadow": True,
            "world_position_offset_disable_distance": int(TREE_WPO_DISABLE)}}},
        calls=[["set_mesh_selector_type", {"cls": "PCGMeshSelectorByAttribute"}]], lane=1)
    g.edge(m, "Out", spawn, "In")
    return g


# ---------------------------------------------------------------- editor side
# The spec is compiled here into plain editor Python: python_run forbids eval, try and
# getattr, so every class, enum and value is written out literally.
EDITOR_PRELUDE = r"""
import unreal
PATH = None

def imp(cur, text):
    cur.import_text(text)
    return cur

def mk_list(cls, texts):
    out = []
    for t in texts:
        e = cls()
        e.import_text(t)
        out.append(e)
    return out

def sub(cur, fns):
    for k in fns:
        cur.set_editor_property(k, fns[k](cur.get_editor_property(k)))
    return cur

def setp(obj, path, fn):
    parts = path.split('/')
    if len(parts) == 1:
        obj.set_editor_property(parts[0], fn(obj.get_editor_property(parts[0])))
        return
    child = obj.get_editor_property(parts[0])
    setp(child, '/'.join(parts[1:]), fn)
    if isinstance(child, unreal.StructBase):
        obj.set_editor_property(parts[0], child)

g = unreal.load_asset(PATH)
if g is None:
    folder, name = PATH.rsplit('/', 1)
    g = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, folder, unreal.PCGGraph, unreal.PCGGraphFactory())
keep = [g.get_input_node(), g.get_output_node()]
for n in list(g.get_editor_property('nodes')):
    if n not in keep:
        g.remove_node(n)
ids = {'IN': g.get_input_node(), 'OUT': g.get_output_node()}
bad = []

def labels(pins):
    return [str(p.get_editor_property('properties').get_editor_property('label')) for p in pins]

def edge(a, ap, b, bp):
    if ap not in labels(ids[a].output_pins) or bp not in labels(ids[b].input_pins):
        bad.append([a, ap, b, bp])
        return
    if g.add_edge(ids[a], ap, ids[b], bp) is None:
        bad.append([a, ap, b, bp])
"""


def value_code(v):
    """A spec value -> Python source of a one-argument function of the current value."""
    if isinstance(v, dict):
        if "sel" in v:
            return f"lambda c: imp(c, {('PCGBegin(' + v['sel'] + ')PCGEnd')!r})"
        if "text" in v:
            return f"lambda c: imp(c, {v['text']!r})"
        if "enum" in v:
            return f"lambda c: unreal.{v['enum']}"
        if "vec" in v:
            x, y, z = v["vec"]
            return f"lambda c: unreal.Vector({x!r}, {y!r}, {z!r})"
        if "rot" in v:
            p, y, r = v["rot"]
            return f"lambda c: unreal.Rotator(roll={r!r}, pitch={p!r}, yaw={y!r})"
        if "xf" in v:
            (lx, ly, lz), (p, y, r), (sx, sy, sz) = v["xf"]
            return (f"lambda c: unreal.Transform(unreal.Vector({lx!r}, {ly!r}, {lz!r}), "
                    f"unreal.Rotator(roll={r!r}, pitch={p!r}, yaw={y!r}), unreal.Vector({sx!r}, {sy!r}, {sz!r}))")
        if "asset" in v:
            return f"lambda c: unreal.load_asset({v['asset']!r})"
        if "cls" in v:
            return f"lambda c: unreal.{v['cls']}"
        if "name" in v:
            return f"lambda c: unreal.Name({v['name']!r})"
        if "texts" in v:
            return f"lambda c: mk_list(unreal.{v['elem']}, {v['texts']!r})"
        if "sub" in v:
            inner = ", ".join(f"{k!r}: {value_code(x)}" for k, x in v["sub"].items())
            return f"lambda c: sub(c, {{{inner}}})"
        raise ValueError(v)
    return f"lambda c: {v!r}"


def compile_spec(spec):
    lines = [fill(EDITOR_PRELUDE, "PATH", spec.path)]
    for n in spec.nodes:
        lines.append(f"node, s = g.add_node_of_type(unreal.{n['cls']})")
        lines.append(f"ids[{n['id']!r}] = node")
        lines.append(f"print('N {n['id']} {n['cls']}')")
        for name, arg in n["calls"]:
            lines.append(f"s.{name}({value_code(arg)[len('lambda c: '):]})")
        for k, v in n["props"].items():
            lines.append(f"setp(s, {k!r}, {value_code(v)})")
        lines.append("s.set_editor_property('enabled', True)")
        lines.append(f"node.set_node_position({n['pos'][0]}, {n['pos'][1]})")
    for a, ap, b, bp in spec.edges:
        lines.append(f"edge({a!r}, {ap!r}, {b!r}, {bp!r})")
    lines.append(f"print('BUILT ' + PATH + ' nodes ' + str(len(g.get_editor_property('nodes'))) + ' edges {len(spec.edges)} bad ' + str(bad))")
    return "\n".join(lines) + "\n"


def fill(script, name, value):
    return check_pcg_culls.fill(script, name, value)


def run(script):
    reply = check_pcg_culls.send(script)
    data = reply.get("data") or {}
    out = (data.get("stdout") or "") + (("\nSTDERR " + data["stderr"]) if data.get("stderr") else "")
    if not reply.get("ok"):
        out += "\nERROR " + str(reply.get("error"))[:1500]
    return reply.get("ok", False), out


def build(taps=()):
    """taps: debug only, [(node id, pin)] of the subgraph also wired to its Output."""
    origin, extent = mask_mapping(ROOT / "Tools" / "Terrain" / "MASKS.md")
    ok_all = True
    sub = sub_spec(origin, extent)
    for nid, pin in taps:
        sub.edge(nid, pin, "OUT", "Out")
    for spec in (sub, trees_spec()):
        ok, out = run(compile_spec(spec))
        print("\n".join(l for l in out.strip().splitlines() if not l.startswith("N ")) if ok else "FAILED " + out[-3000:])
        ok_all = ok_all and ok and "bad []" in out
    return 0 if ok_all else 1


def main(argv):
    cmd = argv[0] if argv else ""
    if cmd == "code":
        origin, extent = mask_mapping(ROOT / "Tools" / "Terrain" / "MASKS.md")
        print(compile_spec(sub_spec(origin, extent) if argv[1:] == ["sub"] else trees_spec()))
        return 0
    if cmd == "spec":
        origin, extent = mask_mapping(ROOT / "Tools" / "Terrain" / "MASKS.md")
        print(json.dumps({"sub": sub_spec(origin, extent).to_json(), "trees": trees_spec().to_json()}, indent=1))
        return 0
    if cmd == "build":
        return build([tuple(t.split(":")) for t in argv[1:]])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
