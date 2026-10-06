# Six-way smoke prototype

Root installed both textures and the isolated material, compiled it with zero errors, saved all three packages, and passed metadata readback. Rendered appearance and GPU cost remain unverified. Native billow integration is prepared for the next build.

## Current packet

`Saved/Verification/six_way_smoke_20261001/material_v2`

Manifest SHA256: `06dfcec3225f9ca09ba01b6725aa7af91c9b60aaa669d7cbf75336528392a208`

The original seven scripts and manifest are preserved. The first material call stopped at the unnamed Transform input after creating seven nodes. Root recovered those same nodes with the separate `21_resume_material.py`, completed all 15 expressions, then saved and read back the three assets. Do not replay the creation steps over these installed assets.

`Saved/Verification/six_way_smoke_20261001/material_v2-recovery-addendum.json` records the recovery script, five successful readbacks, three saved package hashes, and the later generator correction. Its SHA256 is `4b13d69c26efee0333d7a59b6dca5a62507c5a30e1b1e634d58b054d4a905887`; the recovery script SHA256 is `f20dcb7973b543fc0ec627fcfc163c61cad059422f3dfb42c5ba4ce3b07f616b`.

The future generator uses the observed empty Transform input name and now targets `material_v3`, which has not been emitted. Its SHA256 is `c98ae3410d9b9470210433832c8ee0302246678f30343abc83bb7adffd702240`. The v2 manifest's old generator fingerprint is historical and its additional recovery script is intentional. Do not run the current generator's `check` against v2. Original `material_v1` is also preserved as superseded preparation evidence.

Root must own an idle editor lease and execute each file separately under the existing PIE/native-fault/deadline guards. The material compile can take longer than metadata reads; keep it as one isolated bounded operation, inspect compile errors, and stop on a fault. No editor call is made by the preparation utility.

Preserved original installation order (already completed through recovery):

1. `10_import_P.py` and `11_import_N.py`: import new assets with replacement disabled; set linear RGBA/BC7/max2048. Source originals stay 4096² and unchanged.
2. `20_material.py`: create `M_DustSixWay` once in `/Game/SaskartaGaea/Look/Storm/SixWayPrototypeV1`, connect 15 expressions, and require zero compile errors.
3. `90_save.py`, `91_save.py`, `92_save.py`: one package per save; each strictly requires True.
4. `99_read.py`: exact texture settings and material metadata. This does not establish visual acceptance.

The creation steps deliberately stop if a destination asset already exists. If an earlier attempt partially succeeds, inspect and record it; do not overwrite its evidence or replay the entire creation packet blindly. No changes are required to `SaskartaDustFront` for material preparation.

## Material behavior and acceptance

The two samples retain all six directional responses. Sky-atmosphere sun direction is transformed from world space into the actual sprite tangent basis. P weights right/top/back, N weights left/bottom/front. Emissive combines a modest dust tint/ambient floor and directional response; P alpha, particle lifetime alpha and Opacity feed a 200 cm DepthFade.

`CloudVariant` selects one of eight static shapes. It does not pretend that these files are a verified animation sequence. Default is tile0; there is no Time node or additional texture sampling. Imported textures remain linear data, including the original `_N` source. The master is unlit translucent, two-sided and explicitly compiled for Niagara sprites.

Before integration, root must inspect alpha sense, the 2×4 tile orientation, sun signs under six cardinal light directions, camera orbit, and a rotated sprite. A 2×4 atlas means each tile has a 2:1 pixel aspect, so shape-preserving sprites should use width twice height unless the visual inspection establishes a different authoring convention. Mip boundaries/overdraw need rendered checks. No visual or GPU-cost claim has been made.

## Current native integration: ten front-anchored billows

Root chose a bounded native helper after the renderer inventory below. No Niagara duplication or Hayba plugin extension is required. Native source is prepared for root's next build; runtime appearance has not been accepted.

