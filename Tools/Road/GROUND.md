# The ground material (world sprint, Task V2)

`/Game/SaskartaGaea/Materials/M_Saskarta_Ground` and its instance `MI_Saskarta_Ground` are the landscape
material. They are set on the `Landscape` actor only; the streaming proxies inherit it.

## Passes

| Pass | Runs | What it does |
|---|---|---|
| **Write** (Runtime Virtual Texture Output into `RVT_Saskarta_Terrain`) | only when RVT pages update | `Shaders/GroundAuto.hlsl`: rock by slope, bare alpine rock above the clouds, dry dirt, moisture-tinted grass, snow **patches** in the top zone band, macro tone, AO baked into colour. Reads `T_Saskarta_Ecology` and four texture sets, each sampled through `Shaders/GroundNoTile.hlsl` + `GroundNoTileNormal.hlsl` (anti-tiling, below). The road ribbon (Task V1) draws on top of it in the same RVT. |
| **Read** (main pass) | every frame | One `Runtime Virtual Texture Sample` (BaseColor, Normal, Roughness), then `Shaders/GroundRead.hlsl`: a detail normal and a zero-mean tone variation faded in within `NearEnd` (30 m), and the `DebugView` viewer. World-space normal output (`tangent_space_normal` off). |
| **Grass** (Landscape Grass Output) | when grass maps render | Densities for `NearGrass`, `DryGrass`, `Reeds` as math nodes (below). |

Ruling R21: no `T_Gaea_*` texture is used. Ruling R5: the mask mapping comes from `Tools/Terrain/MASKS.md`.

### Texture sets

Read from `MI_Saskarta_ColdWasteland_PerfCandidate`'s parameters when it existed (it is now retired); a
rebuild keeps the master's own texture parameters, with the paths in `LAYERS` as the last fallback.

| Layer | Colour / ORM / Normal | Tile | Tint |
|---|---|---|---|
| Layer | Colour / ORM / Normal | Tile | Flatten | Turn | Tint |
|---|---|---|---|---|---|
| Rock | AzielArts `Rock_Color`, `Rock_ORM`, `Rock_NormalDX` | 9 m | 0.4 | 0.06 (at most 22 deg) | old "Layer01 Slope" tint |
| Dirt | Pallbearer `T_PH_dirt_aerial_02_diff/_arm/_nor_gl` | 5.2 m | 0.85 | 1 | old "Layer02" tint |
| Grass | Pallbearer `T_PH_forest_ground_04_diff/_arm/_nor_gl` | 4 m | 0.5 | 1 | old "Layer03" tint |
| Snow | AzielArts `ClumpSnow_Color/_ORM/_Normal` | 7 m | 0.5 | 1 | old "Snow" tint |
| Detail normal (read pass) | `T_PH_forest_ground_04_nor_gl` (uniform gravel) | 2.3 m | | | |

The `_nor_gl` maps already have `flip_green_channel` set, so the build does not flip them (it would if
not, per sample, before the copy is turned back).

### Anti-tiling (fix round 1)

The first version mixed each colour map with a transposed 2.37x copy of itself. The copy was a mirror
image of the same tile, so the two made a regular diamond lattice, and the aerial dirt's large light
streaks and dark blotches repeated every 4.5 m. A top-down base-colour capture at 200 m measured a 2D
autocorrelation peak of **0.433 at a 4.48 m lag**, exactly the dirt tile.

Now each layer goes through `GroundNoTile` (one Custom node per layer, write pass only):

- A value noise over the tile UV (lattice 0.8 tile) is cut into 8 levels. Each level is a copy of the
  tile, **offset** (R2 sequence) and **turned** (golden-ratio angle steps, scaled by `<Layer> Turn`).
  A pixel blends the copies of its two nearest levels with weight `W`.
- Where the level changes, `W` is exactly 0 or 1, so the copy that jumps never shows (a test walks
  20,000 steps and checks every switch).
