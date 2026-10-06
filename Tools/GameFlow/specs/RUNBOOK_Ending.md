# The ending: editor runbook and PIE checklist

Task ENDING-PREP, 2026-09-28. This finishes what the ENDING lane started. The ending Blueprints are built (017afa0b); the Level Sequences, the High Voice set, the traveller placement and the story re-import are not. Everything below is prepared offline and checked, so the editor part is about 25 calls and 20–30 minutes.

**Needs a SaskartaCore build first.** The road cinematics' origin now sits at the pawn's feet, not at the spline's z (a0d81360: `FSaskartaEventLogic::RoadCineOrigin`, used by `USaskartaEventRunner::StartSequence`; source only, a copy compiles clean). The CIN_15/18/19/23 keys assume it. With older binaries CIN_15's POV eye is up to 5 m under the ground or over the carrier depending on where the beat lands (`validate-ending --origin=spline` shows it). The integration stage builds it; step 0 checks it.

**What the player gets when this is done:** the carrier collapses at 4,790 m; *Release the inner latch.*; the hatch; *Rise.*; the Keeper stands and you walk the last 222 m; *Lay your hand on the mark.*; the transmission; black; the end card (see gap 1).

Background: [`README_Ending.md`](README_Ending.md) (the chain and every hook), `docs/story/CINEMATICS.md` sections 4–8, `.superpowers/sdd/2026-09-26-saskarta-world-sprint/task-ENDING-brief.md`.

## Gaps this runbook does not close (tell the user)

1. **The end-card widget patch is prepared offline, not installed in the editor yet.** Apply step 8a before CIN_25 review. Until then CIN_25 plays black and wind, then returns to the title without the card.
2. **CIN_25 timing fixed in source (Codex recovery, 2026-09-28).** `story-events.json` now has **102.0 s** with the `CreditsRoll` cue lasting **82.0 s**, matching all 104 credit lines. The ending tests pass without xfails. Re-import the DA in step 9 to apply it to the game.
3. **The V10 hut is designed but not placed.** V10 (47b826a1, `Tools/World/story_sets/V10.json` `story_hooks`) puts the plate on the hut wall at (297413.6, 483140.8), with the StandPoint at the capsule centre facing yaw 108.7, and has its own hooks step for `BP_Saskarta_HighVoice`. Until the hut exists, `place` puts the plate on the mast's road-facing side, 130 cm above the Keeper's feet. When V10's editor steps have run, use V10's hooks for Plate and StandPoint. Don't use `place --plate-at`: its StandPoint faces the road's 83.7°, 25° off V10's plate. Then re-probe (step 6) and rerun `validate-ending`. CIN_23's insert rides the road axis 2.5 m short of whichever plate is probed. V10's `camera_plan_flag` says plan_cin24/23 assume the StandPoint is at the feet. That note is out of date: plan_cin24 subtracts `keeper_half_height_cm`, and plan_cin23 no longer uses the StandPoint.
4. **The V9 blocking volumes** (8 m either side of 4,790–5,009 m) are not scripted. The Keeper's own tether (9 m) catches him without them.

## What changed offline (why the old chunks must not be used)

