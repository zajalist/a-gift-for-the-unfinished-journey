"""Offline FBX audit/extract and short, serial editor import steps for the drone.

Run audit, extract offline; with the sole editor gate run mesh, finalize,
texture BC/N/R/M, material, audio NAME, read, and verify. Inspect each result before the next.
After any timeout run read before retrying an import. No level is touched.
"""
import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
FBX = ROOT / "SourceArt/Characters/Drone/drone01.fbx"
STAGE = ROOT / "Saved/Drone/Textures"
CHAR = "/Game/SaskartaGaea/Characters/Drone"
AUDIO = "/Game/SaskartaGaea/Audio/Drone"
VOICE_DEST = "/Game/SaskartaGaea/Audio/CarrierVoice"
VOICE_NAME = "VO_Carrier_CV_DRONE_02"
sys.path.insert(0, str(ROOT / "Tools/Look"))
sys.path.insert(0, str(ROOT / "Tools/ModelReview"))
from apply_look import check_banned, python_run  # noqa: E402
from fbx_reader import parse_tree, _clean_name, _props70  # noqa: E402

VIDEOS = {"BC": "drone01_color", "N": "drone01_normal",
          "R": "drone01_roughness", "M": "drone01_metallic"}
WAVS = ("SFX_Echo_Ping", "SFX_Echo_Return", "SFX_Echo_WindLoop", "SFX_Drone_RotorLoop",
        "SFX_Drone_Scrape", "SFX_Drone_FallImpact", "SFX_Drone_OpticsSnap",
        "SFX_Carrier_ServoShriek")


def objects():
    version, root = parse_tree(FBX)
    return version, root.find("Objects")


def audit():
    import numpy as np
    version, group = objects()
    models = [o for o in group.children if o.name == "Model"]
    meshes = [o for o in group.children if o.name == "Geometry"]
    bones = [_clean_name(o.props[1]) for o in models if o.props[2] == "LimbNode"]
    stacks = [o for o in group.children if o.name == "AnimationStack"]
    verts = np.concatenate([g.find("Vertices").props[0].reshape(-1, 3) for g in meshes])
    assert version == 7400 and len(meshes) == 5
    assert bones == ["root", "rotor_fl", "rotor_fr", "rotor_rl", "rotor_rr"]
    assert len(stacks) == 1 and _clean_name(stacks[0].props[1]) == "Spin"
    duration = _props70(stacks[0])["LocalStop"][0] / 46186158000
    assert abs(duration - 2) < .001
    print("FBX", version, "parts", len(meshes), "bones", bones, "Spin", duration, "s")
    print("local bounds", verts.min(axis=0).tolist(), verts.max(axis=0).tolist())
    for role, name in VIDEOS.items():
        o = next(x for x in group.children if x.name == "Video" and _clean_name(x.props[1]) == name)
        blob = o.find("Content").props[0]
        assert blob[:3] == b"\xff\xd8\xff", name
        print(role, name, len(blob), "JPEG bytes")


def extract():
    _, group = objects()
    STAGE.mkdir(parents=True, exist_ok=True)
    for role, name in VIDEOS.items():
        o = next(x for x in group.children if x.name == "Video" and _clean_name(x.props[1]) == name)
        blob = o.find("Content").props[0]
        assert blob[:3] == b"\xff\xd8\xff", name
        path = STAGE / f"T_AuxDrone_{role}.jpg"
        if not path.exists() or path.read_bytes() != blob:
            path.write_bytes(blob)
        print(path, len(blob))


MESH = r'''
import unreal
eal = unreal.EditorAssetLibrary
d = "__DEST__"
temp = d + "/_Import"
if eal.does_asset_exist(d + "/SK_AuxDrone"):
    print("MESH finalized")
elif eal.does_directory_exist(temp) and eal.list_assets(temp, False, False):
    print("MESH pending " + str(eal.list_assets(temp, False, False)))
else:
    p = unreal.InterchangeGenericAssetsPipeline()
    p.set_editor_property("asset_name", "SK_AuxDrone")
    p.set_editor_property("use_source_name_for_asset", False)
    mp = p.get_editor_property("mesh_pipeline")
    mp.set_editor_property("import_static_meshes", False)
    mp.set_editor_property("import_skeletal_meshes", True)
    mp.set_editor_property("create_physics_asset", False)
    p.get_editor_property("animation_pipeline").set_editor_property("import_animations", True)
    mat = p.get_editor_property("material_pipeline")
    mat.set_editor_property("import_materials", False)
    mat.get_editor_property("texture_pipeline").set_editor_property("import_textures", False)
    override = unreal.InterchangePipelineStackOverride()
    override.add_pipeline(p)
    task = unreal.AssetImportTask()
    task.set_editor_property("filename", "__FILE__")
    task.set_editor_property("destination_path", temp)
    task.set_editor_property("automated", True)
    task.set_editor_property("replace_existing", False)
    task.set_editor_property("save", False)
    task.set_editor_property("options", override)
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    print("MESH made " + str(task.get_editor_property("imported_object_paths")))
'''

