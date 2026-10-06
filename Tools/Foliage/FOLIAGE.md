# Foliage motion and far tree stand-ins (world sprint, Task V4)

Spec: `docs/superpowers/specs/2026-09-26-saskarta-world-sprint-design.md`, section 3 "Motion" (revised 2026-09-26, ruling R24).

- Trees are animated near and static far. The native Megaplant with DynamicWind is used within about 70 m, and the static stand-in `SM_Saskarta_TreeFar_*` from 65 m to 300 m. HLOD takes over beyond that.
- Reeds, nettles and shrubs keep their materials' WPO: the player trample plus the global wind below.
- **Never enable or build Nanite on a converted Megaplant or assembly mesh.** On 2026-09-26 the editor asserted `HasCachedNaniteAssemblyReferences` and crashed.

Every script here is sent to the live editor through `node Tools/Foliage/run_foliage.mjs` (Hayba `python_run`, raw TCP 52342). Hold the editor gate while you run them (`python Tools/GameFlow/editor_gate.py acquire/release`). No script saves anything by itself. Save with `save_packages.py`, by explicit list.

## Wind

| Piece | Where | What |
|---|---|---|
| `MPC_Saskarta_Wind` | `/Game/SaskartaGaea/Foliage/` | `WindDirection` (0.94, 0.34, 0), `WindStrength` 0.5, `GustPhase` 0. This is the one place to set the wind. |
| Mirror in `MPC_Saskarta_Player` | `/Game/SaskartaGaea/Materials/` | The same three parameters with the same defaults. A material may reference only 2 collections, and `M_MS_Foliage` already uses `QMPC_GlobalFoliageActor` (Fab health, colour and wind functions) and `MPC_Saskarta_Player` (trample). So its wind node reads the mirror. |
| `BP_Saskarta_WindDriver` | `/Game/SaskartaGaea/Foliage/`, one placed actor, not spatially loaded | BeginPlay starts a looping 0.1 s timer on `UpdateGust`, which does three things:<br>1. `GustPhase += GustRate(0.8) * 0.1 * rand(0.3, 1.7)`, written to `MPC_Saskarta_Wind`;<br>2. copies `GustPhase` into the Player mirror;<br>3. copies `WindStrength` and `WindDirection` from `MPC_Saskarta_Wind` into the mirror.<br>Built from `specs/BP_Saskarta_WindDriver.json` with `node Tools/GameFlow/bpgraph.mjs build`. |
| `SaskartaWind` Custom node | both masters | The body is `Shaders/FoliageWind.hlsl`, pasted in by `build_wind_nodes.py` (`CODE=@Shaders/FoliageWind.hlsl`). Its output is **added** to the existing WPO: in `M_Saskarta_PlantFoliage` to the Break-attributes WPO plus trample, and in `M_MS_Foliage` to the Fab wind plus trample. Trample is untouched. |

Inputs to the Custom node:
- `ObjectPositionWS`, so the phase is per plant;
- `LocalPosition`;
- `Height01`: in PlantFoliage this is the trample's own `saturate(LocalPos.z / TramplePlantHeight)`, and in MS_Foliage it is `saturate(LocalPos.z / SaskartaWindHeight)` (default 120);
- `PerInstanceRandom` and `Time`;
- the wind direction through a ComponentMask RGB (the LWC gotcha);
- `WindStrength × SaskartaWindAmount`, a per-instance scalar that defaults to 1 and turns the wind down or off;
- `GustPhase`.

Rebuild or refresh (the scripts are idempotent, and a second run only refreshes the code):

```
node Tools/Foliage/run_foliage.mjs py Tools/Foliage/make_wind_mpc.py
node Tools/Foliage/run_foliage.mjs py Tools/Foliage/build_wind_nodes.py "MAT='/Game/SaskartaGaea/Materials/M_Saskarta_PlantFoliage'" CODE=@Shaders/FoliageWind.hlsl
node Tools/Foliage/run_foliage.mjs py Tools/Foliage/build_wind_nodes.py "MAT='/Game/Fab/Materials/Standard/M_MS_Foliage'" "WIND_MPC='/Game/SaskartaGaea/Materials/MPC_Saskarta_Player'" CODE=@Shaders/FoliageWind.hlsl
# then Hayba material_compile on each master (it compiles, reports errors and saves)
node Tools/GameFlow/bpgraph.mjs build Tools/Foliage/specs/BP_Saskarta_WindDriver.json
node Tools/Foliage/run_foliage.mjs py Tools/Foliage/place_wind_driver.py
python -m pytest Tools/Foliage/tests -q        # offline: HLSL body, dxc compile, maths
```

