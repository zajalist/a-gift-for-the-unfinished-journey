# Environment SFX: recorded replacements

`Tools/Audio/fetch_env_sfx.py` swaps 28 synthesized environment sounds for CC0 Freesound recordings and adds 6 new ones. It writes the files to `Saved/GameAudio/Recorded/Environment/`, along with:

- `manifest.json`, the import list
- `_analysis.json`, the measurements for every file

Import them into `/Game/SaskartaGaea/Audio/Environment`. Each replacement keeps the synth asset's exact name, so the import overwrites the asset in place and existing Sound Cues keep working.

```
python Tools/Audio/fetch_env_sfx.py                     # fetch, process, write, credit
python Tools/Audio/fetch_env_sfx.py --only SFX_Spot_Drip_Loop
python Tools/Audio/fetch_env_sfx.py --no-credit         # rebuild files without touching credits
```

**Swapping a pick.** Every pick is pinned by Freesound id and source region in `PICKS`, with three alternates. To swap one, change its `id` (and `region`) to an alternate and re-run with `--only <asset>`. The alternates are also listed in `Tools/Audio/freesound_credits.json`.

**Sounds that stay synthesized** (from `make_env_sfx.py`):

- `SFX_Radio_Static_Bed_Loop`, `SFX_Radio_Tune_Sweep`
- `SFX_Transmitter_PowerUp`, `SFX_Transmission_Beam`, `SFX_Transmission_Complete`
- `SFX_Cloud_Open`, `SFX_Crow_Distant_01..03`

Crow was not in this pass. ENVIRONMENT_SFX.md still lists it as the weakest synth sound.

**Formats.** 48 kHz, 16-bit.

- Spot loops: stereo, peak -12 dBFS, seamless. The loop is built with a 2 s equal-power crossfade, so the wrap is sample-continuous.
- One-shots: mono, peak -3 dBFS, trimmed, 5 ms fade-in. Where a region was cut while the sound was still going, the fade-out is longer (up to 0.25 s) so it does not click off.

**Processing.** The sources were only filtered where a measurement called for it:

- a high-pass for wind rumble and handling thump
- a notch at the mains frequency and its harmonics, on five files that showed a narrow mains peak: ClothFlutter, Insects, Chain_Rattle_02, Pulley_Squeak_02 and Door_Swing_Creak_02

Nothing is pitched or time-stretched.

**Levels.** All loops share the same peak level, but their loudness differs a lot: RMS runs from -50 to -30 dBFS. Set each loop's volume in its cue, using the RMS column below as a starting point. The dripping loop is sparse, so it sounds quiet at a given peak.

**Variations.** Each numbered set comes from different recordings, or from clearly separate takes or gestures in one recording, so a randomised cue does not repeat. As before, put each set in one randomised Sound Cue with pitch ±3 % and volume ±2 dB.

## Spot loops

Attenuation, as in ENVIRONMENT_SFX.md: the fade-out radius below, an inner radius of about 15 % of it, natural (log) falloff, and air absorption on.

| Asset | Recording | Len | RMS | Radius | Where it goes |
|---|---|---|---|---|---|
| `SFX_Spot_WaterTrickle_Loop` | Thin streams falling from two pipes onto stone (UK) | 30 s | -46 | 12 m | At the break in a stone channel, ceramic pipe, spillway lip or gutter; not at the pool. Valley ditches, settlement gutters, waterworks cracks. |
| `SFX_Spot_Drip_Loop` | Drops in a small ice cave, natural reverb (Russia) | 36 s | -50 | 15 m | Inside an enclosed space: cistern, culvert mouth, reservoir gallery, cellar. The reverb is baked in, so keep it out of outdoor reverb. |
| `SFX_Spot_ClothFlutter_Loop` | Light tent fabric flapping in heavy wind | 28 s | -45 | 15 m | Torn tarp on a transfer-yard frame, camp awning, a shelter left behind. |
| `SFX_Spot_Insects_Loop` | Grasshoppers and small insects, sunny meadow | 27 s | -32 | 10 m | Sun-warmed stone walls and dry verges in the valley. Use one or two per stretch, and never above the ridge. |
| `SFX_Spot_ReedRustle_Loop` | Wind through a reed bed, faint shore wash under it (Baltic) | 30 s | -35 | 18 m | Reed beds in valley wet ground and on the reservoir margins. Pair it with Reed_Push where the carrier can walk through. |
| `SFX_Spot_PipeWind_Loop` | Wind whistling through a pipe, gusting, faint wood creak (Patagonia) | 32 s | -31 | 20 m | The open end of a broken pipe run on an exposed ridge or in the settlement. The whistle is the pipe's own resonance, a physically motivated tone. |
| `SFX_Spot_Flag_Rope_Loop` **new** | An empty flagpole in wind: halyard and clasp knocking the mast | 30 s | -39 | 20 m | Bare poles at the settlement, the transfer yard, and the summit transmitter compound. |
| `SFX_Spot_Stream_Loop` **new** | A small stream running over stones (Sweden) | 32 s | -41 | 25 m | Mountain-foot and switchback gullies, and any culvert outfall on the climb. Space emitters about 30 m apart along a stream so two are always audible and the loop does not stand out. |

## One-shots

Fire these from actors placed at the ruin, on random 8-40 s timers. Never fire the same actor twice within 5 s.