FINALIZE = r'''
import unreal
eal = unreal.EditorAssetLibrary
d = "__DEST__"
temp = d + "/_Import"
names = {"SkeletalMesh": "SK_AuxDrone", "Skeleton": "SKEL_AuxDrone", "AnimSequence": "A_AuxDrone_Spin"}
seen = {}
for path in eal.list_assets(temp, False, False):
    asset = eal.load_asset(path)
    if asset is not None:
        kind = asset.get_class().get_name()
        if kind in names:
            if kind in seen:
                raise RuntimeError("duplicate " + kind)
            seen[kind] = path
print("FINALIZE found " + str(seen))
for kind, name in names.items():
    path = d + "/" + name
    if not eal.does_asset_exist(path):
        if kind not in seen or not eal.rename_asset(seen[kind], path):
            raise RuntimeError("missing or rename failed " + kind)
    asset = eal.load_asset(path)
    if asset is None or not eal.save_loaded_asset(asset, False):
        raise RuntimeError("save failed " + name)
    print("FINALIZE saved " + path)
'''

TEXTURE = r'''
import unreal
eal = unreal.EditorAssetLibrary
dest = "__DEST__/Textures"
name = "T_AuxDrone___ROLE__"
path = dest + "/" + name
if not eal.does_asset_exist(path):
    task = unreal.AssetImportTask()
    task.set_editor_property("filename", "__FILE__")
    task.set_editor_property("destination_path", dest)
    task.set_editor_property("destination_name", name)
    task.set_editor_property("automated", True)
    task.set_editor_property("replace_existing", False)
    task.set_editor_property("save", False)
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
asset = eal.load_asset(path)
if asset is None:
    raise RuntimeError("missing texture " + path)
asset.set_editor_property("srgb", __SRGB__)
asset.set_editor_property("compression_settings", unreal.TextureCompressionSettings.__COMPRESSION__)
asset.set_editor_property("max_texture_size", 2048)
print("TEXTURE " + name + " saved=" + str(eal.save_loaded_asset(asset, False)))
'''

SOUND = r'''
import unreal
eal = unreal.EditorAssetLibrary
dest = "__DEST__"
name = "__NAME__"
path = dest + "/" + name
if not eal.does_asset_exist(path):
    task = unreal.AssetImportTask()
    task.set_editor_property("filename", "__FILE__")
    task.set_editor_property("destination_path", dest)
    task.set_editor_property("destination_name", name)
    task.set_editor_property("automated", True)
    task.set_editor_property("replace_existing", False)
    task.set_editor_property("save", False)
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
asset = eal.load_asset(path)
if asset is None:
    raise RuntimeError("missing sound " + path)
asset.set_editor_property("looping", __LOOP__)
if __LOOP__:
    asset.set_editor_property("loading_behavior", unreal.SoundWaveLoadingBehavior.PRIME_ON_LOAD)
print("SOUND " + name + " duration=" + str(asset.get_editor_property("duration")) + " saved=" + str(eal.save_loaded_asset(asset, False)))
'''

VOICE_IMPORT = r'''
import unreal
eal = unreal.EditorAssetLibrary
dest = "__DEST__"
name = "__NAME__"
path = dest + "/" + name
reference = eal.load_asset(dest + "/VO_Carrier_CV_BOOT_01")
if reference is None:
    raise RuntimeError("carrier voice route reference missing")
if not eal.does_asset_exist(path):
    task = unreal.AssetImportTask()
    task.set_editor_property("filename", "__FILE__")
    task.set_editor_property("destination_path", dest)
    task.set_editor_property("destination_name", name)
    task.set_editor_property("automated", True)
    task.set_editor_property("replace_existing", False)
    task.set_editor_property("save", False)
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
voice = eal.load_asset(path)
if voice is None:
    raise RuntimeError("drone voice import missing")
voice.set_editor_property("looping", False)
for setting in ("sound_class_object", "attenuation_settings", "virtualization_mode"):
    voice.set_editor_property(setting, reference.get_editor_property(setting))
print("VOICE " + name + " duration=" + str(voice.get_editor_property("duration")) + " saved=" + str(eal.save_loaded_asset(voice, False)))
'''

