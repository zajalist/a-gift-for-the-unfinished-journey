"""Prepare and install the supplied compact biofuel generator meshes.

Offline except for the explicit host ``mount`` command. ``prepare`` safely extracts
only the documented FBX/maps to Saved/BiofuelGenerator. ``script mount`` prints only
the transform half; the gated host command sets the SCS socket first.

The intact 13-part assembly is attached as StaticMeshComponents to the carrier's
actual SkeletalMeshComponent. The host ``mount`` command attaches its child actor
to the fixed rear ``capsule_root`` housing, then applies the measured compact
transform. The broken assembly is a separate, ground-placed set-dressing prop. Its
road anchor is deliberately supplied at execution time rather than picking a
story/wreck site without a composition review.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from prepare_rear_battery import MOUNT_LOCATION, MOUNT_SCALE, ROOF_SLOPE, rack_editor_script

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'Tools' / 'ModelReview'))
from fbx_reader import read_fbx  # noqa: E402
sys.path.insert(0, str(ROOT / 'Tools' / 'GameFlow'))
import editor_gate  # noqa: E402

INTACT_ZIP = pathlib.Path(r'C:\Users\Admin\Downloads\Telegram Desktop\biofuel01.zip')
BROKEN_ZIP = pathlib.Path(r'C:\Users\Admin\Downloads\Telegram Desktop\biofuel_broken01.zip')
STAGE = ROOT / 'Saved' / 'BiofuelGenerator' / 'Source'
ROAD_PROFILE = ROOT / 'docs' / 'story' / 'road-profile.json'
DEST = '/Game/SaskartaGaea/Characters/Carrier/Biofuel'
BP_PATH = '/Game/SaskartaGaea/Characters/Carrier/BP_Saskarta_Carrier'
ASSEMBLY_FOLDER = DEST + '/Assemblies'
INTACT_BP = ASSEMBLY_FOLDER + '/BP_Biofuel01_Assembly'
BROKEN_BP = ASSEMBLY_FOLDER + '/BP_BiofuelBroken01_Assembly'
MOUNT_SOCKET = 'capsule_root'
MOUNT_NODE = 'Biofuel01Assembly'
MOUNT_RELATIVE_LOCATION = MOUNT_LOCATION
MOUNT_RELATIVE_SCALE = MOUNT_SCALE

INTACT_PARTS = (
    'body', 'charge01', 'charge02', 'charge03', 'charge04', 'charge05', 'charge06',
    'charge07', 'glass', 'lid', 'liquid', 'mount', 'running',
)
BROKEN_PARTS = (
    'bare_edge', 'body_broken', 'charge01', 'charge02', 'charge03', 'charge04',
    'charge05', 'charge06', 'charge07', 'drop01', 'drop02', 'drop03', 'drop04',
    'drop05', 'glass', 'leak', 'leak_small', 'lid_loose', 'liquid', 'mount',
    'running', 'spill', 'tank_inner', 'torn_edge', 'torn_tabs',
)
INTACT_FILES = ('biofuel01.fbx', 'biofuel01_color.png', 'biofuel01_normal.png',
                'biofuel01_roughness.png', 'biofuel01_metallic.png')
BROKEN_FILES = ('biofuel_broken01.fbx', 'biofuel01_color.png', 'biofuel01_normal.png',
                'biofuel01_roughness.png', 'biofuel01_metallic.png',
                'biofuel_broken01_goo.png', 'biofuel_broken01_window.png')


def archive_entries(archive: pathlib.Path, required: tuple[str, ...]) -> dict[str, bytes]:
    """Read allow-listed members only; reject duplicate or path-traversing names."""
    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
        if len(names) != len(set(names)):
            raise ValueError(f'{archive}: duplicate ZIP member names')
        for name in names:
            p = pathlib.PurePosixPath(name)
            if p.is_absolute() or '..' in p.parts or '\\' in name:
                raise ValueError(f'{archive}: unsafe ZIP member path {name!r}')
        result = {}
        for member in required:
            candidates = [n for n in names if pathlib.PurePosixPath(n).name == member]
            if len(candidates) != 1:
                raise ValueError(f'{archive}: expected exactly one {member}, found {len(candidates)}')
            result[member] = zf.read(candidates[0])
        return result


def scene_from_bytes(raw: bytes):
    # The repository FBX reader accepts paths. Use a task-scoped temporary file so
    # the user ZIP remains untouched and no source copy is needed for inspection.
    with tempfile.TemporaryDirectory(prefix='biofuel_fbx_') as tmp:
        path = pathlib.Path(tmp) / 'model.fbx'
        path.write_bytes(raw)
        return read_fbx(str(path))


def inspect_archive(archive: pathlib.Path, files: tuple[str, ...], parts: tuple[str, ...]) -> dict:
    data = archive_entries(archive, files)
    fbx_name = next(n for n in files if n.endswith('.fbx'))
    scene = scene_from_bytes(data[fbx_name])
    model_names = {m.name.split('\x00')[0] for m in scene.models.values() if m.kind == 'Mesh'}
    geo_names = {scene.model_of_geometry(gid).name.split('\x00')[0]
                 for gid in scene.geometries
                 if scene.model_of_geometry(gid) is not None}
    missing = sorted(set(parts) - model_names)
    extras = sorted(model_names - set(parts))
    if missing or extras or model_names != geo_names:
        raise ValueError(f'{archive}: FBX part mismatch missing={missing}, extras={extras}, geometry mismatch={model_names ^ geo_names}')
    transformed = []
    import numpy as np
    from fbx_reader import model_geometric_matrix, model_world_matrix
    for geom in scene.geometries.values():
        model = scene.model_of_geometry(geom.id)
        if model is None:
            raise ValueError(f'{archive}: unparented geometry {geom.name}')
        # Model transforms are in the shared assembly frame. Report their span in
        # FBX units; UnitScaleFactor=1 in supplied files (one FBX unit = one cm).
        matrix = model_world_matrix(scene, model) @ model_geometric_matrix(model)
        p = np.column_stack((geom.vertices, np.ones(len(geom.vertices)))) @ matrix.T
        transformed.append(p[:, :3])
    xyz = __import__('numpy').concatenate(transformed, axis=0)
    size = xyz.max(axis=0) - xyz.min(axis=0)
    return {
        'archive': str(archive), 'fbx_version': scene.version,
        'unit_scale': scene.unit_scale, 'parts': len(scene.geometries),
        'triangles': sum(int(np.maximum(g.polygons()[2] - 2, 0).sum())
                         for g in scene.geometries.values()),
        'bounds_cm': [round(float(v), 3) for v in size],
        'materials': sorted({m.name.split('\x00')[0] for m in scene.materials.values()}),
        'files': {k: len(v) for k, v in data.items()},
    }


def prepare() -> list[pathlib.Path]:
    """Extract only allow-listed model/maps to a disposable, ignored Saved folder."""
    outputs = []
    for archive, subdir, required in (
        (INTACT_ZIP, 'intact', INTACT_FILES),
        (BROKEN_ZIP, 'broken', BROKEN_FILES),
    ):
        members = archive_entries(archive, required)
        outdir = STAGE / subdir
        outdir.mkdir(parents=True, exist_ok=True)
        for name, data in members.items():
            path = outdir / name
            path.write_bytes(data)
            outputs.append(path)
    return outputs


def road_anchor(road_m: float, lateral_m: float = 0.0, yaw_offset_deg: float = 0.0) -> tuple[float, float, float, float]:
    """Map road metres/right-offset to a provisional world pose from the saved profile."""
    doc = json.loads(ROAD_PROFILE.read_text(encoding='utf-8'))
    samples = doc['samples']
    if not 0.0 <= road_m <= float(doc['summary']['length_m']):
        raise ValueError(f'road metre {road_m} is outside 0..{doc["summary"]["length_m"]}')
    dists = [float(s['dist_m']) for s in samples]
    import bisect
    hi = min(max(bisect.bisect_right(dists, road_m), 1), len(samples) - 1)
    a, b = samples[hi - 1], samples[hi]
    t = (road_m - float(a['dist_m'])) / max(float(b['dist_m']) - float(a['dist_m']), 1e-9)
    x = float(a['x_cm']) + t * (float(b['x_cm']) - float(a['x_cm']))
    y = float(a['y_cm']) + t * (float(b['y_cm']) - float(a['y_cm']))
    z = (float(a['terrain_z_m']) + t * (float(b['terrain_z_m']) - float(a['terrain_z_m']))) * 100.0
    yaw = float(a['heading_ue_yaw'])
    yaw_r = __import__('math').radians(yaw)
    x += -__import__('math').sin(yaw_r) * float(lateral_m) * 100.0
    y += __import__('math').cos(yaw_r) * float(lateral_m) * 100.0
    yaw = (yaw + float(yaw_offset_deg) + 180.0) % 360.0 - 180.0
    return round(x, 2), round(y, 2), round(z, 2), round(yaw, 3)


def exported_object_references(value: str) -> list[str]:
    """Read object paths from Unreal ExportText arrays without MCP truncation."""
    return [match.group(1) for match in re.finditer(r"[A-Za-z_][A-Za-z_0-9]*'([^']+)'", value)]


def exported_name(value: str) -> str:
    """Normalize a reflected FName's ExportText value."""
    text = str(value).strip()
    match = re.fullmatch(r"(?:FName)?'([^']*)'", text)
    return match.group(1) if match else text


