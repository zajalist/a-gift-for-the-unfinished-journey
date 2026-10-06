# Road tether: spurs and exploration zones (task TETHER)

Task TETHER, 2026-09-28. The tether change proposed in `docs/world/SETDRESS_PLAN.md` §8, which makes the six reachable off-road POIs (O01, O03, O06, O09, O10, O14) walkable. It was written offline. The C++ compiles on a copy but is **not built in the project yet**, and the Blueprint change and the level actors wait for the steps below.

## What changes

| Before | After |
|---|---|
| `BPC_RoadTether` measures the 2D distance to `BP_Saskarta_Road`'s spline | It measures the 2D distance to the **nearest allowed line**: the road plus every tether path, and 0 inside an exploration zone |
| Warn at 10 m, clear at 9 m, reboot at 20 m | The same thresholds, measured to the nearest road or path |
| The respawn goes to the nearest road point | The respawn goes to the nearest road **or path** point. On a path it steps toward the junction and faces it; on the road it faces up-road as before |
| `road_m` follows the pawn's nearest road point | `road_m` **holds** while the pawn is on a detour (more than 10 m off the road, on a path or in a zone). A spur never fires or skips a beat |
| No radio hook | A change to Warning calls the station's `NotifyOffroad`. The C++ ignores it unless the carrier is more than 10 m from every allowed line |

## Files

| File | What it is |
|---|---|
| `Plugins/SaskartaCore/Source/SaskartaCore/Public/SaskartaTetherSubsystem.h`, `Private/SaskartaTetherSubsystem.cpp` | `USaskartaTetherSubsystem` (a world subsystem for Game and PIE worlds), `FSaskartaTetherQuery` and the pure `FSaskartaTetherLogic` |
| `.../Public/SaskartaTetherActors.h`, `Private/SaskartaTetherActors.cpp` | `ASaskartaTetherPath` (a spline, tag `Saskarta.TetherPath`) and `ASaskartaExploreZone` (a sphere whose radius follows `RadiusCm`, tag `Saskarta.ExploreZone`). Both are always loaded in World Partition and register at BeginPlay |
| `.../Private/Tests/SaskartaTetherTest.cpp` | `Saskarta.Tether.NearestSpline`, `.ZoneOverride`, `.RespawnSelection`, `.RoadProgressHolds` |
| `.../Private/SaskartaEventRunner.cpp` (hook) | `PollRoad` returns before the `road_m` / high-water update while `IsDetour` |
| `.../Private/SaskartaRadioStation.cpp` (hook) | `NotifyOffroad` returns while `IsPlayerOnAllowedGround` |
| `Tools/GameFlow/gen_tether_specs.py` → `specs/BPC_RoadTether.tether.json` | the scoped Blueprint change: the `CheckRoad` and `ComputeRespawn` graphs |
| `Tools/World/make_tether_paths.py` → `Tools/World/tether_paths.json`, `Saved/Tether/scripts/tether_*.py` | the paths, zones and editor scripts |
| `Tools/World/tests/test_tether_paths.py` | the offline tests (11) |

## The subsystem

- **Allowed lines.**
  - The road is the `BP_Saskarta_Road*` actor's spline, or any actor tagged `Saskarta.Road`. This is the same rule as the event runner.
  - The paths are every `ASaskartaTetherPath`, or any actor tagged `Saskarta.TetherPath` that has a spline with at least 2 points.
  - The zones are every `ASaskartaExploreZone`, or any actor tagged `Saskarta.ExploreZone`. The radius comes from a sphere component, then from a numeric `RadiusCm` / `ExploreRadiusCm` / `Radius` property, then from the actor's horizontal bounds (for a volume). A zone is a vertical cylinder: only the XY distance counts.