MATERIAL = r'''
import unreal
eal = unreal.EditorAssetLibrary
mel = unreal.MaterialEditingLibrary
d = "__DEST__"
path = d + "/Materials/M_AuxDrone"
for role in ("BC", "N", "R", "M"):
    if not eal.does_asset_exist(d + "/Textures/T_AuxDrone_" + role):
        raise RuntimeError("missing texture " + role)
mesh = eal.load_asset(d + "/SK_AuxDrone")
if mesh is None:
    raise RuntimeError("missing drone mesh")
if not eal.does_asset_exist(path):
    mat = unreal.AssetToolsHelpers.get_asset_tools().create_asset("M_AuxDrone", d + "/Materials", unreal.Material, unreal.MaterialFactoryNew())
    if mat is None:
        raise RuntimeError("material create failed")
    for role, y, prop, channel, sample in (("BC", -400, unreal.MaterialProperty.MP_BASE_COLOR, "RGB", unreal.MaterialSamplerType.SAMPLERTYPE_COLOR),
                                           ("N", -100, unreal.MaterialProperty.MP_NORMAL, "RGB", unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL),
                                           ("R", 200, unreal.MaterialProperty.MP_ROUGHNESS, "R", unreal.MaterialSamplerType.SAMPLERTYPE_MASKS),
                                           ("M", 500, unreal.MaterialProperty.MP_METALLIC, "R", unreal.MaterialSamplerType.SAMPLERTYPE_MASKS)):
        node = mel.create_material_expression(mat, unreal.MaterialExpressionTextureSample, -550, y)
        node.set_editor_property("texture", eal.load_asset(d + "/Textures/T_AuxDrone_" + role))
        node.set_editor_property("sampler_type", sample)
        if not mel.connect_material_property(node, channel, prop):
            raise RuntimeError("material link failed " + role)
mat = eal.load_asset(path)
mat.set_editor_property("used_with_skeletal_mesh", True)
if len(mel.get_material_expressions(mat)) != 4:
    raise RuntimeError("drone material must have four texture samples")
errors = [str(e) for e in mel.recompile_material(mat)]
print("MATERIAL compile_errors=" + str(errors))
if errors:
    raise RuntimeError("drone material compile failed")
if not eal.save_loaded_asset(mat, False):
    raise RuntimeError("material save failed")
slots = list(mesh.get_editor_property("materials"))
if not slots:
    raise RuntimeError("drone mesh has no material slots")
for slot in slots:
    slot.set_editor_property("material_interface", mat)
mesh.set_editor_property("materials", slots)
print("MATERIAL slots=" + str(len(slots)) + " mesh_saved=" + str(eal.save_loaded_asset(mesh, False)))
'''

READ = r'''
import unreal
eal = unreal.EditorAssetLibrary
for path in eal.list_assets("__DEST__", True, False):
    asset = eal.load_asset(path)
    if asset is not None:
        kind = asset.get_class().get_name()
        if kind == "SkeletalMesh":
            skeleton = asset.get_editor_property("skeleton")
            print("READ " + path + " SkeletalMesh skeleton=" + str(skeleton.get_name() if skeleton else "none"))
        elif kind == "AnimSequence":
            print("READ " + path + " length=" + str(asset.get_editor_property("sequence_length")))
        else:
            print("READ " + path + " " + kind)
for path in eal.list_assets("__AUDIO__", False, False):
    print("READ " + path)
'''