def scs_reference_from_export(value: str, blueprint_object_path: str) -> str:
    refs = exported_object_references(value)
    for path in refs:
        if 'SimpleConstructionScript' in path:
            return path
    name = re.search(r"SimpleConstructionScript_[0-9]+", value)
    if name:
        return blueprint_object_path + ':' + name.group(0)
    raise ValueError('Could not resolve the carrier SimpleConstructionScript path from its reflected property')


def _gate_cli(action: str, owner: str, *, timeout_min: float = 0.0, scope: str | None = None) -> subprocess.CompletedProcess:
    command = [sys.executable, str(ROOT / 'Tools' / 'GameFlow' / 'editor_gate.py'), action,
               '--owner', owner]
    if action == 'acquire':
        command.extend(['--timeout-min', str(timeout_min), '--ttl-min', '5'])
        if scope:
            command.extend(['--scope', scope])
    return subprocess.run(command, capture_output=True, text=True, timeout=15)


def mount_live() -> dict:
    """Safely configure the SCS socket, then apply the measured transform."""
    owner = f'biofuel_mount_{os.getpid()}'
    acquired = _gate_cli('acquire', owner, scope='asset:' + BP_PATH)
    if acquired.returncode != 0:
        raise RuntimeError('Could not acquire the carrier asset editor gate: ' + acquired.stdout.strip())
    lease_match = re.search(r'HAYBA_LEASE=([^\s]+)', acquired.stdout)
    lease = lease_match.group(1) if lease_match else None
    blueprint_object_path = BP_PATH + '.' + BP_PATH.rsplit('/', 1)[-1]
    try:
        blueprint = editor_gate.hayba('object_get_property', {
            'path': blueprint_object_path, 'names': ['SimpleConstructionScript']}, owner=owner, lease=lease)
        bp_props = blueprint.get('properties', {})
        scs_export = bp_props.get('SimpleConstructionScript')
        if not scs_export:
            raise RuntimeError('Carrier Blueprint did not expose SimpleConstructionScript')
        scs_path = scs_reference_from_export(scs_export, blueprint_object_path)
        scs_data = editor_gate.hayba('object_get_property', {
            'path': scs_path, 'names': ['AllNodes']}, owner=owner, lease=lease)
        all_nodes = scs_data.get('properties', {}).get('AllNodes')
        if not all_nodes:
            raise RuntimeError('Carrier SimpleConstructionScript returned no AllNodes data')
        node_paths = exported_object_references(all_nodes)
        matches = []
        for node_path in node_paths:
            node_data = editor_gate.hayba('object_get_property', {
                'path': node_path, 'names': ['InternalVariableName', 'AttachToName']},
                owner=owner, lease=lease)
            node_props = node_data.get('properties', {})
            if exported_name(node_props.get('InternalVariableName', '')) == MOUNT_NODE:
                matches.append((node_path, node_props))
        if len(matches) != 1:
            raise RuntimeError(f'Expected one SCS node named {MOUNT_NODE}, found {len(matches)}')
        node_path, node_props = matches[0]
        prior_socket = exported_name(node_props.get('AttachToName', ''))
        if prior_socket != MOUNT_SOCKET:
            changed = editor_gate.hayba('object_set_property', {
                'path': node_path, 'properties': {'AttachToName': MOUNT_SOCKET}},
                owner=owner, lease=lease)
            if not changed.get('ok') or 'AttachToName' not in changed.get('applied', []):
                raise RuntimeError('Hayba did not apply AttachToName=capsule_root to ' + node_path)
        run = editor_gate.hayba('python_run', {'script': make_editor_script('mount')},
                                owner=owner, lease=lease)
        check = editor_gate.hayba('object_get_property', {
            'path': node_path, 'names': ['InternalVariableName', 'AttachToName']},
            owner=owner, lease=lease).get('properties', {})
        if exported_name(check.get('InternalVariableName', '')) != MOUNT_NODE:
            raise RuntimeError('Carrier SCS mount node changed unexpectedly during compile')
        if exported_name(check.get('AttachToName', '')) != MOUNT_SOCKET:
            raise RuntimeError('Carrier battery socket did not persist through Blueprint compile')
        return {'node': node_path, 'socket': MOUNT_SOCKET, 'previous_socket': prior_socket,
                'relative_location': MOUNT_RELATIVE_LOCATION, 'relative_scale': MOUNT_RELATIVE_SCALE,
                'python_run': run}
    finally:
        released = _gate_cli('release', owner)
        if released.returncode != 0:
            raise RuntimeError('Carrier asset editor gate release failed: ' + released.stdout.strip())


