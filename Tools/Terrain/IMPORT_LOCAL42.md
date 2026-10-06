# Local42 Landscape patch: editor installation

Installed in `Saskarta_WP` on 2026-09-29. Guarded preflight matched all
71,232 source samples in both raw and composed heightmaps. The write created a
scoped backup; verification matched all 71,232 target samples and collision,
then saved only two Landscape packages. RoadSpline points 20 and 21 and
WayStones 25 and 26 (including glyphs) were aligned to the new terrain. The
offline traversability gate now reports zero full-core impassable stations at
50°. A live carrier drive remains the runtime acceptance check.
The steps below document the one-time installation and should not be rerun on
the patched map: the source-height guard will correctly reject a second apply.

This is a guarded editor-only regional import, not a whole-map reimport. The
installed candidate is `Saved/TerrainRegrade/local42_review_u16.png`; the only
write payload is the exact 212 × 336 uint16 rectangle under
`Saved/TerrainRegrade/Local42Patch`. The source and target files are checked
against the manifest SHA256 hashes. No HLOD rebuild is part of this step.

The native helper lives in the new `SaskartaTerrainEditor` module. Build it only
with the editor **closed**, then open `/Game/level/Saskarta_WP`, load the region
at road 3450–4200 m, and save other work first. No PIE or standalone game may
be running. Use the editor Python command runner in this order, inspecting each
returned string. A result beginning `FAIL:` stops the process; do not continue
to the next call or save the map.

```python
import unreal
patch = unreal.SaskartaTerrainPatchLibrary
result = patch.preflight_local42()
print(result)
assert result.startswith("PASS:"), result
```

Preflight requires the exact map and Landscape label, complete 0–8160
component extent, origin (−18920.4, 50, 0) cm, scale (100, 100, 200), no
rotation, one visible unlocked edit layer, all overlapping World Partition
components loaded and registered, and no pre-existing dirty affected packages.
It compares **all 71,232** source samples in both that edit layer and the final
composed heightmap. The older 2026-09-20 record reports Z=120000 and XY scale
99.987747. If the live Landscape still has that transform, preflight will
stop. Inspect the actual mapping and source export; do not weaken this guard
based on the historical record alone.

After a passing preflight and a reviewed visual candidate:

```python
result = patch.apply_local42()
print(result)
assert result.startswith("APPLIED"), result
```

`ApplyLocal42` repeats preflight, copies every affected package to a new
`Saved/TerrainRegrade/Local42Patch/BackupPackages/<GUID>` directory and writes
the ROI only through `FLandscapeEditDataInterface::SetHeightData`. It flushes
the layer data and requests height/collision updates. Let the editor process
the update, inspect the nearby road and flanks, then run:

```python
result = patch.verify_and_save_local42()
print(result)
assert result.startswith("PASS:"), result
```

This forces layer composition, compares every raw and final height sample to
the target, traces the updated collision at the strongest change in each
affected component, then saves only allowlisted affected Saskarta_WP packages.
If verification fails, the in-memory restoration method requires the exact
target as its starting state and writes the baseline back; it does not save:

```python
print(patch.restore_local42())
```

Following a successful save, inspect the road control points near 3593,
3643 and 3915 m, S20 placements, and WayStones 25–26. Refresh only their
grounded Z as needed. Export a fresh authoritative `Current_u16.png`, then
regenerate the road profile and re-run the traversability gate. Finish with
an actual carrier drive over 3450–4200 m; offline slope sampling cannot prove
the live collision/drive behavior by itself.

Offline checks run: `python -m pytest Tools/Terrain/tests/test_regrade_road.py
-q` (7 passed), and `git diff --check` (no whitespace errors). Native helper
build and live preflight are pending the editor owner.
