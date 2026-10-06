"""Resume the supplied Tripothon importer with saved-asset checkpoints.

The delivered package is read without editing it. Its import body is adapted
in memory to skip recorded saved assets and collect unused editor objects.
Run in UnrealEditor-Cmd with -ExecutePythonScript.
"""

from pathlib import Path
import hashlib
import json
import sys

import unreal


ROOT = Path(r"C:\Users\Admin\Desktop\Tripothon_All_Scenes_Handoff_v003_EN")
sys.path.insert(0, str(ROOT / "Scripts"))

from scene_rebuild_582 import run as scene_run
from target_asset_import_582 import package_file, sha, verify_import_receipt
from validate_raw_catalogs import validate_raw


def run():
    scene_run(ROOT, mode="PREFLIGHT")
    validate_raw(ROOT)
    receipt = ROOT / "TargetResults/asset_registry.json"
    old = json.loads(receipt.read_text(encoding="utf-8"))
    if old.get("status") != "FAILED" or not old.get("created_paths"):
        raise RuntimeError("Expected the audited partial import receipt")
    project = unreal.Paths.convert_relative_path_to_full(unreal.Paths.get_project_file_path())
    if old.get("project_file") != project:
        raise RuntimeError("Receipt belongs to another project")
    if any(not package_file(unreal, path).exists() for path in old["created_paths"]):
        raise RuntimeError("A registered native package is missing")

    body_file = ROOT / "Scripts/target_asset_import_body_582.py"
    lines = body_file.read_text(encoding="utf-8").splitlines()
    mesh_index = [i for i, line in enumerate(lines) if "own_save(mesh);rr['meshes'][module['key']]" in line]
    scene_index = [i for i, line in enumerate(lines) if line.strip() == "for material in materials.values():own_save(material)"]
    scene_start = [i for i, line in enumerate(lines) if "rr=report['scenes'][scene];dest=rr['dest'];textures={};materials={}" in line]
    module_loop = [i for i, line in enumerate(lines) if line.strip() == "for module in cat['modules']:"]
    texture_name = [i for i, line in enumerate(lines) if "tn='T_'+scene+'_'+hashlib.sha256((item['relative_file']+role).encode()).hexdigest()[:12]" in line]
    if len(mesh_index) != 1 or len(scene_index) != 1 or len(scene_start) != 1 or len(module_loop) != 1 or len(texture_name) != 1:
        raise RuntimeError("Delivered import body shape changed")
    # Work backward so the original line indices remain stable.
    lines[scene_index[0]] = "   textures.clear();materials.clear();u.SystemLibrary.collect_garbage()"
    lines.insert(mesh_index[0] + 1, "    mesh=None;u.SystemLibrary.collect_garbage()")
    lines.insert(mesh_index[0] + 2, "    if sum(len(s['meshes']) for s in report['scenes'].values())-globals()['TARGET_START_MESHES']>=60:raise RuntimeError('PACED_BATCH_COMPLETE')")
    lines.insert(module_loop[0] + 1, "    if module['key'] in rr['meshes']:continue")
    # For an interrupted scene, load completed textures instead of rewriting
    # their packages. New textures still use the delivered import path.
    texture_start = texture_name[0]
    for index in range(texture_start + 1, texture_start + 7):
        lines[index] = " " + lines[index]
    lines.insert(texture_start + 1, "      if tn in rr['textures']:")
    lines.insert(texture_start + 2, "       texture=u.load_asset(rr['textures'][tn]['path'])")
    lines.insert(texture_start + 3, "       if not isinstance(texture,u.Texture2D):raise RuntimeError('Registered texture missing '+tn)")
    lines.insert(texture_start + 4, "       textures[key]=texture")
    lines.insert(texture_start + 5, "      else:")
    # A fully recorded scene needs no asset mutation on resume.
    lines.insert(scene_start[0] + 1, "   if len(rr['meshes'])==len(cat['modules']):continue")
    paced_body = "\n".join(lines) + "\n"
    compile(paced_body, str(body_file), "exec")
    print("TRIPOTHON_PACED_SOURCE_SHA256", hashlib.sha256(body_file.read_bytes()).hexdigest())

    context = {
        "TARGET_ROOT": ROOT,
        "TARGET_MODE": "APPLY",
        "TARGET_RESUME": True,
        "TARGET_REPORT": receipt,
        "TARGET_START_MESHES": sum(len(s["meshes"]) for s in old["scenes"].values()),
    }
    try:
        exec(compile(paced_body, str(body_file), "exec"), context)
    except RuntimeError as exc:
        if str(exc) != "PACED_BATCH_COMPLETE":
            raise
        paused = json.loads(receipt.read_text(encoding="utf-8"))
        if paused.get("status") != "FAILED" or paused.get("error") != "PACED_BATCH_COMPLETE":
            raise RuntimeError("Batch checkpoint was not saved correctly")
        print("TRIPOTHON_PACED_BATCH_SAVED", sum(len(s["meshes"]) for s in paused["scenes"].values()))
        return
    reg = json.loads(receipt.read_text(encoding="utf-8"))
    if reg.get("status") != "TARGET_582_NATIVE_HASH_PENDING":
        raise RuntimeError("Import body did not finish")
    try:
        reg["project_file"] = project
        reg["native_package_hashes"] = {}
        for path in reg["created_paths"]:
            native = package_file(unreal, path)
            if not native.exists():
                raise RuntimeError("Own imported package missing: " + path)
            reg["native_package_hashes"][path] = {
                "sha256": sha(native),
                "relative_content_file": str(native.relative_to(Path(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_content_dir())))),
            }
        reg["status"] = "TARGET_582_ASSET_IMPORT_PASSED"
        temp = receipt.with_suffix(".tmp")
        temp.write_text(json.dumps(reg, indent=2), encoding="utf-8")
        temp.replace(receipt)
        print("TRIPOTHON_PACED_IMPORT_RESULT", verify_import_receipt(ROOT))
    except Exception as exc:
        reg["status"] = "FAILED"
        reg["error"] = "Native package hash/readback: " + str(exc)
        receipt.write_text(json.dumps(reg, indent=2), encoding="utf-8")
        raise


if __name__ == "__main__":
    run()

