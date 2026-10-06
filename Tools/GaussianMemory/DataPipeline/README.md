# Offline genuine Gaussian memory data preparation

This package is prepared for the approved `lower_gate_road`,
`numbered_stop_wall` and `cistern_relay` tableaux. No capture, reconstruction,
training, export, installation, editor operation or GPU work was executed in
this preparation pass. No real Gaussian data is present in this package.

Current state: **needs_root_bounds_and_offline_capture**. Root must survey the
actual source actors and bounds after the live playtest ends. The bounds
template deliberately contains null coordinates. A planned camera is never
accepted as proof of a captured camera.

## Scripts

- `prepare_capture.py`: consumes root-approved surveyed bounds and writes 96
  overlapping orbit poses, 48 at each of two heights, at 960 by 540. It creates
  a camera plan only. `CAPTURE_CONTRACT.md` describes the capture bridge inputs.
- `build_colmap.py`: checks actual capture provenance and prints the official
  known-pose COLMAP workflow. `--execute` later prepares masked foreground
  images, extracts/matches features on CPU, reconciles actual image IDs with
  the database, writes measured poses and triangulates real source features.
- `train_gsplat.py`: prints the training configuration. `--execute` later runs
  the unmodified official gsplat Runner from a clean pinned source checkout.
  It uses genuine triangulated initialization, full SH degree 3, fixed poses,
  normalization disabled, one process and an MCMC count cap. It records the
  final full Gaussian PLY, checkpoint hash, source receipts and environment.
- `export_gaussians.py`: consumes the real training receipt, full PLY and root's
  actual-data review. It produces uncompressed float Gaussian GLB and glTF/bin,
  a local `tileset.json`, and a per-asset `manifest.json`. XYZ/RGB point clouds,
  compressed PLYs, missing anisotropic scales/rotation/opacity/SH, partial SH,
  nonfinite parameters, changed hashes and counts above 65000 are rejected.

All generated files stay below
`Saved/Verification/gaussian_memory_20261001/data_pipeline/`. These scripts
do not stage files into plugin resources. Later reviewed staging must copy the
asset's `tileset.json`, `memory.glb`, `manifest.json` and requested `tiers/`
folders to `Plugins/SaskartaCore/Resources/GaussianMemories/<id>/` through root.
The alternate `memory.gltf` requires its adjacent `memory.bin`.

## Reproducible source pins and dependencies

