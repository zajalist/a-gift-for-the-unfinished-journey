# Ambience placement in Saskarta_WP

This page lists the AmbientSound actors that play the recorded ambience in `/Game/level/Saskarta_WP`: zone beds, moody layers, spatial site loops and Geiger hotspots. It gives every actor's label, sound, location, radius and volume so the mix can be tuned. The recipe comes from [`AMBIENCE_MIX.md`](AMBIENCE_MIX.md), and positions come from [`docs/story/road-profile.json`](../../docs/story/road-profile.json).

The plan is written in code in [`place_ambience.py`](place_ambience.py). To tune, edit its `PLAN` / `PRESETS` and re-run the simulation:

```
python Tools/Audio/place_ambience.py          # level of every sound along the road vs the AMBIENCE_MIX target
python Tools/Audio/place_ambience.py --md     # regenerate the actor table below
python Tools/Audio/place_ambience.py --json plan.json   # resolved list the editor script consumed
```

Small tweaks can also be made in the editor. To change a level, select the actor in the Outliner folder **Audio** and edit *Sound > Volume Multiplier*. To change a radius, edit the shared preset under `/Game/SaskartaGaea/Audio/Attenuation`, which moves every actor that uses it. If you tune in the editor, copy the value back into `PLAN`, so the simulation stays true.

## Rules every actor follows

- **Class:** `AmbientSound`, with auto-activate on (the default).
- **Label and folder:** the label says zone and sound (`AMB_Z1_ValleyWind`, `GEI_B09_WorksHigh`). All actors are in the Outliner folder **Audio**.
- **Always loaded:** *Is Spatially Loaded* is **off** on every actor, so World Partition streaming never drops a bed while the player is inside its radius.
- **Height:** Z is the road height from the profile, plus 3 m for 2D emitters and 2.5 m for spatial ones. The landscape was not loaded to place them.
- **Level mapping:** the mix doc's "0 dB" (the zone's main bed) is **-15 dB** Volume Multiplier (`MASTER_DB`). Every other bed and layer keeps its doc offset from that. At the boot point (spline point 54, road 0 m) the bed sum is -16 dB, and nothing else is audible there.
- **Geiger volumes:** these are absolute values, not offset from the bed.

## Attenuation presets (`/Game/SaskartaGaea/Audio/Attenuation`)

"Radius" is the sphere's inner radius (full volume) and "falloff" is the distance over which it fades to silence. An actor's audible reach is radius + falloff.

| Preset | Spatialised | Radius | Falloff | Curve | Other | Used by |
|---|---|---|---|---|---|---|
| `ATT_2D_XL` | **off** | 700 m | 400 m | Linear | reverb send off | valley bed and life, both rumbles |
| `ATT_2D_L` | **off** | 320 m | 300 m | Linear | reverb send off | basin wind, summit wind, thunder, basin Geiger, summit-approach Geiger |
| `ATT_2D_M` | **off** | 150 m | 220 m | Linear | reverb send off | ridge, mountain-foot and cloud winds, drizzle, walk Geiger |
| `ATT_2D_S` | **off** | 50 m | 120 m | Linear | reverb send off | Geiger peaks (works, cistern, hut) |
| `ATT_3D_Site` | on | 22 m | 100 m | Natural Sound, -50 dB at max | non-spatialised radius 22 → 8.8 m, stereo spread 6 m, air absorption LPF 20 kHz → 3.5 kHz | settlement creaks, infrastructure |
| `ATT_3D_Near` | on | 8 m | 60 m | Natural Sound, -50 dB at max | non-spatialised radius 8 → 3.2 m, stereo spread 4 m, air absorption LPF 20 kHz → 3.5 kHz | reeds, ruin moans, transmitter hum |

**Why linear for the 2D beds.** Two instances of one bed fade against each other in amplitude, so neighbouring zones cross-fade smoothly as the listener walks from one sphere into the next. The loops use the default *Restart* virtualisation, so overlapping instances are uncorrelated and add in power. The simulation assumes this.

## Actors (25)

The Location column is world cm. "Road m" is the metre along the road from the boot point, and "lat" is the metres right (+) or left (-) of travel.

