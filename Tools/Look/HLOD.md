# Far terrain: the HLOD_Saskarta_Far layer and the Build HLODs steps

Spec: `docs/superpowers/specs/2026-09-26-saskarta-world-sprint-design.md`, section 6,
"The central mountain, always visible". Task L2 of the world sprint set up the layer.
**Build HLODs is the user's button. No agent builds it.**

> **2026-09-27 correction.** UE 5.8 requires every HLOD layer to be listed in a runtime
> partition's HLOD setups (World Settings > Runtime Partitions > MainPartition > HLOD Partitions).
> `HLOD_Saskarta_Far` was never listed there, so the builder reported "invalid HLOD layer" for all
> 256 landscape proxies and built 0 HLOD actors. The level now uses its registered template chain:
> the World Partition default HLOD layer is `Saskarta_WP_HLODLayer_Instanced` (spatially loaded),
> whose parent `Saskarta_WP_HLODLayer_Merged` is always loaded and keeps the far mountain drawn
> from anywhere. The `Landscape` actor's explicit layer was cleared. `HLOD_Saskarta_Far` is unused.
> The build now runs from the controller with the editor open (the builder only writes HLOD actor
> packages): `MSYS_NO_PATHCONV=1 UnrealEditor-Cmd.exe <uproject> /Game/level/Saskarta_WP
> -run=WorldPartitionBuilderCommandlet -Builder=WorldPartitionHLODsBuilder -SetupHLODs -BuildHLODs
> -AllowCommandletRendering -SCCProvider=None -DisablePlugins=HaybaMCPToolkit -unattended`.
> The open editor sees the new HLODs after the level is reopened.

## Why

World Partition streams the terrain in cells around the player. Without HLODs, terrain beyond
the loading range is not there at all. The central mountain then vanishes, or (in the editor)
renders as a floating slab over empty ground. HLODs are the always-present stand-ins for the
unloaded cells. The High Voice beacon itself is not spatially loaded, so it renders from
anywhere even without HLODs; the ground under it and the mountain behind it need this.

## What L2 set up (saved, not built)

| Item | Value |
|---|---|
| Layer asset | `/Game/SaskartaGaea/HLOD/HLOD_Saskarta_Far` |
| Layer type | **Instancing** (`HLODBuilderInstancingSettings`, engine defaults) |
| Spatially loaded | **No**: the HLOD actors are always resident, so the mountain renders from anywhere on the 8.16 km map (the farthest corner is about 6.3 km from the summit) |
| Cell size | 102400 cm (1 km), so about 9 x 9 HLOD cells over the map |
| Parent layer | none (this is the last level) |
| World Partition default HLOD layer | changed from `/Game/level/Saskarta_WP_HLODLayer_Instanced` to `HLOD_Saskarta_Far` (saved in `/Game/level/Saskarta_WP`) |
| Landscape actor (`Landscape`) | `HLODLayer = HLOD_Saskarta_Far` (explicit) |

### How the landscape and the big rocks get this layer

- **Landscape streaming proxies (256).** Each proxy carries its own `HLODLayer`, and a proxy
  does not inherit it from the parent `Landscape` actor (checked: `LandscapeStreamingProxy_6_9_0`
  still reads `None` after the parent was set). Setting it on each proxy would mean loading and
  re-saving all 256 proxy packages (about 3.2 GB of LFS files). Instead, the proxies keep
  `None`, which resolves to the World Partition **default** layer, now `HLOD_Saskarta_Far`.
  Landscape proxies are built by the landscape's own HLOD builder whatever the layer type. The
  proxies' own settings are `HLODTextureSizePolicy = SpecificSize` and
  `HLODMeshSourceLODPolicy = LowestDetailLOD`.
- **Big rocks.** The rocks are PCG output (`PCG_Saskarta_RocksDebris`). Their instances live in
  PCG partition actors (1056 partition actors in the level, for every PCG graph). Partition
  actors have no layer of their own, so they also resolve to the default layer. Nanite rock
  meshes stay Nanite in an Instancing HLOD, which is cheap at distance. The PCG volume itself was
  not loaded or changed, because loading it risks a PCG regeneration.
