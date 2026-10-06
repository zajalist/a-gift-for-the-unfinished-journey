# Saskarta masks: `T_Saskarta_RoadInfluence` and `T_Saskarta_Ecology`

Baked by `Tools/Terrain/bake_masks.py` (Task P1), imported by `Tools/Terrain/import_masks.py`
(Task P1b) as `/Game/SaskartaGaea/Masks/T_Saskarta_RoadInfluence` and
`/Game/SaskartaGaea/Masks/T_Saskarta_Ecology`. Both are 4096x4096 RGBA16, linear (no sRGB).

## UV mapping (TRUE mapping, confirmed by P1 — Ruling R5)

```
UV = (WorldXY − (−18920.4, 50.0)) / 816000
```

- **Origin:** world `(X0, Y0) = (−18920.4, 50.0)` cm — `Tools/Story/build_road_profile.py`'s
  `LAND_X0_CM, LAND_Y0_CM`, the same origin the live heightmap (`Saved/TerrainRebuild/Current_u16.png`,
  8161x8161 px, 1 m/px) uses. This is the landscape's world-space origin, not the Gaea export's
  (see task-P1-report.md: the Gaea export at `D:/GaeaBuilds/Saskarta_direct_16k` is stale and
  spatially unusable against the live landscape — masks use the live heightmap only).
- **Extent:** `816000` cm = 8160 m, matching the heightmap's 8161 px at 1 m/px (8160 one-metre
  intervals). The masks are baked at 4096x4096 over this same extent (≈1.99 m/texel), so `UV`
  in `[0, 1]` covers the whole landscape with no scale correction needed per-texture.
- **No flip, either axis.** `bake_masks.py` builds its sample grid as
  `xs = X0 + (arange(size)+0.5) * EXTENT/size`, `ys = Y0 + (arange(size)+0.5) * EXTENT/size`,
  `X, Y = np.meshgrid(xs, ys)` (default `'xy'` indexing: array row increases with world Y, array
  column increases with world X), and writes the array to PNG row-major with no vertical flip.
  So texel row 0 / V=0 is world `Y = Y0` (the minimum, south edge in this project's convention),
  and texel col 0 / U=0 is world `X = X0` (the minimum, west edge) — i.e. sampling the imported
  texture with `U = (WorldX − X0) / 816000`, `V = (WorldY − Y0) / 816000` (both increasing away
  from the origin, no `1 − V`) reproduces the baked array exactly. Any material or PCG node that
  reads these masks must use this formula verbatim, on both channels, with no additional flip.

## `T_Saskarta_RoadInfluence`

| Channel | Meaning |
|---|---|
| R, road core | 1 on the road surface. Width wanders 3.5–5.5 m; the edge is noise-warped. |
| G, verge | Falls from 1 at the road edge to 0 at 25 m out. |
| B, neglect | A slow value along the road, biased by zone — lowlands run higher, switchbacks lower. |
| A, surface type | 0 = dirt/gravel, 1 = paving. From `Tools/Terrain/road_surface.json`, with soft (≈15 m) transitions. |

## `T_Saskarta_Ecology`

| Channel | Meaning |
|---|---|
| R, moisture | Terrain-hollow (Laplacian of smoothed height) and flow-accumulation derived; see task-P1-report.md §"R21" — GAEA priors were dropped, moisture is live-heightmap-only. |
| G, exposure | Slope, altitude and aspect. |
| B, zone / altitude band | Valley floor, ruins, switchbacks, above the clouds. |
| A, macro noise | Domain-warped fBm, no tiling — patch-scale variation. |

## Import settings (both textures)

| Property | Value | Why |
|---|---|---|
| `srgb` | `False` | Mask data, not colour — must read back linearly. |
| `compression_settings` | `TC_BC7` | Ruling R28: BC7 keeps the four channels independent within a block, so the road-core edge does not bleed into verge or neglect the way BC3-style `TC_MASKS` does, at the same 1 byte/texel (about 21 MB per 4096² texture with mips). 8-bit precision is enough for these 0..1 masks. |
| `address_x` / `address_y` | `TA_CLAMP` | The mapping only covers the landscape extent once; no tiling. |
| `lod_group` | `TEXTUREGROUP_TERRAIN_WEIGHTMAP` | Matches how the engine already budgets/streams other terrain weightmaps. |
| resolution | **full 4096², all mips** | Ruling R28: 2 m/texel. A 2048 cap (4 m/texel) made the 3.5–5.5 m road core about one texel wide. |

## Regenerating

1. `python Tools/Terrain/bake_masks.py --size 4096` (writes `Saved/Masks/*.png`, gitignored).
2. In the live editor: `import_masks.import_all()` (or `import_one(...)` per texture), then
   `import_masks.verify()` to read back `srgb`, `compression_settings`, `address_x/y`,
   `lod_group` and `max_texture_size`.