| Label | Sound | Road m, lat | Location (x, y, z) | Attenuation: radius + falloff | Volume | Role |
|---|---|---|---|---|---|---|
| `AMB_Z1_ValleyWind` | `AMB_Valley_Wind` | 760 m, +0 m | (562588, 414291, -34122) | ATT_2D_XL: 700 m + 400 m | -15 dB (0.178) | Valley floor bed, 0-1,550 m |
| `AMB_Z2_RidgeWind` | `AMB_Valley_Wind` | 1830 m, +0 m | (507654, 328985, -31406) | ATT_2D_M: 150 m + 220 m | -12 dB (0.251) | Ridge: Valley_Wind +3 dB, crest 1,980 m |
| `AMB_Z3_BasinWind` | `AMB_Valley_Wind` | 2420 m, +0 m | (456033, 333921, -39510) | ATT_2D_L: 320 m + 300 m | -19 dB (0.112) | Descent and basin floor: Valley_Wind -3/-4 dB |
| `AMB_Z4_FootWindLow` | `AMB_Valley_Wind` | 3050 m, +0 m | (403461, 361338, -38340) | ATT_2D_M: 150 m + 220 m | -19 dB (0.112) | Mountain foot, lower half (cistern): wind still low |
| `AMB_Z4_FootWindHigh` | `AMB_Valley_Wind` | 3300 m, +0 m | (383615, 375050, -33060) | ATT_2D_M: 150 m + 220 m | -15 dB (0.178) | Mountain foot, upper half: "wind rising" to 0 dB |
| `AMB_Z5_CloudWind` | `AMB_Cloud_Wind` | 3850 m, +0 m | (344218, 403411, -10480) | ATT_2D_M: 150 m + 220 m | -15 dB (0.178) | Switchbacks in the cloud, 3,540-4,250 m |
| `AMB_Z6_SummitWind` | `AMB_Summit_Wind` | 4680 m, +0 m | (308271, 454777, 11186) | ATT_2D_L: 320 m + 300 m | -15 dB (0.178) | Above the cloud, the shoulder and the human walk |
| `AMB_Z1_ValleyLife` | `AMB_Valley_Life` | 650 m, +0 m | (570462, 421972, -34930) | ATT_2D_XL: 700 m + 400 m | -18 dB (0.126) | Life layer, fades out by ~1,700 m |
| `AMB_Z3_BasinRumble` | `AMB_Mountain_Rumble` | 2100 m, +0 m | (482970, 320550, -33580) | ATT_2D_XL: 700 m + 400 m | -32 dB (0.025) | Mountain rumble: ridge -16, descent and basin -18 |
| `AMB_Z5_MountainRumble` | `AMB_Mountain_Rumble` | 3600 m, +0 m | (356602, 384528, -25780) | ATT_2D_XL: 700 m + 400 m | -29 dB (0.035) | Mountain foot to the cloud top |
| `AMB_Z4_ThunderFar` | `AMB_Thunder_Far_Loop` | 2850 m, +0 m | (417705, 347298, -40160) | ATT_2D_L: 320 m + 300 m | -26 dB (0.050) | Far dry thunder, basin and mountain foot |
| `AMB_Z5_CloudDrizzle` | `AMB_Cloud_Drizzle` | 3850 m, +0 m | (344218, 403411, -10480) | ATT_2D_M: 150 m + 220 m | -21 dB (0.089) | Drizzle inside the cloud |
| `AMB_V4_ReedMarsh` | `AMB_Reed_Marsh` | 1220 m, +0 m | (544614, 374336, -36116) | ATT_3D_Near: 8 m + 60 m | -19 dB (0.112) | Waiting Water dry channel, which crosses under the road. No water sound |
| `AMB_V5_SettlementCreaks` | `AMB_Settlement_Creaks` | 2560 m, -18 m | (442856, 338350, -40644) | ATT_3D_Site: 22 m + 100 m | -17 dB (0.141) | Numbered Stop: V5 gutted buildings, left side |
| `AMB_V5_WorksInfra` | `AMB_Infrastructure` | 2600 m, +30 m | (438856, 333550, -41340) | ATT_3D_Site: 22 m + 100 m | -13 dB (0.224) | The works by the platform, right of the road |
| `AMB_V5_RuinsMoan` | `AMB_Ruins_Wind_Moan` | 2540 m, +10 m | (444856, 335550, -40428) | ATT_3D_Near: 8 m + 60 m | -23 dB (0.071) | Broken arch or gutted building |
| `AMB_V6_CisternInfra` | `AMB_Infrastructure` | 3050 m, +15 m | (402408, 360270, -38390) | ATT_3D_Site: 22 m + 100 m | -19 dB (0.112) | Dry cistern, right 15 m (6 dB under the works) |
| `AMB_V6_CisternMoan` | `AMB_Ruins_Wind_Moan` | 3060 m, +22 m | (401204, 360473, -38364) | ATT_3D_Near: 8 m + 60 m | -25 dB (0.056) | Cistern walls |
| `AMB_V10_HutMoan` | `AMB_Ruins_Wind_Moan` | 4990 m, +8 m | (297289, 481122, 11398) | ATT_3D_Near: 8 m + 60 m | -27 dB (0.045) | Relay hut walls |
| `AMB_V10_TransmitterHum` | `AMB_Transmitter_Electrical` | 4995 m, +8 m | (297236, 481585, 11309) | ATT_3D_Near: 8 m + 60 m | -15 dB (0.178) | Relay hut and mast foot |
| `GEI_B07_BasinMedium` | `SFX_Geiger_Medium` | 2600 m, +0 m | (438856, 336550, -41290) | ATT_2D_L: 320 m + 300 m | -12 dB (0.251) | B07 ramp from ~2,050 m, and the basin tail to ~3,100 m |
| `GEI_B09_WorksHigh` | `SFX_Geiger_High` | 2585 m, +0 m | (440356, 336550, -41029) | ATT_2D_S: 50 m + 120 m | -14 dB (0.200) | Peak 10 cps at the platform and works |
| `GEI_B10_CisternMedium` | `SFX_Geiger_Medium` | 3050 m, +15 m | (402408, 360270, -38340) | ATT_2D_S: 50 m + 120 m | -14 dB (0.200) | Bump to ~4 cps within 60 m of the cistern |
| `GEI_B18_SummitMedium` | `SFX_Geiger_Medium` | 4850 m, +0 m | (304036, 469744, 12020) | ATT_2D_M: 150 m + 220 m | -14 dB (0.200) | Summit approach 2-4 cps, the collapse and the walk |
| `GEI_B23_HutHigh` | `SFX_Geiger_High` | 5000 m, +0 m | (297978, 482138, 11270) | ATT_2D_S: 50 m + 120 m | -22 dB (0.079) | Hut: 8 cps (High at -8 dB over Medium) |

