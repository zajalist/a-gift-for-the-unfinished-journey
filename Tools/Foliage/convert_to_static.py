# Make the static FAR stand-in of one Megaplant tree (world sprint, Task V4, ruling R24).
#
#   node Tools/Foliage/run_foliage.mjs convert <job ...|all>     (jobs: Tools/Foliage/foliage_jobs.json)
#
# The runner rewrites the JOB line and sends this file as a Hayba python_run
# script again and again: each call does one bounded step (python_run stops at
# 5 s) and prints "CONVERT <step> ...", until it prints "CONVERT DONE ...".
# Work in progress lives in unreal.saskarta_v4_convert between calls. It is NOT
# a standalone module.
#
# Why not the Nanite path: building Nanite on a converted Megaplant (a static
# mesh carrying NaniteAssemblyData) asserted HasCachedNaniteAssemblyReferences
# and crashed the editor on 2026-09-26. The stand-in therefore carries NO
# assembly data and NO Nanite: it is a plain static mesh with LOD0-LOD3.
#
# What a Megaplant is: the skeletal mesh holds the trunk; its
# NaniteSettings.NaniteAssemblyData places part meshes (branches, bark plates,
# spurs, leaves) at up to ~6,800 nodes. Baked whole, a dead pine is 3.8 M
# triangles and a ginkgo 52 M, so the stand-in is baked in the reference pose
# (the node transforms are mesh-space at the reference pose) and reduced to a
# LOD0 of at most BUDGET triangles while it is baked:
#
#   * leaves (triangles whose material slot is a Foliage/Leaf/Needle material):
#     each leaf is one connected component. Every K-th leaf of a part is kept
#     and scaled about its centre by sqrt(leaves / kept), so the canopy keeps
#     its covered area (times LEAF_GROW_DAMP: spread-out cards overlap less
#     than the original clumps, and undamped the ginkgo read 46 % denser than
#     the native tree in a base-colour capture). A kept leaf becomes a 2-triangle card: the affine map
#     UV -> position is fitted to the leaf's vertices (least squares) and the
#     card's corners are that map at the leaf's UV rectangle, so the masked
#     leaf texture still draws the leaf on it; it carries the leaf's average
#     vertex colour. (Decimating a leaf instead
#     stalls at ~9 triangles: its outline stays rigid.)
#   * wood: components under JUNK_TRIS are dropped, and of the rest only the
#     largest, up to WOOD_KEEP of the part's triangles, are kept (twigs go:
#     the decimator floors each component at its rigid tube ends); that is
#     decimated by
#     one ratio r for the whole tree. A part whose share falls under WOOD_MIN
#     triangles (twigs, spur stems) is dropped: at 65 m and beyond it is
#     sub-pixel. The trunk and main limbs (the skeletal root) keep at least
#     ROOT_MIN: squeezed harder, the decimator webs a limb and its twigs into
#     flat slabs (seen on the first dead pine at 1,500).
#   * K and r are solved per tree so leaves take at most LEAF_SHARE of BUDGET
#     and wood the rest. The decimator stops short of very small targets, so
#     a bake can overshoot the plan; it is then baked again with r scaled by
#     the overshoot (at most MAX_BAKES bakes; a last, gentle whole-wood pass
#     only if still over).
#
# Steps: plan -> parts (several calls) -> write -> lods -> check (DONE).
# LOD1-3 come from the engine reducer (set_lods) at LOD_PERCENT of LOD0 and
# LOD_SCREEN screen sizes: LOD0 covers the 65-110 m band where the stand-in
# first replaces the animated tree. Materials are the source's MIs (their
# master, MA_Foliage_Trees, is flagged for instanced static meshes).
#
# It never saves: save with Tools/Foliage/save_packages.py.
# python_run rules obeyed: no try, no getattr, no file-open, no string
# substitute call (re.sub), no level switch.

import unreal
import re
import math
import datetime

JOB = {'src': '', 'dst': ''}  # JOB-LINE (rewritten by run_foliage.mjs)