Instruction cost, measured with `MaterialEditingLibrary.get_statistics` before and after:

| Master | Vertex shader | Pixel shader |
|---|---|---|
| `M_Saskarta_PlantFoliage` | 389 → 418 (+29) | 333 → 333 |
| `M_MS_Foliage` | 274 → 301 (+27) | 260 → 260 |

From `material_compile` after the change: PlantFoliage is 305 on static meshes, 418 on skeletal meshes and 2207 in the Nanite mesh shader. MS_Foliage is 301 on static meshes.

**WPO disable distance** is a per-component or per-spawner setting (`world_position_offset_disable_distance`), not a material one. The spawners that place reeds, nettles and shrubs (V5 and V6) set it to **6000**. It is measured from the camera and the trample radius is at most 2 m around the player, so it never cuts trample near the player. The proof rig ran the reed with 6000 set. The far tree stand-ins start at 6500 cm, so with the same 6000 their WPO is always off. Their Megaplant MIs have no Saskarta WPO anyway.

`M_MS_Foliage` now also has `bUsedWithInstancedStaticMeshes` set, for PCG ISM shrubs in cooked builds.

## Trample and wind proof (ruling R9)

`proof_reed.py` spawns a skinned `Plant_Dry_Common_Reed_A` (material `MI_Dry_Common_Reed_01_Foliage` on `M_Saskarta_PlantFoliage`) 600 m above the map. It sets the editor world's MPC instance values, never the assets, and cleans up afterwards. Captures come from `snap.sh`: a SceneCapture2D in base colour, 4 m away. The captures are in `Saved/Screenshots/V4/`.

- **Trample** (wind 0; its trample MI values are radius 200, bend 190, height 320):
  - With the player 1 m at +X (screen left), the reed tops shift right. The top 15% of pixels has a centroid x of 688.4, against 657.1 upright.
  - With the player 1 m at −X (screen right), they shift left: centroid 571.4.
  - With the player 10 m away, the reed stays upright. The bases are identical in all three.
  - Overlay: `overlay_trample.png` (red is +X 1 m, green is 10 m, blue is −X 1 m). The reed bends away from the player at 1 m and not at 10 m.
- **Wind** (player 1 m, wind 0.5): two captures about 1 s apart differ in 19,940 pixels (`overlay_wind.png`). The control pair with wind 0 differs in 0 pixels, so the change is wind over `Time`, not noise.

## Far tree stand-ins: `SM_Saskarta_TreeFar_<Species>`

`/Game/SaskartaGaea/Foliage/Static/`. Made by `convert_to_static.py`, with jobs in `foliage_jobs.json`:

```
node Tools/Foliage/run_foliage.mjs convert DeadPine_A        # or: convert all
```

Each python_run does one bounded step and keeps its work in progress in `unreal.saskarta_v4_convert`. The steps are plan → parts (several calls) → write → lods → check, and the run ends at `CONVERT DONE`.

A Megaplant is a skeletal trunk plus a Nanite Assembly of parts: branches, bark plates, spurs and leaves, at 156 to 6,760 nodes. Baked whole, a dead pine is 3.8 M triangles and a ginkgo 52 M. The stand-in is baked in the reference pose and reduced during the bake. The reference pose is valid because the node transforms are mesh-space.

- **Plain static mesh, Nanite OFF, no assembly data.** The check step refuses the result if either is present. It has LOD0–LOD3 and keeps the source Megaplant MIs, whose master `MA_Foliage_Trees` is flagged for instanced static meshes.
- **Wood:** components under 4 triangles are dropped. Of the rest, only the largest are kept, up to 70% of each part's triangles; the twigs go. The decimator floors every component at its rigid tube ends, and twigs are sub-pixel at 65 m. What remains is decimated with **volume-preserving** QEM, with one ratio per tree solved against the budget and re-baked if the result overshoots.
  - The trunk keeps at least 8,000 triangles.
  - The attribute-aware default decimator, and seam collapse, webbed forks into flat slabs. That was seen on DeadPine_A and fixed.