- **The road frame was wrong.** `road_frame` interpolated the 50 m profile samples, which cut the corners of the spline. At 4,790 m it was 6.4 m off, and at 4,575 m the yaw was 14° off. It now walks the spline polyline, which matches all 102 samples within 5 cm.
- **The origin is the carrier's feet (runner change, C++).** The runner put the sequence origin at the spline's z. The spline is a straight chord between points ~100 m apart, and the landscape the carrier walks on lies 11.6 m below (3,101 m) to 7.4 m above it (1,809 m) along the road; inside CIN_15's window, +7.3 m at 4,533, +3.7 m at 4,555, +1.0 m at 4,575, −3.2 m at 4,607, −0.19 m at 4,790. The first ENDING-PREP pass corrected the heights only at each plan's nominal stop, so CIN_15's POV eye was 1.5 m under the ground for a stop at 4,555 and 2.8–5.4 m over the carrier's eye from 4,590; the carrier also left shot 2's frame. The runner now takes the origin's Z from the pawn (location minus collision half height), and the plans key the eye, the capsule and the Keeper over the feet. Every other road plan (CIN_06, CIN_11, the POI beats) already keyed "+Z up from the road surface", so they gain from it too (CIN_06 +0.75 m, CIN_11 +0.49 m, P04 +2.1 m of error removed).
- **`validate-ending` now checks every stop point.** For each ending cinematic the pawn can stop anywhere in a window (CIN_15: 4,520, where B15 fires, to 4,610, where the crown drops behind the shoulder; CIN_18/19: 4,790–4,796). Every metre of it, every camera and key is placed in that stop's frame and checked for ground clearance, framing and terrain lines of sight. The cameras standing on the carrier (the POVs, the capsule interior, the half-rise, the hand) must stay within 25 cm of where the plan puts them at that stop. The old window check re-projected only the crown for the POV cameras, and the terrain check tested only the nominal stop.
- **What the window found and fixed.** CIN_18 shot 3 was 70 cm over its ground and dropped to 27 cm for a stop at 4,796; CIN_19 shot 5 dropped from 60 to 14 cm. Both are now 1 m up. At 4,610 a crest 32 m out grazes the line to the crown's centre by 5 cm; the top of the 8.4 m glow still shows, and the check allows the crest to reach a third of the crown's radius.
- **CIN_23 (optional, CINEPOI's plan).** It framed the High Voice StandPoint + 100 cm as "the Keeper". Since the set moved onto the mast, the StandPoint is the capsule centre (so that was 95 cm too high), and it is also ~18 m up-road of where B23 stops him. The Keeper is the pawn at the origin, so shot 1 frames (0, 0, 100) over his feet, and only at its first key (the tilt climbs the mast). The plate insert sat 90 cm back and 60 cm left of the plate and lost it for a stop 2 m on; it now looks straight up-road from 2.5 m before the plate, so a later stop only brings it closer. It is in `validate-ending` as an optional row.
- **CIN_15 shot 2 was behind a hill.** The road crests behind the carrier: from the shot list's "below" position, the crest hides the carrier by 3.7 m. The camera is now 40 m back on an 8 m crane. It rides with the carrier's frame, so it frames the carrier the same way at every stop; its lowest clearance over the window is 5.7 m (at 4,600).
- **CIN_15's zoom stops at 45°, not 30°.** The frame turns 14° at spline point 6 (road ~4,589 m), inside the range where the queued beat lands. At 30° the crown would leave the frame on one side of that point.
- **CIN_24 shot 1 was blocked by the shoulder.** The plate sat 3° from the Keeper's right shoulder, directly behind it. The camera moved to 85 cm right of the spine. The StandPoint is now at the capsule centre (ground + 95), which is where `SnapKeeperToPlate` teleports the capsule. The old plan put it at the sunk mast base, 50 cm inside the ground.
- **The carrier's `SnapToRoad` now uses the runner's rule** (the tangent at the closest key) instead of a ±3 m chord. B18 fires 1.96 m past spline point 4 (UE 221.84 m; point 4 is at 223.80 m), where the road turns 49°. The chord could turn the carrier up to ~25° away from the sequence origin, which would swing the capsule about 1 m out of the interior camera. **The carrier's scoped spec must be rebuilt** (step 2).
- **The probe chunk** no longer uses `try`. It takes the road by class: the actor tagged `Saskarta.Road` is `BP_Saskarta_RouteTrace`, which has no spline. It prints a `PROBE_JSON` line that `merge-probe` merges.
- **`capture_cin.py`** now converts road-local keys to world space. Before this, CIN_15/18/19 frames would have been captured near the map origin.
- **Brief step 6d is wrong about the road tag.** Do **not** tag the road `Saskarta.Road`: LANE5 put that tag on the RouteTrace on purpose, and the runner and the Keeper find the road by class.
- **Brief step 10's caveat is obsolete.** The runner's "no sequence, no freeze" branch is built, so a re-import no longer freezes the carrier on sequence-less cinematics.

## Tools

- `python Tools/Cinematics/build_cinematics.py validate-ending` is the gate for CIN_15/18/19/24 (CIN_23 is reported, not gating). It checks the framing at every key; the stop window (every metre: ground clearance, framing, lines of sight, and the carrier-mounted cameras staying on the carrier); and the terrain at the nominal stop. It uses the offline heightmap. `check <cin> --window` prints the per-camera worst cases. `--origin=spline` replays the old runner, which fails CIN_15, CIN_19 and CIN_23; `emit` refuses that flag.
- `python Tools/GameFlow/editor/ending_editor.py <step>` sends one `python_run` per step:
  - it checks for banned words first;
  - it refuses while PIE runs, and for 30 s after;
  - it scans the editor log after each call and **stops on any native fault**. After a fault, make no more calls: the editor needs a restart.
  - Add `--print` to see a chunk without sending it.
- `python Tools/GameFlow/editor/ending_editor.py watch OUT -- <cmd>` runs a long job under a per-second watchdog that kills it when Play starts or a fault is logged.

## Editor runbook (in order; stop at the first failed gate)

**0. Preflight (offline, 2 min).**
- **The runner build.** The editor must run a SaskartaCore built from a0d81360 ("Runner: road cinematics' origin at the pawn's feet (RoadCineOrigin)") or later. In PowerShell, `(Get-Item Plugins/SaskartaCore/Binaries/Win64/UnrealEditor-SaskartaCore.dll).LastWriteTime` must be later than `git log -1 --format=%ci a0d81360`, and the integration build must have succeeded. If not, stop: the sequences would be keyed for an origin the game doesn't use.
- The editor is up, the user is not in PIE, and no other lane is mutating it. **Ask the user not to press Play for about 25 minutes.**
- `EDITOR_GATE_MODE=file python Tools/GameFlow/editor_gate.py acquire --owner ENDING --timeout-min 45 --ttl-min 60`. Leases are only advisory: Hayba redacts the token.
- `python Tools/Cinematics/build_cinematics.py validate-ending`. **Gate:** four lines of `framing ok   window ok (...)   terrain ok` (CIN_24 shows `window -`), and `origin z: feet`.
- `python -m pytest Tools/Cinematics/tests Tools/GameFlow/tests/test_ending_editor.py -q -p no:cacheprovider`. **Gate:** all pass. If pytest cannot clean its temp folder, add `--basetemp=<a scratch dir>`.
- `git status --short Content/SaskartaGaea/Characters/Carrier Content/SaskartaGaea/Story`. Nothing from another lane may be dirty there.
- Read-only check (PowerShell): `(Get-Item Content/SaskartaGaea/Characters/Carrier/BP_Saskarta_Carrier.uasset).IsReadOnly` and the same for `Content/SaskartaGaea/Story/DA_Saskarta_Story.uasset`. If either is read-only, run `attrib -r <file>` (memory: committed-uassets-are-read-only).

**1. Survey (1 call, read-only).** Run `python Tools/GameFlow/editor/ending_editor.py survey`. Check:
- there is exactly one beacon `HighVoice`, and its `Crown` sits about 43 m over it;
- `tagged Saskarta.HighVoice` is empty (or only `HighVoice_Ending`);
- how many travellers there are (0 or 1);
- `MI exists`;
- the mesh bounds: a `SM_Cylinder` lowest z of 0 means a base pivot, otherwise `place` falls back to `Tile_10MPillar`.

**2. Rebuild the carrier's ending graphs (1 run, about 1 min).**
- `python Tools/GameFlow/gen_ending_specs.py` → `git diff --stat Tools/GameFlow/specs/BP_Saskarta_*.json Tools/GameFlow/specs/*ending*.json`. **Gate:** no change (the committed specs are current).
- `python Tools/GameFlow/editor/ending_editor.py watch Saved/Ending/bpgraph_carrier.json -- node Tools/GameFlow/bpgraph.mjs build --reset-graphs Tools/GameFlow/specs/BP_Saskarta_Carrier.ending.json`. It must run with **only** this spec: its six functions already exist, and the traveller's functions it calls are built.
- **Gate:** exit 0, compiled with 0 errors, and pass 4 finds every link.

**3. The crown material (2 calls).** `... ending_editor.py mi`, then `... ending_editor.py mi-save`.

**4. The High Voice set (3 calls and a capture).**
- `... ending_editor.py place`. Read the `ground` line. A trace should agree with the heightmap to within a few cm. If it says `grid`, the landscape there isn't loaded; the baked heightmap is exact (0.1 cm at L2's trace), so that's fine.
- `... ending_editor.py read`. **Gate:**
  - one `HighVoice_Ending`, tagged, not spatially loaded;
  - Crown uses `Sphere` with `MI_HighVoice_Glow` at scale 8.4;
  - Column is at the mast foot at scale z 0.01;
  - StandPoint is at yaw 83.7, roughly 95 cm over the ground.