BUDGET = 48000
LEAF_SHARE = 0.6
LEAF_TRIS = 2
LEAF_GROW_DAMP = 0.75
JUNK_TRIS = 4
WOOD_KEEP = 0.7
SIMPLIFY_METHOD = unreal.GeometryScriptRemoveMeshSimplificationType.VOLUME_PRESERVING
WOOD_MIN = 8
ROOT_MIN = 8000
MAX_BAKES = 4
LOD_PERCENT = [1.0, 0.5, 0.25, 0.12]
LOD_SCREEN = [1.0, 0.12, 0.07, 0.045]
LEAF_WORDS = ['Foliage', 'Leaf', 'Leaves', 'Needle']
STEP_SECONDS = 2.0

T0 = datetime.datetime.now()
NUM = r'(-?[0-9.]+(?:[eE][-+]?[0-9]+)?)'
gs_asset = unreal.GeometryScript_AssetUtils
gs_new = unreal.GeometryScript_NewAssetUtils
gs_edit = unreal.GeometryScript_MeshEdits
gs_mat = unreal.GeometryScript_Materials
gs_dec = unreal.GeometryScript_MeshDecomposition
gs_q = unreal.GeometryScript_MeshQueries
gs_x = unreal.GeometryScript_MeshTransforms
gs_s = unreal.GeometryScript_MeshSimplification

if JOB['src'] == '' or JOB['dst'] == '':
    raise RuntimeError('JOB line was not rewritten: run this through Tools/Foliage/run_foliage.mjs')
if not hasattr(unreal, 'saskarta_v4_convert'):
    unreal.saskarta_v4_convert = {}
STATE = unreal.saskarta_v4_convert


def elapsed():
    return (datetime.datetime.now() - T0).total_seconds()


def copy_skeletal(sk):
    lod = unreal.GeometryScriptMeshReadLOD()
    lod.lod_type = unreal.GeometryScriptLODType.SOURCE_MODEL
    lod.lod_index = 0
    dm = unreal.DynamicMesh()
    dm, outcome = gs_asset.copy_mesh_from_skeletal_mesh(sk, dm, unreal.GeometryScriptCopyMeshFromAssetOptions(), lod)
    if outcome != unreal.GeometryScriptOutcomePins.SUCCESS:
        raise RuntimeError('copy_mesh_from_skeletal_mesh failed for ' + sk.get_path_name())
    return dm


def field(block, name, default):
    m = re.search(name + '=' + NUM, block)
    return float(m.group(1)) if m else default


def sub_block(text, name):
    # The text inside name=( ... ), with balanced parentheses.
    i = text.find(name + '=(')
    if i < 0:
        return ''
    i += len(name) + 2
    depth = 1
    j = i
    while j < len(text) and depth > 0:
        if text[j] == '(':
            depth += 1
        elif text[j] == ')':
            depth -= 1
        j += 1
    return text[i:j - 1]


def parse_assembly(nanite_text):
    assembly = sub_block(nanite_text, 'NaniteAssemblyData')
    parts = []
    for m in re.finditer(r'MeshObjectPath="([^"]*)",MaterialRemap=\(([^)]*)\)', sub_block(assembly, 'Parts')):
        parts.append((m.group(1), [int(x) for x in m.group(2).split(',') if x.strip() != '']))
    nodes = []
    for chunk in sub_block(assembly, 'Nodes').split('PartIndex=')[1:]:
        part_index = int(re.match(r'[0-9]+', chunk).group(0))
        xf = sub_block(chunk, 'Transform')
        rot = sub_block(xf, 'Rotation')
        loc = sub_block(xf, 'Translation')
        scl = sub_block(xf, 'Scale3D')
        nodes.append((part_index,
                      [field(rot, 'X', 0.0), field(rot, 'Y', 0.0), field(rot, 'Z', 0.0), field(rot, 'W', 1.0)],
                      [field(loc, 'X', 0.0), field(loc, 'Y', 0.0), field(loc, 'Z', 0.0)],
                      [field(scl, 'X', 1.0), field(scl, 'Y', 1.0), field(scl, 'Z', 1.0)]))
    return parts, nodes


def to_transform(node):
    t = unreal.Transform()
    t.rotation = unreal.Quat(node[1][0], node[1][1], node[1][2], node[1][3])
    t.translation = unreal.Vector(node[2][0], node[2][1], node[2][2])
    t.scale3d = unreal.Vector(node[3][0], node[3][1], node[3][2])
    return t