`USaskartaDustBillows` is owned by `ASaskartaDustFront`. It asynchronously requests Engine/BasicShapes/Plane and this packet's exact material, polls the retained load handle at the front's existing 10 Hz cadence, and registers ten hidden components only after the mesh, Surface/Translucent material, Opacity/CloudVariant parameters and shader compilation checks pass. Missing or failed assets leave the original eight fog lobes as the effect. EndPlay cancels pending load work and destroys the components; no asynchronous completion callback can recreate a plane after rescue.

The ten fixed seeded centres are 34–118 metres behind the supplied moving front, spread laterally and in height. They drift slowly through independent 13–18.7 second life cycles and fade before each reset. All quad bounding spheres remain behind the front. Their world positions never depend on the camera; only normal/tangent orientation and distance fade do. Each plane uses one MID, one fixed atlas variant and the existing Opacity scalar. Engine non-particle material parameters initialize Particle.Color to one, so the v2 shader requires no modification. Width:height stays 2:1. Maximum opacity is .39; near fade is 8–18 metres, far fade 320–400 metres, with a 400 metre component draw limit. Collision, overlaps, navigation, shadows, volumetric translucent shadows, ray tracing and decals are disabled. No independent actor/component tick, Niagara simulation, sync load or dynamic component allocation is introduced after initial preparation.

Focused offline verification:

```
python Tools/Look/six_way/run_billows_smoke.py
python -m unittest discover -s Tools/Look/six_way -p test_billows_contract.py
```

The real pure header passed MSVC C++17 `/W4 /WX`: 300,010 deterministic samples, eight atlas variants, finite/bounded inputs, lifetime wrap fades, distance fades, all quads behind the front and minimum centre separation 36.7 metres. Five source contracts passed. The material_v2 manifest still hashes to `06dfcec3225f9ca09ba01b6725aa7af91c9b60aaa669d7cbf75336528392a208`. Its original source check passed before the later demonstrated generator fix and remains historical evidence. A read-only peer review found no concrete UE API/lifecycle blocker. These checks do not compile the Unreal helper or measure GPU cost.

Exact source hashes and captured verification outputs are preserved in `Saved/Verification/six_way_smoke_20261001/native_billows_v1/preparation-audit.json` (SHA256 `eb9df2df5d1b517f37c54474133fa62fb6dbff0bcdafa9d327e69e090d7a938f`). This source receipt is separate from the unchanged asset preparation manifest.

Root acceptance after native rebuild and material compile/readback:

1. Inspect the actual Engine Plane corner UVs and a rendered tile. `MakeFromZX(ToView, CameraRight)` intentionally uses +Z as the normal and +X as the right tangent; local +Y points camera-down. The Plane UV-V orientation decides image uprightness. Do not flip a shader/basis sign speculatively.
2. Check the six cardinal light responses and one camera orbit. Preserve a continuous dust silhouette with the eight fog lobes; inspect atlas seams, depth fade and swirl rather than accepting metadata alone.
3. Inspect the actual advancing front during CIN04 and pursuit: no camera-centred translation, no giant wall/shell, no large near-camera card, and no material fallback flash. Assets missing or compiling must show fog alone.
4. Pause/resume, escape/rescue and start a second chase. No additional planes should accumulate; EndPlay should leave none.
5. Compare matched rendered/GPU captures against fog alone. The native update/component budget is fixed; translucent overdraw still needs measurement.

## Preserved Niagara inventory history (superseded integration route)

`read_niagara_inventory.py` is a read-only bounded probe for three existing candidates. It prints the reflected emitter version, CPU/GPU target, local-space flag, renderer class/material/user binding, atlas size, facing and alignment. It does not spawn, activate, advance, duplicate, edit or save anything. It fails at the first unavailable reflected field so root can correct the probe using observed UE output.

