# Reported scenes V13: root execution packet

Prepared offline on 2026-10-01. **No editor call, Content write, build, test, gameplay, screenshot or save was performed.** Generated scripts require stopped PIE in `Saskarta_WP`. Root is the sole operator. No all-map loading.

## First next action after PIE ends

Read the file below and send its complete text to native Hayba `execute_python_code`. Save the native response as an envelope containing `script`, the script's SHA-256, `status: "ok"`, and untruncated `output` in the owned V13 Saved directory.

`Saved/Verification/reported_scenes_v13/discovery_v1/R03_Verge3300_127_125/00_descriptors.py`

This is the closest authored cohort: five bag placements and a cart, 9.7 m from the supplied live carrier position. Source placement coordinates only select descriptor queries. They never set a repair height or stand in for current actor identity. The manifest orders R03, L10, S18, S19, S14, S15, L06, then S11. Its 21 queries cover 334 relevant source candidates; actual installed counts remain unknown.

## Root commands after each actual receipt

Run these offline commands from `D:\UnrealEngine\saskartarad`. Replace the bracketed GUID/path values with fields from the actual receipt; these are required inputs, not invented identities.

```powershell
python -B Tools/World/ReportedScenesV13/prepare.py bind --receipt Saved/Verification/reported_scenes_v13/readbacks/R03_descriptors.json --guid <actual-actor-guid> --out Saved/Verification/reported_scenes_v13/R03_bound_v1
python -B Tools/World/ReportedScenesV13/prepare.py measure --receipt Saved/Verification/reported_scenes_v13/readbacks/R03_catalog.json --out Saved/Verification/reported_scenes_v13/R03_contacts_v1
python -B Tools/World/ReportedScenesV13/prepare.py fix --catalog Saved/Verification/reported_scenes_v13/readbacks/R03_catalog.json --contact <actual-contact-receipt-for-each-instance> --out Saved/Verification/reported_scenes_v13/R03_fix_v1
```

1. Execute generated `10_load_exact_guids.py`. It loads at most two exact source actors and two exact Landscape proxies. Root must keep overall residency bounded and unload completed clean cohorts before proceeding. HLODs are never loaded as support.
2. Execute the separate `20_catalog_*.py` calls after loading has completed. They pin every mesh component and every actual instance, not the first eight. A component with more than 128 instances stops for an explicit split instead of truncating.
3. Execute each `30_contact_*.py` separately. Each call transforms actual RenderLOD0 vertices into world space and selects the lowest vertex in each occupied 3 by 3 XY footprint bin. It records the first real mesh support and continues to real Landscape, recording HLOD occluders. Limit: 20,000 render vertices, 96 rays, six occlusion layers, cooperative 3.5 seconds. Missing support aborts; no heightmap/source-Z fallback.
4. Root reviews contact points in Lit. A complete bag/rock survey with every actual contact more than 5 cm above Landscape can generate a Z-only correction. A stack/platform contact refuses automatic lowering. A slope with one touching foot also refuses lowering. Rotation, XY, scale, materials and unaffected instance poses remain pinned. A render-vertex survey does not include material WPO or prove every triangle touches terrain.
5. `fix` requires **all actual instance contact receipts**, backs up the exact actor package, and limits a packet to 16 contacts (96 worst-case rays), a 200 cm default drop and 1 cm sink. Larger hosts need explicit chunks while preserving the full-host pose pins; do not bypass the bound. Packed/attached carts and firewood are refused until root chooses actual wheel/foot support and a shared assembly shift. Never lower their bags/rails separately.
6. Execute `40_apply_z_only.py` once, then `50_verify_contacts_before_save.py`. Accept the actual Lit result before executing `60_force_save_exact_package.py`. Save uses only the exact source package and `only_dirty=False`; never SaveAll.
7. Hash the saved package. Execute `70_unload_clean_host.py`; request normal editor GC separately; execute `80_prove_old_object_absent.py`. An object still resident blocks disk proof. Execute `90_reload_exact_guid.py`, then separately `95_verify_reloaded_contacts.py`. Record a fresh Lit image and saved package SHA-256. The generated verification markers alone do not establish that root completed the ordered save/reload sequence.

## Already known identities

`L06_exact_v1` binds the real V12 descriptors to fresh V13 catalogs:

| Host | Actor GUID | Exact package suffix |
| --- | --- | --- |
| SD_L06_DescentCarts_000 | B52C4D9D499EF12F4F17D199150099FF | 0/DY/C83WMBCUUSTIXNQVHCIRXQ |
| SD_L06_DescentCarts_001 | 3D8F7B644794C9C814CE4BB3DFCC1A28 | 9/GX/T82V3MZTRR6YSB75TC8JAI |
| SD_L06_DescentCarts_002 | F5C95CA7435853F6E1C007A493CFD353 | 3/78/CZL8RYA1SC7NNBCLRJ0T1Q |

Prefix: `/Game/__ExternalActors__/level/Saskarta_WP/`. All actor paths are in that packet's manifest. Landscape GUID `B98FEA4F4863F1AEA4D50484CF04C478`, package `4/MK/VMN93GVU6OT7QGY6YQA1CZ`. L06 has no HLOD ownership receipt; new discovery must fill that evidence.

`S11_exact_v1` binds real legacy firepit `SD_S11_SignalFire_000` GUID `6EE2FB874EB2AAAC9E6DA891AFA02935`, package `0/UH/TOXUX94BEDDCVADRWGKU8G`, and nearby legacy actor `_006` GUID `367D907344226B16A3B098BBF95CE5C6`, package `B/YT/5E15KKD00ECKJ87CC1XE3P`. The latter's mesh must be read before treating it as a wall. Its manifest records two real overlapping HLOD candidates. Bounds overlap does **not** prove subactor ownership.

`SD_S13_NumberedStop_037` and `_038` are excluded throughout. Their saved V12 corrections of -124.0886 cm and approximately -119 cm must not be repeated.

## Repeated wall composition

The current L10 source contains twelve `B01_wall02` modules across a terrace and yard; S15 has twelve wall entries in `W_1`. These are source evidence of repetition, not proof the screenshot depicts those actors. S14's category `wall` includes **eight platform floor slabs and six fence modules**, so category alone is not a removal rule. Preserve platform, fence, entrance arch, door/window, stele and unique story pieces.

For a confirmed redundant ruin cluster, retain the two useful broken end/corner anchors and one distinct taller fragment; create two uneven gaps in the middle run, leaving a clear sightline and walkable negative space. Retain existing lower rubble only after grounding it. Do not add a second identical wall row. Preserve the real road corridor and landmark silhouette; this packet makes no new XY placement or guessed tilt.

After actual catalogs and Lit review, root can remove selected redundant solo wall modules from the visible composition reversibly:

```powershell
python -B Tools/World/ReportedScenesV13/wall_cleanup.py --catalog <actual-wall-catalog> --catalog <actual-retained-anchor-catalog> --hide-guid <actual-redundant-wall-guid> --reason "Retain reviewed broken corner/end anchors; two uneven middle gaps; road and landmark silhouette protected" --out Saved/Verification/reported_scenes_v13/wall_cleanup_v1
```

This packet requires exact current GUIDs, backups, a retained anchor in the same authored block and matching real wall mesh. It accepts at most three redundant modules per call, disables their visibility/game visibility/collision, preserves transforms and retained actor properties, then supplies exact package save/unload/absence/reload/readback calls. It rejects packed/attached pieces and known platform/entrance/landmark source keys. Root must review overlapping HLODs: a stale merged proxy may still show the old walls. Source package readback cannot prove the HLOD/render result. No HLOD build or ownership guess is included.

## Generator diagnosis and limits

Historical generated ISM scripts accepted first blocking collision hits, including stale HLODs; the existing inventory and measured L01 receipts prove that failure mode. Current `place_setdress.py` already uses Landscape-only ISM traces and strict complete support for solo ground-only actors. Existing generated Saved scripts remain historical. Its current ISM placement path still accepts a partial five-probe footprint because its config does not request `require_complete_support`; this is a structural gap, but this pass has no new actual bag/rock contact evidence proving that it caused the reported poses. No speculative generator edit was made.

ActorDesc provides exact GUID, package, path, class and bounds. Its queried 30 m grid is **not** a World Partition runtime cell identity. Runtime cell names and actual HLOD subactor ownership require root readback; they are explicitly unresolved. Missing current identities, terrain contacts, packed assembly decisions, HLOD ownership and fresh saved Lit evidence remain blockers. No full “no floating objects” completion is claimed.