def remap_materials(dm, remap):
    # A single-material part may carry no material-ID attribute at all (every
    # triangle is implicitly 0, and a remap would do nothing), so it is set
    # outright. Otherwise two passes through a high range, so a swap such as
    # (1,0) is safe.
    has_ids = gs_mat.get_all_triangle_material_i_ds(dm)[2]
    if not has_ids:
        sel = unreal.GeometryScript_MeshSelection.create_select_all_mesh_selection(
            dm, unreal.GeometryScriptMeshSelectionType.TRIANGLES)[1]
        gs_mat.set_material_id_for_mesh_selection(dm, sel, remap[0])
        return
    for i in range(len(remap)):
        gs_mat.remap_material_i_ds(dm, i, 1000 + remap[i])
    for i in range(len(remap)):
        gs_mat.remap_material_i_ds(dm, 1000 + remap[i], remap[i])


def split_part(dm, slot_count, leaf_ids):
    # -> (wood mesh without junk components, [(leaf component mesh, slot)]).
    # Split by material by deleting the other slots from a copy
    # (split_mesh_by_material_i_ds returns no ids after a remap in 5.8).
    wood = unreal.DynamicMesh()
    leaves = []
    for mid in range(slot_count):
        one = unreal.DynamicMesh()
        gs_edit.append_mesh(one, dm, unreal.Transform())
        for other in range(slot_count):
            if other != mid:
                gs_mat.delete_triangles_by_material_id(one, other)
        if one.get_triangle_count() == 0:
            continue
        _, comps = gs_dec.split_mesh_by_components(one, unreal.DynamicMeshPool())
        if mid in leaf_ids:
            leaves = leaves + [(c, mid) for c in comps]
            continue
        # Wood: the largest components up to WOOD_KEEP of the triangles. The
        # rest are twigs, sub-pixel at 65 m, and each would cost the
        # decimator's per-component floor (its open tube ends stay rigid).
        comps = sorted([c for c in comps if c.get_triangle_count() >= JUNK_TRIS],
                       key=lambda c: c.get_triangle_count(), reverse=True)
        total = sum([c.get_triangle_count() for c in comps])
        kept = 0
        for c in comps:
            if kept >= WOOD_KEEP * total:
                break
            gs_edit.append_mesh(wood, c, unreal.Transform())
            kept += c.get_triangle_count()
    return wood, leaves


def simplify(dm, target):
    if dm.get_triangle_count() > target:
        options = unreal.GeometryScriptSimplifyMeshOptions()
        options.method = SIMPLIFY_METHOD
        gs_s.apply_simplify_to_triangle_count(dm, max(1, int(target)), options)
    return dm


def solve3(m, b):
    # 3x3 linear solve by Cramer's rule; None when singular.
    def det(a):
        return (a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1]) - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0]) +
                a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0]))
    d = det(m)
    if abs(d) < 1e-12:
        return None
    out = []
    for c in range(3):
        a = [[b[r] if k == c else m[r][k] for k in range(3)] for r in range(3)]
        out.append(det(a) / d)
    return out