- Samples use `TMVM_DERIVATIVE` with the plain UV's derivatives turned per copy (`DA`, `DB`), so the
  jump cannot pick a wrong mip.
- Normals are turned back to the world-XY frame by `GroundNoTileNormal` before the blend.
- The rock set is stratified; turned freely its strata read as fur, so rock turns by at most 22 deg.
- **Flatten**: `colour + Flatten * (average - low)`, where `low` is the same two copies at mip 7
  (blotches larger than about 1/8 tile) and `average` is mip 12. It removes the aerial photo's
  blotches and keeps the grain; large-scale tone comes from Ecology macro and the breakup noise,
  which never repeat.
- `NoTile` (default 1) scales offsets and turns together; 0 gives plain tiling for A/B checks.

Measured with the same top-down capture and metric (fix-round report): 200 m 0.433 -> **0.056**;
3000 m (NoTile 0 vs 1) 0.125 -> **0.035**, with the diagonal-streak lattice visibly gone.

**RVT texel density** (the review's check): `RVT_Saskarta_Terrain` is 1024 tiles x 1024 px = 1,048,576 px
over 816,000 cm, **0.78 cm per texel** at its finest mip, well under the 10 cm threshold. It was not
the cause of the tiling or of the soft 4700 m ground (that was snow: see below).

### Grass densities (brief Step 3, LOOK2)

```
offcore   = saturate(1 - core / 0.3)
NearGrass = saturate((0.25 + 0.75 m)(1 - 0.8 e)) offcore (1 - verge (1 - neglect) 0.85)
            + core * saturate((neglect - 0.8) / 0.2) * 0.15
DryGrass  = saturate((0.25 + 0.75 e)(1 - 0.8 m)) offcore (1 - verge (1 - neglect) 0.85)
Reeds     = m^2 offcore
```

`m`, `e` = Ecology moisture, exposure; `core`, `verge`, `neglect` = RoadInfluence R, G, B.

- **Crown term (LOOK2).** V2 substituted `core * neglect` for the ribbon's missing crown, which gave
  `core * neglect^2 * 0.8`: 0.41 at the 200 m stretch (neglect 0.72), a full-width carpet of about 5 blades
  per m2 that hid the road. Now only truly abandoned stretches (neglect > 0.8) grow crown tufts, rising from 0
  at 0.8 to 0.15 (under 2 per m2) at neglect 1; with the 0.03 spawn floor the first appear at neglect 0.84.
  The 200 m and 1050 m stretches (neglect 0.72, 0.6) grow none; 2300 m (0.87) gets about 0.05.
- **Off-core (LOOK2).** V3 fix round 1 made it `saturate(1 - 2 core)`. The RVT road's noise-warped edge
  draws out to core ~0.15 in places, so every type is now zero from core 0.3 inward. On the real masks the
  core falls from 0.3 to 0 over about 1-1.5 m just outside the road edge, so the verge regrows over 1-2 m.

`LGT_Saskarta_Reeds` is created by Task V3.

### Snow and rock above the clouds (fix round 1)

The first version put snow on about half of the 4700 m view (63 % of the lower half of the capture was
snow-white): its ramp (0.6..0.78) sat below the median of `zone + 0.8 m` up there (zone is about 0.83).
The spec's above-cloud zone is rock with snow patches. Now:

- `alpine = smoothstep(AlpineLo, AlpineHi, ZoneSoft + 0.3 m + 0.15 breakup)` makes the ground bare rock
  from the top of the switchbacks (zone about 0.62 at 4150 m) and fully by the mountain approach;
  `rock = max(slopeRock, alpine * AlpineRock)`.
- Snow's ramp moved above the median (0.78..0.85), so it settles only where macro and breakup lift it,
  and cliffs shed it harder (`1 - 0.9 slopeRock`).
- Snow and alpine rock read `ZoneSoft`, the Ecology zone at mip 2 (about 8 m). The zone channel steps
  by 0.3 at the 35-degree cut of its baked snow term, which at 2 m texels drew stair-stepped snow edges.

On the real masks and heightmap (the view box 10..160 m ahead of the camera), snow covers 14 % of the
4700 m view with 75 % visible rock (the old defaults: 49 % snow). The capture's snow-white fraction went
from 0.63 to 0.18. The 3850 m hairpin band gets neither snow nor alpine rock.

### Colour variation and the road read (LOOK2)

User: "ideally less foliage inside the road and more color variation". All colour terms are in the
**write pass** (`GroundAuto.hlsl`, between the rock and snow lerps), so they cost nothing per frame:

| Term | Scale | What it does |
|---|---|---|
| Hue patches (`HueAmount`) | 90 m + 35 m value noise (patches ~20-200 m) | Dry earth goes ochre or rust (`1.6 e - 1.2 m + 0.2 + 2.5 hp`); moist hollows go olive, then dark green as moisture rises (`2.5 (m - 0.38) - 2 hp`, so wet and dry patches fall on opposite sides of the noise). Rock takes 30 % of it. |
| Scree (`ScreeAmount`) | same patches | Exposed ground (`3 (e - 0.4) + 1.5 (hq - 0.5)`) is pulled toward a cool neutral grey. |
| Mottling (`MottleTone`, `MottleHue`) | 8 m + 3 m value noise | +-value and a warm/cool swing, so no stretch reads as one flat colour. |
| Roadside (`VergeDarken`) | verge mask, first ~8 m | The ground right beside the road goes darker and greener (runoff collects in the ditch), so the lighter road reads against it. Zero under the road itself (core > 0.5). |

The **read pass** (`GroundRead.hlsl`) samples `T_Saskarta_RoadInfluence` once per pixel (the DebugView branch
reuses that sample) and, on the road core interior (`smoothstep(0.5, 0.85, core)`, inside the RVT road's own
edge, so no halo on the verge):

- multiplies the albedo by `RoadLift`, so the core reads lighter than the verge;
- scales roughness by `RoadWetRough` (a slight wet sheen);
- pulls the core toward a light warm-grey stone (`RoadTone`, normalised to luminance 1) by `RoadDesat` at
  unchanged luminance (LOOK2 fix round 1, review 7): the lift alone made the road a brighter shade of the
  same ochre as the ground, which the low warm sun turned the same red, so it did not read as a different
  surface;
- puts puddles (albedo x0.55, roughness 0.08, normal flattened) in 1.6 m noise blobs, only where the RVT
  albedo luminance is below `PuddleCut` (ruts and damp compacted dirt), so paving slabs stay dry.

### Foliage off the road (grass output)

All three Landscape Grass Types (near grass, dry tufts, reeds) are multiplied by:
- the off-core factor `saturate(1 - core / 0.3)` (LOOK2): zero wherever the RVT road can draw;
- the shoulder `saturate((0.835 - verge) / 0.095)` (LOOK2 fix round 1, review 4): the verge mask falls
  linearly with distance (0.96 on the centreline, 0.83 at 3 m, 0.74 at 4.5 m), so nothing roots within
  about 3 m of the centreline (the first ~0.7 m outside the visible edge of a 4.5 m road) and the verge
  regrows over the next 1.5 m. Analytic count of tufts rooted in the 1 m strip just outside the core
  polygon, 20-60 m ahead of road_1050: 305 (V3) -> 121 (LOOK2) -> 18 (fix round 1).

Only the crown term (neglect > 0.8) grows inside the core.

### DebugView

`DebugView` 0 is off. 1 core, 2 verge, 3 neglect, 4 surface, 5 moisture, 6 exposure, 7 zone, 8 macro,
in a blue-to-red false colour. The two mask samples run only inside the branch.

## Parameters (defaults)

| Group | Parameter | Default |
|---|---|---|
| Auto | `SlopeLo` / `SlopeHi` (on 1 - N.z) | 0.16 / 0.33 (about 33 to 48 degrees) |
| Auto | `GrassLo` / `GrassHi` (on moisture) | 0.42 / 0.72 |
| Auto | `SnowLo` / `SnowHi` (on ZoneSoft + macro - exposure + breakup) | 0.78 / 0.85 |
| Auto | `AlpineLo` / `AlpineHi` (bare rock on ZoneSoft + macro + breakup), `AlpineRock` | 0.62 / 0.78, 0.9 |
| Auto | `MacroTone`, `NormalStrength` | 0.12, 1.0 |
| Auto | `DryTint`, `GrassTint` | (1.08, 1.02, 0.92), (0.85, 0.95, 0.70) |
| Near | `NearStart` / `NearEnd` (cm) | 2000 / 3000 |
| Near | `DetailStrength`, `DetailTile` (cm) | 0.35, 230 |
| Near | `MacroNearStrength`, `MacroNearScale` (cm) | 0.07, 600 |
| Layers | `<Layer> Tile`, `<Layer> Tint`, `<Layer> Flatten`, `<Layer> Turn`, `NoTile` | see above; `NoTile` 1 |
| Colour | `HueAmount`, `ScreeAmount`, `MottleTone`, `MottleHue` | 1.8 (fix round 1; LOOK2 1.0), 0.35, 0.12, 1.0 |
| Road | `VergeDarken`, `RoadLift`, `RoadWetRough`, `PuddleAmount`, `PuddleCut`, `RoadDesat` | 0.5, 1.3, 0.8, 0.8, 0.1, 0.5 |
| Road | `RoadTone` | (1.06, 1.0, 0.9) |
| Debug | `DebugView` | 0 |

## Cost (read pass, `MaterialEditingLibrary.get_statistics`)

| Material | Pixel instructions |
|---|---|
| A constant-colour lit material in this project (the floor) | 186 |
| A bare RVT sample (BaseColor, Normal, Roughness) | 313 |
| `M_Saskarta_Ground`, as compiled (V2) | 394 |
| `M_Saskarta_Ground`, as compiled (LOOK2: road lift, sheen, puddles; 2026-09-27) | 438 |
| `M_Saskarta_Ground`, as compiled (LOOK2 fix round 1: road stone tone) | 447 |
| `M_Saskarta_Ground` without the DebugView branch (the path that executes at DebugView 0) | 362 |
| `MI_Saskarta_ColdWasteland_PerfCandidate` (the previous instance) | 350 |

Texture sample sites in the read pass: the RVT sample, the detail normal, and the two DebugView mask
samples (branch only), so 4. LOOK2 moves the road-mask sample out of the branch (the core lift, sheen and
puddles need it every pixel; DebugView reuses it), so it is still 4 sites, of which 3 run at DebugView 0
(V2: 2). The LOOK2 colour variation is all in the write pass and costs nothing per frame. `NumVirtualTextureSamples` is 6 and `NumSamplers` 5. The material-level
`NumPixelTextureSamples` (79) counts the write and grass passes too; it is not the main pass.

## Rebuild

With the editor gate held:

```
python Tools/Road/prepare_ground_material.py --send            # rebuild M/MI_Saskarta_Ground (saves only these)
python Tools/Road/prepare_ground_material.py --send --assign   # set it on the Landscape actor (saves only its package)
python -m pytest Tools/Road/tests -q                           # offline checks
```

After a rebuild, run `r.VT.Flush` so the RVT pages re-render.

## Nanite landscape

The landscape has Nanite on. Its built Nanite meshes carry the material they were built with
(`MI_Saskarta_ColdWasteland_Opt` on 2026-09-27), and the main pass draws those, so a material change
shows in the main pass only after **the user rebuilds the landscape Nanite data and saves the proxies**.
Until then the RVT (written by this material) is read through the old instance. To see this material
without the rebuild, set `landscape.RenderNanite 0` for the capture, and back to 1 afterwards.
