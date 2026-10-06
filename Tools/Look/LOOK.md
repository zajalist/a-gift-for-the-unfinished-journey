# Saskarta look: keys, grade and how to judge them

Spec: `docs/superpowers/specs/2026-09-26-saskarta-world-sprint-design.md`, section 6.
Task L1 of the world sprint. Ruling R13: this lighting is the reference for judging the road and
the ground; ruling R26: judge from near and mid captures on loaded ground, never from far views
of the mountain in the editor.

## The concept board, as numbers

Dark dusk, charcoal `#2A2826`, umber `#3B312B`, taupe `#6E5F55`; storm-lit clouds with warm
breaks; the accent `#C8703A` only for the sun disc, fire and the High Voice beacon.

`Tools/Look/measure_look.py <png>...` turns that into a gate every look capture must pass:

| Measure | Rule |
|---|---|
| Mean luminance (Rec.709 luma of the sRGB 8-bit frame, 0..1) | 0.14 - 0.26 |
| Median HSV saturation of mid-tone pixels (luma 0.25 - 0.75) | at most 0.30 |

## Tools

| File | What it does |
|---|---|
| `look_keys.json` | The five keys along the road (walk metres from the carrier dock, spline point 54). |
| `apply_look.py --key <name>` | Sets the level's sun, SkyAtmosphere, VolumetricCloud, height fog, SkyLight, `MPC_Saskarta_Sky` and the two grade volume weights to one key (python_run over Hayba TCP). |
| `apply_look.py --grades` | Creates or updates `PPV_Saskarta_Grade_Storm` / `_Clear` (unbound, not spatially loaded) and turns off `PPV_Saskarta_Mood`'s grading overrides (its manual exposure stays). Idempotent. |
| `apply_look.py --read` | Prints the current lighting state as JSON. |
| `capture_look.py <view> <out.png>` | Reproducible captures: `road_200`, `road_1050`, `road_2300`, `road_4700`, `sky_1050`, `title`. |
| `measure_look.py <png>...` | The palette gate above. |
| `sky_motion.py capture/measure/strip <tag>` | Task SKY: title-sky motion (frame difference 1 s apart) and variation (t0/t20/t39 spread), from the title sequence's own poses and WindOffset, into `Saved/Screenshots/Sky/`. |
| `fog_model.py report/render` | Task SKY: the engine's exponential height-fog integral, evaluated on the Gaea heightmap from the title camera. Judges the fog on the far mountain before HLODs exist. |
| `check_silhouette.py <png> <mountain_box> <sky_box>` | Mountain/sky luminance difference, pass at >= 0.08 (spec). Only meaningful after Build HLODs. |
| `build_look_keys_asset.py build` | Builds `DA_Saskarta_LookKeys` (class `USaskartaLookKeys`, SaskartaCore) from `look_keys.json` for the runtime lighting director (L7). Needs the SaskartaCore module built. |
| `build_look_keys_asset.py tag-actors` | Adds the director's tags (`Saskarta_Sun`, `_Sky`, `_Clouds`, `_Fog`, `_GradeStorm`, `_GradeClear`) to the six lighting actors by label and saves only those actors. |
| `build_ember_material.py check / build / stats` | The studio intro's RetainerBox effect `M_UI_EmberFire` (L5) from `Shaders/EmberFire.hlsl`: offline hygiene + FXC stats, the live build, and Hayba `material_compile` stats. `fonts` imports Cinzel / Cormorant (`F_Cinzel`, `F_Cormorant`) if missing; `defaults I B` sets the material's default Ignite/Burn for renders. |

Every editor use goes inside `python Tools/GameFlow/editor_gate.py acquire/release`.

### Why captures use a temporary SceneCapture2D

