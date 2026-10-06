# Tripo models: import plan (editor lane)

The user's Tripo Studio models are on this PC under `SourceArt/Tripo/<key>/`. `SourceArt/Tripo/manifest.json` lists every one (task id, triangles, textures, native size, the game slot it fills). `SourceArt/Tripo/contact_sheet.png` shows them all. This page is how they go into the project.

Editor verification is recorded per model in `Saved/Tripo/imported_bounds.json`.
Only rows in that report have passed the live import checks; `check` alone verifies
offline preparation. The offline half is handled by `Tools/Tripo/tripo_ingest.py`:
download, decode, pivot, scale, texture cap and ORM.

## Resume runner

`Tools/Tripo/import_tripo.py prepare` stages all 24 approved meshes and extracts their
72 texture maps; `check` verifies triangle counts, dimensions and editor scripts offline.
Source GLBs are preserved. Staged GLBs omit materials so the importer cannot create
unused material permutations; the original texture bytes are imported separately.

With the sole editor lane held, run `mesh KEY`, `textures KEY`, `master KEY` (once,
after the first texture set), `finish KEY`, then `verify KEY`. Each command uses the
existing Hayba client and refuses PIE. Start with `radio_desk`; after verification,
repeat mesh/textures/finish/verify for the other manifest rows marked `use`.
`finish` assigns the shared ground-blend master, enables Nanite and uses fallback-mesh
complex collision. Extracted OpenGL normals explicitly flip green on import.
The Interchange importer already supplies preserved normals, MikkTSpace tangents
and disabled lightmap-UV generation. `finish` and `verify` check these settings
without rebuilding the loaded mesh. Hayba blocks `set_lod_build_settings` because
it can crash this editor; an unexpected setting must be fixed at import time.
`verify` checks real bounds, bottom-centred pivot, Nanite, material/texture bindings,
clean packages and the saved mesh file. It writes `Saved/Tripo/imported_bounds.json`;
feed those measurements into the set-dressing catalog before planning placements.
Offline preparation alone does not mean the assets are imported.

**In short:**
- 37 projects are on disk (1.1 GB with the intermediates).
- 24 are **use**: the steampunk-medieval list, 1.85 M triangles in total, 36k to 137k each, one material, 4K textures.
- 4 are **review**, and 9 are **skip**: the older image-to-model arches and ruins, most of them untextured.
- The 24 import files (`*_ue.glb`) total 155 MB.

## 1. What is on disk

Per model, in `SourceArt/Tripo/<key>/`:

| file | what it is | import it? |
|---|---|---|
| `tripo_pbr_model_<task>_meshopt.glb` | the Studio's `model_url`, as served (EXT_meshopt_compression + KHR_mesh_quantization) | no, it is the archive copy |
| `<key>.glb` | the same mesh, meshopt decoded and dequantized (`gltf-transform copy` + `dequantize`) | no |
| `<key>_ue.glb` | **the import file**: pivot at the base centre, scaled to the planned real size, textures capped at 2048, packed ORM, PNG/JPEG only | **yes** |
| `output_mesh_<task>.fbx` / `texture_<task>.fbx` | the older image-to-model projects (arches, ruins); plain FBX, served as-is | only the two `review` ones, after a look |
| `preview.webp` | the Studio's `studio_mesh.webp` cover render | no (contact sheet only) |

What a Tripo model contains (all 24 **use** models, v3.1 text-to-model, 40k or 140k face limit):
- One mesh and one material.
- `Color` base colour, 4096 JPEG.
- `ORM` metallic-roughness, 4096 JPEG. **R is white**: there is no baked AO in any of the 24. G is roughness and B is metallic.
- `NormalGL` normal map, 4096 PNG (OpenGL, +Y).
- No tangents.
- The native size is normalised to a longest axis of about 0.98 m.

The meshopt GLB is the full-quality source. The Studio's own Export button (GLB/FBX/OBJ at the native texture size) converts that same `model_url` file in the browser, so no better file exists on the server without a paid re-export. No credits were spent.

