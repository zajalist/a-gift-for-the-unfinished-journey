"""Offline numpy port and preview of Shaders/AuxSensors.hlsl (the acoustic point cloud).

    python Tools/Drone/aux_feed_preview.py [out_dir]

Ray-casts a synthetic scene (a heightfield slope with a curving road, rocks and a
ruined wall), then shades it with a line-by-line port of the post-process shader.
Writes one ping seen at 0.5/1.5/3/6 s, three overlapping pings, and a contact sheet
to Saved/UI/AuxSensors/previews/. No editor, no GPU.
"""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "Saved/UI/AuxSensors/previews"
# Mirrors build_aux_material.SCALARS; kept literal so the preview runs without Tools on sys.path.
PARAMS = dict(PingSpeed=6000., Fade=7., RangeCm=9000., RoadHalfWidth=300., GridCm=2.,
              SpacingPx=9., DotPx=.95, Gain=1.)
EMPTY = (0., 0., 0., -10000.)
W, H, HFOV = 960, 540, 80.
PERIOD, WALK = 3.0, 130.   # s between pings, carrier cm/s


# ---- shader port (keep in step with Shaders/AuxSensors.hlsl) ----------------------
def smoothstep(a, b, x):
    t = np.clip((x - a) / (b - a), 0., 1.)
    return t * t * (3. - 2. * t)


def ping_energy(age, fade=PARAMS["Fade"]):
    """One ping's contribution at a surface whose front arrived `age` seconds ago."""
    memory = np.clip(1. - age / max(fade, .5), 0., 1.)
    return np.clip(age * 40., 0., 1.) * (.55 * np.exp(-4. * np.maximum(age, 0.)) + .5 * memory * np.sqrt(memory))


def brightness(energy):
    return 1. - np.exp(-1.7 * energy)