def leaf_card(leaf, grow, material_id):
    # -> a 2-triangle DynamicMesh standing in for one leaf, or None
    got = gs_q.get_all_vertex_positions(leaf, False)
    pos = unreal.GeometryScript_List.convert_vector_list_to_array(got[1])
    got_uv = unreal.GeometryScript_UVs.get_mesh_per_vertex_u_vs(leaf, 0)
    uvs = unreal.GeometryScript_List.convert_uv_list_to_array(got_uv[1])
    if got[2] or not got_uv[2] or len(pos) < 3 or len(uvs) != len(pos):
        return None
    m = [[0.0] * 3 for i in range(3)]
    rhs = [[0.0] * 3 for i in range(3)]
    for i in range(len(pos)):
        row = [1.0, uvs[i].x, uvs[i].y]
        p = [pos[i].x, pos[i].y, pos[i].z]
        for a in range(3):
            for b in range(3):
                m[a][b] += row[a] * row[b]
            for c in range(3):
                rhs[c][a] += row[a] * p[c]
    coef = [solve3(m, rhs[c]) for c in range(3)]
    if None in coef:
        return None
    u0 = min([q.x for q in uvs])
    u1 = max([q.x for q in uvs])
    v0 = min([q.y for q in uvs])
    v1 = max([q.y for q in uvs])
    corners_uv = [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]
    pts = [unreal.Vector(*[coef[c][0] + coef[c][1] * u + coef[c][2] * v for c in range(3)]) for (u, v) in corners_uv]
    centre = (pts[0] + pts[1] + pts[2] + pts[3]) * 0.25
    pts = [centre + (q - centre) * grow for q in pts]
    n = (pts[1] - pts[0]).cross(pts[3] - pts[0])
    if n.length() < 1e-6:
        return None
    n = n.normal()
    buf = unreal.GeometryScriptSimpleMeshBuffers()
    buf.vertices = pts
    buf.normals = [n, n, n, n]
    buf.uv0 = [unreal.Vector2D(u, v) for (u, v) in corners_uv]
    buf.triangles = [unreal.IntVector(0, 1, 2), unreal.IntVector(0, 2, 3)]
    # The leaf's average vertex colour (the Megaplant material reads it: at
    # 100 m white cards read visibly brighter than the native canopy).
    got_c = unreal.GeometryScript_VertexColors.get_mesh_per_vertex_colors(leaf, True)
    if got_c[2]:
        cols = unreal.GeometryScript_List.convert_color_list_to_array(got_c[1])
        k = float(max(1, len(cols)))
        avg = unreal.LinearColor(sum([c.r for c in cols]) / k, sum([c.g for c in cols]) / k,
                                 sum([c.b for c in cols]) / k, sum([c.a for c in cols]) / k)
        buf.vertex_colors = [avg, avg, avg, avg]
    card = unreal.DynamicMesh()
    gs_edit.append_buffers_to_mesh(card, buf, material_id)
    return card


def wood_target(w, r, is_root):
    if is_root:
        return min(w, max(ROOT_MIN, int(round(w * r))))
    t = int(round(w * r))
    return 0 if t < WOOD_MIN else min(w, t)


def plan():
    sk = unreal.load_asset(JOB['src'])
    if not isinstance(sk, unreal.SkeletalMesh):
        raise RuntimeError('not a SkeletalMesh: ' + JOB['src'])
    slots = [s.material_interface.get_path_name() for s in sk.materials]
    leaf_ids = [i for i in range(len(slots)) if len([w for w in LEAF_WORDS if w in slots[i].split('/')[-1]]) > 0]
    parts, nodes = parse_assembly(sk.get_editor_property('nanite_settings').export_text())
    # Unit -1 is the skeletal root (the trunk) at identity; units 0.. are parts.
    units = []
    root = copy_skeletal(sk)
    wood, leaves = split_part(root, len(slots), leaf_ids)
    units.append({'index': -1, 'wood': wood, 'leaves': leaves, 'n': 1, 'fallbacks': 0})
    for p in range(len(parts)):
        dm = copy_skeletal(unreal.load_asset(parts[p][0].split('.')[0]))
        remap_materials(dm, parts[p][1])
        wood, leaves = split_part(dm, len(slots), leaf_ids)
        units.append({'index': p, 'wood': wood, 'leaves': leaves, 'n': len([x for x in nodes if x[0] == p]), 'fallbacks': 0})
    # Leaves: smallest K with cost <= LEAF_SHARE * BUDGET (every leafy unit keeps >= 1).
    leaf_budget = LEAF_SHARE * BUDGET
    k = 1
    most = max([len(u['leaves']) for u in units] + [1])
    while k < most and sum([u['n'] * int(math.ceil(len(u['leaves']) / float(k))) * LEAF_TRIS for u in units]) > leaf_budget:
        k += 1
    leaf_cost = sum([u['n'] * int(math.ceil(len(u['leaves']) / float(k))) * LEAF_TRIS for u in units])
    # Wood: the largest ratio r with cost <= the rest of the budget (bisection).
    wood_budget = BUDGET - leaf_cost
    lo = 0.0
    hi = 1.0
    for it in range(40):
        r = (lo + hi) / 2.0
        cost = sum([u['n'] * wood_target(u['wood'].get_triangle_count(), r, u['index'] < 0) for u in units])
        if cost > wood_budget:
            hi = r
        else:
            lo = r
    STATE[JOB['dst']] = {'step': 'parts', 'bakes': 1, 'units': units, 'nodes': nodes, 'next': 0, 'k': k, 'r': lo,
                         'slots': [unreal.StaticMaterial(s.material_interface, s.material_slot_name) for s in sk.materials],
                         'out_wood': unreal.DynamicMesh(), 'out_leaf': unreal.DynamicMesh(), 'leaf_ids': leaf_ids}
    raw = sum([u['n'] * (u['wood'].get_triangle_count() + sum([c[0].get_triangle_count() for c in u['leaves']])) for u in units])
    print('CONVERT plan parts=' + str(len(parts)) + ' nodes=' + str(len(nodes)) + ' raw_tris=' + str(raw) +
          ' leaf_slots=' + str(leaf_ids) + ' leaves=' + str(sum([u['n'] * len(u['leaves']) for u in units])) +
          ' K=' + str(k) + ' leaf_cost=' + str(leaf_cost) + ' r=' + str(round(lo, 5)) + ' t=' + str(round(elapsed(), 2)))


