"""Build a real known-pose COLMAP dataset; dry-run unless --execute is given."""
import argparse
import shutil
import sqlite3
import struct
import subprocess
from pathlib import Path

from common import actual_pose_to_colmap, require_capture_receipt, scoped, sha256, write_json


def write_known_model(folder, receipt, database):
    with sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True) as connection:
        rows = connection.execute("SELECT image_id, camera_id, name FROM images ORDER BY name").fetchall()
        cameras = connection.execute("SELECT camera_id, model, width, height, params FROM cameras").fetchall()
    frames = {f["name"]: f for f in receipt["frames"]}
    if {r[2] for r in rows} != set(frames) or len(cameras) != 1:
        raise ValueError("COLMAP database does not match the capture images / shared camera")
    camera_id, model, w, h, blob = cameras[0]
    params = struct.unpack("<" + "d"*(len(blob)//8), blob)
    if model != 1 or (w, h) != (960, 540) or len(params) != 4:
        raise ValueError("Expected one calibrated PINHOLE camera")
    expected = receipt["intrinsics"]
    if max(abs(a-b) for a, b in zip(params, expected)) > 1e-6:
        raise ValueError("Database camera calibration mismatch")
    folder.mkdir(parents=True, exist_ok=True)
    (folder/"cameras.txt").write_text(f"{camera_id} PINHOLE 960 540 " + " ".join(map(str, params)) + "\n", encoding="utf-8")
    lines = []
    for image_id, cid, name in rows:
        q, t = actual_pose_to_colmap(frames[name], receipt["origin_ue_cm"])
        lines.append(f"{image_id} " + " ".join(f"{v:.17g}" for v in q+t) + f" {cid} {name}\n\n")
    (folder/"images.txt").write_text("".join(lines), encoding="utf-8")
    (folder/"points3D.txt").write_text("", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--colmap", default="colmap")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    dataset = scoped(args.dataset)
    receipt, receipt_path = require_capture_receipt(dataset)
    intrinsics = ",".join(str(float(v)) for v in receipt["intrinsics"])
    db, images, masks = dataset/"database.db", dataset/"images", dataset/"feature_masks"
    known, sparse = dataset/"known_model", dataset/"sparse/0"
    commands = [
        [args.colmap, "feature_extractor", "--database_path", str(db), "--image_path", str(images),
         "--ImageReader.mask_path", str(masks), "--ImageReader.single_camera", "1",
         "--ImageReader.camera_model", "PINHOLE", "--ImageReader.camera_params", intrinsics,
         "--SiftExtraction.use_gpu", "0"],
        [args.colmap, "exhaustive_matcher", "--database_path", str(db), "--SiftMatching.use_gpu", "0"],
        [args.colmap, "point_triangulator", "--database_path", str(db), "--image_path", str(images),
         "--input_path", str(known), "--output_path", str(sparse), "--clear_points", "1", "--refine_intrinsics", "0"],
        [args.colmap, "model_converter", "--input_path", str(sparse), "--output_path", str(sparse), "--output_type", "TXT"]]
    if not args.execute:
        for command in commands:
            print(subprocess.list2cmdline(command))
        print("Dry run; no COLMAP process or file preparation executed")
        return
    version = subprocess.run([args.colmap, "-h"], check=True, capture_output=True, text=True)
    if "COLMAP 3.11.1" not in version.stdout + version.stderr:
        raise ValueError("This pipeline pins COLMAP 3.11.1; use that official release")
    if db.exists() or sparse.exists():
        raise ValueError("Refusing to mix this capture with an existing reconstruction")
    from PIL import Image
    import numpy as np
    images.mkdir(parents=True, exist_ok=True)
    masks.mkdir(parents=True, exist_ok=True)
    sparse.mkdir(parents=True, exist_ok=True)
    image_hashes = {}
    for frame in receipt["frames"]:
        rgb = Image.open(dataset/frame["rgb"]["path"]).convert("RGB")
        mask = Image.open(dataset/frame["mask"]["path"]).convert("L")
        depth = np.load(dataset/frame["depth"]["path"], allow_pickle=False)
        if rgb.size != (960, 540) or mask.size != rgb.size or depth.shape != (540, 960):
            raise ValueError("RGB / mask / measured depth dimensions disagree")
        mask_array = np.asarray(mask)
        if not np.all((mask_array == 0) | (mask_array == 255)) or not np.any(mask_array == 255):
            raise ValueError("A nonempty binary foreground mask is required")
        if not np.all(np.isfinite(depth[mask_array > 0])) or np.any(depth[mask_array > 0] <= 0):
            raise ValueError("Foreground needs finite positive measured depth")
        # Retain originals. The official trainer has no per-image mask loader;
        # train on actual foreground composited over its default black background.
        rgb_array = np.asarray(rgb).copy()
        rgb_array[mask_array == 0] = 0
        dest = images/frame["name"]
        Image.fromarray(rgb_array).save(dest)
        mask.save(masks/(frame["name"] + ".png"))
        image_hashes[frame["name"]] = sha256(dest)
    subprocess.run(commands[0], check=True)
    write_known_model(known, receipt, db)
    for command in commands[1:]:
        subprocess.run(command, check=True)
    point_lines = [line for line in (sparse/"points3D.txt").read_text().splitlines() if line and not line.startswith("#")]
    if not 4 <= len(point_lines) <= 65000:
        raise ValueError("Need 4..65000 real triangulated initialization points; review/filter before training")
    executable = Path(shutil.which(args.colmap) or args.colmap).resolve()
    write_json(dataset/"colmap_receipt.json", {"completed": True, "version": "3.11.1",
               "invoked_launcher": str(executable), "invoked_launcher_sha256": sha256(executable),
               "capture_receipt_sha256": sha256(receipt_path), "world_frame": receipt["world_frame"],
               "known_camera_poses_fixed": True, "intrinsics_fixed": True, "commands": commands,
               "triangulated_point_count": len(point_lines), "training_images_sha256": image_hashes,
               "model_sha256": {p.name: sha256(p) for p in sparse.iterdir() if p.is_file()}})


if __name__ == "__main__":
    main()