def shade(wp, normal, depth, stencil, cam, clock, pings, road_centre, road_forward, p=PARAMS):
    """wp/normal: (H, W, 3); depth/stencil: (H, W); pings: three (x, y, z, t), newest first."""
    to_p = wp - cam
    dist = np.maximum(np.linalg.norm(to_p, axis=-1), 1.)
    v = to_p / dist[..., None]
    n = normal + np.array([0., 0., 1e-4])
    n = n / np.linalg.norm(n, axis=-1, keepdims=True)
    facing = np.abs((n * v).sum(-1))
    ddx = np.diff(v, axis=1, append=v[:, -1:] * 2 - v[:, -2:-1])
    pixel_angle = np.maximum(np.linalg.norm(ddx, axis=-1), 1e-5)
    footprint = dist * pixel_angle
    speed = max(p["PingSpeed"], 1.)

    energy = np.zeros_like(dist)
    for px, py, pz, pt in pings:
        age = clock - pt - np.linalg.norm(wp - np.array([px, py, pz]), axis=-1) / speed
        energy += ping_energy(age, p["Fade"])

    range_fade = 1. - smoothstep(p["RangeCm"] * .7, max(p["RangeCm"], 1.), dist)
    graze = smoothstep(.06, .25, facing)
    visible = range_fade * graze * (depth < 999000.)

    fwd = np.array(road_forward[:2]) / max(np.linalg.norm(road_forward[:2]), .01)
    side = np.array([-fwd[1], fwd[0]])
    rel = wp[..., :2] - np.array(road_centre[:2])
    lateral = np.abs(rel @ side)
    ahead = np.abs(rel @ fwd)
    hw = p["RoadHalfWidth"]
    road_band = ((1. - smoothstep(hw, hw + 40., lateral)) * (1. - smoothstep(2600., 3600., ahead))
                 * (np.abs(n[..., 2]) >= .55))
    road = np.maximum(road_band, (np.abs(stencil - 3.) < .5).astype(float))

    spacing = p["SpacingPx"] * (1. + .8 * np.clip(dist / p["RangeCm"], 0., 1.)) * (1. - .25 * road)
    grid = max(p["GridCm"], 1.)
    lod = np.log2(np.maximum(spacing * footprint / (np.sqrt(np.maximum(facing, .15)) * grid), 1.))
    level = np.floor(lod)
    handover = lod - level
    an = np.abs(n)
    axis = np.where(an[..., 2] >= np.maximum(an[..., 0], an[..., 1]), 0, np.where(an[..., 0] >= an[..., 1], 1, 2))
    perm = {0: [0, 1, 2], 1: [1, 2, 0], 2: [2, 0, 1]}      # q = WP, WP.yzx, WP.zxy
    unperm = {0: [0, 1, 2], 1: [2, 0, 1], 2: [1, 2, 0]}    # back: q, q.zxy, q.yzx
    q = np.zeros_like(wp)
    m = np.zeros_like(n)
    for a_, idx in perm.items():
        sel = axis == a_
        q[sel] = wp[sel][:, idx]
        m[sel] = n[sel][:, idx]
    radius = p["DotPx"] * (1. + .2 * road)
    dots = np.zeros_like(dist)
    tint = np.zeros_like(dist)
    for k in (0, 1):
        cell = grid * np.exp2(level + k)
        c = np.floor(q[..., :2] / cell[..., None])
        key = np.concatenate([c, (level + k + 64. * axis)[..., None]], -1)
        p3 = np.mod(key * np.array([.1031, .1030, .0973]), 1.)
        p3 = p3 + (p3 * (p3[..., [1, 0, 2]] + 33.33)).sum(-1, keepdims=True)
        h = np.mod((p3[..., [0, 0, 1]] + p3[..., [1, 0, 0]]) * p3[..., [2, 1, 0]], 1.)
        keep = np.mod((h * np.array([17.31, 31.77, 11.13])).sum(-1), 1.)
        fade_key = np.mod((h * np.array([23.11, 7.73, 41.37])).sum(-1), 1.)
        lod_keep = np.clip(((fade_key - handover) if k == 0 else (handover - fade_key)) * 12. + .5, 0., 1.)
        j = (c + .2 + .6 * h[..., :2]) * cell[..., None] - q[..., :2]
        lift = -(m[..., :2] * j).sum(-1) / np.maximum(np.abs(m[..., 2]), .3) * np.sign(m[..., 2])
        off_q = np.concatenate([j, lift[..., None]], -1)
        off = np.zeros_like(off_q)
        for a_, idx in unperm.items():
            sel = axis == a_
            off[sel] = off_q[sel][:, idx]
        perp = off - (off * v).sum(-1, keepdims=True) * v
        pxd = np.linalg.norm(perp, axis=-1) / footprint
        disc = np.clip(radius + .5 - pxd, 0., 1.) * lod_keep * (keep <= .6 + .4 * road)
        dots += disc * (.65 + .35 * h[..., 2])
        tint += disc * h[..., 1]

    hot = np.array([.807, .434, .162])
    ember = np.array([.578, .162, .042])
    t = np.clip(tint / np.maximum(dots, 1e-3), 0., 1.)[..., None]
    colour = hot + (ember - hot) * t * (1. - .6 * road)[..., None]
    bright = brightness(energy) * (1. + .6 * road)
    out = colour * (dots * bright)[..., None]
    return p["Gain"] * visible[..., None] * out


# ---- synthetic scene ---------------------------------------------------------------
def road_y(x):
    return 180. * np.sin(x / 2600.)


def softplus(x):
    return np.logaddexp(0., x)


def terrain(x, y):
    s = y - road_y(x)
    shoulder = smoothstep(300., 420., np.abs(s))
    left = 60. * softplus((s - 340.) / 60.) * .45
    right = -60. * softplus((-s - 340.) / 60.) * .3
    noise = (25. * np.sin(x / 310. + 1.3) * np.sin(y / 270.) + 12. * np.sin(x / 97. + y / 131.)
             + 5. * np.sin(x / 23. - y / 37.))
    return -.025 * x + 40. * np.sin(x / 1300.) + left + right + shoulder * noise