The editor normally sits behind other windows. Its level viewport is then not redrawn and
`editor_capture_viewport` returns a black frame. `capture_look.py` spawns a SceneCapture2D
(final colour LDR, which applies the level's post-process volumes and the manual exposure),
captures every frame for 4 s so Lumen, clouds and fog converge, exports the PNG and destroys the
actor. The level is left as it was.

Road views sit 2.5 m above the ground (line trace), look along the road (heading from the
spline 60 m ahead) at pitch +4 deg with a 70 deg horizontal FOV; `sky_1050` looks up at +25 deg.
The capture needs the landscape proxies under and ahead of the camera loaded (at most 4 at a time):

| View | Proxies |
|---|---|
| road_200 | LandscapeStreamingProxy_12_8_0, _11_8_0, _11_7_0, _12_7_0 |
| road_1050, sky_1050 | LandscapeStreamingProxy_11_7_0, _10_7_0, _10_6_0, _11_6_0 |
| road_2300 | LandscapeStreamingProxy_9_6_0, _8_6_0, _9_7_0, _8_7_0 |
| road_4700 | LandscapeStreamingProxy_6_8_0, _6_9_0 |

The first three rows are the tiles the 70 deg frustum crosses out to about 600 m (tile = 510 m,
index `floor((x + 18920) / 51000)`, `floor((y - 50) / 51000)`). LOOK2 fix round 1: with only
`_11_7_0` and `_10_6_0` loaded and editor HLODs hidden, tile `_10_7_0` on the left of road_1050 was
empty, and the loaded mountain tile behind it drew as a floating slab over a hole.

## Before state (the saved level, 2026-09-26 21:41)

A first L1 attempt left unsaved lighting edits in the open editor. The "before" state is
therefore the **saved on-disk level**: the external-actor packages last saved at 21:41 (before
the first attempt). Their tagged properties were read straight from the `.uasset` files.
Anything not listed was at the engine default. Before the before-captures, these values were
restored in the editor.

| Actor | Saved values |
|---|---|
| DirectionalLight | rotation pitch -8, yaw -44, roll -105; intensity 4.0 lux; use temperature, 5200 K; source angle 0.6; movable; dynamic shadow distance 250 m |
| SkyAtmosphere | Mie scattering 0.006, Mie absorption 0.002, multi-scattering 0.65, Rayleigh 0.038; at the world origin, default transform mode |
| VolumetricCloud | all defaults: `/Engine/EngineSky/VolumetricClouds/m_SimpleVolumetricCloud_Inst`, layer 5-15 km |
| ExponentialHeightFog | density 0.1, height falloff 0.35, max opacity 0.8, start 10 m, volumetric fog on (distance 80 m, scattering distribution 0.4); inscattering and second fog at defaults |
| SkyLight | intensity 0.85, light colour (R188, G201, B222), movable, real-time capture off |
| PPV_Saskarta_Mood | unbound, priority 1, manual exposure bias 10.5, colour saturation (0.86, 0.88, 0.92, 1.0), vignette 0.45 |

Before captures, measured (`Saved/Screenshots/Sprint/`):

| Capture | L | S_mid | Gate |
|---|---|---|---|
| L1_before_road_200.png | 0.115 | 0.512 | fail (dark, saturated red ground) |
| L1_before_road_1050.png | 0.138 | 0.446 | fail |
| L1_before_sky_1050.png | 0.162 | 0.454 | fail (blue sky, yellow clouds) |
| L1_before_title.png (first attempt, far view) | 0.265 | 0.514 | not judged (floating-slab far view) |

## The Valley key (applied and saved)

`look_keys.json` Valley plus the constants in `apply_look.py`:

| Part | Value | Why |
|---|---|---|
| Sun | pitch -8 (8 deg elevation), yaw 4, 2.2 lux, **4500 K**, cloud shadows off | The spec's "about 3,500 K" is the colour the light should read at. The atmosphere's transmittance at 8 deg already reddens the sun a lot, and a 3500 K source through it came out saturated orange (the first attempt). A 4500 K source reads warm, not orange, after the atmosphere. |
| SkyAtmosphere | Mie 0.006, anisotropy 0.75, Rayleigh 0.0331; planet top at Z -450 m; **sky luminance factor 3.5** | The open sky between storm clouds was near black at this exposure; 3.5 lifts it to charcoal. |
| VolumetricCloud | `MI_Saskarta_Cloud` (parent `M_Saskarta_Cloud`), layer 1.0-4.0 km above the planet top; **sky-light bottom occlusion 0.1**; cloud shadows off | At the engine's 0.5, storm undersides go black whenever the view faces away from the sun (sky framing L 0.08). Cloud shadows on made a strong storm look but pushed the road views to L 0.11-0.16, so they stay off (an option for the lighting director). |
| MPC_Saskarta_Sky | Coverage 0.7, Density 0.55, BaseAltitude 1.0, StormIntensity **0.45**, WindOffset 0, LightningFlash 0 | StormIntensity blends the cloud material toward its storm clouds (coverage, density, albedo). At 0.7 the sky is a black overcast (L 0.01-0.09), so the storm keys are capped at 0.45-0.6. The same value drives the audio (spec). |
| MI_Saskarta_Cloud | Cloud albedo (0.9, 0.84, 0.78); storm albedo **(0.8, 0.77, 0.74)** | Lighter storm albedo keeps lit cloud tops grey-taupe rather than brown. |
| Height fog | **task SKY:** density 0.32, falloff 0.4, colour #6E5F55 x 0.08 luminance scale, start **500 m**, second layer **0.002 at +200 m, falloff 0.25**, max opacity 0.8, no cutoff (L1 had 0.015 / 0.6 / start 150 m / 0.0003 at +250 m, falloff 0.08) | Horizontal fog bands: a dense sea in the valleys and basins with a sharp top (fog actor at Z -420 m; density halves every 25 m), a second, lighter tier topping out near -220 m, and the summit and beacon clear. See "Horizontal fog bands" below. |
| SkyLight | real-time capture on, intensity **0.62**, tint (0.95, 0.96, 1.0) | Ambient follows each key's sky; the slight cool tint keeps ambient near neutral so shadows read charcoal. |
| Grade | Storm weight 1, Clear 0 | See below. |

### The grade volumes

`PPV_Saskarta_Grade_Storm` (priority 2) and `PPV_Saskarta_Grade_Clear` (priority 3), both unbound
and not spatially loaded. `PPV_Saskarta_Mood` keeps only its manual exposure.

| Setting | Storm | Clear |
|---|---|---|
| Global saturation (luminance W) | **0.22** | **0.4** |
| Global contrast | 1.1 | 0.92 |
| Shadows | saturation 0.7, gain (1.03, 1.0, 0.96), offset (0.004, 0.0035, 0.003) toward #2A2826 | gain (1.02, 1.0, 0.97) |
| Mid-tones | saturation 0.8, gain (1.03, 1.0, 0.95) toward umber/taupe | gain (1.03, 1.0, 0.95) |
| Highlights | saturation 3.0, min 0.6, gain (1.02, 1.0, 0.96) | saturation 3.0, min 0.6, gain (1.1, 1.0, 0.82) toward #E8B070, W 1.02 |
| Film toe | 0.6 | 0.55 |
| Vignette / grain | 0.35 / 0.1 | 0.35 / 0.1 |

The accent #C8703A is not graded in. Orange belongs to emissive sources only.

Ruling R31 / task L1b: the global saturation above desaturates every luminance range, including
the brightest pixels, so raw emissive accents (the High Voice crown and beam) rendered near-white.
`ColorCorrectionHighlightsMin` at 0.6 narrows "highlights" to only the brightest band (the sun
disc, fire and the beacon; ordinary lit cloud tops sit below it), and a highlight-range saturation
of 3.0 (well above 1) pushes the accent hue back out from under the global desaturation for just
that band. Global saturation and the shadow/mid-tone values are untouched, so the rest of the
frame stays as dark and desaturated as before (Tools/Look/measure_look.py gate, unchanged).
Verified: the beacon crown hue is within 15 deg of #C8703A at saturation >= 0.45 (task-L2-report.md
capture position), while road_200 / road_1050 / sky_1050 still pass the L1 palette gate.

### After captures (Valley), measured

Two sets, 60 s apart; the cloud field drifts, so single frames vary by about +-0.03 L.

