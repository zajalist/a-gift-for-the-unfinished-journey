# The road in the terrain RVT (world sprint, Task V1)

The road is drawn into `RVT_Saskarta_Terrain` by an RVT-only writer. It is never rendered as a
mesh in the main pass. The landscape material reads that RVT, so the road shows on the ground.
It costs nothing per frame: it renders only when RVT pages update.

## What existed (Step 1, read from the live editor on 2026-09-27)

| Thing | State found |
|---|---|
| `RVT_Saskarta_Terrain` | `material_type` BaseColor_Normal_Roughness. `tile_count` 10 (1024 tiles), `tile_size` 8 (256 px). About 3 cm per texel over the map. Compressed, single physical space, no continuous update. Volume `RVT_Volume_Saskarta` at (−18920.4, 50, −48000), scale (815900, 815900, 70000). No streaming low mips. |
| Landscape | `MI_Saskarta_ColdWasteland_PerfCandidate` → `M_Saskarta_Aziel_Perf`. Writes `RVT_Saskarta_Terrain` (pass type Exclusive) and reads it back through two `RuntimeVirtualTextureSample` nodes (`Use Runtime Virtual Textures` = true). Landscape components' `TranslucencySortPriority` is −1. |
| Road ribbon | `BP_Saskarta_Road`'s `RoadRibbonPCG` runs `PCG_Saskarta_RoadRibbon` (GetSplineData → SpawnSplineMesh). The graph generates on load. It makes 54 `SplineMeshComponent`s, one per spline segment, from `/Game/Pallbearer/Road/SM_PB_RoadStrip`: a 1 m × 1 m flat strip, 17 × 9 vertices, **Nanite on**, **UV.y across the strip, UV.x along it**. The spline scale gives 9 m wide. The strips have zero tangents. They use material `/Game/Pallbearer/Road/M_PB_RoadRVT` (Masked), `RuntimeVirtualTextures` = `RVT_Saskarta_Road`, and pass type Never. |
| `RVT_Saskarta_Road` | BaseColor only, written by the ribbon, read by nothing. |

**Writer chosen:** the existing ribbon plus changes to its PCG spawner, which is the preferred option. No new component was added to `BP_Saskarta_Road`. The generated components are rebuilt from the spawner descriptor on every generation, so the change lives in the graph.

## What V1 changed

`PCG_Saskarta_RoadRibbon`:

1. **SpawnSplineMesh descriptor:**
   - `StaticMesh` = `SM_Saskarta_RoadRibbon`
   - `OverrideMaterials` = `MI_Saskarta_RoadRVT`
   - `RuntimeVirtualTextures` = `RVT_Saskarta_Terrain`
   - `VirtualTextureRenderPassType` = Never, which draws into the RVT only
   - `TranslucencySortPriority` = 10, so it draws after the landscape's −1
2. **New joint caps:**
   - Nodes: GetSplineData → SplineSampler (Subdivision, 0 per segment, which gives the 55 control points) → TransformPoints (absolute scale 1) → StaticMeshSpawner.
   - The spawner places `SM_Saskarta_RoadJointCap` as an ISM with the same MI and RVT, pass type Never, and `TranslucencySortPriority` 9, which is under the ribbon.
   - Cull start/end is 45000/50000 cm. It is RVT-only, and the value is set explicitly (Review Focus 4).
   - Shadows, ray tracing, distance-field lighting and contact shadow are all off.

New assets (all in `/Game/SaskartaGaea/Road/`):

| Asset | What |
|---|---|
| `M_Saskarta_RoadRVT` | The writer master. Built by `build_road_material.py`. |
| `MI_Saskarta_RoadRVT` | The instance the ribbon and caps use. |
| `SM_Saskarta_RoadRibbon` | A copy of `SM_PB_RoadStrip` with **Nanite off**. |
| `SM_Saskarta_RoadJointCap` | A 4.5 m-radius disc with radial UVs, from `make_joint_cap.py`. Nanite is off. |
| `Debug/M_V1_RVTPreview` | Unlit RVT viewer used to verify the RVT itself (see below). |

### Why the mesh copy (Nanite off)

With Nanite on, the ribbon wrote nothing into the RVT: no captured pixel changed when the ribbon was hidden. Once a non-Nanite copy was swapped in, the same ribbon wrote the road. Editing the Pallbearer asset itself would have rebuilt Nanite on a shared mesh, so V1 uses a copy.

