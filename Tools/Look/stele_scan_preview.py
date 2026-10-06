"""Offline previews of the stele scan (task STELESCAN): the POM-carved face, the scan sweep and the HUD line.

    python Tools/Look/stele_scan_preview.py      # -> Saved/UI/SteleScan/previews/

The face is shaded by EVALUATING the material graph that Tools/Look/build_stele_scan.py builds
(M_Saskarta_SteleFace), node by node, with numpy: the same nodes, links, parameters and Custom
Primitive Data. What is modelled, not the engine:
  - ParallaxOcclusionMapping: a linear ray march of the height atlas (steps lerp(Max, Min, N.V),
    reference plane 1, offset -V.xy / V.z x Height Ratio), then a linear refinement; no shadows,
    as in the material.
  - textures: bilinear, clamp; the mip-bias-2 height sample is a 4x box mip, bilinear.
  - RockColor / RockNormal are the AshesOfBazaar sandstone in the game; here a procedural sandstone.
  - lighting: one low raking sun + sky ambient, the material's AO; no Lumen, no fog, no CRT pass.
  - the camera: a pinhole looking at the flat front face (the only part the Face slot covers).
The HUD mock uses VT323 (Saved/Fonts, the boot terminal's font) at the HudLine / ScanBlock places and
amber of Tools/GameFlow/gen_caption_specs.py, with the text formatting of FSaskartaSteleScanCore.

Outputs:
  stele_face_pom.png       WayStone_A with I05 at 3 m, raking light: POM on | UsePOM off | the height cell
  stele_face_dock.png      the dock post's I02 at 4 m
  scan_sweep_0..3.png      a full reading at t = 0.3, 0.8, 1.3 and 4.0 s (the grooves hold, then fade)
  scan_sweep_strip.png     the four frames side by side, plus a match reading at 0.3 s
  hud_reading_mock.png     1920 x 1080: the reading as the carrier's HUD shows it
"""
import json
import math
import pathlib
import sys
import unicodedata

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Tools" / "Look"))
sys.path.insert(0, str(ROOT / "Tools" / "Story"))
import build_stele_scan as bss  # noqa: E402

OUT = ROOT / "Saved" / "UI" / "SteleScan" / "previews"
ATLAS = ROOT / "SourceArt" / "Inscriptions" / "atlas"
AMBER = (0.95, 0.72, 0.42)          # linear, HudLine SpecifiedColor
HEADER_AMBER = (0.86, 0.66, 0.34)


