"""The storm shells' dust noise (task STORM-SHELLS): a tileable RGBA volume, 32 (along the wind) x 64 (across)
x 64 (vertical) texels, written as a 2D atlas that the editor turns into VT_Saskarta_StormDust (a VolumeTexture
WITH mips, trilinear, wrap).

    python Tools/Look/storm_shells/storm_dust_noise.py      # writes Saved/Look/StormShells/T_Saskarta_StormDust_Atlas.png

Why our own volume and not the engine's VT_PerlinWorley_Balanced: that asset has no mips
(MipGenSettings=TMGS_NoMipmaps), so SampleGrad cannot prefilter it and the far shells shimmer, and its Worley
cells read as a cellular "cracked mud" network once thresholded. This one is smooth gradient noise with a full
mip chain (the engine box-filters volume mips in X, Y and Z: TextureCompressorModule.cpp), and the preview
samples exactly the same texels.

The field is STRATIFIED, like wind-blown dust: long along the wind, wide across it, thin vertically. Each octave
has its own integer frequency per axis (tileable), and the across-wind frequencies stay low (features >= 8 m at
the default tile): the forward part of a shell slices through the field as the carrier drives, and a feature
narrower than about 10 m along the direction of travel would change faster than a second (boiling). Vertical
detail is free of that (the carrier does not move up through the dust fast).

Channels (all 0..1):
    R  body: 5 octaves of streak fBm, mean 0.5, sd ~0.17: the dust masses
    G  wisps: ridged (1 - |fBm|), fine VERTICAL detail only (long, wide, thin filaments); the shader reads it
       at 3.1x the body's frequency on the near shells
    B  clumps: 2 very low octaves through a soft contrast: where the storm is thick or thin (macro variation)
    A  relief: 0.5 + the body's downward gradient (density above minus below, normalised): > 0.5 on the top of a
       mass (lit from above), < 0.5 on its underside (self-shadowed). Free lighting: no extra fetch.

Atlas layout (UVolumeTexture::UpdateSourceFromSourceTexture, VolumeTexture.cpp): tiles of NX x NY texels
(Source2DTileSizeX = 32, Source2DTileSizeY = 64), TILES_X tiles per row, slice z at tile (z % TILES_X,
z // TILES_X), row-major; texel (x, y) of a slice is column x, row y of its tile. The volume is indexed
vol[x, y, z, c] here, so texture coordinate q.x -> x (along the wind), q.y -> y (across), q.z -> z (vertical),
as SampleGrad reads it.
"""
from __future__ import annotations

import pathlib
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ATLAS = ROOT / "Saved" / "Look" / "StormShells" / "T_Saskarta_StormDust_Atlas.png"
NX, NY, NZ = 32, 64, 64      # along the wind, across, vertical
TILES_X = 8                  # atlas: 8 tiles per row x 8 rows = 64 slices -> 256 x 512 px
SEED = 23

# (fx, fy, fz) periods per tile on each axis, amplitude. With Shape = (160, 64, 12) m per tile the body's
# finest features are 27 m along, 8 m across and 0.75 m tall.
BODY = [((2, 2, 1), 1.0), ((3, 4, 2), 0.62), ((4, 6, 4), 0.42), ((6, 8, 8), 0.27), ((6, 8, 16), 0.16)]
WISPS = [((2, 1, 4), 1.0), ((4, 2, 8), 0.55), ((4, 2, 16), 0.3)]
CLUMPS = [((1, 1, 1), 1.0), ((2, 2, 1), 0.45)]


