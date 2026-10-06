# Offline road regrade candidate

Historical first-pass study. The narrower local42 candidate was installed on
2026-09-29; see `IMPORT_LOCAL42.md` and `ROAD_TRAVERSABILITY.md` for the
installed patch and its remaining runtime drive check.

`regrade_road.py` prepares a review-only heightmap for the switchback following
B11. It reads `Saved/TerrainRebuild/Current_u16.png`, preserves RoadSpline XY,
and writes only to `Saved/TerrainRegrade/`. It does not edit Unreal Content or
the authoritative heightmap.

Run from the project root:

```powershell
python Tools/Terrain/regrade_road.py
python -m pytest Tools/Terrain/tests/test_regrade_road.py -q
```

The output contains `candidate_u16.png`, `regrade_report.json`, the sampled
profile CSV, and profile, corridor, and cross-section plots. The candidate
keeps the source 16-bit dimensions and mapping. `--cap-deg` sets the target
longitudinal grade; `--feather-m` changes the lateral terrain blend width.
The report includes grades, cut/fill totals, and before/after terrain
steepness in road buffers.

## Feasibility and review result

The fixed 3450–3950 m elevations are −315.742 m and −83.262 m, a 232.481 m
rise over 500 m. This 46.50% mean grade is feasible under a 42° target. The
default 42° profile with a 20 m endpoint ease produces a quantized maximum
one-metre road grade of 43.04° (below the 44.765° hard cap); endpoint errors
are 3–4 mm. The route XY remains unchanged.

This candidate is **not approved for import** pending parent visual review.
In the 40°/41°/42° sweep with a 20 m feather, the 42° candidate is least
destructive: maximum correction is a 9.11 m cut and 5.94 m fill, with estimated
21,486 m³ cut and 12,523 m³ fill across 24,280 changed 1 m² pixels. The largest
cut is near station 3644 m. Extending the longitudinal window to 3400–4000 m did
not reduce the maximum cut. Increasing the feather to 25/30 m raised max cut to
9.75/10.47 m and cut volume to about 31,470/43,917 m³, so a wider smoothstep
feather is not an improvement by itself.

The 20 m candidate also steepens some adjacent flanks. In the 23 m buffer,
terrain-slope p95 changes from 50.57° to 51.30°, and the maximum changes from
64.57° to 78.34°. The profile and corridor plots show where the local cuts and
fills fall. A different longitudinal shape or slope-aware grading design is
needed if the goal is to keep cut under 8 m and avoid steep adjacent faces.

The 6 m bed improves the sampled drive-width cross-slope p95 from 34.03° to
1.27°, but this single-width metric hides the adjacent cuts and fills. The
sampled maximum is 21.05° at the hairpin near 3860 m. Do not use the p95 as an
acceptance criterion by itself. Inspect
`road_regrade_corridor.png`, `road_regrade_cross_sections.png`, and
`regrade_report.json` together.

## Affected authored content and data authority

The affected footprint is broader than the nominal road-distance window. A
read-only placement audit found changed terrain within 23 m of placements in:

- `S19_LastWaystation` (14/25 placements, although its site is at road 3400 m);
- `S20_LongStair` (39/41 placements, site road 3650 m);
- `R04_Verge3750` (2/2 placements);
- `S21_CloudNiche` (75/75 placements, site road 3850 m).
- Waystones `Stele_WayStone_24`–`_27` sample about +1.56, −3.58, −0.36, and
  −1.27 m terrain correction at their XY. `Stele_WayStone_28` is close to the
  changed footprint and should be checked even though its sampled height is
  unchanged.

The B12 story anchor at road 3600 m also falls in the window. Preserve its XY
and refresh its Z from the accepted Landscape. The stele plan derives body and
glyph Z from `Tools/Story/build_road_profile.py`'s terrain sampler; re-run
`Tools/Story/place_steles.py plan` after the new heightmap is authoritative,
then update the existing actors and glyph decals. S20, R04, and S21 are story or
place groups whose authored XY remains valid, but their grounded actor Z and
any support geometry need re-settling after a final regrade. S19 needs the
same review because the lateral terrain cut reaches its actors.

The live road actor is `BP_Saskarta_Road` and its `RoadSpline` drives the road
ribbon and nearest-road/story logic. No project-side spline construction or
write script was found: the offline source points are duplicated in
`Tools/Story/build_road_profile.py` (`SPLINE_POINTS_CM`, points 0–54) and
`Saved/TerrainRebuild/saskarta_road_thing.json`. The saved JSON is a data
snapshot, not a tool that updates the live actor. After a candidate is approved
and imported, keep the RoadSpline XY fixed and align its control-point Z to the
new terrain; points 15–23 overlap the candidate, while points 14 and 24 sit just
outside its road-distance bounds and should be checked at the blend edges. Then
update the offline point snapshot/array from the accepted live spline and regenerate
`docs/story/road-profile.json` and `.md` with
`python Tools/Story/build_road_profile.py`. Review story trigger distances
afterward because RoadSpline's 3D arc length changes when Z changes.

After the accepted Landscape has been exported as the new authoritative
`Current_u16.png`, rerun the affected terrain-derived placement, road profile,
and ecology-mask tools and review their outputs before importing them. Keep
XY-based road influence masks and story anchors in place; regenerate slope and
height-dependent foliage/ecology masks. Do not regenerate broad PCG content
as part of this local road edit.

## UE 5.8 heightmap update path

The local UE 5.8 source exposes two editor-side paths. The World Browser
Landscape reimport path works when
`ReimportHeightmapFilePath` is set. `FWorldTileModel::CanReimportHeightmap`
checks the path and imported image resolution against Landscape component
bounds in `Engine/Source/Editor/WorldBrowser/Private/Tiles/WorldTileModel.cpp`
(lines 344–357); its import path calls `ALandscapeProxy::Import` (around line
1049). The runtime property is declared in
`Engine/Source/Runtime/Landscape/Classes/LandscapeProxy.h` (around line 877).

For an editor C++ utility, `LandscapeEditorUtils::SetHeightmapData` is declared
in `Engine/Source/Editor/LandscapeEditor/Public/LandscapeEditorUtils.h:18` and
implemented in `LandscapeEdMode.cpp:4400`. It accepts a full-landscape
row-major `TArray<uint16>`, returns false unless the sample count exactly
matches the Landscape bounds plus section base, then writes through
`FHeightmapAccessor` and its edit-data interface. The lower-level
`FLandscapeEditDataInterface::SetHeightData` supports regional writes
(`Engine/Source/Runtime/Landscape/Public/LandscapeEdit.h:145`); its interface
has explicit edit-layer constructors and `Flush()` (`LandscapeEdit.h:125–145,
98`). `LandscapeEditorUtils` belongs to the editor-only `LandscapeEditor`
module and is not a Python-callable API. The reviewed Python editor-scripting
sources exposed no equivalent setter. This identifies a possible native
implementation path; no plugin or editor change was made, and it is not
approval to import any candidate.