# ------------------------------------------------------------------------------------------------ textures
def load_textures():
    h = np.asarray(Image.open(ATLAS / "T_Inscr_Atlas_H.png"), np.float32)[..., None] / 255.0
    n = np.asarray(Image.open(ATLAS / "T_Inscr_Atlas_N.png"), np.float32) / 255.0 * 2 - 1
    n[..., 1] *= -1                                             # the import flips green (OpenGL -> DirectX)
    rng = np.random.default_rng(7)

    def noise(size, scale):
        small = rng.random((max(2, size // scale), max(2, size // scale)))
        return ndimage.zoom(small, size / small.shape[0], order=3)[:size, :size]

    s = 512                                                     # 1 UV0 unit (1 m) of sandstone
    grain = 0.5 * noise(s, 96) + 0.3 * noise(s, 16) + 0.2 * noise(s, 3)
    rock_c = np.dstack([0.40 + 0.12 * grain, 0.33 + 0.10 * grain, 0.25 + 0.08 * grain]).astype(np.float32)
    bump = 0.7 * ndimage.gaussian_filter(noise(s, 4), 0.8) + 0.3 * noise(s, 24)
    gy, gx = np.gradient(bump)
    rn = np.dstack([-gx * 2.5, gy * 2.5, np.ones_like(bump)])
    rn /= np.linalg.norm(rn, axis=2, keepdims=True)
    return {bss.TEX_H: h, bss.TEX_N: n.astype(np.float32), bss.ROCK_COLOR: rock_c,
            bss.ROCK_NORMAL: rn.astype(np.float32)}, {bss.TEX_H: box_blur_mip(h, 2)}


def box_mip(a, level):
    f = 2 ** level
    hh, ww = a.shape[0] // f, a.shape[1] // f
    return a[:hh * f, :ww * f].reshape(hh, f, ww, f, a.shape[2]).mean(axis=(1, 3))


def box_blur_mip(a, level):
    return box_mip(a, level)


def sample(tex, uv, wrap=False):
    """Bilinear sample, texel centres at (i + 0.5) / size; clamp (or wrap for the rock)."""
    h, w = tex.shape[:2]
    x = uv[..., 0] * w - 0.5
    y = uv[..., 1] * h - 0.5
    x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
    fx, fy = (x - x0)[..., None], (y - y0)[..., None]

    def at(ix, iy):
        if wrap:
            return tex[iy % h, ix % w]
        return tex[np.clip(iy, 0, h - 1), np.clip(ix, 0, w - 1)]

    return ((at(x0, y0) * (1 - fx) + at(x0 + 1, y0) * fx) * (1 - fy)
            + (at(x0, y0 + 1) * (1 - fx) + at(x0 + 1, y0 + 1) * fx) * fy)


# ------------------------------------------------------------------------------------------------ graph eval
class Graph:
    """Evaluates bss.graph() for a grid of pixels. Every value is an array (..., C)."""

    def __init__(self, env, textures, mips, static=None):
        self.nodes = {k: (cls[len("MaterialExpression"):], dict(props)) for k, cls, _x, _y, props in bss.graph()[0]}
        self.inputs = {}
        for a, ao, b, bi in bss.graph()[1]:
            self.inputs.setdefault(b, {})[bi] = (a, ao)
        self.env, self.tex, self.mips = env, textures, mips
        self.static = static or {}
        self.memo = {}
        self.shape = env["uv1"].shape[:-1]

    def full(self, v):
        v = np.asarray(v, np.float32).reshape(-1)
        return np.broadcast_to(v, self.shape + (v.size,)).astype(np.float32)

    def get(self, key, out=""):
        k = (key, out)
        if k not in self.memo:
            self.memo[k] = self.eval(key, out)
        return self.memo[k]

    def inp(self, key, name, default=None):
        src = self.inputs.get(key, {}).get(name)
        if src is None:
            return default
        return self.get(*src)

    def eval(self, key, out):
        cls, p = self.nodes[key]
        env = self.env
        A = lambda d=None: self.inp(key, "A", d)                        # noqa: E731
        B = lambda d=None: self.inp(key, "B", d)                        # noqa: E731
        ca = self.full(p.get("const_a", 0.0))
        cb = self.full(p.get("const_b", 1.0))
        if cls == "TextureCoordinate":
            return env["uv%d" % p.get("coordinate_index", 0)]
        if cls == "ScalarParameter":
            if p.get("use_custom_primitive_data"):
                return self.full(env["cpd"][p["primitive_data_index"]])
            return self.full(env.get("params", {}).get(p["parameter_name"], p["default_value"]))
        if cls == "VectorParameter":
            if p.get("use_custom_primitive_data"):
                i = p["primitive_data_index"]
                v = self.full(env["cpd"][i:i + 4])
            else:
                v = self.full(color_of(p["default_value"]))
            return pick(v, out)
        if cls in ("Constant",):
            return self.full(p["r"])
        if cls == "Constant2Vector":
            return pick(self.full([p["r"], p["g"]]), out)
        if cls in ("Constant3Vector", "Constant4Vector"):
            c = color_of(p["constant"])
            return pick(self.full(c[:3] if cls == "Constant3Vector" else c), out)
        if cls == "StaticBool":
            return bool(p["value"])
        if cls == "TextureObjectParameter":
            return str(p["texture"])
        if cls == "TextureSampleParameter2D":
            uv = self.inp(key, "UVs", env["uv0"])
            path = str(p["texture"])
            bias = "MIP_BIAS" in str(p.get("mip_value_mode", ""))
            t = self.mips[path] if bias and path in self.mips else self.tex[path]
            v = sample(t, uv, wrap=path in (bss.ROCK_COLOR, bss.ROCK_NORMAL))
            if v.shape[-1] == 1:
                v = np.concatenate([v, v, v, np.ones_like(v)], -1)
            elif v.shape[-1] == 3:
                v = np.concatenate([v, np.ones_like(v[..., :1])], -1)
            return pick(v, out)
        if cls == "PixelDepth":
            return env["depth"]
        if cls == "VertexNormalWS":
            return self.full(env["N"])
        if cls == "CameraVectorWS":
            return env["camv"]
        if cls == "Time":
            return self.full(env["time"])
        if cls == "Noise":
            return env["noise"]
        if cls == "VertexColor":
            return pick(env["vc"], out, rgb_default=True)
        if cls == "Multiply":
            return A(ca) * B(cb)
        if cls == "Add":
            return A(ca) + B(cb)
        if cls == "Subtract":
            return A(ca) - B(cb)
        if cls == "Divide":
            return A(ca) / B(cb)
        if cls == "Max":
            return np.maximum(A(ca), B(cb))
        if cls == "Min":
            return np.minimum(A(ca), B(cb))
        if cls == "Fmod":
            return np.fmod(A(), B())
        if cls == "DotProduct":
            return (A() * B()).sum(-1, keepdims=True)
        if cls in ("OneMinus", "Abs", "Saturate", "Floor", "Normalize", "ComponentMask"):
            x = self.inp(key, "")
            if cls == "OneMinus":
                return 1 - x
            if cls == "Abs":
                return np.abs(x)
            if cls == "Saturate":
                return np.clip(x, 0, 1)
            if cls == "Floor":
                return np.floor(x)
            if cls == "Normalize":
                return x / np.maximum(np.linalg.norm(x, axis=-1, keepdims=True), 1e-8)
            idx = [i for i, c in enumerate("rgba") if p.get(c)]
            return x[..., idx]
        if cls == "Clamp":
            x = self.inp(key, "")
            return np.clip(x, self.inp(key, "Min", self.full(p.get("min_default", 0.0))),
                           self.inp(key, "Max", self.full(p.get("max_default", 1.0))))
        if cls == "LinearInterpolate":
            a, b, t = A(), B(), self.inp(key, "Alpha")
            return a + (b - a) * t
        if cls == "AppendVector":
            return np.concatenate([A(), B()], -1)
        if cls == "StaticSwitchParameter":
            on = self.static.get(p["parameter_name"], p["default_value"])
            return self.inp(key, "True" if on else "False")
        if cls == "MaterialFunctionCall":
            return self.pom(key, out)
        raise AssertionError(f"no model for {cls}")

    def pom(self, key, out):
        g = lambda n: self.inp(key, n)                                # noqa: E731
        height = self.tex[g("Heightmap Texture")]
        ratio, mins, maxs, uv = g("Height Ratio")[..., 0], g("Min Steps")[..., 0], g("Max Steps")[..., 0], g("UVs")
        ch = g("Heightmap Channel")
        T, Bt, N = self.env["T"], self.env["B"], self.env["N"]
        V = self.env["camv"]
        vts = np.stack([(V * T).sum(-1), (V * Bt).sum(-1), (V * N).sum(-1)], -1)
        steps = np.maximum(1, np.round(maxs + (mins - maxs) * np.clip(vts[..., 2], 0, 1)))
        dstep = 1.0 / steps
        duv = -vts[..., :2] / np.maximum(vts[..., 2:3], 0.05) * (ratio * dstep)[..., None]

        def h_at(u):
            return (sample(height, u) * ch[..., :height.shape[-1]]).sum(-1)

        ray = np.ones(uv.shape[:-1], np.float32)
        cur = uv.copy()
        hcur = h_at(cur)
        prev_ray, prev_h, prev_uv = ray.copy(), hcur.copy(), cur.copy()
        active = hcur < ray                                          # the ray is above the surface: march
        for _ in range(int(steps.max()) + 2):
            if not active.any():
                break
            prev_ray = np.where(active, ray, prev_ray)
            prev_h = np.where(active, hcur, prev_h)
            prev_uv = np.where(active[..., None], cur, prev_uv)
            ray = np.where(active, ray - dstep, ray)
            cur = np.where(active[..., None], cur + duv, cur)
            hcur = np.where(active, h_at(cur), hcur)
            active = active & (hcur < ray) & (ray > 0)
        # linear refinement between the last two samples
        d0 = prev_ray - prev_h
        d1 = hcur - ray
        w = np.clip(d0 / np.maximum(d0 + d1, 1e-6), 0, 1)[..., None]
        puv = prev_uv + (cur - prev_uv) * w
        if out == "Parallax UVs":
            return puv
        raise AssertionError(out)


def color_of(v):
    if isinstance(v, str) and v.startswith("unreal.LinearColor("):
        return [float(x) for x in v[len("unreal.LinearColor("):-1].split(",")]
    return list(v)


def pick(v, out, rgb_default=False):
    if out in ("", "RGB"):
        return v[..., :3] if v.shape[-1] >= 3 else v
    if out == "RGBA":
        return v
    return v[..., "RGBA".index(out):"RGBA".index(out) + 1]


# ------------------------------------------------------------------------------------------------ scene
def face_info(mesh_key):
    m = json.loads((ROOT / "SourceArt" / "Steles" / "steles.json").read_text(encoding="utf-8"))["meshes"][mesh_key]
    return m


def render(mesh_key, cell, wear, cam_offset_cm, look_z, fov_deg, size, time=10.0, scan=(0.0, 0.0, 0.0),
           pom=True, light=(-0.80, 0.50, 0.33), textures=None, bg=(0.10, 0.11, 0.12)):
    """Render the flat front face of one stele. Face frame: x right (viewer), y up, z toward the viewer."""
    tex, mips = textures
    info = face_info(mesh_key)
    ymin, ymax = info["face_rect_cm"]["y"]
    zbot, ztop = info["face_rect_cm"]["z"]
    fw, fh = ymax - ymin, ztop - zbot
    data = bss.load_data()
    rect = data["meshes"][info["mesh"]]["cell_rect_uv1"]
    W, H = size
    C = np.array([cam_offset_cm[0], look_z + cam_offset_cm[1], cam_offset_cm[2]], np.float64)
    target = np.array([0.0, look_z, 0.0])
    fwd = (target - C) / np.linalg.norm(target - C)
    right = np.cross(fwd, [0.0, 1.0, 0.0])
    right /= np.linalg.norm(right)
    up = np.cross(right, fwd)
    tan = math.tan(math.radians(fov_deg) / 2)
    px = (np.arange(W) + 0.5) / W * 2 - 1
    py = 1 - (np.arange(H) + 0.5) / H * 2
    X, Y = np.meshgrid(px * tan * W / H, py * tan)
    d = fwd + X[..., None] * right + Y[..., None] * up
    d /= np.linalg.norm(d, axis=-1, keepdims=True)
    t = -C[2] / np.minimum(d[..., 2], -1e-6)
    hit = C + t[..., None] * d
    x, y = hit[..., 0], hit[..., 1]
    on = (x >= -fw / 2) & (x <= fw / 2) & (y >= zbot) & (y <= ztop)
    u1 = (x + fw / 2) / fw
    v1 = (ztop - y) / fh
    env = {
        "uv1": np.stack([u1, v1], -1).astype(np.float32),
        "uv0": np.stack([(x + fw / 2) / 100.0, (ztop - y) / 100.0], -1).astype(np.float32),
        "depth": (t * (d @ fwd))[..., None].astype(np.float32),
        "camv": (-d).astype(np.float32),
        "N": np.array([0, 0, 1.0], np.float32), "T": np.array([1.0, 0, 0], np.float32),
        "B": np.array([0, -1.0, 0], np.float32),
        "time": time,
        "cpd": [wear, float(cell), scan[0], scan[1]] + list(rect) + [scan[2]],
        "vc": np.stack([np.zeros_like(x), np.clip(1 - (y - zbot) / 30.0, 0, 1),
                        np.clip(1 - np.minimum.reduce([x + fw / 2, fw / 2 - x, ztop - y]) / 3.0, 0, 1) * 0.6],
                       -1).astype(np.float32),
        "noise": ndimage.zoom(np.random.default_rng(3).random((H // 8 + 2, W // 8 + 2)), 8, order=1)[:H, :W, None].astype(np.float32),
    }
    G = Graph(env, tex, mips, static={"UsePOM": pom})
    base = G.get("bfin")
    nts = G.get("nnorm")
    ao = G.get("aol")
    emis = G.get("emis")
    nw = nts[..., :1] * env["T"] + nts[..., 1:2] * env["B"] + nts[..., 2:3] * env["N"]
    nw /= np.linalg.norm(nw, axis=-1, keepdims=True)
    L = np.array(light) / np.linalg.norm(light)
    lam = np.clip((nw * L).sum(-1, keepdims=True), 0, 1)
    sky = 0.16 + 0.06 * nw[..., 1:2]                            # storm light: a dim sky and a weak low sun
    col = base * (sky + 0.75 * lam) * ao + emis
    img = 1 - np.exp(-col * 1.3)
    img = np.where(on[..., None], img, np.array(bg))
    return (np.clip(img, 0, 1) ** (1 / 2.2) * 255).astype(np.uint8)


# ------------------------------------------------------------------------------------------------ HUD text
RESOLVED = "OK"         # FSaskartaSteleScanCore's default: Font_Terminal (VT323) has no check mark
DOT = "·"


def machine_translit(s):
    """Diacritics stripped, upper case (FSaskartaSteleScanCore::MachineTranslit): rzag-zrîrit -> RZAG-ZRIRIT."""
    s = "".join(c for c in unicodedata.normalize("NFD", s) if not unicodedata.combining(c))
    s = s.translate(str.maketrans({"’": "'", "ʼ": "'", "ʿ": "'", "ʾ": "'"}))
    return "".join(c if ord(c) < 128 else "?" for c in s).upper()


def hud_text(text):
    return text.replace("✓", RESOLVED)


def reading_lines(number, saskartan, approx):
    unresolved = approx.count("[?]") + approx.count("[ERASED]") + approx.count("[NAME:") + approx.count("~")
    head = f"INSCRIPTION {number:02d} {DOT} " + ("READ" if unresolved == 0 else f"PARTIAL {DOT} {unresolved} ?")
    return [head, " " + machine_translit(saskartan), " ~ EN: " + hud_text(approx)]


def lin_to_srgb8(c):
    return tuple(int(round(255 * (12.92 * x if x <= 0.0031308 else 1.055 * x ** (1 / 2.4) - 0.055))) for x in c)


def hud_mock(face_img, path):
    W, H = 1920, 1080
    yy = np.linspace(0, 1, H)[:, None, None]
    bg = (np.array([0.16, 0.17, 0.18]) * (1 - yy) + np.array([0.09, 0.085, 0.08]) * yy) * np.ones((H, W, 3))
    img = Image.fromarray((bg * 255).astype(np.uint8))
    stone = Image.fromarray(face_img).resize((int(face_img.shape[1] * 1.3), int(face_img.shape[0] * 1.3)))
    img.paste(stone, (W // 2 + 180, H - stone.height - 90))
    draw = ImageDraw.Draw(img)
    font_p = ROOT / "Saved" / "Fonts" / "VT323-Regular.ttf"
    f20 = ImageFont.truetype(str(font_p), 30) if font_p.exists() else ImageFont.load_default()
    f18 = ImageFont.truetype(str(font_p), 27) if font_p.exists() else ImageFont.load_default()
    amber, head = lin_to_srgb8(AMBER), lin_to_srgb8(HEADER_AMBER)
    draw.text((64, 92), "Q03  KETTLE?  ->  ?", font=f20, fill=amber)                 # HudLine (a Q-query)
    y = 124
    for i, line in enumerate(reading_lines(1, "rzag-zrîrit", "THE WAY ✓")):   # ScanBlock
        draw.text((64, y), line, font=f18, fill=head if i == 0 else amber)
        y += 30
    y += 40
    draw.text((64, y), "later, a text still waiting for the author:", font=f18, fill=(120, 120, 120))
    y += 34
    for i, line in enumerate(reading_lines(6, "AUTHOR", "KEEP A LIGHT ✓ · FOR [?] ~UNITS IN TRANSIT")):
        draw.text((64, y), line.replace(" AUTHOR", " [AUTHOR'S TEXT]"), font=f18, fill=head if i == 0 else amber)
        y += 30
    y += 40
    draw.text((64, y), f"MATCH 02 {DOT} THE WAY {RESOLVED}", font=f18, fill=amber)
    y += 30
    draw.text((64, y), f"MATCH 02 {DOT} THE WAY {RESOLVED} {DOT} 15 % LEGIBLE", font=f18, fill=amber)
    draw.text((64, H - 60), "mock: VT323 stand-in for Font_Terminal; no CRT pass (SensorCRT is another lane)",
              font=f18, fill=(90, 90, 90))
    img.save(path)


# ------------------------------------------------------------------------------------------------ main
def label(img, text):
    im = Image.fromarray(img)
    ImageDraw.Draw(im).text((8, 6), text, fill=(235, 190, 120))
    return np.asarray(im)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    textures = load_textures()
    data = bss.load_data()
    cells = {r["id"]: r["atlas_cell"] for r in data["inscriptions"]}
    # 1. POM face, WayStone_A, I05: close and oblique (where parallax shows), and at 3 m; raking light
    near = dict(mesh_key="WayStone_A", cell=cells["I05"], wear=0.2, cam_offset_cm=(75.0, 30.0, 105.0), look_z=82.0,
                fov_deg=36.0, size=(480, 800), textures=textures)
    on = render(pom=True, **near)
    off = render(pom=False, **near)
    diff = np.clip(np.abs(on.astype(np.int16) - off.astype(np.int16)) * 4, 0, 255).astype(np.uint8)
    far = render(pom=True, mesh_key="WayStone_A", cell=cells["I05"], wear=0.2, cam_offset_cm=(95.0, 35.0, 285.0),
                 look_z=82.0, fov_deg=22.0, size=(480, 800), textures=textures)
    sheet = np.concatenate([label(on, "POM on, 1.3 m, oblique"), label(off, "UsePOM off (normal + AO)"),
                            label(diff, "|on - off| x 4"), label(far, "POM on, 3 m")], 1)
    Image.fromarray(sheet).save(OUT / "stele_face_pom.png")
    dock = render(mesh_key="DockPost", cell=cells["I02"], wear=0.15, cam_offset_cm=(-120.0, -40.0, 380.0), look_z=200.0,
                  fov_deg=24.0, size=(560, 800), textures=textures)
    Image.fromarray(label(dock, "dock post, I02, 4 m")).save(OUT / "stele_face_dock.png")
    # 2. scan sweep: a full reading (mode 1, hold = sweep + text-only hold), front view from the road
    start = 10.0
    frames = []
    for i, t in enumerate((0.3, 0.8, 1.3, 4.0)):
        f = render(mesh_key="WayStone_A", cell=cells["I05"], wear=0.2, cam_offset_cm=(40.0, 10.0, 520.0), look_z=72.0,
                   fov_deg=20.0, size=(420, 760), time=start + t, scan=(start, 1.0, 1.4 + 6.0), textures=textures)
        f = label(f, f"full reading t = {t:.1f} s")
        Image.fromarray(f).save(OUT / f"scan_sweep_{i}.png")
        frames.append(f)
    m = render(mesh_key="WayStone_A", cell=cells["I05"], wear=0.2, cam_offset_cm=(40.0, 10.0, 520.0), look_z=72.0,
               fov_deg=20.0, size=(420, 760), time=start + 0.3, scan=(start, 0.5, 0.0), textures=textures)
    frames.append(label(m, "match t = 0.3 s"))
    Image.fromarray(np.concatenate(frames, 1)).save(OUT / "scan_sweep_strip.png")
    # 3. HUD mock over the reading at t = 1.6 s (text shown, grooves lit)
    lit = render(mesh_key="WayStone_A", cell=cells["I05"], wear=0.2, cam_offset_cm=(40.0, 10.0, 520.0), look_z=72.0,
                 fov_deg=20.0, size=(420, 760), time=start + 1.6, scan=(start, 1.0, 7.4), textures=textures,
                 bg=(0.012, 0.012, 0.013))
    hud_mock(lit, OUT / "hud_reading_mock.png")
    for p in sorted(OUT.glob("*.png")):
        print(p.relative_to(ROOT).as_posix())
    return 0


if __name__ == "__main__":
    sys.exit(main())
