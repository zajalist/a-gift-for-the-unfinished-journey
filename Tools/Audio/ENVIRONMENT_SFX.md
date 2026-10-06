# Environment SFX

`Tools/Audio/make_env_sfx.py` synthesises 37 environment sounds offline, using numpy and scipy with fixed seeds. It writes them to `Saved/GameAudio/Environment/` together with `manifest.json` and a `_spectrograms.png` contact sheet. It never touches Unreal.

```
python Tools/Audio/make_env_sfx.py           # generate, check, draw the contact sheet
python Tools/Audio/make_env_sfx.py --check   # check the existing files only
```

**No music.** Everything is filtered noise, modal impacts (sums of decaying inharmonic partials), stick-slip pulse trains and granular crackle. The only pitched parts are all physically caused:

- mains hum (a 50 Hz family)
- a low pipe whistle that only sounds in gust peaks
- friction squeals
- the crow call
- 60 ms heterodyne squeaks in the dial sweep

The `--check` tonal test catches any pitch you could hear over the bed; the script docstring has its calibration.

**Formats.** All files are 48 kHz, 16-bit PCM.

- One-shots: mono, peak -3 dBFS, 5 ms fades.
- Loops: stereo with decorrelated channels, peak -12 dBFS, seamless. The render overhangs by 1.5 s and that overhang is equal-power crossfaded onto the head.

The `_01.._0N` variations differ in seed, pitch, envelope and layer mix, not just gain. Put them in one randomised Sound Cue with pitch ±3 % and volume ±2 dB.

**Attenuation.** The radius below is where the sound fades out. Use an inner radius of about 15 % of it, the natural (log) falloff, and air absorption on. Spot loops are meant to be heard only as you pass the ruin they belong to.

## Where along the road

| Stretch | Spot loops | Ruin one-shots (random interval triggers) |
|---|---|---|
| Lowland valley | Insects, ReedRustle, WaterTrickle (field ditches) | Reed_Push (foliage system), Crow_Distant, Stone_Settle, Gravel_Trickle |
| Industrial settlement | PipeWind, ClothFlutter, WaterTrickle (gutters), Drip (cellars) | SheetMetal_Bang, Chain_Rattle, Wood_Creak, Pulley_Squeak, Stone_Settle, Crow_Distant (rare) |
| Great waterworks | Drip (galleries, culverts), WaterTrickle (spillway cracks), ReedRustle (reservoir margins) | Stone_Settle, Gravel_Trickle, Chain_Rattle (sluice gear), Wood_Creak_03/04 (walkway beams) |
| Cloud band | none (the ambience bed carries it) | Cloud_Open when the cloud parts, Stone_Settle / Gravel_Trickle (rare) |
| Summit, the High Voice | none | Transmitter_PowerUp, Transmission_Beam, Transmission_Complete |
| Radio (2D, any stretch) | Radio_Static_Bed under idle radio lines | Radio_Tune_Sweep before a line |

## Spot loops

| Sound | Radius | Suits these ruins |
|---|---|---|
| `SFX_Spot_WaterTrickle_Loop` (30 s) | 12 m | Broken stone channel, cracked ceramic pipe, spillway lip, settlement gutter. Place it at the break, not the pool. |
| `SFX_Spot_Drip_Loop` (36 s) | 15 m | Cistern, culvert mouth, reservoir gallery, cellar. It has its own chamber reverb, so put it inside the enclosed space, where outdoor reverb won't double it. |
| `SFX_Spot_ClothFlutter_Loop` (28 s) | 15 m | Torn tarp on a transfer-yard frame, banner pole, abandoned camp awning. |
| `SFX_Spot_PipeWind_Loop` (32 s) | 20 m | Open end of a broken ceramic pipe run on an exposed ridge in the settlement. The low 210-260 Hz whistle only comes up in gusts. |
| `SFX_Spot_Insects_Loop` (30 s) | 10 m | Sun-warmed stone walls, dry verges in the valley. Use it sparingly, at one or two spots per stretch. |
| `SFX_Spot_ReedRustle_Loop` (30 s) | 18 m | Reed beds in valley wet ground and on the reservoir margins. Pair it with `SFX_Reed_Push` where the player can walk through. |
| `SFX_Radio_Static_Bed_Loop` (24 s) | 2D | Under idle radio chatter. It is soft AM static band-limited to about 3.2 kHz. Duck it under speech rather than stopping it. |