def terrain_normal(x, y, e=2.):
    dx = (terrain(x + e, y) - terrain(x - e, y)) / (2 * e)
    dy = (terrain(x, y + e) - terrain(x, y - e)) / (2 * e)
    n = np.stack([-dx, -dy, np.ones_like(dx)], -1)
    return n / np.linalg.norm(n, axis=-1, keepdims=True)


def scene_objects():
    rocks = []
    for x, side, r, sink in [(900, 430, 110, .35), (1250, -390, 70, .3), (1650, -500, 160, .4),
                             (2450, 580, 210, .45), (3450, -430, 95, .3), (4300, 520, 170, .4)]:
        y = road_y(x) + side
        rocks.append((np.array([x, y, terrain(x, y) + r * (1 - 2 * sink)]), r))
    # a ruined retaining wall standing out of the drop on the right, facing the road
    wy0 = road_y(1430.) - 360.
    top = terrain(1430., road_y(1430.)) + 280.
    wall = (np.array([1400., wy0 - 900., top - 900.]), np.array([1460., wy0, top]))
    return rocks, wall


def camera_rays(cam, yaw, pitch):
    fwd = np.array([np.cos(pitch) * np.cos(yaw), np.cos(pitch) * np.sin(yaw), np.sin(pitch)])
    right = np.array([np.sin(yaw), -np.cos(yaw), 0.])
    up = np.cross(right, fwd)
    tx = np.tan(np.radians(HFOV) / 2)
    u = (np.arange(W) + .5) / W * 2 - 1
    vv = ((np.arange(H) + .5) / H * 2 - 1) * H / W
    d = fwd + (u[None, :, None] * right + -vv[:, None, None] * up) * tx
    return d / np.linalg.norm(d, axis=-1, keepdims=True)


def cast(cam, rays):
    far = 1.2e4
    t_hit = np.full(rays.shape[:2], np.inf)
    t0 = np.full(rays.shape[:2], 5.)
    above0 = cam[2] + rays[..., 2] * 5. > terrain(cam[0] + rays[..., 0] * 5., cam[1] + rays[..., 1] * 5.)
    t = 5.
    lo = np.zeros(rays.shape[:2])
    found = np.zeros(rays.shape[:2], bool)
    while t < far:
        t_next = t + max(6., .018 * t)
        p = cam + rays * t_next
        below = p[..., 2] < terrain(p[..., 0], p[..., 1])
        new = below & ~found & above0
        lo[new] = t
        found |= new
        t = t_next
    hi = lo + np.maximum(6., .018 * lo)
    for _ in range(14):
        mid = (lo + hi) / 2
        p = cam + rays * mid[..., None]
        below = p[..., 2] < terrain(p[..., 0], p[..., 1])
        hi = np.where(below, mid, hi)
        lo = np.where(below, lo, mid)
    t_hit[found] = hi[found]
    kind = np.where(found, 0, -1)
    p = cam + rays * np.where(found, t_hit, 0.)[..., None]
    normal = terrain_normal(p[..., 0], p[..., 1])

    rocks, (bmin, bmax) = scene_objects()
    for centre, r in rocks:
        oc = cam - centre
        b = (rays * oc).sum(-1)
        disc = b * b - (oc @ oc - r * r)
        ts = -b - np.sqrt(np.maximum(disc, 0.))
        hit = (disc > 0) & (ts > 1.) & (ts < t_hit)
        t_hit[hit] = ts[hit]
        kind[hit] = 1
        hp = cam + rays[hit] * ts[hit][:, None]
        rn = (hp - centre) / r
        # a little lumpiness so rocks are not billiard balls
        rn += .18 * np.sin(hp[:, [1, 2, 0]] / 23.)
        normal[hit] = rn / np.linalg.norm(rn, axis=-1, keepdims=True)
    inv = 1. / np.where(np.abs(rays) < 1e-9, 1e-9, rays)
    t1 = (bmin - cam) * inv
    t2 = (bmax - cam) * inv
    tn = np.minimum(t1, t2).max(-1)
    tf = np.maximum(t1, t2).min(-1)
    hit = (tn < tf) & (tn > 1.) & (tn < t_hit)
    t_hit[hit] = tn[hit]
    kind[hit] = 2
    axis = np.argmax(np.minimum(t1, t2), -1)
    bn = np.zeros(rays.shape)
    np.put_along_axis(bn, axis[..., None], -np.sign(np.take_along_axis(rays, axis[..., None], -1)), -1)
    normal[hit] = bn[hit]

    sky = ~np.isfinite(t_hit)
    depth = np.where(sky, 1e7, t_hit)
    wp = cam + rays * depth[..., None]
    s = wp[..., 1] - road_y(wp[..., 0])
    stencil = np.where((kind == 0) & (np.abs(s) < 300.), 3., 0.)
    return wp, normal, depth, stencil