- **Side effect, to review after the build.** Every other spatially loaded actor with meshes and
  no layer of its own also resolves to this layer. That includes the tree, shrub and test PCG
  partition actors and `SM_Skybox_Mesh`. Before this change, they resolved to the engine
  template's chain (`Saskarta_WP_HLODLayer_Instanced`, 768 m, then `Saskarta_WP_HLODLayer_Merged`),
  so they were already in HLOD. Only the layer changed. If their far instances cost too much
  after the build (see the checks below), give those PCG volumes or actors their own layer (V5/V6).

## Build HLODs (the user)

1. **Before the build: two temporary capture actors in the level are dirty and unsaved**:
   `HaybaMCPCaptureActor` (Hayba's helper) and `V2_RoadCapture` (a SceneCapture2D from task V2).
   Neither belongs in the level. In the Outliner, delete both, then **do not** save them. The
   HLOD builder works from the saved map, so it asks you to save dirty packages first; if it
   lists either of these, untick them or delete them first.
2. Close any PIE session. Make sure no agent holds the editor gate:
   `python Tools/GameFlow/editor_gate.py status` should print `free`, or hold it yourself with
   `python Tools/GameFlow/editor_gate.py acquire --owner USER --ttl-min 120`.
3. With `/Game/level/Saskarta_WP` open, choose **Build > Build HLODs** from the main menu. The
   World Partition editor's **Build HLODs** button does the same. The editor saves, then runs the
   World Partition HLOD builder in a separate process. It can take several minutes: it builds
   256 landscape proxies and every PCG partition cell. Let it finish.

   Command-line equivalent, with the editor closed:

   ```
   "C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Cmd.exe" ^
     "D:\UnrealEngine\saskartarad\saskartarad.uproject" /Game/level/Saskarta_WP ^
     -run=WorldPartitionBuilderCommandlet -Builder=WorldPartitionHLODsBuilder -AllowCommandletRendering
   ```
4. When it finishes, release the gate if you took it:
   `python Tools/GameFlow/editor_gate.py release --owner USER`.

## Checks after the build

1. **HLOD actors exist.** The Outliner, or the World Partition editor with HLODs shown, lists
   `WorldPartitionHLOD` actors for `HLOD_Saskarta_Far`: roughly one per 1 km cell with content
   (up to about 81). The editor's Git provider stages the new HLOD packages; commit them as the
   user's build.
2. **The far view is complete.** Capture the title view aimed at the mountain:

   ```
   python Tools/Look/capture_look.py title Saved/Screenshots/Sprint/L2_hlod_title.png --yaw 180 --pitch 5
   ```

   The terrain between the camera and the mountain is continuous, not a floating slab. Then do
   L1's silhouette check (`Tools/Look/LOOK.md`, "The silhouette check waits for Build HLODs"):
   it must print at least 0.08. Do it on the real title framing once L3 has re-aimed TitleCam
   (today TitleCam looks 52 degrees right of the mountain; see the L2 report).
3. **The beacon still reads.**
   `python Tools/Look/beacon_pixels.py Saved/Screenshots/Sprint/L2_hlod_title.png --cam 618206.6 465448.1 -35173.3 5 180 37.5`
   The crown luma and beam luma must stay well above the background luma around them.
4. **Budget.** In the flythrough (the user's run), watch VRAM (at most 8.5 GB) and the Nanite
   and foliage GPU time. The HLOD layer is always resident. If the always-loaded tree or debris
   instances cost too much, move their PCG output to a spatially loaded layer (V5/V6).

## Undo

To go back to the engine template's chain, set **World Settings > World Partition >
Default HLOD Layer** to `/Game/level/Saskarta_WP_HLODLayer_Instanced`, and clear the
`Landscape` actor's HLOD layer. Then save `/Game/level/Saskarta_WP` and the `Landscape` actor
package, and rebuild HLODs.

## Re-running the setup

`python Tools/Look/build_high_voice.py hlod` recreates and reassigns the layer (idempotent,
inside the editor gate). It saves nothing. Save the layer asset, `/Game/level/Saskarta_WP` and
the Landscape actor package (`/Game/__ExternalActors__/level/Saskarta_WP/7/20/E0WCUFB7A6X6PKSZ1PK4QM`)
by explicit list. **Do not save the world package through
`EditorLoadingAndSavingUtils.save_packages`** while other external actors are dirty: saving
the persistent World Partition map this way also saves **every** dirty external actor package
(seen on 2026-09-27; two temporary capture actors got saved and had to be removed again).