### Why the master is duplicated from a template

A material made with `MaterialFactoryNew` never drew into the RVT from a spline mesh. That held even for a bare constant-red RVT Output with opacity 1, and with every exposed usage flag and blend mode matched to the working material. The same material type drew fine from a plain static mesh. A **duplicate** of `/Game/Pallbearer/Road/M_PB_RoadRVT`, with the same rebuilt graph, draws. So when the master is missing, `build_road_material.py` duplicates that template, then deletes every expression and rebuilds the graph. The cause is a hidden property that UE 5.8 does not expose to Python. The evidence captures are in `Saved/Screenshots/Sprint/V1_debug/` (`*_min*`, `*_dup*`).

## The material

`M_Saskarta_RoadRVT` is Surface, Translucent (the RVT Opacity pin blends), Used with Spline Meshes and ISM. Only the RVT Output is wired.

| Node | Does |
|---|---|
| Mask sample | `T_Saskarta_RoadInfluence` at `UV = (AbsoluteWorldPosition.xy − MASK_ORIGIN_CM) / MASK_EXTENT_CM`. It uses the mapping from `Tools/Terrain/MASKS.md`, read by `prepare_road_material.py` on every build (Ruling R5; no hardcoded extent). Linear Color sampler. |
| `RoadFrame` (Custom) | `RoadU = (UV.y·2−1) · RibbonHalfWidth / RoadHalfWidth`. `RoadV` is metres along the segment, anchored in the world: `dot(P.xy, along)/100`, where `along` comes from the UV Jacobian (screen derivatives). `Across` is the world direction of +RoadU. |
| `Wear` | `lerp(WearDirt 0.45, WearPaving 0.78, Surface)`. The per-stretch wear values in `road_surface.json` average to these. |
| `RoadRVT` (Custom) | `Shaders/RoadRVT.hlsl`: the brief's body verbatim, plus `ProfileNormal`, the analytic dh/du signed by side and scaled by `HalfWidth`. |
| `RoadNormal` (Custom) | ProfileNormal (X across, Z up) to world space from `Across` and `VertexNormalWS`. |
| RVT Output | BaseColor, Roughness, Normal, **Opacity = Mask = road core (R)**. The road feathers into the ground where the core falls off, and any ribbon or cap pixel off the core writes nothing. |

**Parameters** (group `Road`):

| Parameter | Value |
|---|---|
| `RoadHalfWidth` | 2.25 m |
| `RibbonHalfWidth` | 4.5 m |
| `WearDirt` | 0.45 |
| `WearPaving` | 0.78 |
| `DirtColor` | (0.150, 0.108, 0.080) |
| `GravelColor` | (0.190, 0.160, 0.130) |
| `PavingColor` | (0.170, 0.158, 0.142) |
| `CrownGrassColor` | (0.080, 0.086, 0.046) |

**Differences from the brief:**

- `RoadU` comes from **UV.y**, because that is how the existing strip is laid out.
- It is scaled to the road core, so ruts sit at ±0.45 of the core's half-width, not of the 9 m ribbon.
- `RoadV` is world-anchored instead of `UV.y × length`. A spline mesh has no segment length in the material, and its zero tangents stretch UV.x non-linearly.
- `Wear` has no mask channel, so it comes from `Surface`.

**Compile:** 0 errors. Hayba `material_compile` reports 344 instructions and 8 samples for the unused main-pass permutation. The RVT write runs only on page updates.

## Joint caps (Review Focus 1)

The road spline is a polyline, so each ribbon segment ends square at its control point. Where two segments meet at an angle, the outer corner of the road core had no ribbon over it:

- At spline point 17 (76°, the 3,850 m hairpin) the mask's rounded corner showed bare ground.
- Capture `V1_rvt_p17.png` shows the gap; `V1_rvt_p17_mask.png` shows the mask.

The cap is a disc the size of the ribbon's half-width, drawn under the ribbons at every control point:

- **Geometry.** Its UV.y runs 0.5 → 1 from centre to rim, so `RoadU` is the distance from the joint. That matches what the ribbon's profile would be for points whose nearest centre-line point is the joint.
- **Result.** It fills the wedge (`V1_rvt_p17_caps.png`). Ruts curve around the corner.
- **Overlap.** On the inner side of a turn the segments overlap. Both write the same world-space opacity, so nothing is doubled beyond a slightly denser feather.

## V1b: the look pass (2026-09-27)