VERIFY = r'''
import unreal
eal = unreal.EditorAssetLibrary
d = "__DEST__"
mesh = eal.load_asset(d + "/SK_AuxDrone")
skel = eal.load_asset(d + "/SKEL_AuxDrone")
anim = eal.load_asset(d + "/A_AuxDrone_Spin")
if mesh is None or skel is None or anim is None:
    raise RuntimeError("drone mesh, skeleton or Spin missing")
if mesh.get_editor_property("skeleton") != skel or anim.get_editor_property("skeleton") != skel:
    raise RuntimeError("drone skeleton association mismatch")
ses = unreal.get_editor_subsystem(unreal.SkeletalMeshEditorSubsystem)
children = [str(x) for x in ses.get_bone_children(mesh, "root")]
print("VERIFY root children=" + str(children))
expected = {"rotor_fl", "rotor_fr", "rotor_rl", "rotor_rr"}
base = {x[:-1] if x.endswith("1") else x for x in children}
if base != expected:
    raise RuntimeError("drone bones missing")
tracks = [str(x) for x in unreal.AnimationLibrary.get_animation_track_names(anim)]
print("VERIFY Spin tracks=" + str(tracks))
if not set(children).issubset(set(tracks)):
    raise RuntimeError("Spin has no matching rotor bone tracks")
duration = anim.get_editor_property("sequence_length")
print("VERIFY Spin duration=" + str(duration))
if duration < 1.95 or duration > 2.05:
    raise RuntimeError("drone Spin duration outside 2s")
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
probe = eas.spawn_actor_from_class(unreal.SkeletalMeshActor, unreal.Vector(0, 0, 0), unreal.Rotator())
if probe is None:
    raise RuntimeError("drone bounds probe spawn failed")
component = probe.get_component_by_class(unreal.SkeletalMeshComponent)
component.set_skeletal_mesh_asset(mesh)
origin, ext, radius = unreal.SystemLibrary.get_component_bounds(component)
width = 2 * max(abs(ext.x), abs(ext.y))
eas.destroy_actor(probe)
print("VERIFY width_cm=" + str(width) + " origin=" + str(origin) + " ext=" + str(ext) + " radius=" + str(radius))
if width < 50 or width > 150:
    raise RuntimeError("drone imported width unexpected; inspect FBX unit scaling")
'''


def run(template, replacements):
    script = template
    for before, after in replacements.items():
        script = script.replace(before, after)
    ok, out, err = python_run(check_banned(script))
    print(out)
    if not ok:
        raise SystemExit(err or "editor step failed")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("step", choices=("audit", "extract", "mesh", "finalize", "texture", "material", "audio", "voice", "read", "verify"))
    ap.add_argument("name", nargs="?")
    args = ap.parse_args()
    if args.step == "audit":
        audit()
    elif args.step == "extract":
        extract()
    elif args.step == "mesh":
        run(MESH, {"__DEST__": CHAR, "__FILE__": FBX.as_posix()})
    elif args.step == "finalize":
        run(FINALIZE, {"__DEST__": CHAR})
    elif args.step == "texture":
        if args.name not in VIDEOS:
            ap.error("texture name must be BC, N, R or M")
        path = STAGE / f"T_AuxDrone_{args.name}.jpg"
        if not path.exists():
            ap.error("run extract first")
        compression = "TC_NORMALMAP" if args.name == "N" else "TC_MASKS" if args.name in ("R", "M") else "TC_DEFAULT"
        run(TEXTURE, {"__DEST__": CHAR, "__ROLE__": args.name, "__FILE__": path.as_posix(),
                      "__SRGB__": str(args.name == "BC"), "__COMPRESSION__": compression})
    elif args.step == "audio":
        if args.name not in WAVS:
            ap.error("audio name must be one of " + ", ".join(WAVS))
        path = ROOT / "SourceArt/Audio/Drone" / (args.name + ".wav")
        if not path.exists():
            ap.error("run make_sfx.py first")
        run(SOUND, {"__DEST__": AUDIO, "__NAME__": args.name, "__FILE__": path.as_posix(),
                    "__LOOP__": str(args.name.endswith("Loop"))})
    elif args.step == "voice":
        path = ROOT / "SourceArt/Audio/Drone" / (VOICE_NAME + ".wav")
        if not path.exists():
            ap.error("render the drone voice take first")
        run(VOICE_IMPORT, {"__DEST__": VOICE_DEST, "__NAME__": VOICE_NAME,
                           "__FILE__": path.as_posix()})
    elif args.step == "material":
        run(MATERIAL, {"__DEST__": CHAR})
    elif args.step == "verify":
        run(VERIFY, {"__DEST__": CHAR})
    else:
        run(READ, {"__DEST__": CHAR, "__AUDIO__": AUDIO})


if __name__ == "__main__":
    main()