- **Leaves (ginkgo):** every K-th leaf of a part is kept and scaled by `sqrt(leaves/kept) × 0.75` about its centre. Each kept leaf becomes a **2-triangle card**: a least-squares fit of the UV→position map, taken at the leaf's UV rectangle, so the masked texture still draws the leaf. The card carries the leaf's average vertex colour.
  - Decimating a leaf instead stalls at about 9 triangles.
  - K is the smallest value that keeps leaves under 60% of the 48k budget.
- **LODs:** the engine reducer at 100 / 50 / 25 / 12 %, with screen sizes 1.0 / 0.12 / 0.07 / 0.045. The pine (sphere diameter about 27 m) is at LOD0 to about 110 m, LOD1 to 190 m, LOD2 to 300 m and LOD3 beyond. The ginkgo (about 18 m) is at LOD0 to about 77 m. These screen sizes are budget lever 3 in the spec.

| Stand-in | Nodes | Tris before reduction (after twig cull) | K | LOD0 / LOD1 / LOD2 / LOD3 |
|---|---|---|---|---|
| DeadPine_A | 247 | 3.8 M (raw) | – | 45,152 / 22,575 / 11,288 / 5,419 |
| DeadPine_B | 234 | 2.53 M | – | 46,738 / 23,368 / 11,685 / 5,609 |
| DeadPine_C | 327 | 3.44 M | – | 46,169 / 23,084 / 11,542 / 5,540 |
| DeadPine_D | 156 | 1.57 M | – | 47,034 / 23,517 / 11,759 / 5,645 |
| DeadPine_E (a 7.9 m snag) | 192 | 1.85 M | – | 47,148 / 23,573 / 11,786 / 5,658 |
| Ginkgo_A | 6,760 | 49.1 M | 12 | 36,188 / 18,094 / 9,047 / 4,343 |
| Ginkgo_B | 5,404 | 27.5 M | 6 | 38,036 / 19,018 / 9,509 / 4,565 |
| Ginkgo_C | 1,332 | 12.0 M | 3 | 44,138 / 22,069 / 11,035 / 5,297 |
| Ginkgo_D | 746 | 3.9 M | 1 | 45,459 / 22,729 / 11,365 / 5,456 |

**Verification** (`proof_standin.py` puts the native and the stand-in side by side or in the same spot; base-colour captures in `Saved/Screenshots/V4/`):

- **DeadPine_A:**
  - The native/stand-in overlay at 40 m (`V4_diag_overlay_DeadPine_A.png`) matches in silhouette: 8,367 px overlap, 2,605 stand-in only, 1,864 native only. The differences are mostly twig thickness.
  - At 100 m (`V4_standin_DeadPine_A_100m_view.png`) the two read the same.
- **Ginkgo_A:**
  - The silhouette matches (`V4_diag_Ginkgo_A.png`). The canopy covers 1.33× the native's pixels (38.5k vs 28.9k), so it reads a little denser.
  - At 100 m the stand-in's canopy base colour is about 30% brighter green than the native's (`V4_standin_Ginkgo_A_100m_view.png`).
- All nine together: `V4_standin_all9_85m_view.png`.

Look follow-ups for the V5 look pass: a darker tint MI for the ginkgo stand-ins, or a lower `LEAF_GROW_DAMP`, if the swap at 65–70 m shows.

## Known issues

- **`MI_vdknafgha`**, the only child of `M_MS_Foliage` (the Fab dead shrubs), fails to compile in its own static-switch permutation: `(Function QMF_WindAnimation|QMF_DistanceBasedGradient) Missing function input 'Function Distance Input'`.
  - This was already in the editor log at startup (03:59 UTC on 2026-09-27), before V4 touched anything.
  - The instance renders the default material, so it has no WPO and neither wind nor trample shows on it. The base `M_MS_Foliage` compiles clean.
  - The fix belongs in Fab's `QMF_WindAnimation` (wire that input) or in the instance's switches. It was left as it was, because V4 does not own the Fab functions.
- The wind driver compiles clean but has not run at runtime: no PIE was started. In the editor the MPC defaults apply, and the proofs drove the MPC instance values directly.
- Skinned reeds stay skinned. The LGT reeds use existing static grass meshes (R25), so V4 made no static reed or nettle meshes.
