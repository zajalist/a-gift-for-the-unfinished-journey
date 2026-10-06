# Actual offline capture bridge contract

Wait until root releases the live playtest freeze. Use only the approved source
actors for one tableau at a time, with original approved materials and fixed
lighting. Exclude known floating cart/broken wall defects. Freeze animation and
wind, lock a single measured exposure and tone map for all views, hide UI and
do not save a modified world. Root must first approve source actor paths,
tableau bounds, orbit radius, two heights and four surveyed visible marks.

`prepare_capture.py` produces a procedural 96-view orbit plan. A trusted Unreal
capture bridge, Movie Render Queue setup or renderer script must capture the
actual 960 by 540 images and read back each camera's actual world position and
forward/right/up basis. It must preserve the PINHOLE intrinsics and account for
any crop, overscan, lens distortion or image flip. Planned transforms may not
be copied to the actual fields without measured readback. No capture bridge was
executed or claimed to be integrated in this packet; root's bridge needs to
produce this contract before reconstruction can proceed.

For each view retain original display-referred sRGB/Rec.709 RGB PNG, a binary
foreground mask PNG (255 foreground / 0 background), and measured forward-Z
depth as a NumPy float array `(540,960)` in meters. Masks select approved source
objects and remove sky/floor shells; they must be actual segmentation, not an
invented point cloud. Perspective linear depth is not Euclidean ray range;
if range is exported, convert it using calibrated per-pixel ray directions and
record that derivation. Derive mask/depth from genuine renderer buffers and
record the tool/version/settings used.

Write `capture_receipt.json` beside the capture folders, as follows. Angle/FOV,
exposure settings, actor paths, actual numbers, SHA-256 strings and source
license must come from root's real capture. This is a shape description;
null values cannot pass the ingestion check.

```json
{
  "id": "lower_gate_road",
  "captured": true,
  "source_scene": "actual saved source map/package and revision",
  "capture_tool": "actual bridge/version/settings",
  "captured_at_utc": "actual timestamp",
  "world_frame": "gltf_right_handed_y_up_meters",
  "origin_ue_cm": null,
  "intrinsics": null,
  "resolution": [960, 540],
  "height_bands": 2,
  "exposure_locked": true,
  "locked_exposure": null,
  "animation_frozen": true,
  "wind_frozen": true,
  "materials_approved": true,
  "source_actor_paths": [],
  "asset_license": null,
  "fiducials": [],
  "frames": [
    {
      "name": "view_000.png",
      "height_band": 0,
      "actual_position_ue_cm": null,
      "actual_forward_ue": null,
      "actual_right_ue": null,
      "actual_up_ue": null,
      "rgb": {"path": "capture_rgb/view_000.png", "sha256": null},
      "mask": {"path": "capture_masks/view_000.png", "sha256": null},
      "depth": {"path": "capture_depth/view_000.npy", "sha256": null},
      "depth_units": "meters",
      "depth_convention": "camera_forward_z"
    }
  ]
}
```

There must be 96 unique frames, 48 in each height band. `intrinsics` is measured
`[fx,fy,cx,cy]` in pixels using COLMAP's pixel-corner convention; the nominal
uncropped plan centers on `[480,270]`. Each of four fiducials has a name,
actual `source_ue_cm` and the corresponding transformed `gltf_m`. Record enough
spacing in the marks to establish axes, handedness and metric scale; four
coincident or collinear marks are insufficient for the later rendered review.

`build_colmap.py` composites the genuine foreground onto black while retaining
original captures, copies actual masks to COLMAP's `image-name.png` mask naming
convention, then follows the official
[known-camera workflow](https://colmap.github.io/faq.html#reconstruct-sparse-dense-model-from-known-camera-poses).
It reads image IDs from the actual database before writing camera poses.
The camera convention follows the official
[COLMAP model format](https://colmap.github.io/format.html#images-txt).

The pinned official trainer uses triangulated source features as initialization;
those plain XYZ/RGB initialization points do not count as trained Gaussians.
Only the full trained PLY containing genuine optimized covariance, orientation,
opacity and SH may be passed to `export_gaussians.py`.