EDITOR_IMPORT = r'''import unreal
from pathlib import Path
eal = unreal.EditorAssetLibrary
at = unreal.AssetToolsHelpers.get_asset_tools()
source = Path(r"__SOURCE__")
kind = "__KIND__"
fbx = source / "__FBX__"
dest = "__DEST__"
expected = __PARTS__
if not fbx.is_file():
    raise RuntimeError("Run Tools/Carrier/import_biofuel_generator.py prepare first: " + str(fbx))
folder = dest + ("/Intact" if kind == "intact" else "/Broken")
if not eal.does_directory_exist(folder):
    eal.make_directory(folder)
temp_folder = folder + "/_Import"
if not eal.does_directory_exist(temp_folder):
    eal.make_directory(temp_folder)
task = unreal.AssetImportTask()
task.set_editor_property("filename", str(fbx))
task.set_editor_property("destination_path", temp_folder)
task.set_editor_property("automated", True)
task.set_editor_property("replace_existing", False)
task.set_editor_property("save", True)
opts = unreal.FbxImportUI()
opts.set_editor_property("import_as_skeletal", False)
opts.set_editor_property("import_mesh", True)
opts.set_editor_property("import_materials", True)
opts.set_editor_property("import_textures", True)
opts.set_editor_property("import_animations", False)
sm = opts.get_editor_property("static_mesh_import_data")
sm.set_editor_property("combine_meshes", False)
sm.set_editor_property("generate_lightmap_u_vs", False)
sm.set_editor_property("convert_scene", True)
sm.set_editor_property("convert_scene_unit", True)
sm.set_editor_property("import_uniform_scale", 1.0)
sm.set_editor_property("transform_vertex_to_absolute", True)
opts.set_editor_property("static_mesh_import_data", sm)
task.set_editor_property("options", opts)
at.import_asset_tasks([task])
paths = task.get_editor_property("imported_object_paths")
meshes = [p for p in paths if isinstance(eal.load_asset(p), unreal.StaticMesh)]
found = {}
for p in meshes:
    asset = eal.load_asset(p)
    key = asset.get_name().lower()
    for part in expected:
        if key == part.lower() or key.endswith("_" + part.lower()):
            if part in found:
                raise RuntimeError("Duplicate FBX mesh part " + part + ": " + str(paths))
            found[part] = p
missing = sorted(set(expected) - set(found))
extra = sorted(set(found) - set(expected))
if missing or extra or len(meshes) != len(expected):
    raise RuntimeError("FBX import part check failed: missing=" + str(missing) + " paths=" + str(paths))
prefix = "SM_Biofuel01_" if kind == "intact" else "SM_BiofuelBroken01_"
expected_size = [44.978, 28.235, 26.697] if kind == "intact" else [44.978, 45.678, 28.181]
lo = [float("inf")] * 3
hi = [float("-inf")] * 3
core_lo = [float("inf")] * 3
core_hi = [float("-inf")] * 3
for part, old in found.items():
    target = folder + "/" + prefix + part
    if eal.does_asset_exist(target):
        raise RuntimeError("Refusing to replace existing prop asset: " + target)
    if not eal.rename_asset(old, target):
        raise RuntimeError("Could not rename imported mesh " + old + " to " + target)
    mesh = eal.load_asset(target)
    if mesh is None:
        raise RuntimeError("Renamed mesh did not load: " + target)
    bounds = mesh.get_bounds()
    for axis, (center, extent) in enumerate(zip(
            (bounds.origin.x, bounds.origin.y, bounds.origin.z),
            (bounds.box_extent.x, bounds.box_extent.y, bounds.box_extent.z))):
        lo[axis] = min(lo[axis], center - extent)
        hi[axis] = max(hi[axis], center + extent)
        if part not in {"spill", "leak", "leak_small", "drop01", "drop02", "drop03", "drop04", "drop05"}:
            core_lo[axis] = min(core_lo[axis], center - extent)
            core_hi[axis] = max(core_hi[axis], center + extent)
    if not eal.save_loaded_asset(mesh, False):
        raise RuntimeError("Mesh save failed: " + target)
measured = [hi[i] - lo[i] for i in range(3)]
core_measured = [core_hi[i] - core_lo[i] for i in range(3)]
if any(abs(a - b) > max(2.0, b * 0.02) for a, b in zip(measured, expected_size)):
    raise RuntimeError("Imported FBX scale/origin check failed: " + str(measured) + " expected cm " + str(expected_size))
expected_core = [44.978, 28.235, 26.697] if kind == "intact" else [44.978, 28.235, 28.181]
if any(abs(a - b) > max(2.0, b * 0.02) for a, b in zip(core_measured, expected_core)):
    raise RuntimeError("Imported generator housing scale check failed: " + str(core_measured) + " expected cm " + str(expected_core))
if any(abs(a + b) > 2.0 for a, b in zip(core_lo[:2], core_hi[:2])) or abs(core_lo[2]) > 2.0:
    raise RuntimeError("Imported housing pivot check failed: min=" + str(core_lo) + " max=" + str(core_hi))
print("BIOFUEL_IMPORT kind=" + kind + " meshes=" + str(len(found)) + " bounds_cm=" + str(measured) + " housing_bounds_cm=" + str(core_measured))
'''