| Asset | Recording | Radius | Use |
|---|---|---|---|
| `SFX_SheetMetal_Bang_01..03` | 01: a rusted tin plate knocked, then rattling. 02 and 03: corrugated iron shaken against its frame (two separate gestures). | 35 m | Loose roof sheets on sheds and transfer-yard hoppers. Fire more often while the wind gusts. |
| `SFX_Chain_Rattle_01..03` | 01: a thick chain against metal. 02: a light chain. 03: a chain hanging from a fence, clanking in wind. | 20 m | Chains on gantries, sluice gear and pulley towers. |
| `SFX_Wood_Creak_01..04` | 01-02: wooden door creaks. 03: a deep timber groan. 04: a mast-like timber creak. | 18 m | 01-02 on hut doors and hatches. 03-04 on pulley frames and reservoir walkways. |
| `SFX_Pulley_Squeak_01..02` | 01: a small rusty wheel turning a little. 02: a big wooden pulley creaking round. | 25 m | Settlement pulley towers only. Keep them rare. |
| `SFX_Stone_Settle_01..03` | 01-02: a small rock tumbling a step (two separate takes). 03: loose stones shifting in an old wall. | 15 m | Ruined walls, road cuttings, the waterworks steps. Also usable as a reaction when the capsule passes close. |
| `SFX_Gravel_Trickle_01..03` | 01: a real small rockslide on a mountain face. 02-03: small gravel and dirt debris falling. | 25 m | Road cuttings, spoil heaps, reservoir banks, and the scree on the switchback climb. Fire rarely. 01 is the biggest; use it on the climb. |
| `SFX_Reed_Push_01..04` | 01: normal pace. 02: slower and fuller. 03: a quick pass. 04: slow and careful. 01 and 03 are separate passes through high grass; 02 and 04 are separate stretches of a slow walk through tall dry grass. | 8 m | The carrier pushing through reeds or tall grass (see the PCG section). Use 04 for the walking-aid ending. |
| `SFX_Door_Swing_Creak_01..02` **new** | 01: an old wooden door swinging slowly. 02: a heavy door groaning through a long swing. | 18 m | Abandoned hut and pump-house doors left ajar. Trigger on wind gusts, not on a timer alone. |
| `SFX_Glass_Shard_Settle_01..02` **new** | 01: small glass plates clinking as they shift. 02: broken shards sliding. | 8 m | Broken windows in the settlement and the transmitter hut. Fire very rarely; it works best as a reaction when the carrier passes. |

## Placing them with PCG

This is a proposal only; no graph has been changed. The existing PCG graphs are described in `docs/pcg-foliage-pipeline.md`. PCG can place the loop emitters, but not the one-shot triggers themselves.

- **Spot-loop and one-shot emitters.** The ruin pieces (fence and beam ruins, barrels) come from `PCG_Saskarta_RocksDebris`, which is partitioned on a 256 m grid and generated on demand.
  - Add a branch that filters those points by mesh, then prunes them to one point per ruin cluster, using Self Pruning at a radius about the size of the sound's attenuation radius.
  - Spawn a small emitter actor with **Spawn Actor**. A mesh spawner makes ISM instances, and those cannot carry an audio component.
  - The actor holds the looping AudioComponent, or the random-timer logic for one-shots.
  - Keep emitters out of `PCG_Saskarta_GrassGPU`. That graph is generated at runtime and rebuilds cells as the player moves, so it would keep creating and destroying audio actors.
- **ReedRustle and Insects** can be placed the same way, from the reed and verge masks the grass graph already samples (`T_Gaea_Shrubs`), in a separate on-demand graph with heavy pruning. Keep it to roughly one emitter per 40-60 m of reed bed.
- **Reed_Push.** The reeds are runtime PCG instances with no actors to overlap, so trigger the sound from the carrier instead. The trample writer already feeds the player position to the reed material. On the gameplay side, a short downward trace (or an overlap query against the reed ISM components) while the carrier is moving can pick 01-04 from its speed, with a cooldown of about 0.4 s.
- **Stream and WaterTrickle** follow water, so place them along the stream spline with a spline sampler (about 30 m spacing), or by hand.
- **Load and CPU.** Let the emitters stream in with World Partition (spatially loaded), give every cue attenuation and *virtualize when silent*, and set a concurrency limit of about three per family, so a dense ruin cluster does not stack ten chains at once.

## Least certain picks

Nobody has listened to these files yet. Check these first:

- **SheetMetal_Bang_02 and 03.** Corrugated iron shaken on a film set: probably more rattle than wind-slap. The alternates are a metal thud (263620) and scaffold sheeting in wind (392241).
- **Chain_Rattle_03.** A phone recording in Brooklyn. The chain is loud, but distant city noise may sit under it.
- **Pulley_Squeak_02.** An old optical-film transfer with film noise and 60 Hz hum. The hum is filtered, but a narrow 60 Hz trace remains at a very low level. The alternate is a studio rope pulley (394222).
- **ReedRustle.** A Baltic shore recording, so faint wave wash is under the reeds. That suits reservoir margins; it is odd in a dry valley.
- **WaterTrickle.** Recorded on a forest path. The level is steady and there are no spikes, but walkers or dogs could not be ruled out without listening.
- **Drip.** The cave drops are uneven, and a few land hard. The window was chosen to avoid the loudest, but it may still sound busy.
- **Gravel_Trickle_02 and 03.** Two quiet takes normalised up to -3 dBFS; the noise floor may be audible.
- **ClothFlutter.** The source has a steady 120 Hz tone (notched), which suggests a fan or electrics near the recording.
- **Stream.** The first choice (236978) was dropped because of a 240 Hz machinery tone; the pick is 275627.