- **Crown gate:** `python Tools/Look/capture_look.py road_4700 Saved/Screenshots/Ending/crown_4700.png` and `python Tools/Look/capture_look.py road_200 Saved/Screenshots/Ending/crown_boot.png --yaw -160`. The crown must read from both. The ending crown (8.4 m, `Col` 4) encloses the beacon's own crown up to about 2 km. If it reads dimmer than L2's captures, raise `Col` on the MI (not the BP's `ColRest`).
- `... ending_editor.py save`. If `place` printed `UNTAGGED <beacon>`, add `--save-beacon`.

**5. The traveller (2 calls).**
- `... ending_editor.py trav`. It is parked on the road 40 m before the collapse, behind every ending camera, with `bStartHidden` set.
- **Gate:** `travellers in level 1` (after the call). Then `... ending_editor.py trav-save`.

**6. Probe (1 call, then offline).**
- `python Tools/Cinematics/build_cinematics.py probe-ending Saved/Ending/probe_chunk.py`.
- `python Tools/GameFlow/editor/ending_editor.py run-file Saved/Ending/probe_chunk.py > Saved/Ending/probe_out.txt`. It spawns one temporary carrier far below the map and destroys it; a leftover `Tmp_ProbeCarrier` from a failed run is destroyed first.
- `python Tools/Cinematics/build_cinematics.py merge-probe Saved/Ending/probe_out.txt`. Check that the note says `PROBED <date>` and that `road_found` was true.
- `python Tools/Cinematics/build_cinematics.py validate-ending`. **Gate:** four `ok`s. If one fails, stop: the probed carrier or set differs from the plan, and the plan needs a look before anything is built.
- Commit `Tools/Cinematics/probe_ending.json` (by pathspec).

**7. Build the sequences (about 40 calls, 3 min).**
- Re-emit all five, because the probe changed the numbers: `for c in CIN_15_IN_RANGE CIN_18_COLLAPSE CIN_19_HATCH CIN_24_TRANSMISSION CIN_25_END_CARD; do rm -f Saved/Ending/$c/*.py; python Tools/Cinematics/build_cinematics.py emit $c Saved/Ending/$c/; done`.
- Then, one folder per command: `python Tools/GameFlow/editor/ending_editor.py run-dir Saved/Ending/CIN_15_IN_RANGE`, then `CIN_18_COLLAPSE`, `CIN_19_HATCH`, `CIN_24_TRANSMISSION` and `CIN_25_END_CARD`. Each runs `00`, `10_*`, `70`, `80`, `90` and `99` in order and stops at the first failure.
- **CIN_23 (optional, only if the `MarkCine` tag is on for this build):** `emit CIN_23_THE_MARK Saved/Ending/CIN_23_THE_MARK/`, then `run-dir` on it. Gate: range 0 → 12, 3 bindings, a cut track with 3 sections. Set `bCanBlend` on its cut track too (the 2 s hand-back).
- **Gate** (from each `99_read` output):
  - range `0.0 → duration`: 10, 28, 19.8, 48, 102 (CIN_25 matches the current 102 s story source);
  - one binding per camera (6 / 2 / 4 / 4 / 0), each with keys;
  - one `MovieSceneCameraCutTrack` with 6 / 2 / 4 / 4 sections;
  - a `MovieSceneFadeTrack` on CIN_19, CIN_24 and CIN_25.
- The cut track's `bCanBlend` is not Python-visible. Set it with Hayba `object_set_property` on the track path that `80_cuts` prints, for CIN_15 (the 2 s hand-back) and CIN_19 (the 2.4 s blend into the half-rise).

**8. Frames (about 25 calls, no PIE; the captures go to `Saved/Screenshots/Ending/`).** The poses come from `build_cinematics.py frames <cin>`, and `capture_cin.py` evaluates them itself:
- `python Tools/Cinematics/capture_cin.py CIN_15_IN_RANGE Saved/Screenshots/Ending 1.8 4.2 6.5 9.0`: the crown centred in the zooms; in shot 2, the carrier lower-left and the crown upper-right.
- `... CIN_18_COLLAPSE ... 1.0 5.0`: in shot 3, the carrier and the capsule in profile, the crown beyond, **no terrain or verge before the lens**. The carrier isn't there in the editor; judge the place and the crown.
- `... CIN_19_HATCH ... 1.0 8.0 14.8`: the sky through the hatch; then the road up to the crown upper-left.
- CIN_19 shot 5 with the Keeper: `ending_editor.py trav --at stand19`, then `capture_cin.py CIN_19_HATCH ... 17.0`, then **`ending_editor.py trav`** to park him again. **Do not save between these.**
- `... CIN_24_TRANSMISSION ... 2.0 9.0 20.0 40.0`:
  - S1: the plate, with the shoulder at the left;
  - S2: the mast up into the sky;
  - S3: the crown and mast above the cloud sea. **The 1.5 km camera is the likeliest to sit in cloud.** If it does, move it along the same bearing and write the new `wide24` into `probe_ending.json`, then re-emit and rebuild CIN_24.
  - S5: the valley east. The offline check puts the near slope in the lowest ~22 % of the frame, where the walking aid lies.
- After any change: re-emit and rebuild that one sequence only.

**8a. Install the scoped end-card panel and binding (Caption widget only).** With the editor gate held and PIE stopped, run these in order. The tree command adds only `EndCard` (no `--clear`); the graph command adds only three new functions (no reset of existing Caption graphs). The last command appends only `OnEndCard` to the existing delegate chain. Check the Caption package is writable first.

```powershell
node Tools/GameFlow/build_settings_ui.mjs Tools/GameFlow/specs/WBP_Saskarta_Caption.endcard.tree.json
node Tools/GameFlow/bpgraph.mjs build Tools/GameFlow/specs/WBP_Saskarta_Caption.endcard.graph.json
python Tools/GameFlow/editor/ending_editor.py run-file Tools/GameFlow/editor/caption_endcard_bind.py
```

The scoped spec reads the existing short-card cue from `story-events.json` and the 104-line roll from `CREDITS_SCREEN.md`; no wording is entered in the editor. Read back `EndCard` as initially collapsed, `OnEndCard_Event` linked to `ShowEndCard`, and a clean widget compile/save. On the current CIN_25 clock: title art at 2–10 s, three-line card at 10–17 s, roll at 17–99 s, black for the final 3 s, then Title. A skip after 3 s must open Title without a lingering card. Check one ordinary subtitle and caption afterward so the pre-existing bindings remain intact.

**Repeat-run rule:** the tree command is additive. If `EndCard` is already present in the Widget Designer, do not run that command again; use `node Tools/GameFlow/build_settings_ui.mjs Tools/GameFlow/specs/WBP_Saskarta_Caption.endcard.tree.json --slots-only` only if its canvas slot or variable flags need repair. Rebuild the three new function graphs with `node Tools/GameFlow/bpgraph.mjs build --reset-graphs Tools/GameFlow/specs/WBP_Saskarta_Caption.endcard.graph.json`; this reset does not touch any older Caption graph. The binder can be rerun and repairs an interrupted link. Skipping CIN_25 runs `OpenLevel Title` in the runner's final state, which tears down the old HUD widget; the roll timer is cleared by world teardown. Inspect the Title viewport for a lingering overlay anyway.

**9. The story asset (2 calls, after narrative review).**
- The existing source has CIN_25 at 102 s and `CreditsRoll` at 82 s. The proposed ending changes in `docs/handoffs/2026-09-28-story-discussion.md` are not canon; finish that discussion before importing story data or changing narrative-dependent staging.
- `... ending_editor.py story-import`. **Gate:** `import ok True` and 0 problems in the report.
- `... ending_editor.py story-save`. It refuses if the file is read-only.

**10. Commit and release.**
- Commit by pathspec only:
  - `Content/SaskartaGaea/GameFlow/Cinematics/LS_CIN_{15_InRange,18_Collapse,19_Hatch,24_Transmission,25_EndCard}.uasset`;
  - `Content/SaskartaGaea/Story/HighVoice/MI_HighVoice_Glow.uasset`;
  - `Content/SaskartaGaea/Characters/Carrier/BP_Saskarta_Carrier.uasset`;
  - `Content/SaskartaGaea/Story/DA_Saskarta_Story.uasset`;
  - the two external-actor packages that `save` and `trav-save` printed;
  - `Tools/Cinematics/probe_ending.json`.
- Check `git diff --cached --stat` first: the editor stages new packages itself.
- `EDITOR_GATE_MODE=file python Tools/GameFlow/editor_gate.py release --owner ENDING`. Then hand the checklist below to the user.

## PIE checklist (for the user; no agent runs this)

Open `/Game/level/Saskarta_WP`, press Play, open the debug menu (F9) and pick `B16_FAILING_STEPS`. Tick each row.

| # | Step | You should see and hear | If not, look at |
|---|---|---|---|
| 0 | *(optional, before the chain)* Pick `B14_LOOK_BACK` instead and drive on: B15 lands behind B14's radio | **CIN_15:** the POV lifts to the crown with the stepped zoom from the carrier's own eye height (**not from inside the ground and not metres above**); the long shot shows the carrier low left and the crown upper right; a 2 s blend back to the POV. The log line `cinematic CIN_15_IN_RANGE: origin (...)` gives a z that differs from its `spline z`, unless you stopped right where the landscape meets the spline. Try once more stopping early (just past 4,520) | the runner build (step 0), `LS_CIN_15_InRange` |
| 1 | Drive on | the carrier slows; `CV_FAIL_01`, then `CV_FAIL_02` | `LogSaskartaEvents` |
| 2 | **B18, the collapse** (4,790 m) | the POV lurches and glitches, then black at ~3 s; one exterior shot: the mast folds, the eyes go dark, the High Voice crown small beyond; four log lines type in the black with the voice; 8 s of wind. **The carrier sits square on the road, facing up it**, and the exterior camera sits about 1 m over the verge | `LS_CIN_18_Collapse`, `SnapToRoad`; the `cinematic CIN_18_COLLAPSE: origin` log line |
| 3 | The latch | *Release the inner latch.* The carrier cannot be driven | B18's prompt |
| 4 | **E: the hatch** | white sky fading in through the open hatch (**no capsule wall or floor filling the frame**); the half-rise view with the fallen carrier low in frame, the crown upper-left, held with no control; *Rise.* | `LS_CIN_19_Hatch`; if the lens is inside the capsule, the carrier's yaw or the ground offset is off: note the stop point |
| 5 | **Rise** | the falter; the hand on the rim; cut to the Keeper standing left of the capsule; a 1.6 s blend to over his right shoulder | `TravellerGripRim`, `TravellerStandBeside` |
| 6 | Possession | you control the Keeper; the staff sits in his right fist | `PossessTraveller` |
| 7 | **The walk** (222 m) | slow (1.1 m/s), no foot slide; the steps alternate; the staff taps every second step; the camera turns freely. Step off the road: at ~9 m you are put back, facing up-road. **Esc pauses and resumes on foot** | `StartWalk`, `CheckTether` |
| 8 | B20 / B21 / B22 | a 4 s rest; the look over the wall to the valley, 10 s, the Segalen stone readable; the handrail rest | runner |
| 9 | **B23 at the relay** | `RADIO_B23_01`, then *Lay your hand on the mark.* With `MarkCine` on, CIN_23 first: the Keeper low in frame where he stopped, the tilt up the mast, the plate insert looking up the road | runner; `LS_CIN_23_TheMark` |
| 10 | **E: the transmission** (48 s) | the Keeper at the plate on the mast (feet on the ground, not sunk or floating); his hand on the plate, the shoulder at the left of the frame; the mast from below, the crown brightening and the column rising; the extreme wide over the cloud; black, `TRANSMISSION COMPLETE`, hiss; the seated view east for 12 s (wind and the Geiger counter only); black | `LS_CIN_24_Transmission`, `HighVoice_Ending` |
| 11 | CIN_25 | black and wind; after step 8a, calligraphy at 2 s, the three-line card at 10 s, the 104-line roll at 17 s, black at 99 s, Title at 102 s. Any key skips after 3 s and leaves no card on Title | `LS_CIN_25_EndCard`, Caption `OnEndCard` |
| 12 | Replay | CIN_19 and CIN_24 skip by holding Space after one full viewing; a skip still leaves the Keeper standing and possessed | `HoldAfterSeen` |

Also watch for: the High Voice crown along the road from 4,400 m should look as it did before, a warm-white point. The ending crown encloses the beacon's own crown.

## First Light install (2026-09-29, after the hatch)

Source: `Tools/GameFlow/gen_first_light_ending.py` (the cue sheet; `--print`), `build_cinematics.py plan_cin24` (First Light, 207 s), SaskartaCore `PlayDawn`/`StopSfx` actions, `SaskartaFirstLightLogic`. One editor pass, playtest closed:
1. Build SaskartaCore; `Automation RunTests Saskarta.FirstLight` (and `Saskarta.` for regressions).
2. Look keys: in `Tools/Look/look_keys.json` rename `Above` (4,550) to `PreDawn` and set sun pitch +3.0, yaw 176.5, 0.4 lux, 9000 K, grade clear 1 (cool blue hour, no disc); rebuild with `build_look_keys_asset.py`. Measure the cloud-sea horizon pitch on bearing -3.5 from SeatCam with `render_camera` and put it in CIN_24's PlayDawn cue `pitch` (default -0.5), then rerun the generator.
3. Audio: `python Tools/Audio/mix_hut_night.py` -> import `HUT_NIGHT_A1` (spatial, inner 3 m, falloff 25 m). New SFX ids to source/import under `/Game/SaskartaGaea/Audio`: `SFX_LampClick`, `SFX_WindLift`, `SFX_LiveRoomClick`, `SFX_TapeRoom_A5`, `SFX_RelaySwitch`; `SFX_OpenChannelHiss` must loop. `eyetae_title` is `/Game/Pallbearer/UI/eyetae_title` (the runner finds sounds by name under `/Game/SaskartaGaea/Audio` only: duplicate or redirect it there).
4. Voices (placeholders until the cast records, `casting-replies.md`): `SAMYOR_B24_01..10`, `BREATH_06`, `BELOW_R01..R21` (relay filter in the mix), `SHOW_A5_TAIL_01/02` (the author), `CV_TRANSMIT_01` re-rendered as "Âlaawb. Live." -> `/Game/SaskartaGaea/Audio/Lines/<id>`.
5. `ending_editor.py lamp` (check the lantern sits on the post, not in the ground), `lamp-save`.
6. `build_cinematics.py emit CIN_24_TRANSMISSION Saved/Ending/CIN_24` and `emit CIN_25_END_CARD Saved/Ending/CIN_25`; `ending_editor.py run-dir` each (LS_CIN_24_Transmission, LS_CIN_25_EndCard).
7. `ending_editor.py story-import`, `story-save` (DA_Saskarta_Story; the report must show 0 problems).
8. Standalone playtest from CP4_HUMAN: lamp prompt, hand prompt, the hut speaker cut mid-word, the sun clearing after "Hold on.", no speaker label on Samyor, `ILAAWB · LIVE` on the replies, fade at 204 s, title track on the cut.