EDITOR_BUILD_ASSEMBLY = r'''import unreal
eal = unreal.EditorAssetLibrary
S = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
BL = unreal.SubobjectDataBlueprintFunctionLibrary
folder, name, parts, prefix = "__ASSEMBLY_FOLDER__", "__BP_NAME__", __PARTS__, "__COMPONENT_PREFIX__"
def find_components(handles, variable):
    unique = {}
    for handle in handles:
        data = BL.get_data(handle)
        if str(BL.get_variable_name(data)) == variable:
            obj = BL.get_object(data)
            unique[str(obj.get_path_name())] = handle
    return list(unique.values())
full = folder + "/" + name
if not eal.does_directory_exist(folder):
    eal.make_directory(folder)
bp = eal.load_asset(full)
if bp is None:
    factory = unreal.BlueprintFactory()
    factory.set_editor_property("parent_class", unreal.Actor)
    bp = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, folder, unreal.Blueprint, factory)
if bp is None:
    raise RuntimeError("Could not create assembly Blueprint " + full)
root_handles = S.k2_gather_subobject_data_for_blueprint(bp)
if not root_handles:
    raise RuntimeError("Assembly has no root component")
root_handle = root_handles[0]
created = 0
for part in parts:
    variable = prefix + ''.join(bit.title() for bit in part.split('_'))
    mesh_path = "__MESH_FOLDER__/__MESH_PREFIX__" + part
    if not eal.does_asset_exist(mesh_path):
        raise RuntimeError("Missing imported mesh " + mesh_path)
    handles = S.k2_gather_subobject_data_for_blueprint(bp)
    found = find_components(handles, variable)
    if len(found) > 1:
        raise RuntimeError("Duplicate assembly component " + variable)
    if not found:
        res = S.add_new_subobject(unreal.AddNewSubobjectParams(parent_handle=root_handle,
            new_class=unreal.StaticMeshComponent, blueprint_context=bp))
        h = res[0] if isinstance(res, tuple) else res
        if not S.rename_subobject(h, unreal.Text(variable)):
            raise RuntimeError("Could not name component " + variable)
        created += 1
        handles = S.k2_gather_subobject_data_for_blueprint(bp)
        found = find_components(handles, variable)
    if len(found) != 1:
        raise RuntimeError("Failed to resolve component template " + variable)
    comp = BL.get_object(BL.get_data(found[0]))
    comp.set_editor_property("static_mesh", eal.load_asset(mesh_path))
    comp.set_editor_property("relative_location", unreal.Vector(0.0, 0.0, 0.0))
    comp.set_editor_property("relative_rotation", unreal.Rotator(0.0, 0.0, 0.0))
    comp.set_editor_property("relative_scale3d", unreal.Vector(1.0, 1.0, 1.0))
    comp.set_editor_property("cast_shadow", True)
    # The carrier uses its existing collision. The road prop is scenery, so it
    # cannot catch the player or interfere with traffic.
    comp.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
    comp.set_editor_property("can_character_step_up_on", unreal.CanBeCharacterBase.ECB_NO)
    comp.set_editor_property("visible", True)
    print("BIOFUEL_ASSEMBLY_PART " + variable + " mesh=" + mesh_path)
unreal.BlueprintEditorLibrary.compile_blueprint(bp)
if not eal.save_loaded_asset(bp, False):
    raise RuntimeError("Assembly Blueprint save failed: " + full)
print("BIOFUEL_ASSEMBLY_READY " + full + " parts=" + str(len(parts)) + " components_added=" + str(created))
'''