The installed engine exposes `NiagaraSystem.EmitterHandles`, `FNiagaraEmitterHandle.VersionedInstance`, `FVersionedNiagaraEmitter.Emitter`, `NiagaraEmitter.VersionData` and `FVersionedNiagaraEmitterData.RendererProperties` as reflected properties. Their source exists locally, but no lane has yet observed these candidates' contents in the editor. A fire-named system must not be assumed to contain smoke alone. Do not duplicate or remap one until the probe proves its composition and the renderer's user material binding is understood.

Root's first live inventory loaded RadialBurst but stopped at protected Python `emitter_handles` access, before any mutation. Preserve that failed probe and the pinned material_v2 packet unchanged. `niagara_native_probe.json` is the separate schema-supported read-only continuation: `niagara_system_inspect` for the already loaded asset, then native `object_get_property` with an explicit `EmitterHandles` name. The native implementation in `HaybaMCPAssetHandler.cpp` uses `FProperty::ExportText_InContainer` and only filters CPF_Edit when no explicit names are given, so this route can expose the reflected non-editable field. Its response is Unreal ExportText; follow exact observed emitter/renderer subobject paths, never generated guesses. No continuation request has been executed by this preparation lane.

The root then established that this editor's native capability set has no Niagara handler despite the wrapper catalogue advertising it: `niagara_system_inspect` returns Unknown command. Native `object_get_property` does work, but its returned EmitterHandles text was truncated at 512 characters; it exposed `RadialBurst.RadialBurst:RIbbonTrailFollower_14`, insufficient for selecting a sprite emitter. Do not repeat the unsupported command. The next separate packet, produced offline by `prepare_renderer_inventory.py`, is `Saved/Verification/six_way_smoke_20261001/renderer_inventory_v1`: three independent load-only scripts, each using `ObjectIterator(load_class(...))` and the exact loaded asset namespace to print owned emitter and sprite-renderer paths as primitive JSON. They read no protected properties. Run one at a time, preserve each response, and use the returned exact renderer paths for small native property reads. An empty sprite list is meaningful and is not permission to guess a renderer or edit another system.

All three path probes subsequently passed live. Their outputs are in `Saved/Verification/playtest_feedback_20261001/{00_RadialBurst,01_MinimalLightweight,02_FireSmallSmoke}.readback.txt`. RadialBurst includes ribbon leader/follower emitters and is not a smoke-only system. FireSmallSmoke contains ashes, two flames, heat, lights, smoke and sparkles, including inherited emitter copies. It must not be deployed wholesale. `prepare_renderer_properties.py` pins those observed outputs and prepares `renderer_properties_v1`: three native `object_get_property` requests for the exact smoke-instance renderer, its parent copy, and MinimalLightweight's observed renderer. Each reads 14 short material, facing, atlas, sorting and culling fields; no binding is changed. Require all requested names and no truncated values. These reads still do not establish which emitter version is active, spawn rates/lifetime, or CPU/GPU cost; those remain integration prerequisites.

The subsequent three property reads passed with no truncation and are preserved as `Saved/Verification/playtest_feedback_20261001/{00_smoke_instance,01_smoke_parent_copy,02_minimal_lightweight}.properties.json`. Both smoke renderer objects use the same existing smoke material, Particles, Unaligned, FaceCamera, 1×1 atlas and an empty user material binding. MinimalLightweight uses DefaultSpriteMaterial, Automatic facing/alignment and 1×1. These observations still do not prove the active emitter's rate/lifetime/CPU budget. Root selected the native ten-plane helper above instead of duplicating a system. No Niagara binding has been changed. Avoid GPU warm-up or `advance_simulation`; the project recorded a native RHI fault from that path on 29 September.

Runtime deployment and visual acceptance remain root-owned. The chosen native route fixes the budget at ten visible billows while retaining the spatial fog bulk. Compare matched captures/GPU timing with fog alone before accepting the result.

Source/provenance and the existing licence-notice discrepancy are preserved in `Saved/SourceAssets/UnitySixWay/PROVENANCE.md` and `docs/performance/2026-09-30-six-way-smoke-feasibility.md`.