| Capture | L | S_mid | Gate |
|---|---|---|---|
| L1_after_road_200.png | 0.191 | 0.277 | pass |
| L1_after_road_1050.png | 0.205 | 0.241 | pass |
| L1_after_sky_1050.png | 0.148 | 0.118 | pass |
| (second set) road_200 | 0.219 | 0.277 | pass |
| (second set) road_1050 | 0.167 | 0.297 | pass |
| (second set) sky_1050 | 0.165 | 0.198 | pass |

| L1_after_title.png (TitleCam, record only) | 0.240 | 0.265 | pass (not judged: far view) |

### The Above key (road 4,700 m), measured

Above: sun 10 deg elevation at 4300 K and **0.7 lux** (the first value, 7 lux, gave L 0.55 under the
shared sky luminance factor); clouds 0.15-0.47 km above the planet top, so below the road; thin
warm fog #B89A7A; Clear grade only, global saturation 0.4 with highlight gain toward #E8B070.

| Capture | L | S_mid | Gate |
|---|---|---|---|
| L1_after_above_road_4700.png | 0.252 | 0.277 | pass |

Tuning path for Above: 6 lux / Clear saturation 0.75: L 0.545; 2 lux: 0.384; 0.9 lux: 0.281 (S 0.398);
0.8 lux / 0.55: 0.267 (S 0.330); 0.7 lux / 0.45: 0.252 (S 0.300); 0.7 lux / 0.4: 0.252 (S 0.277).
The level was restored to Valley afterwards and saved in Valley.

### The other keys

Basin, Climb and InCloud were scaled from Valley with the same reasoning (source temperature about
+1000 K over the spec's perceived temperature; StormIntensity capped at 0.5-0.6; fog densities
lowered from the first attempt). They were **not** captured in L1 (Basin at 2,300 m has a
`road_2300` view ready). Capture and gate them when the lighting director (L7) blends them.

## Title sky calm-down and horizontal fog bands (task SKY, 2026-09-27)

User: "the sky has too much speed and variation in the main title screen"; "we need horizontal fog
+ we dont see the mountain in the far".

### What moved the title sky

`M_Saskarta_Cloud` moves its noise by `CloudWind = (Layout_WindControls.xyz + WindOffset) *
(time / 3.9 s + WindOffset)`: WindOffset (MPC_Saskarta_Sky) is added to both factors, which are then
multiplied. So:

1. **LS_Saskarta_Title's WindOffset ramp (0 -> 3 over 40 s)** was the main driver. It sped the clouds
   up 1x -> 5x -> 9x across one loop in a fresh game (more later in a session, since the product
   term grows with engine time), then snapped back at each loop. Now keyed flat at 0
   (`build_title_sequence.py wind`).
2. **The cloud material's own wind** (`Layout_WindControls` (1, 1, 0.5), engine time): moved the
   storm field far enough in 40 s to swing the sky from near black to bright. Now 0.35x in
   `MI_Saskarta_Cloud` (`apply_look.CLOUD_WIND_CONTROLS` = (0.35, 0.35, 0.175, 0.333)); this is
   also the gameplay cloud speed.
3. Not drivers: SM_Skybox_Mesh (Chaotic Skies dome, `M_Flowmap_Main` Speed 0.3): hiding it from the
   title capture changes the frame by 1-2 of 255 on average, because the fog covers it at 28.7 km.
   The sequence keys nothing else (TitleCam transform only). The lighting director is inactive.
   `MPC_Saskarta_Wind` drives foliage only.

Measured with `sky_motion.py` (TitleCam's sequence poses, clouds at full resolution without
temporal reconstruction, sky region = top 40 % minus the beam column):

| Metric | Before | After |
|---|---|---|
| Motion, mean abs luma difference 1 s apart (0-255), mean of t0/t20/t39 | 76.1 | 3.6 |
| Sky mean-luma spread across t0/t20/t39 (0-1) | 0.379 | 0.022 |
| Sky hue spread (deg) | 2.05 | 0.10 |
| Per-pixel luma std across t0/t20/t39 (0-1) | 0.165 | 0.052 |