EDITOR_ATTACH = r'''import unreal
__RACK_HELPER__
eal = unreal.EditorAssetLibrary
S = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
BL = unreal.SubobjectDataBlueprintFunctionLibrary
def find_components(handles, variable):
    unique = {}
    for handle in handles:
        data = BL.get_data(handle)
        if str(BL.get_variable_name(data)) == variable:
            obj = BL.get_object(data)
            unique[str(obj.get_path_name())] = handle
    return list(unique.values())
bp = eal.load_asset("__CARRIER_BP__")
assembly = eal.load_asset("__ASSEMBLY_BP__")
if bp is None or assembly is None:
    raise RuntimeError("Carrier or intact assembly Blueprint missing")
handles = S.k2_gather_subobject_data_for_blueprint(bp)
components = []
for h in handles:
    obj = BL.get_object(BL.get_data(h))
    if obj is not None and obj.get_class().get_name() == "SkeletalMeshComponent":
        components.append((h, obj))
if len(components) != 1:
    raise RuntimeError("Expected exactly one carrier SkeletalMeshComponent, got " + str([x.get_name() for _, x in components]))
mesh_handle, carrier_mesh = components[0]
skeletal = carrier_mesh.get_editor_property("skeletal_mesh")
if skeletal is None:
    raise RuntimeError("Carrier SkeletalMeshComponent has no mesh")
# This is relative to capsule_root, whose live component-space scale is 100.
# The V12 mount places the battery at actor(-145,0,102), above a short five-part
# steel rack; all56lamp-bound corners clear the roof in offline geometry. Rendered
# visibility is still a separate acceptance. The host `mount` sets AttachToName;
# Python does not expose that SCS node property.
anchor = unreal.Vector(*__MOUNT_RELATIVE_LOCATION__)
variable = "Biofuel01Assembly"
handles = S.k2_gather_subobject_data_for_blueprint(bp)
found = find_components(handles, variable)
if len(found) > 1:
    raise RuntimeError("Duplicate carrier battery component")
if not found:
    res = S.add_new_subobject(unreal.AddNewSubobjectParams(parent_handle=mesh_handle,
        new_class=unreal.ChildActorComponent, blueprint_context=bp))
    h = res[0] if isinstance(res, tuple) else res
    if not S.rename_subobject(h, unreal.Text(variable)):
        raise RuntimeError("Could not name carrier battery component")
    handles = S.k2_gather_subobject_data_for_blueprint(bp)
    found = find_components(handles, variable)
if len(found) != 1:
    raise RuntimeError("Could not resolve carrier battery component")
comp = BL.get_object(BL.get_data(found[0]))
comp.set_editor_property("child_actor_class", assembly.generated_class())
comp.set_editor_property("relative_location", anchor)
comp.set_editor_property("relative_rotation", unreal.MathLibrary.make_rot_from_xy(
    unreal.Vector(1., 0., 0.), unreal.Vector(0., 1., __ROOF_SLOPE__)))
comp.set_editor_property("relative_scale3d", unreal.Vector(__MOUNT_RELATIVE_SCALE__, __MOUNT_RELATIVE_SCALE__, __MOUNT_RELATIVE_SCALE__))
print("BIOFUEL_MOUNT_TRANSFORM socket=__MOUNT_SOCKET__ relative_location=" + str(anchor) + " scale=__MOUNT_RELATIVE_SCALE__")
# Shared helper calculates every relative pose and removes its preview before SCS writes.
ensure_rear_battery_rack(bp)
unreal.BlueprintEditorLibrary.compile_blueprint(bp)
if not eal.save_loaded_asset(bp, False):
    raise RuntimeError("Carrier Blueprint save failed")
print("BIOFUEL_MOUNT saved=True child_class=" + assembly.get_path_name())
'''