## One-shots

Trigger these on random 8-40 s timers from actors placed at the ruin. Never fire the same actor twice within 5 s.

| Sound | Radius | Use |
|---|---|---|
| `SFX_SheetMetal_Bang_01..03` | 35 m | A loose roof sheet slaps its frame, then chatters. Place on sheds, transfer-yard hoppers. Fire more often when the wind is gusting. |
| `SFX_Chain_Rattle_01..03` | 20 m | Chain hanging from a gantry, sluice gear or pulley tower. |
| `SFX_Wood_Creak_01..04` | 18 m | 01-02 are door creaks (hut doors, hatches); 03-04 are beam groans (pulley frames, reservoir walkways). |
| `SFX_Pulley_Squeak_01..02` | 25 m | A seized pulley wheel turning a little. 01 is a small wheel, 02 a big one. Use them on settlement pulley towers only; a squeal gets tiring if overused. |
| `SFX_Stone_Settle_01..03` | 15 m | A small stone shifts. Place on any ruined wall, road cutting or the waterworks steps. It also works as a reaction when the capsule passes close. |
| `SFX_Gravel_Trickle_01..03` | 25 m | Loose gravel runs down a slope. Place on road cuttings, spoil heaps and reservoir banks. Fire it rarely. |
| `SFX_Reed_Push_01..04` | 8 m | For the foliage-push system: fire when the player's body overlaps a tall-grass or reed instance. Speed 01 = normal, 02 = slower and fuller, 03 = quick, 04 = slow and careful (use it during the walking-aid ending). |
| `SFX_Crow_Distant_01..03` | 120 m | A distant crow-like caw. Use it in the valley and settlement, at most once a minute, and never above the clouds. |

## Radio and ending

| Sound | Radius | Use |
|---|---|---|
| `SFX_Radio_Tune_Sweep` (1.5 s) | 2D | A dial sweep through static, passing three stations. Play it before a radio line starts. |
| `SFX_Transmitter_PowerUp` (6 s) | 40 m | Seven relays close in sequence while 50 Hz hum swells in level. The pitch stays constant, so this is not a riser. It ends on sustained hum with a 0.25 s release: start `AMB_Transmitter_Electrical` under its last second. |
| `SFX_Transmission_Beam` (4 s) | 80 m | The transmission itself. It opens with a pressure thump into an airy whoosh whose band climbs about 500 Hz to 3.2 kHz, with spark crackle. |
| `SFX_Cloud_Open` (5 s) | 150 m, or 2D | The cloud parts: the low wind roar thins out, one gust passes, and thin high air is left. Cross-fade the cloud ambience bed down under it. |
| `SFX_Transmission_Complete` (3 s) | 40 m | Hum, then a heavy relay clunk at 0.75 s. The hum collapses in about 25 ms and only the room tail of the clunk remains; there is no tone or chime. Stop `AMB_Transmitter_Electrical` at 0.75 s so the silence lands. |

## Sounds to replace

Synthesis handles water, stone, metal, relays and wind well. Replace these if you can:

- **Crow_Distant** is the weakest. It is voice-like but not a bird; replace it first (Freesound CC0: `crow caw distant`, `rook call far`).
- **ClothFlutter** flaps are plausible at a distance but lack real fabric snap (`tarp flapping wind`, `flag flapping torn`).
- **Reed_Push** gives a good sense of brushing, but recorded foliage is richer. Better still, record yourself walking through tall grass with a close mic (`walking through tall grass`, `reeds rustle movement`).
- **Insects** are generic dry ticks, not a real species. Fine as texture (`grasshopper clicks`, `cicada distant sparse` if a species fits).
- **Wood_Creak** is stick-slip synthesis: convincing as beams, less so as doors (`door creak old wood`, `wooden beam creak`).