The "before" motion is exaggerated in the editor (engine time there is about 18,000 s, so the
ramp's product term is huge); in a fresh game the ramp cost 5-9x speed, as above. The "after"
state has no WindOffset term, so the editor and the game agree. The editor's cloud field sits
wherever its engine time puts it; the game's title starts at time 0, so its cloud cover is the
same at every launch.

### Horizontal fog bands

Valley key: main layer density 0.32, falloff 0.4 at the fog actor (Z -420 m): a dense sea in the
valleys and basins whose density halves every 25 m (a sharp top). Second layer 0.002 at +200 m
(-220 m), falloff 0.25 (key field `second_falloff`; other keys keep 0.08): a lighter upper tier.
Start 500 m (the near air stays clear; the bands read across the valley), max opacity 0.8, no
FogCutoffDistance. Inscattering colour unchanged.

`fog_model.py report` (the engine's fog integral on the Gaea heightmap, title camera t0):

| Receiver | Transmittance before | after |
|---|---|---|
| Mountain, 20 m under the summit (3.2 km) | 0.96 | 0.88 |
| Mountain, upper quarter | 0.96 | 0.83 |
| Mountain, mid-height (-75 m) | 0.95 | 0.67 |
| Mountain, lower quarter | 0.93 | 0.31 |
| Mountain base +20 m / valley floor at 60 % | 0.88 / 0.82 | 0.20 / 0.20 |

So the summit keeps about 88 % of its contrast and the lower half sits in the fog. Tests:
`tests/test_fog_model.py` pins these ranges. The lighting director (L7) blends density, falloff,
start and the second layer's density and offset, but not the second layer's falloff (no header
changes in run 3): when it runs, every key uses the placed 0.25.

The mountain is still not drawn beyond the World Partition range until **Build HLODs** has run
(Tools/Look/HLOD.md). The fog does not hide it: no cutoff distance, and the summit's
transmittance is 0.88.

## The silhouette check waits for Build HLODs (user)

In the editor, World Partition loads only a few landscape tiles, and any far view of the central
mountain renders it as a floating slab over empty ground. Neither fog nor the silhouette check
can be judged against that. After the user's **Build HLODs** (L2 sets up the HLOD layer):

1. `python Tools/Look/capture_look.py title Saved/Screenshots/Sprint/L1_hlod_title.png`
2. Project the summit (287480, 444050) and spline point 0 (298079.6, 483050, 10898) through
   TitleCam to pixels; the mountain box sits just under the summit, the sky box just above it.
3. `python Tools/Look/check_silhouette.py <png> <mountain_box> <sky_box>` must print >= 0.08.
   If not, lower the Valley fog density or raise its second layer, then re-run `measure_look.py`
   on the road views so the near look still passes.

## Known issues

- The capture luminance follows the drifting cloud field (the cloud material animates with
  time). Across tuning runs the same view ranged over about 0.08 L when the storm cover
  changed. Task SKY slowed the wind to 0.35x. Do not animate WindOffset for speed: the material
  multiplies it with engine time (see above).
- The ground material (`MI_Saskarta_ColdWasteland_PerfCandidate`) reads saturated red under the
  old light and pale sand under the new. The ground's own albedo, not the light, dominates the
  road views; judge it (V7) under this light.

## Look pass 2 (task LOOK2, 2026-09-27): a road you want to follow

User: "the colors are all washed out", "a bit more saturation and make the sky a bit more intense",
"ideally less foliage inside the road and more color variation". The ground side (road core, grass,
colour variation) is in `Tools/Road/GROUND.md`; this is the light and grade side, built on task SKY's
fog bands and calm clouds (never reverted).

| Where | Value | Old | New | Why |
|---|---|---|---|---|
| `apply_look.py` | `SKYLIGHT_INTENSITY` | 0.62 | 1.3 | The ground in shadow sat near black (road_200 lower half luma about 0.05). |
| | `SKYLIGHT_TINT` | (0.95, 0.96, 1.0) | (0.9, 0.95, 1.05) | A slightly cooler ambient, so ochre, olive and grey ground do not collapse into one orange. |
| | `SKY_LUMINANCE_FACTOR` | 3.5 | 2.8 | Deeper storm tones overhead. |
| | `CLOUD_BOTTOM_OCCLUSION` | 0.1 | 0.2 | More cloud light/shadow contrast. |
| | `VOLUMETRIC_FOG_EXTINCTION` (new) | 1.0 | 0.5 | Less haze inside the near 500 m that SKY's fog start distance leaves clear; SKY's valley bands are untouched. |
| | `MOOD_EXPOSURE_BIAS` (new, `--grades`) | 10.5 | 11.25 | PPV_Saskarta_Mood manual exposure (EV): the lit frame was near black. |
| Storm grade | global saturation | 0.22 (committed) / 0.55 (uncommitted working tree) | 0.6 | "more saturation". |
| | mid-tone saturation, contrast | 0.8, 1.1 | 1.1, 1.15 | Richer mid-tones, more contrast in the lower frame. |
| | mid-tone gain | (1.03, 1.0, 0.95) | (1.0, 1.0, 0.98) | Less orange cast, so greens read. |
| Clear grade | global saturation | 0.4 | 0.85 | |
| `look_keys.json` Valley | Mie scattering, anisotropy | 0.006, 0.75 | 0.009, 0.8 | A stronger, warmer bright band under the cloud base toward the sun. |
| | storm_intensity | 0.45 | 0.5 | Deeper storm overhead. |

Measured with `Tools/Look/measure_look2.py` (Saved/Screenshots/Look2/, `before_*` = start of task,
`B0_*` = after the ground work, `after_*` = final):

| View | luma | C* (frame) | L* std, lower half | road/verge lit ratio |
|---|---|---|---|---|
| road_200 | 0.077 -> 0.189 | 3.9 -> 18.1 | 6.0 -> 11.2 | 1.06 -> 1.36 |
| road_1050 | 0.076 -> 0.204 | 3.1 -> 16.0 | 3.0 -> 13.3 | 0.94 -> 0.46 (road in a shadowed cut, sunlit bank in the verge sample) |
| road_2300 | 0.120 -> 0.283 | 6.3 -> 26.0 | 11.1 -> 17.8 | 1.04 -> 1.15 |
| sky_1050 | 0.156 -> 0.298 | 6.8 -> 16.7 | | |

**The palette gate (`measure_look.py`, S_mid <= 0.30) now fails on the road and sky views** (S_mid
0.30-0.50). It already failed before this task's grade change (B0_*: 0.37-0.69) because of the uncommitted
0.55 saturation in the working tree. The user asked for more saturation, so the gate's 0.30 ceiling and
its 0.26 luma ceiling need a decision; they were left unchanged.

**Captures in the editor need three things now** (all done by the LOOK2 scratch wrapper, not yet by
`capture_look.py`): pump `capture_scene()` about once a second during the settle (a background editor
does not redraw `capture_every_frame`, so the RVT never gets feedback and stays blurry); hide editor HLODs
(`wp.Editor.HLOD.AllowShowingHLODsInEditor 0`) because the HLODs built on 2026-09-27 draw over loaded
proxies; and landscape grass only grows around an editor viewport camera, never a scene capture.

### Look pass 2, fix round 1: one tint over everything

Review: the frame read as one strong red-orange tint over sky, mountains and ground, and the road at
1050 m was darker than the ground. `measure_look2.py` now also reports the **cast**, |mean(a*, b*)| /
mean(C*) (1 = every pixel leans the same hue way). The after-captures read 0.94-0.97, and the ground's
own albedo only 0.99 with a 5-7 deg hue spread. Causes and changes:

| Where | Value | Old | New | Why |
|---|---|---|---|---|
| `look_keys.json` Valley | sun temperature | 4500 K | 6200 K | At 8 deg elevation the atmosphere already reddens the sun; with the saturation raised for the user, 4500 K turned every lit surface rust. `DA_Saskarta_LookKeys` rebuilt (the lighting director sets it at runtime). |
| Storm grade | white balance (new) | 6500 K, tint 0 | 5400 K, tint -0.1 | Pulls the lit ground back toward its own ochre / olive / grey; clouds keep warm breaks, open sky reads blue-grey. |
| `apply_look.py` | `SKYLIGHT_INTENSITY` | 1.3 | 2.2 | A flat road gets sin(8 deg) = 0.14 of the sun, the rough sun-facing verge far more, so the lit road read darker than the verge. More ambient lets the lighter road albedo show. |
| Ground (GROUND.md) | `Grass Tint` layer, `HueAmount`, `RoadLift`, `RoadDesat` | pink (1.10, 0.62, 0.72), 1.0, 1.3, none | (0.9, 1.0, 0.8), 1.8, 1.5, 0.5 | The inherited pink grass-layer tint turned every moist hollow rust; the road now also differs in hue (warm grey stone). |

Captures: `fr1after_*`, with the four proxies per view in the table above.

| View | luma | cast frame / lower | hue spread | road/verge lit | S_mid (gate 0.30) |
|---|---|---|---|---|---|
| road_200 | 0.189 -> 0.169 | 0.95 / 0.97 -> 0.85 / 0.96 | 16.5 -> 18.0 | 1.36 -> 2.60 | 0.25 pass |
| road_1050 | 0.204 -> 0.180 | 0.94 / 0.96 -> 0.49 / 0.90 | 19.6 -> 34.0 | 0.46 -> 1.32 | 0.28 pass |
| road_2300 | 0.283 -> 0.341 | 0.97 / 0.97 -> 0.91 / 0.93 | 16.7 -> 33.6 | 1.15 -> 1.84 | 0.27 (luma fails) |
| sky_1050 | 0.298 -> 0.165 | 0.97 / 0.98 -> 0.52 / 0.62 | 17.2 -> 63.5 | | 0.31 |
| base colour, road_1050 | | 0.99 -> 0.97 | 6.1 -> 12.4 | albedo 1.31 -> 1.48 | |

The cloud field drifts between shots (single frames vary by about +-0.03 luma), and the sky view
changes most with it.

## Fog 3 (task FOG3, 2026-09-28): a veil around the carrier, not a wall

User: "the fog shouldn't be dense, it should be close to the player, but not dense, especially for objects
that are very high". Fog 2 (eb53b4af) walled every key off by 80-300 m (FogMaxOpacity 0.97) and hid the
summit from the whole road (T 0.03-0.06). Fog 3 keeps the start close (12 m) and the ochre / sickly tints,
and makes the fog a layer that hugs the ground.

**Fix round 1 (same day, after the verifier).** The first cut (ca5c9482) had four problems:

- The veil was too faint to notice: 0.8-4.9 % of a 50 m object's contrast. It read as haze 150-300 m out,
  not as dust around the carrier. It is now 4.4-6.5 % at the valley, basin and cistern keys, and 4.7-8.9 %
  along the valley floor and the basin.
- The climb had a fog sea below it. From Stair on, the dust anchor rode 0-46 m under the road, and the
  dust doubles every 25 m below its anchor. The ground 300 m downhill sat at 0.20-0.28, and the basin
  seen from the climb was on the 0.2 floor. The climb's dust now stays on the basin floor. The ground
  300 m downhill keeps at least 0.88, and the valley and basin at 1 km keep 0.70-0.94.
- The per-key fit bulged between keys, because the carrier's height in the dust layer changes between
  them. The densities are now a least-squares fit along the whole road.
- The blended anchor rose 2.02 m over the road at 3,550 m, just past the 2.0 m tolerance. The anchor is
  now rounded down (worst case 1.98 m).

`apply_look.py --save` also refuses to save unless the data asset already holds the new fog (see the
editor steps below).

### How the fog is built now

| Layer | Job | Values |
|---|---|---|
| Second layer (the director blends its density and height) | **The dust.** It hugs the ground: its density halves every 20 m (`second_falloff` 0.5, the same in every key), so about 90 % of it lies in the first 60 m. Each key anchors it on the low ground under the road (the road's lower envelope, `fog_model._dust_anchors`). The dust pools in the dips and the basin, and the crests and the ridge top stand above it. The director's linear blend never sinks the carrier into the thick bottom of the layer (the anchor stays at most 2 m above the road). From Stair on, the anchor sits on the basin floor (-416 m, the road's lowest ground) with the Cistern key's ground density. The carrier climbs out of the dust, and the basin below keeps the thin layer it had from inside. Any anchor above the basin floor fills the basin with a sea, because the density keeps growing below the anchor. | `second_density` 0.019-0.034; `second_height_m` = the anchor over the fog actor (Z -420 m) |
| Main layer (the director blends density and falloff) | **The haze.** The valley-wide aerial perspective, anchored at the fog actor, which sits at about basin-floor height. It halves every 50 m on every key. With one falloff everywhere, the director's linear blend of the density cannot bulge between keys. The climb keys carry CisternHold's haze, so the haze is one field and the basin looks the same from above as from inside. | `density` 0.016-0.055; `falloff` 0.2 |
| Level-only (apply_look saves them on the fog actor; the director does not touch them) | Start 12 m. **FogMaxOpacity 0.8**: the far ground keeps at least 20 % of its contrast (Fog 2 had 0.97). Second-layer falloff 0.5 (the first cut had 0.4; Fog 2 had 0.08). Directional inscattering (exponent 8, #D89A48) is unchanged. | `apply_look.SECOND_FOG_FALLOFF` 0.5, `FOG_MAX_OPACITY` 0.8 |
| Volumetric fog | Stays **off** (Fog 2's decision: editor captures cannot light it). Its A/B range is the carrier's own air, 10-60 m (fade-in 5 m), with extinction scale 1.0 over the height fog. `M_Saskarta_DustVolume`'s bubble and near layer are thinned to a ~10 % veil over 50 m (`build_storm_fx.py` Shape / Gust / Near). | `VOLUMETRIC_FOG_*`, `VOLUME_PARAMS` |

Every fog number in `look_keys.json` comes from `fog_model.fit_keys(FOG3_PLAN)` (`python Tools/Look/fog_model.py fit
--write`; a test pins it). `FOG3_PLAN` is the one thing to tune. For each valley, basin and cistern key it
gives the veil at 50 m (1 - T50 at the carrier's eye) and the dust's share of that veil. Both layers'
densities are a least-squares fit, every 10 m along the road up to CisternHold and blended as the director
blends them. Each key's own road metre counts five times, and the fit aims at the plan's veil, linear between
keys.

Where the road runs above low ground, more of the veil is haze: the dip at 1,220 m, the descent into the
basin (BasinPeak) and the cistern below CisternHold. From the road down to the basin floor the haze grows
about 2.5x, while the dust grows about 10x. So the ground the carrier looks down on is softened, not a
pocket of dust.

The colours, the fog luminance (the Fog 2 lane's x0.65 is kept), the sun, the sky and the clouds are
unchanged.

### The physics limit

Along a level ray the height fog is uniform, so T1000 = T50^26 (start 12 m). A veil you notice at 50 m
(>= 5 %) leaves flat ground at the carrier's own height at about 0.25 at 1 km, and on the 0.2 floor by 2 km.
The first cut kept Act I's 1 km at 0.29-0.50 only because its veil was 2.8 %. Ground that rises out of the
dust stays clearer (the valley sides, the mountain, the towers; see "ground 1 km mean"). Dust that is thick
near the carrier and thins with distance needs local volumes or particles, which height fog cannot provide.
There is no airborne dust-mote system in the project yet (only the sand-stream decals, road 0-3,300 m, and
the dust devils).

### Before / after (`python Tools/Look/fog_model.py table --terrain [--keys <json>]`)

Transmittance (1 = clear, 0 = fog colour) from the carrier's eye (road + 2.5 m) at each key's road metre:

- **Veil 50 m:** 1 - T50, the dust around the carrier.
- **T20-T2000:** ground-level objects at that distance.
- **Tower:** the top of a 40 m tower 300 m away.
- **Ridge:** a ridge 400 m over the road, 2 km away.
- **Summit:** the hero summit from the spawn (3.3 km, 554 m up) and from road metre 2,300 (2.1 km), under that
  key's fog. n/a where the key's road is more than 60 m above or below that camera (the director never
  applies the key there).
- **Sky:** 30 deg up.
- **Ground 300 / 1 km:** the real Gaea terrain (+1 m) at that distance on 16 headings (`fog_model.terrain_ring`,
  occlusion ignored). These are the downhill views a level ray misses.
- **Half:** the distance where a ground object keeps half its contrast.

Before (Fog 2, eb53b4af):

| Key | road m | T50 | T150 | T300 | T1000 | T2000 | tower | ridge | summit spawn | summit 2300 | sky 30 | half m |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Valley | 0 | 0.79 | 0.36 | 0.11 | 0.03 | 0.03 | 0.19 | 0.07 | 0.04 | 0.06 | 0.37 | 110 |
| ValleyHold | 900 | 0.77 | 0.33 | 0.09 | 0.03 | 0.03 | 0.17 | 0.06 | 0.03 | 0.03 | 0.34 | 105 |
| Ridge | 1500 | 0.69 | 0.20 | 0.03 | 0.03 | 0.03 | 0.06 | 0.03 | 0.03 | 0.03 | 0.11 | 80 |
| BasinPeak | 2150 | 0.45 | 0.03 | 0.03 | 0.03 | 0.03 | 0.03 | 0.03 | 0.03 | 0.03 | 0.03 | 50 |
| BasinHold | 2700 | 0.39 | 0.03 | 0.03 | 0.03 | 0.03 | 0.03 | 0.03 | 0.03 | 0.03 | 0.03 | 45 |
| Cistern | 2950 | 0.73 | 0.26 | 0.05 | 0.03 | 0.03 | 0.10 | 0.03 | 0.04 | 0.07 | 0.20 | 90 |
| CisternHold | 3250 | 0.70 | 0.22 | 0.04 | 0.03 | 0.03 | 0.07 | 0.03 | 0.03 | 0.03 | 0.17 | 80 |
| Stair | 3650 | 0.60 | 0.11 | 0.03 | 0.03 | 0.03 | 0.03 | 0.03 | n/a | n/a | 0.03 | 65 |
| InCloud | 4350 | 0.32 | 0.03 | 0.03 | 0.03 | 0.03 | 0.03 | 0.03 | n/a | n/a | 0.03 | 40 |
| Above | 4550 | 0.92 | 0.70 | 0.46 | 0.07 | 0.03 | 0.50 | 0.15 | n/a | n/a | 0.47 | 270 |

First cut (Fog 3, ca5c9482):

| Key | road m | veil 50 m | T50 | T300 | T1000 | T2000 | tower | ridge | summit spawn | summit 2300 | sky 30 | ground 300 mean / min | ground 1 km mean |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Valley | 0 | 2.8 % | 0.97 | 0.81 | 0.48 | 0.23 | 0.87 | 0.84 | 0.82 | 0.81 | 0.94 | 0.80 / 0.77 | 0.65 |
| ValleyHold | 900 | 2.9 % | 0.97 | 0.80 | 0.47 | 0.21 | 0.86 | 0.83 | 0.75 | 0.75 | 0.94 | 0.78 / 0.72 | 0.47 |
| Ridge | 1500 | 4.3 % | 0.96 | 0.71 | 0.32 | 0.20 | 0.80 | 0.77 | 0.74 | 0.74 | 0.91 | 0.73 / 0.63 | 0.44 |
| BasinPeak | 2150 | 4.9 % | 0.95 | 0.68 | 0.27 | 0.20 | 0.77 | 0.73 | 0.65 | 0.65 | 0.89 | 0.66 / 0.45 | 0.29 |
| BasinHold | 2700 | 4.8 % | 0.95 | 0.69 | 0.28 | 0.20 | 0.78 | 0.73 | 0.88 | 0.89 | 0.89 | 0.73 / 0.71 | 0.53 |
| Cistern | 2950 | 3.2 % | 0.97 | 0.78 | 0.43 | 0.20 | 0.85 | 0.82 | 0.90 | 0.90 | 0.93 | 0.80 / 0.71 | 0.60 |
| CisternHold | 3250 | 2.4 % | 0.98 | 0.83 | 0.53 | 0.28 | 0.88 | 0.85 | 0.79 | 0.80 | 0.94 | 0.83 / 0.69 | 0.50 |
| Stair | 3650 | 1.4 % | 0.99 | 0.90 | 0.70 | 0.48 | 0.93 | 0.89 | n/a | n/a | 0.95 | 0.77 / **0.28** | 0.38 |
| InCloud | 4350 | 2.1 % | 0.98 | 0.85 | 0.57 | 0.33 | 0.89 | 0.83 | n/a | n/a | 0.93 | 0.57 / **0.20** | 0.24 |
| Above | 4550 | 0.8 % | 0.99 | 0.94 | 0.81 | 0.65 | 0.96 | 0.92 | n/a | n/a | 0.97 | 0.85 / 0.55 | **0.22** |

After (Fog 3, fix round 1):

| Key | road m | veil 50 m | T20 | T50 | T150 | T300 | T1000 | T2000 | tower | ridge | summit spawn | summit 2300 | sky 30 | ground 300 mean / min | ground 1 km mean | half m |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Valley | 0 | 5.4 % | 0.99 | 0.95 | 0.82 | 0.66 | 0.24 | 0.20 | 0.78 | 0.77 | 0.73 | 0.69 | 0.91 | 0.64 / 0.59 | 0.49 | 490 |
| ValleyHold | 900 | 5.0 % | 0.99 | 0.95 | 0.83 | 0.68 | 0.26 | 0.20 | 0.77 | 0.70 | 0.58 | 0.58 | 0.88 | 0.64 / 0.57 | 0.31 | 530 |
| Ridge | 1500 | 6.5 % | 0.99 | 0.94 | 0.78 | 0.60 | 0.20 | 0.20 | 0.71 | 0.64 | 0.61 | 0.62 | 0.85 | 0.62 / 0.49 | 0.34 | 405 |
| BasinPeak | 2150 | 5.7 % | 0.99 | 0.94 | 0.81 | 0.64 | 0.22 | 0.20 | 0.73 | 0.65 | 0.57 | 0.58 | 0.85 | 0.62 / 0.40 | 0.26 | 465 |
| BasinHold | 2700 | 5.6 % | 0.99 | 0.94 | 0.81 | 0.65 | 0.22 | 0.20 | 0.75 | 0.70 | 0.86 | 0.87 | 0.88 | 0.70 / 0.67 | 0.49 | 470 |
| Cistern | 2950 | 5.3 % | 0.99 | 0.95 | 0.82 | 0.66 | 0.24 | 0.20 | 0.77 | 0.72 | 0.83 | 0.84 | 0.89 | 0.69 / 0.55 | 0.46 | 495 |
| CisternHold | 3250 | 4.4 % | 0.99 | 0.96 | 0.85 | 0.71 | 0.31 | 0.20 | 0.79 | 0.73 | 0.64 | 0.65 | 0.89 | 0.72 / 0.48 | 0.35 | 605 |
| Stair | 3650 | 0.4 % | 1.00 | 1.00 | 0.98 | 0.97 | 0.90 | 0.80 | 0.97 | 0.96 | n/a | n/a | 0.98 | 0.95 / 0.88 | 0.70 | > 3000 |
| InCloud | 4350 | 0.0 % | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.99 | 1.00 | 1.00 | n/a | n/a | 1.00 | 1.00 / 1.00 | 0.90 | > 3000 |
| Above | 4550 | 0.0 % | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | n/a | n/a | 1.00 | 1.00 / 1.00 | 0.92 | > 3000 |

The summit as the game shows it, with the fog the director blends at that road metre: from the spawn
**0.04 -> 0.73** (first cut 0.82), and from road 2,300 m **0.03 -> 0.67** (first cut 0.74). CIN_01's whip-pan
needs no fog override; its `SetFog 0.6` at shot 5 still thins the haze further.

Along the road, blended as the director does (`python Tools/Look/fog_model.py stretches --terrain`, every 25 m).
Ground 300 min is the worst of the 16 terrain headings at 300 m:

| Stretch | road m | veil 50 m | T300 | T1000 | tower | ridge | sky 30 | ground 300 min | ground 1 km mean |
|---|---|---|---|---|---|---|---|---|---|
| Act I, valley floor | 0-1450 | 4.7-7.4 % | 0.56-0.70 | 0.20-0.29 | 0.68-0.78 | 0.61-0.77 | 0.84-0.91 | 0.46-0.61 | 0.28-0.49 |
| Ridge climb and top | 1450-2150 | 2.1-6.8 % | 0.59-0.85 | 0.20-0.58 | 0.70-0.89 | 0.63-0.84 | 0.85-0.94 | 0.40-0.63 | 0.26-0.41 |
| Basin storm | 2150-2700 | 5.6-8.9 % | 0.49-0.65 | 0.20-0.22 | 0.63-0.75 | 0.54-0.70 | 0.80-0.88 | 0.36-0.67 | 0.25-0.49 |
| Basin floor to the mountain foot | 2700-3650 | 0.4-6.6 % | 0.59-0.97 | 0.20-0.90 | 0.71-0.97 | 0.65-0.96 | 0.85-0.98 | 0.47-0.88 | 0.34-0.70 |
| Climb and summit approach | 3650-5009 | 0.0-0.4 % | 0.97-1.00 | 0.90-1.00 | 0.97-1.00 | 0.96-1.00 | 0.98-1.00 | 0.88-1.00 | 0.70-0.94 |

The summit from every road metre where it is in view (0-2,140 m): 0.63-0.84. The relay tower top (summit
+30 m): 0.64-0.85.

Points of interest (first cut -> now):
- Waiting Water's tower top from 1,060 m: 0.81 -> 0.70.
- The refinery column tops, 1.3 km at +8 deg: 0.72 -> 0.55.
- The Works from 2,260 m (366 m ahead, 5 deg below, at the storm peak): chimney top 0.42 -> 0.36, hall base
  0.39 -> 0.32.

### Trade-offs

- **The ridge climb and top (1,700-2,100 m) stand above the dust.** The veil there drops to 2-4 % while the
  basin ahead lies under it. This is the one vista where standing over the dust reads right.
- **The climb (Stair on) has almost no veil at the carrier** (0-0.5 %). Anything that thickens the air around
  the carrier up there (a lower haze falloff, a dust anchor above the basin floor) fills the basin and the
  valley below with a sea. Near dust on the climb needs particles or the volumetric A/B. InCloud's "in the
  cloud" stays the VolumetricCloud layer's job (its base is at -70 m there).
- **The basin storm** is the densest air around the carrier (up to 8.9 % at 50 m, T300 0.49 at road 2,400 m),
  while the tall things keep 0.54-0.75.
- **1-2 km over flat ground sits on or near the 0.2 floor** on every valley, basin and cistern key (see The
  physics limit). The first cut's Act I T1000 of 0.29-0.50 came with a veil nobody could see.
- **The title (not changed here, needs a decision).** With no road progress, the title plays under the
  level's saved look, the Valley key. Its hill cameras (-192 to -216 m) sit about 150 m over the Valley
  dust anchor (-365 m). The ground 300 m ahead reads 0.96, the ground 2 km ahead 0.72-0.93 and the summit
  0.98. That is nearly fog-free, not Task TITLE's fog sea below the hill. The first cut was the same (0.97 /
  0.79-0.95 / 0.98). A title look (a story SetFog, or its own key) is a separate decision.

### Editor apply steps (editor up, PIE not running)

Nothing is in the game until these steps run. Until then, `DA_Saskarta_LookKeys` and the level still hold
Fog 2: the summit from the spawn reads 0.04, and T300 is 0.03-0.11.

The director sets only density, falloff, colour, start and the second layer's density and height at
runtime. The level-only values (second falloff 0.5, max opacity 0.8) only fit the new densities, so **steps
2 and 3 go together, in this order, and step 3 runs only after step 2 succeeded**:

- **DA rebuilt, level not saved.** The game keeps Fog 2's falloff 0.08 and max opacity 0.97 under the new
  densities. The summit from the spawn reads 0.18, the sky 30 deg up 0.56, and a ridge at 2 km 0.26.
- **Level saved while the DA still holds Fog 2.** Every key reaches the 0.2 floor by 300 m. `apply_look.py
  --save` now refuses this case: it reads the DA's fog for every key and saves nothing ("NOT SAVED ...",
  exit 1) unless it matches `look_keys.json`.

Check the read-only flag of every committed package before a save (`(Get-Item <file>).IsReadOnly`).

1. `python Tools/GameFlow/editor_gate.py acquire --owner LOOK`
2. `python Tools/Look/build_look_keys_asset.py build`: rebuilds `DA_Saskarta_LookKeys` (10 keys, no C++
   change) and saves it. Check that it printed `saved True`.
3. `python Tools/Look/apply_look.py --key Valley`, then `python Tools/Look/apply_look.py --save` (a separate
   call). The level's fog actor gets start 12 m, second falloff 0.5, max opacity 0.8 and the 10-60 m
   volumetric A/B range (volumetric still off). The save writes only the lighting actors, MPC_Saskarta_Sky and
   MI_Saskarta_Cloud (dirty packages only), and only when the DA matches `look_keys.json`.
4. Captures (analytic fog, which a SceneCapture renders correctly):
   - Before each capture, run `python Tools/Look/apply_look.py --road <m>` for that view's road metre, and
     load its landscape proxies (the Fog 2 lane's scratch `fog2_wp.py load|unload <view>`).
   - Capture `capture_look.py spawn Saved/Screenshots/Look/Fog3/spawn_summit.png --yaw -176.6` (the summit
     silhouette, CIN_01's whip-pan). Leave the editor HLODs showing for this one.
   - Then capture `road_1000`, `road_2300f` (the storm peak), `cistern` and `climb` into
     `Saved/Screenshots/Look/Fog3/`.
   - Run `measure_look2.py` on them, and `check_silhouette.py` on the spawn view (>= 0.08).
   - After the last capture, re-apply the Valley key (`--key Valley`), then `--save` as a separate call.
5. `python Tools/Look/gpu_budget.py measure --samples 3`: the fog cost should not move (the analytic fog costs
   the same at any density, and volumetric fog stays off).
6. `python Tools/GameFlow/editor_gate.py release --owner LOOK`. Commit the DA, the saved external actor
   packages, the MPC and the MI by pathspec.
7. Optional volumetric A/B in PIE:
   - Set `VOLUMETRIC_FOG_ENABLED = True` in `apply_look.py` and re-apply.
   - Run `python Tools/Look/build_storm_fx.py set Shape 0.0006 -42000 25 1`, `set Gust 0.35 7 0.0015 30` and
     `set Near 0.0015 1.2 20 1.4`. Each call recompiles and saves M_Saskarta_DustVolume.

   This adds the churning dust bubble in the carrier's 10-60 m, the one way to add near dust that thins
   with distance. Judge it in PIE (captures cannot light it) and with `gpu_budget.py`.

## 2026-10-02 distance cutoff

The summit playtest showed unbuilt terrain beyond the road. The current saved fog actor and all ten
runtime look keys use density `0.06`, height falloff `0`, and start distance `400 m`; maximum opacity
is `0.98`. The focused summit preview at
`Saved/Verification/point_cloud_audit_20261002/fog_horizon_summit.png` keeps nearby road clear and a
faint ridge visible while hiding remote terrain detail. This supersedes the closer `0.12` / `200 m`
cutoff. A full PIE route check remains open.