- **The distance** keeps the old maths: `FindInputKeyClosestToWorldLocation` in 3D, then `Dist2D` to that point. The road is measured first. A path is measured only when its cached 2D bounds (grown by 20 m) are nearer than the best distance so far. On the road the six spurs therefore cost one box test each.
- **Queries** have no Tick. The callers' timers drive them: `BPC_RoadTether.CheckRoad` every 0.2 s, and the event runner's road poll.
  - One query per frame and location is memoised, so the tether, the runner and the radio share it.
  - The actor scan runs when a tether actor begins or ends play, when a level streams in or out (at most every 2 s), and while no road has been found yet (every 2 s).
- **Blueprint API:**
  - `GetTether(WorldContext)`;
  - `GetTetherDistance(Location)` (-1 when no line is known);
  - `QueryTether(Location)` (distance, road distance, path distance, nearest line, zone);
  - `IsDetour(Location)`;
  - `IsOffAllowedPaths(Location, MinDistanceCm)`;
  - `ComputeRespawn(From, CapsuleHalfHeight, TravelSign, StepCm, IgnoreActor) -> Found, Location, Rotation`;
  - `HasRoad`, `GetPathCount`, `GetZoneCount` and `RefreshTether`.
- **The respawn** picks the line nearest the breach point. A tie goes to the road.
  - On the road it is `BFL_SaskartaRoad.ComputeRoadRespawn`, unchanged: `StepCm * TravelSign`, the other way when that runs off an end, a 6 m chord for the yaw.
  - On a path, the step and the facing go toward the road junction. The path end nearer the road is detected, so a reversed spline also works.
  - The ground trace uses the Visibility channel, from 10 m above to 50 m below, and ignores the pawn. The spot is lifted by the capsule half height + 2 cm. `PC_Saskarta.TryRespawn` is unchanged: it still retries with `RespawnStep` + 200 cm.
- **The detour rule** (`IsDetour`, `RoadHoldCm` = 10 m): the pawn is more than 10 m from the road **and** either a path is the nearest line or the pawn is in a zone.
  - The 10–20 m warning band beside the plain road still moves `road_m`, as before.
  - Within 10 m of a junction the nearest road point stays near the junction, so the hold keeps `road_m` within about 10 m of the junction's value.
  - Beats, the lighting road progress and the "next beat" ETA all hold during a detour.

## The paths

`python Tools/World/make_tether_paths.py` reads:
- the reachable POIs from `offroad_poi_locations.json`;
- each spur polyline (point 0 is on the road centreline), the site centre and the zone radius from `setdress_sites.json`;
- the terrain from `build_road_profile.Terrain` (`Saved/TerrainRebuild/Current_u16.png`).

**Grade.** It is `setdress_offroad.spur`'s 20 m-window measure: 10 m samples, a 2-sample mean.
- The samples are spaced by arc length, and the height is averaged over a 9 × 9 m patch (`Ground.zs`). The 1 m heightmap's micro-relief alone reads as 25–35 % on any 5 m step of the O01 bench.
- `raw_grade_pct` in the JSON is the unsmoothed figure, for reference.
- A spur over 20.5 % is rerouted by a grade-limited A* on a 5 m grid. Every edge (with its midpoint) must stay under 18 %, and it may not cross ground steeper than 70 % (35°). The result is simplified only where the chord still holds 20 %.

| POI | junction (road m) | old spur grade | path grade | length | spline points | zone radius |
|---|---|---|---|---|---|---|
| O01 | 725 | 49 % | **17.8 %** (switchbacks) | 779 m | 137 | 55 m |
| O03 | 2775 | 16 % | 17.4 % | 390 m | 41 | 60 m |
| O06 | 2525 | 14 % | 11.3 % | 432 m | 45 | 70 m |
| O09 | 1450 | 17 % | 16.3 % | 263 m | 29 | 70 m |
| O10 | 3225 | 20 % | 19.3 % | 418 m | 43 | 47 m |
| O14 | 100 | 6 % | 6.2 % | 346 m | 36 | 65 m |