EDITOR_BROKEN_PLACE = r'''import unreal
eal = unreal.EditorAssetLibrary
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
X, Y, Z, YAW = __ORIGIN__
assembly = eal.load_asset("__ASSEMBLY_BP__")
if assembly is None:
    raise RuntimeError("Broken assembly Blueprint is missing")
for a in eas.get_all_level_actors():
    if "BIOFUEL_BROKEN" in [str(t) for t in a.tags]:
        raise RuntimeError("Broken prop already exists; refusing duplicate placement: " + a.get_actor_label())
world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
ignore = []
ground = None
for _ in range(12):
    pair = unreal.SystemLibrary.line_trace_single(world, unreal.Vector(X, Y, Z + 5000.0),
        unreal.Vector(X, Y, Z - 5000.0), unreal.TraceTypeQuery.TRACE_TYPE_QUERY1, True,
        ignore, unreal.DrawDebugTrace.NONE, True)
    hit = pair[1] if isinstance(pair, tuple) and pair[0] else pair if isinstance(pair, unreal.HitResult) else None
    if hit is None or not hit.to_tuple()[0]:
        break
    row = hit.to_tuple()
    actor = row[9]
    if actor is not None and "Landscape" in actor.get_class().get_name():
        ground = row[5].z
        break
    if actor is None or actor in ignore:
        break
    ignore.append(actor)
if ground is None:
    raise RuntimeError("No Landscape ground at damaged prop anchor; no actor spawned")
actor = eas.spawn_actor_from_class(assembly.generated_class(), unreal.Vector(X, Y, ground + 0.5),
    unreal.Rotator(0.0, YAW, 0.0))
if actor is None:
    raise RuntimeError("Could not spawn broken generator assembly")
actor.set_actor_label("BiofuelBroken01_Roadside")
actor.set_folder_path("Set/CarrierBiofuel/Broken")
actor.tags = [unreal.Name("BIOFUEL_BROKEN"), unreal.Name("BiofuelBroken01")]
print("BIOFUEL_BROKEN_PLACED actor=" + actor.get_actor_label() + " at=" + str((X, Y, ground)) + " yaw=" + str(YAW))
print("Review spill/leak contact and select a road location only after its composition view is clear.")
'''