## Simulated levels along the road

The simulation is `place_ambience.py`. Values are Volume Multiplier dB after attenuation, at a listener 3 m above the road. The AMBIENCE_MIX target is in brackets, and "-" means silent. "Beds" is the power sum of the three main wind beds.

| Road m | Beds | Valley_Wind | Cloud_Wind | Summit_Wind | Valley_Life | Rumble | Thunder | Drizzle | Geiger M | Geiger H |
|---|---|---|---|---|---|---|---|---|---|---|
| 0 | -16 | -16 (-15) | - (-) | - (-) | -18 (-18) | - (-35) | - (-) | - (-) | - | - |
| 500 | -15 | -15 (-15) | - (-) | - (-) | -18 (-18) | - (-35) | - (-) | - (-) | - | - |
| 1000 | -15 | -15 (-15) | - (-) | - (-) | -18 (-18) | -44 (-35) | - (-) | - (-) | - | - |
| 1220 | -15 | -15 (-15) | - (-) | - (-) | -18 (-18) | -35 (-35) | - (-) | - (-) | - | - |
| 1500 | -15 | -15 (-15) | - (-) | - (-) | -21 (-18) | -32 (-35) | - (-) | - (-) | - | - |
| 1600 | -14 | -14 (-12) | - (-) | - (-) | -25 (fading) | -32 (-31) | - (-) | - (-) | - | - |
| 1750 | -12 | -12 (-12) | - (-) | - (-) | -38 (-) | -32 (-31) | - (-) | - (-) | - | - |
| 2000 | -12 | -12 (-13) | - (-) | - (-) | - (-) | -32 (-31) | - (-) | - (-) | -28 | - |
| 2100 | -16 | -16 (-18) | - (-) | - (-) | - (-) | -32 (-33) | - (-) | - (-) | -18 | - |
| 2250 | -19 | -19 (-18) | - (-) | - (-) | - (-) | -32 (-33) | -41 (-27) | - (-) | -12 | - |
| 2400 | -19 | -19 (-18) | - (-) | - (-) | - (-) | -32 (-33) | -30 (-27) | - (-) | -12 | - |
| 2560 | -19 | -19 (-19) | - (-) | - (-) | - (-) | -31 (-33) | -26 (-25) | - (-) | -12 | -14 |
| 2750 | -19 | -19 (-19) | - (-) | - (-) | - (-) | -29 (-33) | -26 (-25) | - (-) | -12 | -35 |
| 2900 | -18 | -18 (-18) | - (-) | - (-) | - (-) | -28 (-32) | -26 (-27) | - (-) | -12 | - |
| 3050 | -16 | -16 (-18) | - (-) | - (-) | - (-) | -28 (-32) | -26 (-27) | - (-) | -12 | - |
| 3200 | -14 | -14 (-17) | - (-) | - (-) | - (-) | -29 (-31) | -27 (-27) | - (-) | -27 | - |
| 3400 | -15 | -15 (-16) | - (-) | - (-) | - (-) | -29 (-30) | -36 (-27) | - (-) | - | - |
| 3500 | -17 | -17 (fading) | - (-) | - (-) | - (-) | -29 (-29) | - (fading) | - (-) | - | - |
| 3600 | -20 | -24 (-) | -22 (-15) | - (-) | - (-) | -29 (-29) | - (-) | -28 (-21) | - | - |
| 3750 | -15 | - (-) | -15 (-15) | - (-) | - (-) | -29 (-29) | - (-) | -21 (-21) | - | - |
| 4000 | -15 | - (-) | -15 (-15) | - (-) | - (-) | -29 (-29) | - (-) | -21 (-21) | - | - |
| 4200 | -16 | - (-) | -19 (-15) | -20 (-) | - (-) | -29 (-29) | - (-) | -25 (-21) | - | - |
| 4300 | -16 | - (-) | -27 (fading) | -16 (rising) | - (-) | -29 (-30) | - (-) | -33 (-) | - | - |
| 4460 | -15 | - (-) | - (-) | -15 (-15) | - (-) | -30 (-35) | - (-) | - (-) | -34 | - |
| 4600 | -15 | - (-) | - (-) | -15 (-15) | - (-) | -33 (-35) | - (-) | - (-) | -18 | - |
| 4790 | -15 | - (-) | - (-) | -15 (-15) | - (-) | -42 (-35) | - (-) | - (-) | -14 | - |
| 4900 | -15 | - (-) | - (-) | -15 (-18) | - (-) | - (-35) | - (-) | - (-) | -14 | -26 |
| 5000 | -15 | - (-) | - (-) | -15 (-18) | - (-) | - (-35) | - (-) | - (-) | -14 | -22 |