The official Apache-2.0 trainer is gsplat v1.5.3 at
`937e29912570c372bed6747a5c9bf85fed877bae`. Its example is
[`examples/simple_trainer.py`](https://github.com/nerfstudio-project/gsplat/blob/937e29912570c372bed6747a5c9bf85fed877bae/examples/simple_trainer.py).
The verified tag reference points directly to this commit. The exact upstream
license is retained in `licenses/gsplat-LICENSE.txt`; trainer licensing does not
grant rights to the game's captured meshes, materials or resulting assets.
Root must record the actual asset license/rights in the capture receipt.

Use the official COLMAP 3.11.1 release, commit
`682ea9ac4020a143047758739259b3ff04dabe8d`. Its pinned
[`RunPointTriangulator`](https://github.com/colmap/colmap/blob/682ea9ac4020a143047758739259b3ff04dabe8d/src/colmap/exe/sfm.cc)
fixes existing camera poses and exposes `--refine_intrinsics 0`. The source pin
defines the expected CLI; the script checks the executable release string and
records the invoked executable/launcher SHA-256 for the actual reconstruction.
When using a batch launcher, also retain its actual native executable hash in
root's offline environment evidence.

Prepare a dedicated offline environment later with a compatible CUDA/PyTorch
installation, the pinned gsplat source and its exact example requirements.
The upstream requirements themselves pin the example's legacy pycolmap parser
and nerfview/fused modules, but not every transitive dependency. Preserve an
environment lock / installed package listing and actual CUDA/driver versions
when training. `build_colmap.py` also requires Pillow and NumPy for genuine
mask/depth ingestion; the exporter uses only the Python standard library.
This pass did not install dependencies. Dependency/license acceptance and
machine compatibility remain for the offline execution review.

## Later commands (not executed)

Run from the repository root, after configuring the bounds file and completing
the real offline capture. Substitute actual checked-out paths:

```powershell
python Tools/GaussianMemory/DataPipeline/prepare_capture.py --bounds Saved/Verification/gaussian_memory_20261001/data_pipeline/bounds_template.json --id lower_gate_road
python Tools/GaussianMemory/DataPipeline/build_colmap.py --dataset Saved/Verification/gaussian_memory_20261001/data_pipeline/lower_gate_road --colmap D:/Offline/COLMAP-3.11.1/COLMAP.bat
# Add --execute only in the later offline capture/training session.
python Tools/GaussianMemory/DataPipeline/train_gsplat.py --dataset Saved/Verification/gaussian_memory_20261001/data_pipeline/lower_gate_road --gsplat-checkout D:/Offline/gsplat --tier 65000
python Tools/GaussianMemory/DataPipeline/export_gaussians.py --ply Saved/Verification/gaussian_memory_20261001/data_pipeline/lower_gate_road/trained_65000/ply/point_cloud_29999.ply --training-receipt Saved/Verification/gaussian_memory_20261001/data_pipeline/lower_gate_road/trained_65000/training_receipt.json --review Saved/Verification/gaussian_memory_20261001/data_pipeline/lower_gate_road/data_review.json --out Saved/Verification/gaussian_memory_20261001/data_pipeline/lower_gate_road/export
```

Process one tableau at a time. `--tier` caps training at 12000, 32000 or 65000.
Real triangulated initialization must already fit that cap. A 65000 training
can supply export tiers with limits of 12000/32000/65000 by deterministic
selection of existing trained Gaussians, highest opacity first. Actual counts
are recorded and can be lower than a tier's limit. Selection can change visual
coverage: root must review each exported tier; these are data budgets, with no
measured quality or GPU performance claim.

## Coordinate and representation contract

Unreal source cameras/actors use centimeters. Choose a surveyed local source
origin. Train directly in right-handed glTF Y-up meters:

`gltf = [(UE_X-origin_X)/100, (UE_Z-origin_Z)/100, (UE_Y-origin_Y)/100]`.

This explicit reflection/permutation makes physical Unreal Z become glTF Y.
COLMAP camera axes are right, down, forward. Its camera rotation is world to
camera, Hamilton WXYZ; translation is `-R * camera_center`. The implementation
uses actual measured UE forward/right/up vectors, converts those basis vectors
and writes proper right-handed camera rotations. Source origin subtraction
also applies to the four root-surveyed fiducials. Training normalization and
camera optimization are disabled so learned orientation and SH remain in the
same glTF frame. An arbitrary existing PLY from another frame is rejected;
rotating positions alone would leave its covariance/SH inconsistent.

The official gsplat full PLY stores log scales, opacity logits, WXYZ quaternion,
DC SH and channel-major higher SH. Export applies `exp` / `sigmoid`, normalizes
the quaternion, writes glTF XYZW and maps all higher coefficients to VEC3
attributes. It emits explicit `OPACITY` and `SH_DEGREE_0_COEF_0`, plus `COLOR_0`
RGBA for the installed Cesium v2.29.1 loader. Current Khronos mandatory fields
and Cesium's older field consumption therefore coexist. Float `COLOR_0` is
clamped to the core glTF range; complete trained DC values remain in explicit
SH0, which the installed loader does not consume. Out-of-range DC and that
loader's color-space treatment require later visual comparison.

The [Khronos specification](https://github.com/KhronosGroup/glTF/blob/81762cc328b160eafaa0d577dd547a998401ade9/extensions/2.0/Khronos/KHR_gaussian_splatting/README.md)
was inspected on 2026-10-01 and is now ratified. `POINTS` mode, `ellipse` kernel,
`srgb_rec709_display`, perspective projection and camera-distance sorting match
the installed extension header. The extension is required, so a client lacking
Gaussian support must reject the asset rather than display an ordinary point
cloud fallback.

The 3D Tiles box is in right-handed Z-up meters, with glTF's usual Y-to-Z
conversion `[x,-z,y]`. Bounds include each oriented Gaussian's 3-sigma extent
expanded by 4 percent for scale breathing, plus 0.12 m on every axis for dream
motion. Tile transform is identity and
content URI is local `memory.glb`. Root's renderer actor supplies the reviewed
placement; this data has no geographic/ECEF location or fabricated station
coordinates. Cesium's internal `positionScaleFactor = 1024` is paired with
its inverse component transform and must not be mistaken for 100 cm/m.

The installed loader was read at
`Plugins/CesiumForUnreal/Source/CesiumRuntime/Private/CesiumGltfGaussianSplatComponent.cpp`
and its native extension header. It reads float VEC3 position/scales, float
VEC4 orientation/RGBA, and full degree-specific higher SH attributes. Its
`CesiumGltfComponent.cpp` applies glTF Y-up to tile Z-up. Loader correctness,
four-marked-point alignment, static/dream bounds, occlusion, each tier's visual
coverage and actual performance remain unverified until real assets are loaded.

## Actual-data review gate

Root supplies `data_review.json` for the exact trained PLY SHA-256. It must
record reviewer, source bounds, asset license acceptance, four verified
fiducials, removal of sky/floor shells and floaters, and a clear 1.5 m walking
corridor. The exporter does not silently crop an unreviewed scene or synthesize
replacement geometry. Use actual masks/capture isolation and real trained-data
cleanup before signing that review. The full original PLY and capture/training
receipts stay retained in the verification folder.

The package was reviewed as source only. No Python scripts, trainer, tests,
builds, editor, reconstruction or exporter were run. Its missing real capture
and trained PLY are an explicit execution blocker, not a completed memory asset.