def reduce_unit(u, k, r):
    # -> (wood, leaf cards) of the unit, reduced, in its own space. Works on
    # copies: the unit's meshes stay whole for a re-bake.
    wood = unreal.DynamicMesh()
    cards = unreal.DynamicMesh()
    t = wood_target(u['wood'].get_triangle_count(), r, u['index'] < 0)
    if t > 0:
        gs_edit.append_mesh(wood, u['wood'], unreal.Transform())
        simplify(wood, t)
    leaves = u['leaves']
    if len(leaves) > 0:
        kept = [leaves[i] for i in range(len(leaves)) if i % k == 0]
        grow = math.sqrt(len(leaves) / float(len(kept))) * LEAF_GROW_DAMP
        for (c, mid) in kept:
            card = leaf_card(c, grow, mid)
            if card is None:
                # No usable UV map: fall back to the scaled, decimated leaf.
                card = unreal.DynamicMesh()
                gs_edit.append_mesh(card, c, unreal.Transform())
                b = gs_q.get_mesh_bounding_box(card)
                gs_x.scale_mesh(card, unreal.Vector(grow, grow, grow), (b.min + b.max) * 0.5, True)
                simplify(card, LEAF_TRIS * 4)
                u['fallbacks'] = u['fallbacks'] + 1
            gs_edit.append_mesh(cards, card, unreal.Transform())
    return wood, cards


def parts_step(s):
    units = s['units']
    while s['next'] < len(units) and elapsed() < STEP_SECONDS:
        u = units[s['next']]
        wood, cards = reduce_unit(u, s['k'], s['r'])
        for (mesh, out) in [(wood, s['out_wood']), (cards, s['out_leaf'])]:
            if mesh.get_triangle_count() == 0:
                continue
            if u['index'] < 0:
                gs_edit.append_mesh(out, mesh, unreal.Transform())
            else:
                xforms = [to_transform(x) for x in s['nodes'] if x[0] == u['index']]
                if len(xforms) > 0:
                    gs_edit.append_mesh_transformed(out, mesh, xforms, unreal.Transform(), True, True)
        s['next'] += 1
    if s['next'] >= len(units):
        s['step'] = 'write'
    print('CONVERT parts ' + str(s['next']) + '/' + str(len(units)) + ' wood=' + str(s['out_wood'].get_triangle_count()) +
          ' leaf=' + str(s['out_leaf'].get_triangle_count()) +
          ' t=' + str(round(elapsed(), 2)))


