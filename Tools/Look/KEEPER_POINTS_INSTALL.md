# Keeper loading point cloud: post-filming install

The current `M_Saskarta_PointCloudSkin` is a masked surface placeholder. The
replacement system must be real, separate point sprites that follow the
Traveller and staff. Do not run these steps during the user's 4K capture.

## Inputs already saved

- Body: `/Game/SaskartaGaea/Characters/Traveller/SK_Traveller`, walking clip
  `/Game/SaskartaGaea/Characters/Traveller/Anims/A_Traveller_SlowWalk`.
- Staff: `/Game/SaskartaGaea/Characters/Traveller/SM_Traveller_Staff`, attached
  to the animated `staff011` bone by `ASaskartaKeeperPointActor` at runtime.
- Capture/UI: `KeeperPointCloud_Capture`, 512²
  `RT_Saskarta_LoadingTraveller`, `M_UI_KeeperPointCloud`,
  `WBP_Saskarta_Loading.TravellerPointCloud`.

## Author the missing Niagara system

Create `/Game/SaskartaGaea/Characters/Traveller/PointCloud/NS_LoadingKeeperPoints`
in the Niagara editor from the installed `/Niagara/DefaultAssets/Templates/Emitters/SimpleSpriteBurst`
template, then add a second sprite emitter. This is the fastest reliable path
for this one asset: the local UE 5.8 install exposes its Niagara graph editing
utility in C++ without Python-reflected `UFUNCTION`s, and this Hayba host's
`niagara_system_inspect` command returned `Unknown command`. Python asset
factory creation alone would leave an empty system. Save only after both
emitters compile without errors.

In Content Browser, enable **Show Engine Content** and **Show Plugin Content**,
then create a Niagara System from the `SimpleSpriteBurst` emitter template and
save it at the exact path above. Rename its emitter **Body**; add another
`SimpleSpriteBurst` emitter named **Staff**. Remove the template's movement,
shape-location and repeating-spawn modules. Each emitter should burst once,
remain alive beyond the 12 s loading hold, and have a Sprite Renderer only.
Create these **user data interfaces** in the system Parameters panel and bind
the modules to them (the spelling and type must match the native runtime actor):

| Emitter | User variable type | Source | Burst | Motion |
| --- | --- | --- | ---: | --- |
| Body | `User.KeeperMesh`: Skeletal Mesh data interface | live `KeeperPointCloud_Traveller.SkeletalMeshComponent` | ~6,000 | Retain each particle's triangle coordinate from Spawn; sample its skinned position each Update. |
| Staff | `User.StaffMesh`: Static Mesh data interface | hidden `StaffPointSource` component on native point actor | ~500 | Retain each particle's triangle coordinate; resample its world position each Update so it follows `staff011`. |

For Body, use the installed spawn module
`/Niagara/Modules/Spawn/MeshInterface/Initialize_MeshReproductionSprite` and
update module `/Niagara/Modules/Update/MeshInterface/Update_MeshReproductionSprite`.
Bind both to `User.KeeperMesh`, and use
`/Niagara/DynamicInputs/DataInterface/RandomTriCoordinate_SkeletalMesh`
only at spawn. For Staff, the installed
`/Niagara/Modules/Spawn/MeshInterface/SampleStaticMesh` and
`/Niagara/DynamicInputs/DataInterface/RandomTriCoordinate_StaticMesh` provide
the starting point. A Staff update or Scratch Pad module must sample the
**stored** triangle coordinate against `User.StaffMesh` each frame; the local
engine has no matching stock `UpdateStaticMeshReproductionSprite` module.
Confirm in the Niagara debugger that particle IDs and sample coordinates stay
stable while their positions follow the two moving meshes. Resampling a random
triangle every frame recreates the brush-like noise the player rejected. Use
GPU simulation only if both mesh data interfaces compile for it; CPU is the
fallback for the first acceptance pass.

Both emitters use a circular unlit sprite (`/Niagara/DefaultAssets/DefaultSpriteMaterial`
is available as a technical first pass), no ribbon, stretch-by-velocity,
motion blur, or mesh renderer. Start at 1–2 pixels per dot in the 512² capture,
with small stable per-particle colour variation in the ember palette. Keep the
emitter local to the source components: no world drift or random velocity. Burst
once on activation, with life longer than the 12-second minimum loading hold.

## Install after the user finishes filming

1. Stop PIE, obtain the editor lease with `python Tools/GameFlow/editor_gate.py
   acquire --owner keeper-points --scope world:/Game/level/Saskarta_WP`, and set
   `HAYBA_AGENT_ID=keeper-points` for that shell. Verify that
   `Content/SaskartaGaea/Characters/Traveller/PointCloud/NS_LoadingKeeperPoints.uasset`
   does not already contain an unrelated system. Run
   `python Tools/Look/build_keeper_pointcloud.py check` offline; this now parses
   all generated editor snippets before any RPC.
2. Build SaskartaCore with the new Niagara dependency and verify
   `ASaskartaKeeperPointActor` appears in Unreal. The actor binds both user
   variables at BeginPlay and runs only while the guarded capture is active.
3. Save `NS_LoadingKeeperPoints` after the two emitters compile. Run
   `python Tools/Look/build_keeper_pointcloud.py stage` to persist the
   always-ticking animated source, then `... points` to create the native point
   actor and make the capture show only that actor. The `points` step checks
   system type and two emitter handles, staff mesh, native class and source
   actors before spawning or saving. Save the Niagara asset first; a system
   editor error is a stop condition. Release the lease with
   `python Tools/GameFlow/editor_gate.py release --owner keeper-points`.
4. Rebuild the loading widget from
   `Tools/GameFlow/specs/WBP_Saskarta_Loading.tree.json` so both scene boxes
   scale with viewport resolution and the Keeper uses a 540² design box.
5. In a disposable PIE loading run, use
   `Tools/EndingFocus/sample_keeper_runtime_pose.py` in two separate calls at
   least 0.5 seconds apart. Confirm bone motion, live body/staff particle count,
   capture show-only contents, and two visible point frames. Review both 1080p
   and 4K for recognizable motion, stable dots, and the staff attached to the
   hand. If the staff is too long or detached, inspect `staff011` transform
   before rescaling the imported mesh.
6. Confirm no black UI quad on the carrier→Keeper→title fade and no Niagara
   simulation after the capture turns off. Cook once after live acceptance to
   verify that explicit runtime source binding survives packaging.

The Niagara system asset and these live acceptance checks are still outstanding.