def make_editor_script(kind: str, **kwargs) -> str:
    if kind in ('import-intact', 'import-broken'):
        intact = kind == 'import-intact'
        parts = INTACT_PARTS if intact else BROKEN_PARTS
        filename = 'biofuel01.fbx' if intact else 'biofuel_broken01.fbx'
        return (EDITOR_IMPORT.replace('__SOURCE__', str(STAGE / ('intact' if intact else 'broken')))
                .replace('__KIND__', 'intact' if intact else 'broken')
                .replace('__FBX__', filename).replace('__DEST__', DEST)
                .replace('__PARTS__', repr(list(parts))))
    if kind in ('build-intact', 'build-broken'):
        intact = kind == 'build-intact'
        return (EDITOR_BUILD_ASSEMBLY.replace('__ASSEMBLY_FOLDER__', ASSEMBLY_FOLDER)
                .replace('__BP_NAME__', 'BP_Biofuel01_Assembly' if intact else 'BP_BiofuelBroken01_Assembly')
                .replace('__PARTS__', repr(list(INTACT_PARTS if intact else BROKEN_PARTS)))
                .replace('__COMPONENT_PREFIX__', 'Biofuel01_' if intact else 'BiofuelBroken01_')
                .replace('__MESH_FOLDER__', DEST + ('/Intact' if intact else '/Broken'))
                .replace('__MESH_PREFIX__', 'SM_Biofuel01_' if intact else 'SM_BiofuelBroken01_'))
    if kind == 'mount':
        return (EDITOR_ATTACH.replace('__CARRIER_BP__', BP_PATH)
                .replace('__ASSEMBLY_BP__', INTACT_BP)
                .replace('__MOUNT_RELATIVE_LOCATION__', repr(MOUNT_RELATIVE_LOCATION))
                .replace('__MOUNT_RELATIVE_SCALE__', repr(MOUNT_RELATIVE_SCALE))
                .replace('__ROOF_SLOPE__', repr(ROOF_SLOPE))
                .replace('__RACK_HELPER__', rack_editor_script())
                .replace('__MOUNT_SOCKET__', MOUNT_SOCKET))
    if kind == 'place-broken':
        origin = kwargs['origin']
        if len(origin) != 4 or not all(math_is_finite(float(v)) for v in origin):
            raise ValueError('origin must be finite X,Y,Z,Yaw in world centimetres')
        return (EDITOR_BROKEN_PLACE.replace('__ORIGIN__', repr([float(v) for v in origin]))
                .replace('__ASSEMBLY_BP__', BROKEN_BP))
    raise ValueError(kind)