V1's semantics stayed; its look did not survive the before/after sheet. The paving read as a regular
checker "ladder", the hairpin caps showed a fan, and the strip had a crisp outline. V1b rewrote
`Shaders/RoadRVT.hlsl` and rewired the master. The ribbon, the caps, the PCG graph and the RVT are
unchanged.

### The road frame comes from the polyline, not from mesh UVs

`prepare_road_material.py` pastes RoadSpline's 55 control points into the shader as a constant array.
It takes them from `Tools/Story/build_road_profile.py` `SPLINE_POINTS_CM`, the same source the masks
were baked from. They are in metres in the mask frame. Every texel computes the **exact distance to the
polyline**, the foot point and the across direction. From that it gets `u = distance / RoadHalfWidth`.

Nothing in the shader reads a mesh UV. The Custom node's inputs are the world position, the four mask
channels and the parameters. So:

- **No seams between segments.** Two spline-mesh segments that overlap write identical texels.
- **Clean joint caps.** A cap writes the same surface the ribbon would. Around the joint it is the radial
  distance to the centreline point, with no UV fan and no outline.
- **Correct corners.** Inner corners come out mitred and outer corners round. That is what a
  distance-to-polyline field does, and it is continuous (1-Lipschitz, tested).
- **The road's up vector** comes from each segment's grade, blended over the nearby segments with a
  soft-min. The ribbon and the cap agree on slopes.

The caps stay as coverage-only geometry: the 4.5 m discs, drawn under the ribbons.

### The surface

