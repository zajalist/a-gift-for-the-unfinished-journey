# Current road collision diagnosis, 2026-09-29

The baseline table below records the impassable road before the local42 patch.
On 2026-09-29 the guarded patch was installed and verified in the editor; the
updated `Current_u16.png` passes this gate with **zero** full-core stations
above the carrier's 50° walkable-floor angle. The resulting map still needs a
live drive through 3450–4200 m for final acceptance.

Run from the project root:

```powershell
python Tools/Terrain/diagnose_road_traversability.py
```

This read-only gate samples `Saved/TerrainRebuild/Current_u16.png` at 1 m road stations from 3450 to 4200 m and every 0.25 m across the 4.5 m painted road core. It writes `Saved/TerrainRegrade/traversability_current.json` and exits **1 / RED** if any station exceeds the configured 50° carrier walkable-floor angle across that whole core. A passing interval exits 0, for example `python Tools/Terrain/diagnose_road_traversability.py --start-m 3950 --end-m 4200 --out Saved/TerrainRegrade/traversability_upper.json`. It reports the 44.765° engine-default comparison too. Normals come from bilinear height samples at world XY ±1 m; these approximate Landscape collision and do not replace a live floor-normal/standing test.

The current image is 8161×8161 16-bit pixels, with origin (−18920.4, 50) cm, XY spacing 100 cm/pixel and elevation `(u16−32768)×1.5625` cm. `BP_Saskarta_Road`'s RVT ribbon paints the ground; it does not provide a driveable collision surface. `Tools/GameFlow/gen_carrier_drive.py` sets `WalkableFloorAngle` to **50°** in `StartCarrierExtras`, even though the older road-profile default is 44.765°. Motor assist only runs while grounded on a walkable floor, so it cannot carry the pawn across a >50° barrier.

| Road stations | Centerline peak uphill (1 m) | Center floor peak | Full-core >50° stations |
|---|---:|---:|---:|
| 3450–3600 m | 54.34° | 60.71° | 0; lateral lines still contain steep spots |
| 3600–3700 m | **56.03° at 3632–3633 m** | 56.07° | **3632–3641 m** |
| 3700–3860 m | 51.60° | 50.97° | 0 |
| 3860–3950 m | 51.40° | 53.97° | **3921 and 3928–3929 m** |
| 3950–4200 m | 31.15° | 35.91° | 0 |

There are 18 centerline uphill 1 m edges over 50°, 24 center-floor stations over 50°, and **13 stations where all 19 sampled lateral positions exceed 50°**. At the 44.765° default, the corresponding counts are 40, 59 and 32; full-core spans are 3588–3590, 3592, 3621–3622, 3631–3647, 3689–3690, 3703–3704, 3920–3922 and 3928–3929 m. At road 3670 m itself, the estimated floor is only 29.47° on center and at most 40.13° across the core. The fatal grade is earlier near 3632–3641 m; the scripted fall trigger around 3700 m is a separate event.

## Localized review candidate

Keep RoadSpline **XY** and existing story/secret road stations. The first-pass local bed used four windows (3508–3532, 3548–3668, 3680–3720, 3908–3942 m), a 42° fixed-endpoint minimax longitudinal profile, a 5.5 m bed with 2% crossfall, 20 m feather and 8 m endpoint ease. A simple nearest-road feather made a sharp 78° seam where two switchback arms are about 10 m apart. Merely widening that feather to 40 m worsened the result to an 11 m cut and ~82° adjacent slope. The accepted **offline review candidate** smooths the elevation *delta field* outside the protected 2.5 m core across competing switchback branches; no terrain import has occurred.

```powershell
python Tools/Terrain/regrade_road_local.py
python Tools/Terrain/emit_road_height_patch.py
```

The reproducible candidate, gate report and terrain comparison are `Saved/TerrainRegrade/local42_review_u16.png`, `local42_review_report.json` and `local42_review.png`. It changes 13,859 pixels, cuts at most **5.125 m** and fills at most **3.8125 m**. The full 3450–4200 m diagnostic reports no center floor over the configured 50°, no center uphill edge over 50°, and no full-core barrier over 44.765°. In a 31 m road buffer, maximum sampled slope is **64.573° before and after**, while p95 falls from 51.08° to 50.73°. This removes the first-pass cliff without claiming that every bank is driveable. At 0.1 m lateral sampling, the narrowest contiguous walkable width at 50° is about 2.9 m near road 3642; compare that against the **live carrier capsule radius** before acceptance. The road-center floors at 3600/3700/3860 m change by about +0.25/+0.43/0 m respectively. The old full-window 42° candidate changed 24,280 pixels, cut 9.11 m and produced a 78.34° adjacent flank; do not import that version.

The candidate's actual changed pixels intersect bounding boxes of 15 saved `S20_LongStair` set-dress descriptors and none of the saved S19, R04 or S21 descriptors. At the planned stele sample pixels, WayStones 25 and 26 would move about −1.64 m and −0.91 m; the B12 road center rises ~0.25 m. Road spline control points 21 (~3593 m), 20 (~3643 m) and 15 (~3915 m) require height checks. This is not a final moved-actor list: the loaded world may contain actors absent from the saved descriptors, and all supports must be checked after an accepted terrain update.

The offline acceptance gate for any candidate must re-sample **combined floor normals across the whole core and the feather**, not merely centerline longitudinal grade or 6 m average cross-slope. Require zero full-core red stations, enough walkable lateral clearance for the carrier capsule, no new hazardous flank/edge, and an editor visual/collision check at each patch. Re-align affected RoadSpline control-point Z, grounded props/steles and B12 Z from the accepted Landscape; then regenerate the road profile and verify trigger positions because 3D spline arc length changes even with XY fixed. Do not change the secret location or narrative distances.

The change is packaged as `Saved/TerrainRegrade/Local42Patch/{source_roi.r16,target_roi.r16,manifest.json}`. The manifest gives 16-bit little-endian row-major samples in an inclusive **212×336** rectangle at source pixel X 3643–3854, Y 3780–4115 (two unchanged samples around the changed extent), plus exact hashes, world mapping and preflight conditions. An offline reconstruction of the candidate from the source image plus the target rectangle is bit-for-bit exact. This package is **review-only**, not an editor installation command.

Hayba's catalogue search exposes landscape inspection, material/LOD/layer property writes and `hayba_import_landscape`, but **no typed existing-Landscape regional height write**. UE 5.8's Blueprint-callable `ALandscapeProxy::LandscapeImportHeightmapFromRenderTarget` (`LandscapeProxy.h:1572`, `LandscapeEdit.cpp:8078`) takes a render target from the **full Landscape extent's origin** and writes its selected edit layer. Its RGBA16f R-only mode can lose uint16 precision; exact RG packing in RGBA8 and a full 8161² render target would be required here. It is not a regional import path and is too broad for this patch. The safer path is a small editor-only C++ helper using `FLandscapeEditDataInterface`/`FHeightmapAccessor` with explicit edit-layer GUID, loaded component coverage and collision update. Before any write, compare the live Landscape extent, transform, selected layer and **every** current uint16 sample against `source_roi.r16`; abort on any mismatch, missing/locked component or unexpected edit-layer composition. Back up only affected component packages, apply the target rectangle, flush, read back all samples and collision normals, and save only those packages after visual inspection. `LandscapeEditInterface.cpp:235–263` exposes component/lock checks; `:264` exposes regional `SetHeightData`. Parent/root owns the editor gate and live installation. No terrain asset, Landscape component or road spline was changed during this offline work.