def math_is_finite(value: float) -> bool:
    return value == value and abs(value) != float('inf')


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('inspect', help='read ZIP/FBX contents without extracting')
    sub.add_parser('prepare', help='extract only FBX and named maps under ignored Saved/')
    script = sub.add_parser('script', help='print an Unreal Python snippet; never runs it')
    script.add_argument('action', choices=('import-intact', 'import-broken', 'build-intact', 'build-broken', 'mount', 'place-broken'))
    script.add_argument('--origin', nargs=4, type=float, metavar=('X_CM', 'Y_CM', 'Z_CM', 'YAW_DEG'))
    sub.add_parser('mount', help='gate the editor, set Biofuel01Assembly AttachToName=capsule_root, then apply/save its measured transform')
    anchor = sub.add_parser('road-anchor', help='offline: resolve a road metre/right-offset to provisional world X,Y,Z,yaw')
    anchor.add_argument('--road-m', required=True, type=float)
    anchor.add_argument('--lateral-m', default=0.0, type=float, help='positive is right of travel')
    anchor.add_argument('--yaw-offset', default=0.0, type=float)
    args = parser.parse_args(argv)
    if args.command == 'inspect':
        print(json.dumps({
            'intact': inspect_archive(INTACT_ZIP, INTACT_FILES, INTACT_PARTS),
            'broken': inspect_archive(BROKEN_ZIP, BROKEN_FILES, BROKEN_PARTS),
        }, indent=2))
    elif args.command == 'prepare':
        for path in prepare():
            print(path)
    elif args.command == 'script':
        if args.action == 'place-broken' and not args.origin:
            parser.error('script place-broken requires --origin X_CM Y_CM Z_CM YAW_DEG')
        if args.action == 'mount':
            print('PRECONDITION: transform-only; use the top-level mount command to assign the SCS socket first.')
        print(make_editor_script(args.action, origin=args.origin))
    elif args.command == 'mount':
        print(json.dumps(mount_live(), indent=2, default=str))
    elif args.command == 'road-anchor':
        pose = road_anchor(args.road_m, args.lateral_m, args.yaw_offset)
        print(json.dumps({'road_m': args.road_m, 'lateral_m': args.lateral_m,
                          'world_origin_cm_and_yaw': pose,
                          'note': 'Z is the road-profile terrain estimate; the editor placement script traces Landscape at XY before spawning.'}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
