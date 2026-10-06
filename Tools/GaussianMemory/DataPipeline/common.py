"""Offline Gaussian preparation helpers. No Unreal or GPU imports."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
OUTPUT = REPO / "Saved/Verification/gaussian_memory_20261001/data_pipeline"
SCENES = ("lower_gate_road", "numbered_stop_wall", "cistern_relay")
GSPLAT_COMMIT = "937e29912570c372bed6747a5c9bf85fed877bae"
COLMAP_COMMIT = "682ea9ac4020a143047758739259b3ff04dabe8d"
WORLD_FRAME = "gltf_right_handed_y_up_meters"
TIERS = (12000, 32000, 65000)


def scoped(path: str | Path) -> Path:
    result = Path(path).resolve()
    if not result.is_relative_to(OUTPUT.resolve()):
        raise ValueError(f"Output must remain under {OUTPUT}")
    return result


def read_json(path: str | Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: str | Path, value):
    path = scoped(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def finite_vector(value, size=3):
    if not isinstance(value, list) or len(value) != size:
        raise ValueError(f"Expected {size} finite components")
    result = [float(v) for v in value]
    if not all(math.isfinite(v) for v in result):
        raise ValueError("Nonfinite coordinate")
    return result


def ue_to_gltf(point_cm, origin_cm):
    x, y, z = [a - b for a, b in zip(point_cm, origin_cm)]
    return [x / 100, z / 100, y / 100]


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def cross(a, b):
    return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]


def normalized(v):
    length = math.sqrt(dot(v, v))
    if length < 1e-12:
        raise ValueError("Degenerate camera axis")
    return [x / length for x in v]


def rotation_quaternion_wxyz(r):
    """Proper rotation matrix to COLMAP Hamilton quaternion, scalar first."""
    trace = sum(r[i][i] for i in range(3))
    if trace > 0:
        s = math.sqrt(trace + 1) * 2
        q = [s/4, (r[2][1]-r[1][2])/s, (r[0][2]-r[2][0])/s, (r[1][0]-r[0][1])/s]
    else:
        i = max(range(3), key=lambda k: r[k][k])
        j, k = (i+1) % 3, (i+2) % 3
        s = math.sqrt(1+r[i][i]-r[j][j]-r[k][k]) * 2
        q = [0., 0., 0., 0.]
        q[0] = (r[k][j]-r[j][k])/s
        q[i+1], q[j+1], q[k+1] = s/4, (r[j][i]+r[i][j])/s, (r[k][i]+r[i][k])/s
    return normalized(q)


def actual_pose_to_colmap(frame, origin):
    """Consume measured UE camera basis; never use a planned pose as evidence."""
    center = finite_vector(frame["actual_position_ue_cm"])
    f = finite_vector(frame["actual_forward_ue"])
    right = finite_vector(frame["actual_right_ue"])
    up = finite_vector(frame["actual_up_ue"])
    for axis in (f, right, up):
        if abs(dot(axis, axis)-1) > 1e-5:
            raise ValueError("Actual camera basis must be unit length")
    if max(abs(dot(f, right)), abs(dot(f, up)), abs(dot(right, up))) > 1e-5:
        raise ValueError("Actual camera basis must be orthogonal")
    if dot(cross(f, right), up) < 0.99999:
        raise ValueError("Expected measured Unreal forward/right/up basis")
    swap = lambda a: [a[0], a[2], a[1]]
    r = [swap(right), [-v for v in swap(up)], swap(f)]
    c = ue_to_gltf(center, origin)
    return rotation_quaternion_wxyz(r), [-dot(row, c) for row in r]


def require_capture_receipt(dataset: Path):
    """Check real capture files and immutable hashes before reconstruction/training."""
    receipt_path = dataset / "capture_receipt.json"
    receipt = read_json(receipt_path)
    if receipt.get("id") not in SCENES or receipt.get("captured") is not True:
        raise ValueError("A genuine capture receipt is required")
    if receipt.get("world_frame") != WORLD_FRAME or len(receipt.get("frames", [])) != 96:
        raise ValueError("Expected 96 measured views in the agreed world frame")
    if receipt.get("resolution") != [960, 540] or receipt.get("height_bands") != 2:
        raise ValueError("Capture size / height bands disagree with the packet")
    if not all(receipt.get(k) is True for k in ("exposure_locked", "animation_frozen", "wind_frozen", "materials_approved")):
        raise ValueError("Capture must attest fixed exposure, scene, wind and approved materials")
    if not receipt.get("source_scene") or not receipt.get("capture_tool") or not receipt.get("asset_license"):
        raise ValueError("Capture tool, source scene and asset license are required")
    if not isinstance(receipt["asset_license"], str):
        raise ValueError("Asset license must be a nonempty rights/license string")
    exposure = receipt.get("locked_exposure")
    if not isinstance(exposure, dict) or exposure.get("method") != "manual" or not exposure.get("tone_mapper"):
        raise ValueError("Measured manual exposure and tone-mapper settings are required")
    if not isinstance(exposure.get("ev100"), (int, float)) or not math.isfinite(exposure["ev100"]):
        raise ValueError("A finite actual locked EV100 is required")
    if not receipt.get("source_actor_paths") or not receipt.get("captured_at_utc"):
        raise ValueError("Source actor identities and real capture timestamp are required")
    finite_vector(receipt["origin_ue_cm"])
    fx, fy, cx, cy = finite_vector(receipt["intrinsics"], 4)
    if fx <= 0 or fy <= 0 or not 0 <= cx <= 960 or not 0 <= cy <= 540:
        raise ValueError("Invalid measured PINHOLE camera intrinsics")
    if len(receipt.get("fiducials", [])) != 4:
        raise ValueError("Exactly four surveyed source fiducials are required")
    for f in receipt["fiducials"]:
        expected = ue_to_gltf(finite_vector(f["source_ue_cm"]), receipt["origin_ue_cm"])
        actual = finite_vector(f["gltf_m"])
        if max(abs(a-b) for a, b in zip(expected, actual)) > 1e-6:
            raise ValueError("Fiducial transform mismatch")
    names = set()
    bands = [0, 0]
    for frame in receipt["frames"]:
        name = frame["name"]
        if Path(name).name != name or name in names or not name.endswith(".png"):
            raise ValueError("Capture image names must be unique local PNG basenames")
        names.add(name)
        band = frame["height_band"]
        if band not in (0, 1):
            raise ValueError("Invalid height band")
        bands[band] += 1
        actual_pose_to_colmap(frame, receipt["origin_ue_cm"])
        for key in ("rgb", "mask", "depth"):
            entry = frame[key]
            file = (dataset / entry["path"]).resolve()
            if not file.is_relative_to(dataset.resolve()) or sha256(file) != entry["sha256"]:
                raise ValueError(f"Missing or changed {key} capture for {name}")
        if frame.get("depth_units") != "meters" or frame.get("depth_convention") != "camera_forward_z":
            raise ValueError("Depth must record metric camera-forward Z")
    if bands != [48, 48]:
        raise ValueError("Each height band must contain 48 actual views")
    return receipt, receipt_path