**The GLBs are not in git.** `.gitattributes` does not route `*.glb` to LFS, so they stay untracked. If they should be versioned, add `*.glb filter=lfs diff=lfs merge=lfs -text` to `.gitattributes` first (the PERF/config owner decides), then commit `SourceArt/Tripo/**/*_ue.glb` only.

## 2. Destination and names

The set-dressing catalog already reserves the paths (`Tools/World/setdress_catalog.py`, `TRIPO2`):

- Mesh: `/Game/SaskartaGaea/Environment/Tripo02/SM_T2_<t2>`, where `<t2>` is the manifest's `t2` field (`relay_tower`, `carrier_cradle`, `mudbrick_house`, ...).
- Textures: `/Game/SaskartaGaea/Environment/Tripo02/Textures/T_T2_<t2>_BC`, `_N`, `_ORM`.
- Material instance: `/Game/SaskartaGaea/Environment/Tripo02/Materials/MI_T2_<t2>`.

When an `SM_T2_*` asset exists, `setdress_catalog.load()` marks it `exists` and `place_setdress.py` swaps it in for the stand-in. No re-planning is needed.

Some slots need a `TRIPO2` row or a size change before they place:
- `stone_hut` (S19) and `mudbrick_house_collapsed` (O14, S07) are new slots.
- Several models came out a different shape from the plan, so their sizes changed (see the table).

The per-model sizes and notes are in `Tools/Tripo/tripo_projects.json`; update `TRIPO2` from the imported bounds.

## 3. Import settings (Interchange glTF, UE 5.8)

One `AssetImportTask` per `<key>_ue.glb`, `automated=True`, `replace_existing=True`, `save=False`. Save separately, in chunks (see the WP save memory). Run one model per `python_run` call: the Hayba limit is 5 s, and a 150k-triangle Nanite build can run longer. Let it background, then read back the asset in a separate call.