**Spline points.**
- They are Linear, 10 m apart, and ground-snapped to the heightmap.
- The editor script snaps each one again by a down trace to the landscape (only a `LandscapeProxy` hit counts) and lifts it 20 cm.
- A spur that ends outside its zone is run on to the site centre.

**O01's way-markers.** The layer-2 markers stand on the old straight 49 % line. `tether_paths.json` → `paths[O01].markers_cm` has 11 new spots (every 70 m, 2 m to the right of the new line). The SETDRESS lane replaces O01's `spur_markers` group with them. Until then, the old markers lead off the tether corridor.

## Post-build steps (in order)

1. **Build SaskartaCore** with the editor closed:
   `Build.bat UnrealEditor Win64 Development -Project=D:\UnrealEngine\saskartarad\saskartarad.uproject`
   The new reflected names are `USaskartaTetherSubsystem`, `FSaskartaTetherQuery`, `ASaskartaTetherPath` and `ASaskartaExploreZone`. The plain structs are `FSaskartaTetherLine`, `FSaskartaTetherZone` and `FSaskartaTetherLogic`. There is no U/F clash.
2. **Run the tests** in the editor: `Automation RunTests Saskarta.Tether` (4 tests). The hooks touch the runner and the station, so also run `Automation RunTests Saskarta`.
3. **Apply the Blueprint change** (editor lane, gate held):
   ```
   python Tools/GameFlow/gen_tether_specs.py
   node Tools/GameFlow/bpgraph.mjs check Tools/GameFlow/specs/BPC_RoadTether.tether.json
   node Tools/GameFlow/bpgraph.mjs build --reset-graphs Tools/GameFlow/specs/BPC_RoadTether.tether.json
   ```
   - It rebuilds only `CheckRoad` and `ComputeRespawn`. `PC_Saskarta` and `BFL_SaskartaRoad` are unchanged; the BFL's `ComputeRoadRespawn` is no longer called by the tether but stays for the tests.
   - If `BPC_RoadTether.json` is ever rebuilt from scratch, run this scoped build again after it.
   - `BPC_RoadTether` is a committed uasset (read-only, LFS lockable). Check it out before the build.
4. **Place the actors** (SETDRESS lane, gate held, `Saskarta_WP` open):
   - Regenerate if the sites changed: `python Tools/World/make_tether_paths.py`.
   - Send: `python Tools/World/make_tether_paths.py send --owner LANE_SD`. This sends 6 path scripts, 6 zone scripts, then one save. Each script replaces its own earlier actor (tag `TETHER_<poi>`) and stays well inside the 5 s deadline.
   - Or run the files in `Saved/Tether/scripts/` one per `python_run` call.
   - The actors go in the `Tether/Paths` and `Tether/Zones` folders, not spatially loaded, tagged `TetherGen`.
5. **Replace O01's way-markers** with `paths[O01].markers_cm` (see above).
6. **Check in PIE** (at the user's go-ahead: never start PIE unasked):
   - The log shows `tether: road found, 6 path(s), 6 zone(s)`.
   - Walk the O14 spur (it turns off at road 100 m). There should be no warning on the spur, a warning 10 m off it, and a reboot 20 m off it that respawns on the spur facing the road.
   - In the POI's zone, `Saskarta.Events` status keeps `road_m` at about 100 m.
   - `Saskarta.Station.React` is untouched; a real OFFROAD reaction logs `show: OFFROAD queued a reaction` only off every line.

## Limits and notes

- **The ground guard** (`BP_Saskarta_GroundGuard`) still rescues a fall-through to the **road**. On a spur that is a long jump back, but it is rare. It could use `ComputeRespawn` later.
- **The Keeper's human walk** (the ending) has its own 9 m road tether. The carrier tether is stopped then, so paths do not apply.
- The carrier ending and the relative-to-pawn cinematics read the road spline directly. They sit far from every spur (the last junction is at road 3,225 m).
- `bDebugDraw` still draws nothing.