def write_step(s):
    wood_left = BUDGET - s['out_leaf'].get_triangle_count()
    before = s['out_wood'].get_triangle_count()
    if before > wood_left * 1.02 and s['bakes'] < MAX_BAKES:
        # Overshoot: scale the non-root wood ratio and bake again.
        root = min(s['units'][0]['wood'].get_triangle_count(), max(ROOT_MIN, int(round(s['units'][0]['wood'].get_triangle_count() * s['r']))))
        s['r'] = s['r'] * max(0.05, float(wood_left - root) / float(max(1, before - root)))
        s['bakes'] += 1
        s['next'] = 0
        s['out_wood'] = unreal.DynamicMesh()
        s['out_leaf'] = unreal.DynamicMesh()
        s['step'] = 'parts'
        print('CONVERT rebake ' + str(s['bakes']) + ': wood ' + str(before) + ' > ' + str(wood_left) + ', r -> ' + str(round(s['r'], 5)))
        return
    if before > wood_left:
        simplify(s['out_wood'], max(ROOT_MIN, wood_left))
    out = unreal.DynamicMesh()
    gs_edit.append_mesh(out, s['out_wood'], unreal.Transform())
    gs_edit.append_mesh(out, s['out_leaf'], unreal.Transform())
    s['out'] = out
    dst = JOB['dst']
    eal = unreal.EditorAssetLibrary
    if eal.does_asset_exist(dst):
        sm = unreal.load_asset(dst)
        lod = unreal.GeometryScriptMeshWriteLOD()
        lod.lod_index = 0
        gs_asset.copy_mesh_to_static_mesh(s['out'], sm, unreal.GeometryScriptCopyMeshToAssetOptions(), lod)
    else:
        options = unreal.GeometryScriptCreateNewStaticMeshAssetOptions()
        options.enable_nanite = False
        options.enable_collision = False
        options.enable_recompute_normals = False
        options.enable_recompute_tangents = False
        sm, outcome = gs_new.create_new_static_mesh_asset_from_mesh(s['out'], dst, options)
        if outcome != unreal.GeometryScriptOutcomePins.SUCCESS or sm is None:
            raise RuntimeError('create_new_static_mesh_asset_from_mesh failed for ' + dst)
    sm.set_editor_property('static_materials', s['slots'])
    s['step'] = 'lods'
    print('CONVERT write ' + dst + ' lod0_tris=' + str(out.get_triangle_count()) + ' (wood ' + str(before) + ' -> ' +
          str(s['out_wood'].get_triangle_count()) + ', leaf ' + str(s['out_leaf'].get_triangle_count()) + ') t=' + str(round(elapsed(), 2)))


def lods_step(s):
    sm = unreal.load_asset(JOB['dst'])
    ns = sm.get_editor_property('nanite_settings')
    if ns.enabled:
        raise RuntimeError('Nanite is on for ' + JOB['dst'] + ': refusing (R24)')
    options = unreal.StaticMeshReductionOptions()
    options.auto_compute_lod_screen_size = False
    settings = []
    for i in range(len(LOD_PERCENT)):
        st = unreal.StaticMeshReductionSettings()
        st.percent_triangles = LOD_PERCENT[i]
        st.screen_size = LOD_SCREEN[i]
        settings.append(st)
    options.reduction_settings = settings
    s['step'] = 'check'
    print('CONVERT lods requested ' + str(LOD_PERCENT))
    # Last statement: the build is native and can outlive the deadline; the
    # next call checks the result.
    unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem).set_lods(sm, options)


def check_step(s):
    sm = unreal.load_asset(JOB['dst'])
    ns = sm.get_editor_property('nanite_settings')
    lods = sm.get_num_lods()
    tris = [sm.get_num_triangles(i) for i in range(lods)]
    parts_left = ns.export_text().count('PartIndex=')
    ok = (not ns.enabled) and parts_left == 0 and lods == len(LOD_PERCENT) and tris[0] <= 50000
    print(('CONVERT DONE' if ok else 'CONVERT FAILED') + ' dst=' + JOB['dst'] + ' nanite=' + str(ns.enabled) +
          ' assembly_nodes=' + str(parts_left) + ' lods=' + str(lods) + ' tris=' + str(tris) +
          ' slots=' + str(len(sm.get_editor_property('static_materials'))) + ' K=' + str(s['k']) + ' r=' + str(round(s['r'], 5)) +
          ' card_fallbacks=' + str(sum([u['fallbacks'] for u in s['units']])))
    STATE.pop(JOB['dst'])


s = STATE[JOB['dst']] if JOB['dst'] in STATE else None
if s is None:
    plan()
elif s['step'] == 'parts':
    parts_step(s)
elif s['step'] == 'write':
    write_step(s)
elif s['step'] == 'lods':
    lods_step(s)
else:
    check_step(s)