Static mesh pipeline:
- Import as a **static mesh**. In the Interchange generic pipeline, turn on:
  - Static Meshes → `Combine Static Meshes` (one `SM_T2_*` per model);
  - Common Meshes → `Bake Meshes` (the root node's scale and pivot go into the vertices).
- **Uniform scale 1.0.** The scale is already baked: the root node carries `import_scale` from the manifest, which brings the model to `real_size_m` in `tripo_projects.json` (section 4). glTF metres become UE centimetres, and Y-up becomes Z-up, in the importer.
- **Pivot at the base.** It is already baked: the base centre sits at the origin, with Z = 0 on the lowest vertex. Do not use "Transform vertex to absolute".
- **Nanite on** (`nanite_settings.enabled = True`). Keep the fallback at the default relative error. Tripo meshes are 36k to 137k triangles of dense, even topology, which suits Nanite. Lightmap UVs off (Lumen), `Generate Lightmap UVs` = false.
- **Collision.** Small props (jars, milestone, bench, desk, cradle, mirror): `Auto Convex`, 4 hulls. Buildings and walls: simple boxes from `Generate Simple Collision` → Box, or `Use Complex as Simple` for the courtyard and terrace walls that the carrier brushes against. Nanite's complex collision uses the fallback mesh, so it stays cheap.
- Normals: import them (the Studio bakes them), and compute tangents with MikkTSpace.
- Materials: **do not keep** the importer's generated materials. Import the textures, then assign `MI_T2_<t2>` (section 5) and delete the generated `MI_*` so they don't ship.

Textures:
- `_BC`: sRGB on, `TC_Default` (BC1), LOD group `World`.
- `_N`: `TC_Normalmap` (BC5), sRGB off.
  - The maps are OpenGL-style (+Y, `NormalGL`). UE expects DirectX-style (-Y).
  - Whether the 5.8 Interchange glTF importer converts them is **not verified here**. Check the first model in the editor: if the relief looks lit from below, set `flip_green_channel = True` on every `T_T2_*_N`.
- `_ORM`: sRGB off, `TC_Masks` (BC1 without sRGB). R = AO, G = roughness, B = metallic.
  - This is the glTF metallic-roughness texture, and the file's `occlusionTexture` points at it.
  - R is 255 on every Tripo model, so AO comes from Lumen/SSAO only. Set `AOStrength` 0 in the MI, or leave it; white is a no-op.
- **2K cap:** the files are already at most 2048. As a safety net, also set `max_texture_size = 2048` on every `T_T2_*`, so a later re-import of a 4K source still caps.
- Virtual textures off: these are unique props, not tiling materials.

**The FBX rows** are the older image-to-model projects (only `ruin_architecture_5df3` and `ruin_378f` are `review`). They get no `_ue.glb`. If one is kept:
- Import the FBX with the manifest's `import_scale` as the uniform import scale.
- Fix the pivot in the editor: Modeling mode → Pivot → Bottom center, then bake it.
- Cap the one 8K map of `ruin_378f` with `max_texture_size`.

## 4. Real-world size

`import_scale` (in the manifest) = planned largest dimension ÷ native largest dimension. Where a model's height is the dependable measure (`scale_basis` = `h`), it is planned height ÷ native height instead: the water wheel, the pipe manifold and the two-storey house.

The planned sizes are the `TRIPO2` ones, except where the model differs from the plan. In those cases `real_size_m` in `Tools/Tripo/tripo_projects.json` holds the reviewed size, and the row's `note` says why:
- the airship, which is a small scout craft, not a 60 m hull;
- the pen, which has a tall gate arch;
- the terrace block;
- the short rope bridge;
- the jar rack.

After import, check the `SM_T2_*` bounds against `manifest.models[].import_size_cm_wdh`, then set `TRIPO2`'s size to the imported bounds, so the site footprints use the real one.

## 5. One shared master material

Create one master material, `/Game/SaskartaGaea/Environment/Tripo02/Materials/M_T2_Master`, with these parameters:
- `BaseColor` (Texture2D, sRGB), `Normal` (Texture2D normal), `ORM` (Texture2D masks).
- `Tint` (Vector, default 1,1,1), `RoughnessScale` (Scalar, 1), `AOStrength` (Scalar, 1).
- The set-dress ground blend `MF_SD_PropGroundBlend` inserted before BaseColor and Roughness, with the same `SD_FadeHeight` / `SD_PaletteMatch` / `SD_BaseStrength` parameters and CPD 0 to 4 that `place_setdress.py material` writes (docs/world/SETDRESS_V2.md §2b). The Tripo props then get the palette match and base fade for free, with no `_GB` copies.
- Usage: Nanite, static mesh. Opaque, default lit, not two-sided (the Studio meshes are closed).

Then create one `MI_T2_<t2>` per model with its three textures set. The whole set shares one shader permutation.

Style check before placing: the models must read as steampunk, biofuel, medieval or retrofuturistic, with nothing modern and nothing religious. The manifest `verdict` flags the ones to look at first.

## 6. Order of work (one editor lane)

1. Offline, with the editor closed: `python Tools/Tripo/tripo_ingest.py all`. It is idempotent, so files already present are skipped.
2. Editor: build `M_T2_Master` (one call), then compile and save it.
3. Editor: for each manifest row with `verdict` = `use`, import `<key>_ue.glb`, then fix the textures, then create the MI and assign it. That is three calls per model. Save every 5 models.
4. Editor: bounds read-back for all `SM_T2_*` → compare with `real_size_m` → update `TRIPO2` offline.
5. Set dressing: `place_setdress.py replace` on the Tripo-heavy sites (O13, O14, O10, O01), one site at a time, with captures reviewed by the user (see the set-dressing memory: prototype one site first).

Do not rebuild meshes in `python_run` (`build_from_static_mesh_descriptions` crashed the editor on 9/28). Import creates new assets, which is safe; editing existing mesh geometry in place is not.

## 7. Per model

`**use**` = import now. `review` = look in the editor first. `skip` = don't import (the reason is in the notes). Sizes are metres after `import_scale`: width (glTF X) × depth (glTF Z) × height. The triangle counts and maximum texture sizes are for the source files; the import files cap textures at 2048.

| # | key | mesh | verdict | tris | max tex | import scale | size m (w x d x h) | slot | notes |
|---|---|---|---|---:|---:|---|---|---|---|
| 01 | `radio_desk` | `SM_T2_radio_desk` | **use** | 121,200 | 4096 | 2.043 (max) | 1.3 x 2.0 x 1.8 | O01 Low Voice post (radio room) |  |
| 02 | `signal_mirror` | `SM_T2_signal_mirror` | **use** | 134,786 | 4096 | 2.449 (max) | 1.6 x 1.8 x 2.4 | O11 Signal-mirror hill |  |
| 03 | `wind_pump` | `SM_T2_wind_pump` | **use** | 134,096 | 4096 | 12.245 (max) | 5.7 x 4.2 x 12.0 | O08 Wind-pump ridge |  |
| 04 | `airship` | `SM_T2_airship_hull` | **use** | 137,002 | 4096 | 14.523 (max) | 14.0 x 11.5 x 9.6 | O04 Downed airship | A small scout airship (gondola pod under a short envelope), not the 60 m rib-frame hull TRIPO2 planned; sized 14 m. O04 layout (a 60 m frame across the plain) needs re-planning around a small wreck, or keep the hull slot open. |
| 05 | `animal_pen` | `SM_T2_animal_pen` | **use** | 37,529 | 4096 | 5.607 (max) | 5.0 x 5.5 x 3.6 | O14 Granary hamlet | The pen has a tall woven gate arch; sized 5 m across so the fence reads about 1.2 m. TRIPO2 planned 8 x 6 x 1.3. |
| 06 | `stone_terrace` | `SM_T2_terrace_wall` | **use** | 37,271 | 4096 | 4.082 (max) | 4.0 x 3.7 x 3.0 | O13 Terrace orchards | A stepped terrace block with a sluice gate, taller than a single wall run; sized 4 m long (3 m high). TRIPO2 planned 5 x 1 x 1.5. |
| 07 | `watchtower` | `SM_T2_watchtower` | **use** | 36,376 | 4096 | 12.245 (max) | 6.3 x 6.4 x 12.0 | S08 Valley watchtower |  |
| 08 | `granary` | `SM_T2_granary` | **use** | 38,256 | 4096 | 6.122 (max) | 4.8 x 5.4 x 6.0 | O14 Granary hamlet |  |
| 09 | `rope_bridge` | `SM_T2_rope_footbridge` | **use** | 38,624 | 4096 | 8.155 (max) | 8.0 x 3.7 x 2.3 | O05 Cliff dwellings | A short span with anchor posts; sized 8 m so the deck width stays believable. O05 wants 16 m: use two, or bridge a narrower gap. |
| 10 | `dovecote` | `SM_T2_dovecote` | **use** | 38,108 | 4096 | 8.325 (max) | 7.3 x 8.0 x 7.7 | O14 Granary hamlet |  |
| 11 | `milestone` | `SM_T2_way_marker` | **use** | 37,942 | 4096 | 1.226 (max) | 0.8 x 0.8 x 1.2 | Spur way-markers (O01, O09, O14, O15) and road markers |  |
| 12 | `water_wheel` | `SM_T2_water_wheel` | **use** | 37,669 | 4096 | 7.924 (h) | 2.3 x 7.8 x 5.0 | O06 Old dam | Wheel, clay pots and stone channel in one piece; scaled by height (5 m). |
| 13 | `distillation_column` | `SM_T2_distillation_column` | **use** | 38,117 | 4096 | 22.312 (max) | 9.3 x 11.3 x 22.0 | O02 Hilltop biofuel refinery |  |
| 14 | `steam_pipe` | `SM_T2_pipe_manifold` | **use** | 38,197 | 4096 | 2.554 (h) | 2.0 x 2.2 x 2.5 | O02 Hilltop biofuel refinery | A standing manifold with a valve wheel; scaled by height (2.5 m), not the planned 4 m run. |
| 15 | `lab_bench` | `SM_T2_chem_bench` | **use** | 37,304 | 4096 | 2.24 (max) | 1.0 x 2.2 x 1.9 | O10 Chemist's workshop |  |
| 16 | `copper_still` | `SM_T2_biofuel_still` | **use** | 37,856 | 4096 | 7.136 (max) | 4.7 x 4.2 x 7.0 | O02 refinery and O10 chemist's workshop |  |
| 17 | `clay_jars` | `SM_T2_jars` | **use** | 38,642 | 4096 | 2.446 (max) | 1.5 x 2.4 x 2.3 | O05, O10, O14 and S13 caravanserai | A rack of about 14 jars and amphorae, not one jar; sized 2.4 m long. Single jars still need the B01_tank01 stand-in or a split. |
| 18 | `bread_oven` | `SM_T2_bread_oven` | **use** | 38,508 | 4096 | 2.593 (max) | 2.5 x 2.5 x 2.2 | O14 Granary hamlet |  |
| 19 | `courtyard` | `SM_T2_courtyard` | **use** | 131,676 | 4096 | 20.45 (max) | 20.0 x 17.8 x 8.2 | S13 Numbered Stop caravanserai, S07 Waiting Water | Sized to the planned 20 m; the gate block then stands about 8 m. Check against the S13 layout. |
| 20 | `stone_mud_hut` | `SM_T2_stone_hut` | **use** | 135,572 | 4096 | 6.11 (max) | 6.0 x 4.8 x 4.2 | S19 Last Waystation |  |
| 21 | `mudbrick_house_ruined` | `SM_T2_mudbrick_house` | **use** | 131,322 | 4096 | 10.714 (h) | 10.5 x 9.6 x 6.0 | O01 post office, O10 workshop, O14 hamlet, S07 | Two-storey house on a rubble apron; scaled by height (6 m), so the footprint with rubble is about 10.5 m. |
| 22 | `mudbrick_house_collapsed` | `SM_T2_mudbrick_house_collapsed` | **use** | 132,008 | 4096 | 8.172 (max) | 8.0 x 7.5 x 4.6 | O14 ruined hamlet, S07 Waiting Water |  |
| 23 | `carrier_cradle` | `SM_T2_carrier_cradle` | **use** | 133,316 | 4096 | 3.265 (max) | 3.2 x 2.0 x 2.5 | O09 Caravan graveyard (two old cradles), V1, V7 |  |
| 24 | `relay_tower` | `SM_T2_relay_tower` | **use** | 132,137 | 4096 | 26.45 (max) | 16.8 x 16.8 x 26.0 | O12 Old relay (first High Voice), O01 | The mound at the foot makes the base about 17 m wide at 26 m tall. |
| 25 | `ruin_arch_be1a` | `SM_T2_ruin_arch_be1a` | **skip** | 9,259 | 0 | 7.7 (max) | 7.7 x 5.4 x 6.8 | S13 broken arch gate, S10 crest fort, O03 bridge arches | Untextured Nexus image-to-model mesh (the Studio only has a wireframe preview). Gothic tracery windows and banners: reads as a church ruin, which the style rules avoid. Skip unless a plain arch is needed. |
| 26 | `ruin_archway_1428` | `SM_T2_ruin_archway_1428` | **skip** | 19,887 | 0 | 7.7 (max) | (native) 1.0 x 0.6 x 0.9 | S13 broken arch gate, S10 crest fort, O03 bridge arches | Untextured Nexus image-to-model mesh (the Studio only has a wireframe preview). Gothic tracery windows and banners: reads as a church ruin, which the style rules avoid. Skip unless a plain arch is needed. |
| 27 | `ruin_arch_6aff` | `SM_T2_ruin_arch_6aff` | **skip** | 18,799 | 0 | 7.715 (max) | (native) 1.0 x 0.6 x 0.9 | S13 broken arch gate, S10 crest fort, O03 bridge arches | Untextured Nexus image-to-model mesh (the Studio only has a wireframe preview). Gothic tracery windows and banners: reads as a church ruin, which the style rules avoid. Skip unless a plain arch is needed. |
| 28 | `ruin_architecture_5df3` | `SM_T2_ruin_architecture_5df3` | **review** | 20,435 | 4096 | 7.7 (max) | (native) 1.0 x 0.6 x 0.8 | S13 broken arch gate, S10 crest fort, O03 bridge arches | Textured (one 4K map) version of the gothic arch ruin; same church-ruin read. Review before use. |
| 29 | `ruin_arch_b7b9` | `SM_T2_ruin_arch_b7b9` | **skip** | 19,385 | 0 | 7.7 (max) | (native) 1.0 x 0.6 x 1.0 | S13 broken arch gate, S10 crest fort, O03 bridge arches | Untextured Nexus image-to-model mesh (the Studio only has a wireframe preview). Gothic tracery windows and banners: reads as a church ruin, which the style rules avoid. Skip unless a plain arch is needed. |
| 30 | `ruin_archway_c5d2` | `SM_T2_ruin_archway_c5d2` | **skip** | 8,958 | 0 | 7.7 (max) | (native) 1.0 x 0.7 x 1.0 | S13 broken arch gate, S10 crest fort, O03 bridge arches | Untextured Nexus image-to-model mesh (the Studio only has a wireframe preview). Gothic tracery windows and banners: reads as a church ruin, which the style rules avoid. Skip unless a plain arch is needed. |
| 31 | `ruin_378f` | `SM_T2_ruin_378f` | **review** | 4,490 | 8192 | 6.0 (max) | (native) 0.9 x 1.0 x 0.3 | rubble footings: O03 broken bridge, S10 crest fort | Low stepped ruin foundation with one 8K map (capped to 2K on import). Candidate rubble footing for O03/S10. |
| 32 | `ruins_8116` | `SM_T2_ruins_8116` | **skip** | 4,694 | 0 | 6.0 (max) | (native) 0.9 x 1.0 x 0.3 | rubble footings: O03 broken bridge, S10 crest fort | Untextured low ruin foundation (wireframe preview only); needs a triplanar stone material. |
| 33 | `ruins_4acf` | `SM_T2_ruins_4acf` | **skip** | 4,347 | 0 | 6.0 (max) | (native) 0.9 x 1.0 x 0.3 | rubble footings: O03 broken bridge, S10 crest fort | Untextured low ruin foundation (wireframe preview only); needs a triplanar stone material. |
| 34 | `ruins_7646` | `SM_T2_ruins_7646` | **skip** | 4,511 | 0 | 6.0 (max) | (native) 1.0 x 1.0 x 0.3 | rubble footings: O03 broken bridge, S10 crest fort | Untextured low ruin foundation (wireframe preview only); needs a triplanar stone material. |
| 35 | `ruin_machinery_3179` | `SM_T2_ruin_machinery_3179` | **skip** | 9,048 | 4096 | 5.025 (max) | 2.9 x 2.5 x 5.0 | S15 Works (old forge) / O02 refinery | Same model file as ruin_machinery_5208 (a Studio clone); kept for completeness, do not import twice. |
| 36 | `ruin_arch_5d5d` | `SM_T2_ruin_arch_5d5d` | **review** | 1,879,257 | 2048 | 7.865 (max) | 6.6 x 7.7 x 6.6 | S13 broken arch gate, S10 crest fort, O03 bridge arches | 1.88 M triangles in 185 materials (the 2 M face-limit generation). Too heavy and too many slots; merge materials offline before any import. Same gothic arch look. |
| 37 | `ruin_machinery_5208` | `SM_T2_ruin_machinery_5208` | **review** | 9,048 | 4096 | 5.025 (max) | 2.9 x 2.5 x 5.0 | S15 Works (old forge) / O02 refinery | Rusted machine tower on a ruin (v3.0), 256 separate parts and materials with small textures. Merge parts and atlas before import; candidate wreck for S15 Works. |

Known data issues:
- `ruin_arch_be1a` (**skip**) has zero-length normals in the source (the glTF validator reports `ACCESSOR_VECTOR3_NON_UNIT`).
- `ruin_machinery_3179` and `ruin_machinery_5208` are the same file: the Studio clone points at its source model.