| Part | How |
|---|---|
| Paving slabs | A power-weighted jittered grid, world anchored: pitch 0.9 m, jitter 0.9, weight (0.35·pitch)²·rand. The slabs are irregular: mean 0.85 m, p10–p90 0.65–1.02 m, size CV 0.19. A test holds the CV above 0.15 against a regular-grid control. Per-slab tone is `0.9 + 0.2·rand`, so within ±10 %. |
| Joints | The exact power-diagram edge distance. They are dark (`DirtColor·0.45`), about 2–7 cm wide, and fade over 1–3.5 cm so they do not stair-step at the 3 cm RVT texel. The height has a 0.8 cm bevel over 6 cm. Grime creeps 10 cm in from each edge. |
| Burial | Per slab: low-frequency noise (2.5 m and 0.9 m) sampled at the slab centre, plus 0.2·neglect. Dirt creeps in from the joints, and a 0.35 m drift noise plus grit rags the edge. Per-pixel low-frequency burial cut slabs into straight-edged shards, so it is taken per slab. On the paving stretches (neglect 0.52–0.9) it covers 40–70 % of the slab area, tested over 80 m. |
| Missing slabs | Whole slabs, chosen by a 2.6 m noise sampled at the slab centre, so they go missing in clusters (tested). The threshold is `0.12 + 0.2·Wear`. |
| Toward the verge | Slabs thin out past u ≈ 0.75 (the missing score drops with the slab centre's u), and the survivors' edges are eroded by pebble noise: broken edges. The paving spans the whole core; V1's narrow ladder is gone. |
| Dirt profile | A crown (4.5 cm), two ruts at u ≈ 0.45 that wander ±0.06 u along the road (5 m noise), 3.5–8.5 cm deep × Wear, and a gravel windrow at u ≈ 0.93. Ruts are darkened ×0.72 (compacted, damp), the crown lightened ×1.1 and grassed in tufts where neglected. |
| Edge | `RoadOpacity = smoothstep(0.4, 0.55, Core + 0.55·(noise − 0.5))`, with noise at 1.6 m and 0.35 m. So the edge follows the mask's core (width wander) and is warped and feathered. Spilled pebbles (0.07 m noise) add coverage up to about 0.5 m beyond it. Patchy gravel shades the last metre inside. |
| Normal | Three height taps, with finite differences in world XY, added to the road up vector. |
| Mips | `ts` is the RVT texel size from the screen derivatives. Grit, pebbles, joints and bevels fade out by 12 cm and 60 cm texels, so coarse RVT mips do not alias. |

**Colours** (linear): Dirt (0.130, 0.092, 0.066), Gravel (0.145, 0.120, 0.096), Paving (0.140, 0.124, 0.104),
CrownGrass (0.080, 0.086, 0.046). These are darker and warmer than V1's, so the road sits in the red-brown ground
instead of reading as a grey band. Slab roughness is 0.86, because 0.74 reflected the sky.

### GPU precision: work cell-local

The first engine build drew the slabs as triangular shards, while the numpy model drew clean polygons. A debug
build that showed the slab ids and sites found the cause:
- The site search was right.
- The edge-distance pass was not. On the GPU, `dot(q − pt, q − pt)` with `q` and `pt` near 4,000 m (world metres)
  lost enough precision to put `(pd − bestPd)/(2l)` wrong across whole wedges of each cell.

The slab maths now runs in cell-local coordinates: `lq = q/0.9 − cell` and a site `lp` in cell units. Every
difference is then between small numbers, and the engine matches the model. Keep any new world-anchored cell
maths local in the same way.

The numpy port `Tools/Road/tests/road_model.py` mirrors the shader line for line. The tests run on it,
and a test checks that the key constants match the shader's.

## ROADNOISE: noise-driven breakage (2026-09-27)

The user's note: "the road itself and its breakages dont look organic enough theres no noise driving the breakages".
In V1b a stone went missing when one 2.6 m value noise, read at its centre, fell under a threshold; everything
else was per-stone dice. ROADNOISE puts one **decay field** under all of the breakage. Only
`Shaders/RoadRVT.hlsl`, the numpy port and the tests changed. The Custom node's pins, the RVT channel meanings
(BaseColor, Roughness, Normal, Opacity = Mask), the build script and the ground side are the same as before.

### The decay field

`decay = fbm(X + 1.1·warp3(X)) + 0.7·(Neglect − 0.63) + 0.25·(Wear − 0.6) + 0.12·ruts·Wear`

- `fbm` is value noise at 15 m, 3 m and 0.5 m, weighted 0.4, 0.35 and 0.25. Mean 0.5, std 0.126.
- `warp3` is a 3 m value-noise domain warp. It bends the octaves, so the patches come out irregular rather than
  blobby or axis-aligned.
- The wheel tracks add to it, so neglected paving breaks along the ruts first.

The field is used in two ways.

| Read at | Gives |
|---|---|
| The stone centre (one value per stone, plus `0.5·smoothstep(0.75, 1.2, uc)` toward the verge) | **Missing stones**: whole stones are gone where it passes 0.62, so they go missing in irregular clustered patches. Stones near the threshold erode at their joints and crack more, and wider. |
| Each pixel, plus a 12 cm crumble noise | **Crumbled patch edges**: the outline cuts through stones raggedly (`chip`, threshold 0.66) instead of following the joints. **Potholes**: past 0.66 there is a 6 cm crumbled lip and a bowl up to 7 cm deep with damp mud on its floor (roughness 0.72). Pits take only half of the neglect term, so neglected stretches get more potholes, not a mud road. They occur on dirt stretches too. |

### What else changed

| Part | How |
|---|---|
| Stone size | The slab lattice is domain-warped: `qw = q + 3.0·w15 + 0.3·w3`. The 15 m warp stretches and squeezes the stones along the road; the mean stone size over 8 m windows varies about 1.8 times as much as window sampling alone gives. The cell maths stays cell-local in the warped space (V1b's precision rule). The stone centre `cW` is computed from the cell id and jitter alone, so it is bit-identical for every pixel of a stone. |
| Neglect | Well kept (0.52): about 60 % of the paving is visible, with thin cracks. Median (0.63): about 48 %. Neglected (0.9): about 10 %, in large exposed-dirt patches with ruts and potholes. The transition follows the noise: over a 0.5 → 0.9 ramp the visible share correlates with neglect at about −0.75, but it rises again in places. Burial takes `0.2·(Neglect − 0.5)` (V1b: fixed 40–70 %). |
| Cracks | A per-stone contour of two value-noise octaves (0.42 m, with a per-stone offset). 30 % of the stones crack where the road is kept, up to 85 % near the decay threshold, and the cracks widen as they decay. The cracks are dark (`DirtColor·0.45`) and 0.5 cm deep, and they fade with the joints on coarse mips. |
| Stone colour | Per stone ±10 % in value, a warm-to-cool hue at equal luminance (R/B from 1.14 down to 0.89), and a ±6 % drift over 12 m. |
| Edge | `ev = Core + 0.7·(edgeN − 0.5) − 0.3·(decay − 0.45) + 0.08·crumble`, where `edgeN` mixes 6 m (warped), 1.6 m and 0.35 m noise. The edge bites in where the road decays. |
| Verge stones | Toward the verge, stones tilt: a per-stone plane of up to about 11 % slope (16 % for the scattered stones), which also grows with decay. They sink by 1.5 cm and are buried more. Past the edge (uc 0.95–1.3), 20 % of the stones stay as shrunken, tilted stones lying in the verge. They write their own coverage. |

### Cost

The Custom node now uses a local `struct RoadNz` for its helpers (value noise, warp, fBm). HLSL allows a struct
with methods inside a function; the file still pastes in as a function body. Compiled with `dxc -T ps_6_0`, the
test harness around the body goes from 841 DXIL instructions (V1b) to 2,403. Per texel that is about 64 value
noises over the three height taps, the 34-cell power-diagram search per tap, and the two 54-segment polyline
loops. This runs only when RVT pages update.

### Tests

The tests added for ROADNOISE are in `test_road_rvt.py` under "ROADNOISE". They check:

- the three octave bands and the warp;
- patchiness at 10 m and neighbour clustering;
- stones partly chipped at the patch edges;
- the noise-modulated neglect ramp;
- potholes and mud following neglect on dirt;
- edge tilt, sinking and scatter;
- stone-size drift against an unwarped control;
- thin cracks that follow decay;
- no second autocorrelation peak from 2 to 60 m along the road.

Where V1b's spec changed, its assertions were updated:

| V1b test | Now |
|---|---|
| "Mostly buried" | Visible share by neglect. |
| Tone within ±10 % | Within ±20 %, plus hue variation. |
| Every normal within 37° of vertical | 99 % of texels are, and no normal tilts more than 53° (z > 0.6); only pothole lips come close. |
| Constants cross-check | Also checks the decay and burial tuning, which lives in `road_model.TUNING`. |

## Rebuild

With the editor gate held:

```
python Tools/Road/make_joint_cap.py                  # only if the cap mesh must be re-imported
python Tools/Road/prepare_road_material.py --send    # rebuild M/MI_Saskarta_RoadRVT
python -m pytest Tools/Road/tests -q                 # offline checks
```

`python_run` refuses `compile (` with a space before the parenthesis, even inside a comment. The prepare step's test checks for this.

## Verify

**V1b captures** are in `Saved/Screenshots/Sprint/`:
- `V1b_{before,after}_{200,1050,2300,3000,3850,4700}_{eye,high}.png`: the eye shots at 1.7 m look along the
  road (pitch −5°); the high shots are 12 m up at −35°.
- `V1b_contact_sheet.jpg`: the before/after sheet.
- `V1b_rvt_3850_p17_final.png`: the hairpin in the RVT, top-down.
- `V1b_rvt_3000_*`: the precision debug pair (`_dbgid` shards, `_dbgid3` fixed).

The scripts are in the session scratchpad (`v1b/station.sh`: 2×2 proxies, capture, unload).


Cameras sit at `docs/story/road-profile.json` samples, 12 m up, pitch −35°, looking along the road. The captures go to `Saved/Screenshots/Sprint/V1_*.png`.

| Capture | What it shows |
|---|---|
| 200, 1050 | Road visible and continuous on the terrain: ruts, crown, gravel shoulders, feathered edge. |
| 2300 | The landscape's main pass there does not show RVT colour, so the road is not visible in the view (V2 replaces the ground material). The RVT itself holds the road with paving: `V1_rvt_2300_wide.png`, taken through `Debug/M_V1_RVTPreview` on a temporary plane. |
| 3000 | Broken paving: slabs knocked out by wear, dirt between them. |
| 3850 | The hairpin, in deep shadow. The joint is verified top-down: `V1_rvt_p17_caps.png`. |
| 4700 | Road visible. The landscape's snow patches draw over it in the main pass (V2). |

To look inside the RVT, put a plane over the road with `Debug/M_V1_RVTPreview`. Set `ShowNormal` = 1 to see normals and `ShowMask` = 1 to overlay the road-core mask. Run `r.VT.Flush` after changing writers.

## Open

- `RVT_Saskarta_Road`, the `Saskarta_RVT_Road` volume and `M_PB_RoadRVT`'s old write path are no longer used by the ribbon. They can be retired once nothing references them. The volume still references the RVT, and the template references `M_PB_RoadRVT`.
- On every regeneration the spline-mesh spawner logs "Failed to attach the component": its Static components cannot attach to the Blueprint's movable `DefaultSceneRoot`. The components still register and draw into the RVT, as the captures show. This task did not check whether the warning existed before V1.