def carrier(t):
    """Carrier eye, ping origin and road frame at time t walking up the road."""
    x = WALK * t
    y = road_y(x)
    g = terrain(x, y)
    heading = np.arctan2(road_y(x + 50.) - road_y(x - 50.), 100.)
    cam = np.array([x, y, g + 165.])
    origin = np.array([x, y, g + 210.])
    return cam, origin, heading, (x, y, g), (np.cos(heading), np.sin(heading), 0.)


def to_srgb(lin):
    lin = np.clip(lin, 0., 1.)
    return np.where(lin <= .0031308, 12.92 * lin, 1.055 * lin ** (1 / 2.4) - .055)


_GEOMETRY = {}


def render(clock, ping_times, view_t):
    cam, _, heading, centre, fwd = carrier(view_t)
    if view_t not in _GEOMETRY:
        _GEOMETRY[view_t] = cast(cam, camera_rays(cam, heading, np.radians(-6.)))
    wp, normal, depth, stencil = _GEOMETRY[view_t]
    pings = []
    for pt in sorted(ping_times, reverse=True)[:3]:
        pings.append((*carrier(pt)[1], pt))
    while len(pings) < 3:
        pings.append(EMPTY)
    rgb = shade(wp, normal, depth, stencil, cam, clock, pings, centre, fwd)
    return (to_srgb(rgb) * 255 + .5).astype(np.uint8)


def main():
    from PIL import Image, ImageDraw

    out = Path(sys.argv[1]) if len(sys.argv) > 1 else OUT
    out.mkdir(parents=True, exist_ok=True)
    frames = []
    for dt in (.5, 1.5, 3., 6.):
        img = render(dt, [0.], 0.)
        frames.append((f"one ping, t = {dt:g} s", f"aux_ping_t{dt:g}s".replace(".", "_") + ".png", img))
    img = render(6.8, [0., PERIOD, 2 * PERIOD], 6.8)
    frames.append(("three pings (0, 3, 6 s), t = 6.8 s", "aux_three_pings.png", img))
    for _, name, img in frames:
        Image.fromarray(img).save(out / name)
        print(out / name)
    sheet = Image.new("RGB", (W * 2 + 12, (H + 30) * 3 + 8), (20, 20, 20))
    draw = ImageDraw.Draw(sheet)
    for i, (label, _, img) in enumerate(frames):
        x, y = (i % 2) * (W + 12), (i // 2) * (H + 30)
        sheet.paste(Image.fromarray(img), (x, y + 26))
        draw.text((x + 6, y + 6), label, fill=(232, 176, 112))
    sheet.save(out / "aux_contact_sheet.png")
    print(out / "aux_contact_sheet.png")


if __name__ == "__main__":
    main()