def _perlin_periodic(shape, freq, rng):
    """Tileable 3D gradient noise on a (nx, ny, nz) grid with freq = (fx, fy, fz) integer periods per axis."""
    fx, fy, fz = freq
    g = rng.normal(size=(fx, fy, fz, 3))
    g /= np.linalg.norm(g, axis=-1, keepdims=True)
    axes = [(np.arange(n) + 0.5) * f / n for n, f in zip(shape, freq)]
    x, y, z = np.meshgrid(*axes, indexing="ij")
    xi, yi, zi = np.floor(x).astype(int), np.floor(y).astype(int), np.floor(z).astype(int)
    xf, yf, zf = x - xi, y - yi, z - zi
    fade = lambda t: t * t * t * (t * (t * 6 - 15) + 10)  # noqa: E731
    u, v, w = fade(xf), fade(yf), fade(zf)
    out = np.zeros(x.shape)
    for dx in (0, 1):
        for dy in (0, 1):
            for dz in (0, 1):
                gg = g[(xi + dx) % fx, (yi + dy) % fy, (zi + dz) % fz]
                dot = gg[..., 0] * (xf - dx) + gg[..., 1] * (yf - dy) + gg[..., 2] * (zf - dz)
                out += (u if dx else 1 - u) * (v if dy else 1 - v) * (w if dz else 1 - w) * dot
    return out


def _fbm(shape, octaves, rng):
    v = sum(_perlin_periodic(shape, f, rng) * a for f, a in octaves)
    return (v - v.mean()) / v.std()


def make_volume(shape=(NX, NY, NZ), seed=SEED):
    """(nx, ny, nz, 4) uint8, tileable on every axis."""
    rng = np.random.default_rng(seed)
    body_n = _fbm(shape, BODY, rng)
    body = np.clip(0.5 + 0.17 * body_n, 0.0, 1.0)
    ridge = _fbm(shape, WISPS, rng)
    wisps = 1.0 - np.abs(ridge)
    wisps = np.clip(0.5 + 0.17 * (wisps - wisps.mean()) / wisps.std(), 0.0, 1.0)
    clump = _fbm(shape, CLUMPS, rng)
    clump = 1.0 / (1.0 + np.exp(-1.8 * clump))          # soft contrast: mostly thin or thick, few in between
    # relief: density just below minus just above (z is up), i.e. how much the dust thins upward here
    rel = np.roll(body_n, 1, axis=2) - np.roll(body_n, -1, axis=2)
    relief = np.clip(0.5 + 0.25 * rel / rel.std(), 0.0, 1.0)
    vol = np.stack([body, wisps, clump, relief], axis=-1)
    return np.round(vol * 255.0).astype(np.uint8)


def to_atlas(vol, tiles_x=TILES_X):
    nx, ny, nz, c = vol.shape
    rows = (nz + tiles_x - 1) // tiles_x
    atlas = np.zeros((rows * ny, tiles_x * nx, c), dtype=vol.dtype)
    for z in range(nz):
        tx, ty = z % tiles_x, z // tiles_x
        atlas[ty * ny:(ty + 1) * ny, tx * nx:(tx + 1) * nx] = vol[:, :, z].transpose(1, 0, 2)  # rows = y, cols = x
    return atlas


def from_atlas(atlas, nx=NX, ny=NY, nz=NZ):
    tiles_x = atlas.shape[1] // nx
    vol = np.zeros((nx, ny, nz, atlas.shape[2]), dtype=atlas.dtype)
    for z in range(nz):
        tx, ty = z % tiles_x, z // tiles_x
        vol[:, :, z] = atlas[ty * ny:(ty + 1) * ny, tx * nx:(tx + 1) * nx].transpose(1, 0, 2)
    return vol


def write_atlas(path=ATLAS, seed=SEED):
    from PIL import Image
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(to_atlas(make_volume(seed=seed)), "RGBA").save(path)
    return path


def load_volume(path=ATLAS):
    """The volume as float32 0..1, (NX, NY, NZ, 4); (re)writes the atlas if it is missing or the wrong size."""
    from PIL import Image
    path = pathlib.Path(path)
    want = (((NZ + TILES_X - 1) // TILES_X) * NY, TILES_X * NX)
    if not path.exists() or np.asarray(Image.open(path)).shape[:2] != want:
        write_atlas(path)
    return from_atlas(np.asarray(Image.open(path).convert("RGBA"))).astype(np.float32) / 255.0


if __name__ == "__main__":
    p = write_atlas()
    v = load_volume(p)
    print(p, v.shape, "means", [round(float(v[..., c].mean()), 3) for c in range(4)],
          "sd", [round(float(v[..., c].std()), 3) for c in range(4)])
    sys.exit(0)