### Where it departs from AMBIENCE_MIX, and why

- **Zone cross-fades are by distance, not by road metre.** They run over about 100-250 m instead of the doc's 60-80 m. The switchbacks stack the cloud directly above the mountain foot, so a sphere cannot draw an exact line there. A brief dip to -20 dB at about 3,600 m, where the road pitches into the cloud, is the only gap of more than 3 dB in the bed sum.
- **Mountain foot rises early.** The rise reaches -14 dB at 3,200 m instead of reaching 0 dB at 3,490. Moving `AMB_Z4_FootWindHigh` 50-100 m up-road would delay it.
- **Thunder fades early.** It comes in at 2,250-2,400 m instead of 2,150, and it fades from 3,300 instead of 3,490.
- **Rumble in the valley.** The -20 dB (doc) valley rumble is not placed: at -35 dB it would be inaudible anyway. The rumble is gone by the 4,790 black, as the doc wants ("everything else is cut").
- **The human walk.** `Summit_Wind` stays at 0 dB (doc) through the walk instead of -3. It would take a separate instance, and the budget was 25 actors. Lower the walk with a third instance if the ending feels too windy.
- **Not placed: the Valley_Life duck** to -9 dB at the Waiting Water. It needs a Sound Class mix or the story director.
- **Not placed: one-shots.** Thunder, ravens, metal groans, gusts and rockfall need random timers. They should become a `BP_AmbientOneShotEmitter`, see "Placing the spatial layers with PCG" in AMBIENCE_MIX.md.
- **Reeds.** One `AMB_Reed_Marsh` sits at the channel crossing, instead of the doc's 2-4 along the channel. Two identical loops started together would play in phase.

## Sites are not built yet

The V4, V5, V6 and V10 set dressing (channel, gutted buildings, works, cistern, hut) is not in the level yet; only the 29 always-loaded system actors are. So the spatial loops and Geiger peaks use the storyline coordinates and offsets:
- V5: both sides at 2,540-2,620 m
- V6: cistern 15 m right at 3,050 m
- V10: hut 8 m off the road end

When `place_story_sites.py` lands, move each `AMB_V*` actor onto its structure: the creaks to the centre of the V5 buildings near the dead pulley, the works loop inside the works, and the moan into the chosen gutted building or the arch.

## With PCG?

The zone beds should not be PCG. They are few and large, they must be always loaded, and their cross-fades are tuned against the road here.

PCG fits the spatial site loops once the ruins exist. Sample the ruin meshes by tag, prune to one emitter per structure, and spawn `AMB_Ruins_Wind_Moan` there. PCG also fits the one-shot emitters, placed by a road-spline sampler at a 150-600 m lateral offset. AMBIENCE_MIX.md has the graph design.

Keep emitters out of the near grass graph (`PCG_Saskarta_NearGPUGrass`). It regenerates as the player moves, so it would keep creating and destroying audio actors.

A PCG spawner's cull distance of 0 means infinite (see the project memory). Let the attenuation handle distance instead.

## Level of the files underneath

Beds peak at -14 dBFS and spot loops at -12 dBFS, and their RMS values differ. The AMBIENCE_MIX base volumes already correct for that, so equal dB here means roughly equal loudness. The Geiger loops are the synthesised ones, all looping; nothing else in the project plays them yet. No Blueprint references the beds or Geiger loops (checked), so these actors are the only source and nothing doubles up.
