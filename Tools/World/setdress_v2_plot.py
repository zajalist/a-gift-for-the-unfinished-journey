"""Review plots for set dressing V2 sites, drawn from the placements (so an older JSON renders the same way).

    python Tools/World/setdress_v2_plot.py                       # S07: new top-down, new axonometric, old-vs-new
    python Tools/World/setdress_v2_plot.py --old <json|rev>      # compare against another file or git revision
    python Tools/World/setdress_v2.py --preview L05_RidgeHamlet  # any site by archetype (preview(), no JSON)

Top-down: every placement as its oriented footprint (walls shaded by their VISIBLE height: the mesh height
minus the sink), the ground decals rasterised per surface (overlapping patches of one surface merge, as the
decals' own opacity does not stack past full), ISM rubble and plants as small marks. Axonometric: an
orthographic 3/4 view from the road side over the village core, the Gaea terrain shaded with the decals
blended into it, every placement an extruded oriented box (painter's algorithm, back faces culled). The old
side defaults to the S07 V2.0 data that stands in the level (commit 5d05c65f); its own plot,
docs/world/setdress_v2_S07_WaitingWater.png, is kept as it was. Pure offline: matplotlib and the heightmap.
"""
import argparse
import json
import math
import os
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import build_setdress_sites as B  # noqa: E402
import setdress_v2 as V  # noqa: E402

OLD_REV = '5d05c65f'
NEW_JSON = os.path.join(HERE, 'setdress_v2_sites.json')
DOCS = os.path.join(ROOT, 'docs', 'world')
SURF_COL = dict(packed_earth='#9c7448', path='#4f3624', gravel='#9b9384', rubble_dust='#d8c7a6', soot='#1c1a18',
                dry_mud='#e0cfae')
CORE = (-20.0, 52.0, -24.0, 48.0)            # u0, u1, v0, v1 of the top-down comparison window (site metres)
VILLAGE = (2.0, 50.0, 4.0, 48.0)             # the axonometric window: the village core and the market


def load(src):
    """A V2 sites JSON from a path or a git revision."""
    if os.path.exists(src):
        return json.load(open(src, encoding='utf8'))
    txt = subprocess.check_output(['git', '-C', ROOT, 'show', '%s:Tools/World/setdress_v2_sites.json' % src])
    return json.loads(txt.decode('utf8'))


def site_of(doc, sid='S07_WaitingWater'):
    return [s for s in doc['sites'] if s['id'] == sid][0]


def vis_h(p):
    if p.get('vis_h') is not None:
        return p['vis_h']
    return p['size_m'][2] - p['settle'].get('sink_cm', 0) / 100.0


def kind(p):
    """A drawing class for a placement."""
    if p['cat'] == 'rubble' or p.get('block') in ('fan', 'base') and p['ism']:
        return 'rubble'
    if p['cat'] == 'shrub':
        return 'grass' if p['key'].startswith('MV_Grass') else 'shrub'
    if p['cat'] == 'rubble_big' or p['key'] == 'B01_rubble01':
        return 'heap'
    if p['key'] in B.GROUND_COVERS or p['key'] == 'B01_channel01':
        return 'cover'
    if p['cat'] == 'cloth':
        return 'cloth'
    if p.get('contact') == 'bear' or p.get('block') == 'beam' or p['cat'] == 'wood':
        return 'wood'
    if p.get('contact') == 'rigid' or p['cat'] in ('wall', 'building'):
        return 'arch'
    return 'prop'


def to_site(F, p):
    u, v = F.site(p['x_cm'] / 100.0, p['y_cm'] / 100.0)
    return u, v, p['yaw'] - V.site_yaw(F)


def outline(g, F, n=28):
    """A decal patch outline in site metres (ellipse or capsule)."""
    u, v = F.site(g['x_cm'] / 100.0, g['y_cm'] / 100.0)
    a = math.radians(g['yaw'] - V.site_yaw(F))
    L, Wd = g['length_m'] / 2.0, g['width_m'] / 2.0
    pts = []
    if g['shape'] == 'capsule' and L > Wd:
        c = L - Wd
        for k in range(n // 2 + 1):
            t = -math.pi / 2 + math.pi * k / (n // 2)
            pts.append((c + Wd * math.cos(t), Wd * math.sin(t)))
        for k in range(n // 2 + 1):
            t = math.pi / 2 + math.pi * k / (n // 2)
            pts.append((-c + Wd * math.cos(t), Wd * math.sin(t)))
    else:
        for k in range(n):
            t = 2 * math.pi * k / n
            pts.append((L * math.cos(t), Wd * math.sin(t)))
    ca, sa = math.cos(a), math.sin(a)
    return [(u + x * ca - y * sa, v + x * sa + y * ca) for x, y in pts]


# ---------------------------------------------------------------------------- top-down

def ground_raster(site, F, window, res):
    """RGBA of the decal ground on a grid over window (u0, u1, v0, v1) at res m: per surface the MAX coverage
    (strength inside a patch), surfaces composited in their sort order."""
    from matplotlib.path import Path
    import matplotlib.colors as mc
    u0, u1, v0, v1 = window
    us = np.arange(u0, u1, res) + res / 2.0
    vs = np.arange(v0, v1, res) + res / 2.0
    UU, VV = np.meshgrid(us, vs)
    pts = np.stack([UU.ravel(), VV.ravel()], 1)
    img = np.zeros((len(vs), len(us), 4))
    by = {}
    for g in site.get('ground', []):
        by.setdefault(g['surface'], []).append(g)
    for surf in sorted(by, key=lambda k: min(g['sort'] for g in by[k])):
        cov = np.zeros(len(pts))
        for g in by[surf]:
            o = np.array(outline(g, F, 24))
            sel = ((pts[:, 0] >= o[:, 0].min()) & (pts[:, 0] <= o[:, 0].max()) &
                   (pts[:, 1] >= o[:, 1].min()) & (pts[:, 1] <= o[:, 1].max()))
            if not sel.any():
                continue
            inside = Path(o).contains_points(pts[sel])
            cov[sel] = np.maximum(cov[sel], inside * g['strength'])
        a = (0.2 + 0.7 * cov) * (cov > 0)
        a = a.reshape(len(vs), len(us))
        col = np.array(mc.to_rgb(SURF_COL[surf]))
        img[..., :3] = img[..., :3] * (1 - a[..., None]) + col * a[..., None]
        img[..., 3] = img[..., 3] + a * (1 - img[..., 3])
    rgb = np.where(img[..., 3:] > 0, img[..., :3] / np.maximum(img[..., 3:], 1e-6), 0.0)
    return np.concatenate([np.clip(rgb, 0, 1), img[..., 3:]], axis=2)


def site_window(site, F, margin=8.0):
    uv = [F.site(p['x_cm'] / 100.0, p['y_cm'] / 100.0) for p in site['placements']]
    uv = np.array(uv)
    return (uv[:, 0].min() - margin, uv[:, 0].max() + margin, uv[:, 1].min() - margin, uv[:, 1].max() + margin)


def topdown(ax, site, F, title, window=None):
    from matplotlib.patches import Polygon
    import matplotlib.cm as cm
    win = window or site_window(site, F)
    ax.imshow(ground_raster(site, F, win, 0.25), extent=win, origin='lower', zorder=1, interpolation='nearest')
    import matplotlib
    hmap = matplotlib.colormaps['YlOrBr']
    marks = {'rubble': [], 'grass': [], 'shrub': []}
    for p in site['placements']:
        k = kind(p)
        u, v, yaw = to_site(F, p)
        if k in marks:
            marks[k].append((u, v, max(p['size_m'][:2])))
            continue
        sx, sy = max(p['size_m'][0], 0.12), max(p['size_m'][1], 0.12)
        q = B.rect_corners(u, v, yaw, sx, sy)
        if p.get('optional'):
            # a Tripo model not imported yet: its slot, dashed (placed only with --with-optional)
            ax.add_patch(Polygon(q, closed=True, fc='none', ec='#555', lw=0.9, ls='--', zorder=5))
            continue
        if k == 'arch':
            h = vis_h(p)
            fc, z = hmap(min(1.0, max(0.0, h / 9.0)) * 0.8 + 0.2), 5
        else:
            fc, z = {'heap': '#b28a66', 'cover': '#b9ab94', 'cloth': '#b0432f', 'wood': '#6e4a2a', 'prop': '#3d5a80'}[k], 4
        ax.add_patch(Polygon(q, closed=True, fc=fc, ec='#222' if k == 'arch' else 'none', lw=0.3, zorder=z))
    for k, col, s in (('rubble', '#7b4a36', 2.2), ('grass', '#a8984e', 5), ('shrub', '#5f6b2e', 9)):
        if marks[k]:
            a = np.array(marks[k])
            ax.scatter(a[:, 0], a[:, 1], s=s * np.clip(a[:, 2] / 0.5, 0.5, 2.5), c=col, lw=0, zorder=6)
    # the road (4.5 m either side of the spline), where it really runs in this site's frame
    RP = np.array([F.site(x, y) for x, y in F.W.P])
    reach = max(win[1] - win[0], win[3] - win[2]) + 20
    near = np.hypot(RP[:, 0] - (win[0] + win[1]) / 2, RP[:, 1] - (win[2] + win[3]) / 2) < reach
    for a, b in zip(RP[:-1][near[:-1]], RP[1:][near[:-1]]):
        d = b - a
        n = np.array([-d[1], d[0]]) / (np.hypot(*d) or 1.0) * 4.5
        ax.add_patch(Polygon([a + n, b + n, b - n, a - n], closed=True, fc='#8a8580', ec='none', alpha=0.45, zorder=0.5))
    ax.set_aspect('equal')
    ax.set_xlim(win[0], win[1])
    ax.set_ylim(win[2], win[3])
    ax.set_facecolor('#e9dcc6')
    ax.set_title(title, fontsize=11)
    ax.set_xlabel('u (m, along the road)')
    ax.set_ylabel('v (m, right of the road)')
    sm = cm.ScalarMappable(cmap=hmap)
    sm.set_clim(0, 9)
    return sm


# ---------------------------------------------------------------------------- axonometric

class Axo:
    """Orthographic 3/4 projection: azimuth az (deg, 0 = looking along +v), elevation el (deg)."""

    def __init__(self, az=-28.0, el=36.0):
        a, e = math.radians(az), math.radians(el)
        self.right = np.array([math.cos(a), -math.sin(a), 0.0])
        fh = np.array([math.sin(a), math.cos(a), 0.0])
        self.up = fh * math.sin(e) + np.array([0, 0, 1.0]) * math.cos(e)
        self.fwd = fh * math.cos(e) - np.array([0, 0, 1.0]) * math.sin(e)    # into the scene
        self.light = np.array([-0.45, -0.55, 0.7])
        self.light /= np.linalg.norm(self.light)

    def xy(self, P):
        P = np.asarray(P, float)
        return np.stack([P @ self.right, P @ self.up], axis=-1)

    def depth(self, P):
        return float(np.mean(np.asarray(P, float) @ self.fwd))


def shade(col, n, L):
    import matplotlib.colors as mc
    r, g, b = mc.to_rgb(col)
    k = 0.45 + 0.55 * max(0.0, float(np.dot(n, L)))
    return (r * k, g * k, b * k)


def axo(ax, site, F, W, title, window=VILLAGE, cam=None):
    from matplotlib.collections import PolyCollection
    cam = cam or Axo()
    u0, u1, v0, v1 = window
    z0 = F.g((u0 + u1) / 2, (v0 + v1) / 2)

    def G(u, v):
        return F.g(u, v) - z0
    # terrain, the decal ground blended into its colour (sampled at the quad centres)
    step = 0.75
    us, vs = np.arange(u0, u1 + 1e-6, step), np.arange(v0, v1 + 1e-6, step)
    Z = np.array([[G(u, v) for u in us] for v in vs])
    gr = ground_raster(site, F, (us[0], us[-1], vs[0], vs[-1]), step)
    import matplotlib.colors as mc
    polys, cols = [], []
    for j in range(len(vs) - 1):
        for i in range(len(us) - 1):
            q = [(us[i], vs[j], Z[j, i]), (us[i + 1], vs[j], Z[j, i + 1]), (us[i + 1], vs[j + 1], Z[j + 1, i + 1]),
                 (us[i], vs[j + 1], Z[j + 1, i])]
            n = np.cross(np.subtract(q[1], q[0]), np.subtract(q[3], q[0]))
            n = n / np.linalg.norm(n)
            road = F.road_dist(us[i] + step / 2, vs[j] + step / 2) < 4.5
            base = np.array(mc.to_rgb('#8f8a82' if road else '#b5764a'))
            if j < gr.shape[0] and i < gr.shape[1] and not road:
                a = gr[j, i, 3]
                base = base * (1 - a) + gr[j, i, :3] * a
            polys.append((cam.depth(q), cam.xy(q)))
            cols.append(shade(tuple(base), n, cam.light))
    order = np.argsort([-d for d, _ in polys])
    ax.add_collection(PolyCollection([polys[k][1] for k in order], facecolors=[cols[k] for k in order], edgecolors='none',
                                     zorder=1))

    # placements as extruded boxes
    faces = []
    for p in site['placements']:
        u, v, yaw = to_site(F, p)
        if not (u0 <= u <= u1 and v0 <= v <= v1) or p.get('optional'):
            continue
        k = kind(p)
        if k == 'cover' and p['key'] == 'B01_channel01':
            continue
        sx, sy, sz = max(p['size_m'][0], 0.12), max(p['size_m'][1], 0.12), max(p['size_m'][2], 0.05)
        q = B.rect_corners(u, v, yaw, sx, sy)
        gz = [G(a, b) for a, b in q]
        sink = p['settle'].get('sink_cm', 0) / 100.0
        if k == 'arch':
            zb = min(gz) - sink
        elif p.get('contact') == 'bear':
            zb = max(gz) + 2.04 - 0.12 * 0 - 0.12       # on its jambs
        elif p.get('unit_role') == 'cover':
            zb = min(gz) + 3.6 - sz * 0.6                # on its frame
        else:
            zb = sum(gz) / 4.0 - sink * 0.5
        zt = zb + sz
        col = {'arch': '#9a7556', 'heap': '#a47c58', 'cover': '#a99a80', 'cloth': '#9e3b2b', 'wood': '#5e3d22',
               'prop': '#6a6f7a', 'rubble': '#83603f', 'grass': '#b6a25a', 'shrub': '#6e6a36'}[k]
        if k == 'cloth' and p.get('unit_role') == 'frame':
            # a frame: four posts, not a box
            for (a, b) in q:
                pu, pv = u + (a - u) * 0.92, v + (b - v) * 0.92
                qq = B.rect_corners(pu, pv, yaw, 0.12, 0.12)
                faces += box_faces(cam, qq, zb, zt, '#4a3525')
            continue
        faces += box_faces(cam, q, zb, zt, col)
    faces.sort(key=lambda f: -f[0])
    ax.add_collection(PolyCollection([f[1] for f in faces], facecolors=[f[2] for f in faces],
                                     edgecolors=[(0, 0, 0, 0.35) if f[3] else 'none' for f in faces], linewidths=0.25,
                                     zorder=3))
    allxy = np.concatenate([p[1] for p in polys])
    ax.set_xlim(allxy[:, 0].min(), allxy[:, 0].max())
    ax.set_ylim(allxy[:, 1].min(), allxy[:, 1].max())
    ax.set_aspect('equal')
    ax.set_axis_off()
    ax.set_title(title, fontsize=11)


def box_faces(cam, q, zb, zt, col):
    out = []
    top = [(a, b, zt) for a, b in q]
    big = abs(zt - zb) > 0.6
    out.append((cam.depth(top), cam.xy(top), shade(col, np.array([0, 0, 1.0]), cam.light), big))
    for i in range(4):
        a, b = q[i], q[(i + 1) % 4]
        n = np.array([b[1] - a[1], -(b[0] - a[0]), 0.0])
        n /= (np.linalg.norm(n) or 1.0)
        # outward normal: away from the box centre
        cx, cy = sum(x for x, _ in q) / 4, sum(y for _, y in q) / 4
        if np.dot(n[:2], [(a[0] + b[0]) / 2 - cx, (a[1] + b[1]) / 2 - cy]) < 0:
            n = -n
        if np.dot(n, cam.fwd) >= 0:
            continue                                      # back face
        f = [(a[0], a[1], zb), (b[0], b[1], zb), (b[0], b[1], zt), (a[0], a[1], zt)]
        out.append((cam.depth(f), cam.xy(f), shade(col, n, cam.light), big))
    return out


# ---------------------------------------------------------------------------- main

def stats(site):
    P = site['placements']
    core = set(site.get('v2', {}).get('core_blocks') or [])
    walls = [p for p in P if kind(p) == 'arch' and p['key'] != 'AB_Side_Arch' and
             (p.get('block') in core if core else p.get('block', '')[:1] in 'ABCH')]
    hs = [vis_h(p) for p in walls]
    return ('%d placements, %d ISM, %d decals; core walls %d, visible height %.1f-%.1f m (sd %.2f)' % (
        len(P), sum(1 for p in P if p['ism']), len(site.get('ground', [])), len(walls), min(hs), max(hs),
        float(np.std(hs))))


def preview(W, so, path=None):
    """Top-down and axonometric of one composed site (any archetype) side by side, for review before rollout."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    F = V.Frame(W, so['road_m'], so.get('lateral_m') or 0.0)
    cu, cv = so['v2']['core']
    win = site_window(so, F)
    R = max(18.0, min(40.0, max(win[1] - win[0], win[3] - win[2]) / 3.0))
    fig, axs = plt.subplots(1, 2, figsize=(26, 12))
    sm = topdown(axs[0], so, F, '%s (%s), top-down\n%s' % (so['id'], so.get('archetype'), stats(so)), window=win)
    fig.colorbar(sm, ax=axs[0], shrink=0.4, label='visible wall height (m)')
    axo(axs[1], so, F, W, '%s, axonometric over the core' % so['id'], window=(cu - R, cu + R, cv - R, cv + R))
    path = path or os.path.join(DOCS, 'setdress_v2_%s_preview.png' % so['id'])
    fig.savefig(path, dpi=60, bbox_inches='tight')
    plt.close(fig)
    print('plot', path)
    return path


def main(argv=None):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    ap = argparse.ArgumentParser()
    ap.add_argument('--old', default=OLD_REV, help='the older sites JSON (path or git revision)')
    ap.add_argument('--new', default=NEW_JSON)
    args = ap.parse_args(argv)
    W = B.World()
    new = site_of(load(args.new))
    old = site_of(load(args.old))
    F = V.Frame(W, new['road_m'])
    out = []
    fig, ax = plt.subplots(figsize=(12, 15))
    sm = topdown(ax, new, F, 'S07 Waiting Water V2.1, top-down (walls shaded by visible height)\n' + stats(new))
    fig.colorbar(sm, ax=ax, shrink=0.4, label='visible wall height (m)')
    out.append(os.path.join(DOCS, 'setdress_v2_S07_WaitingWater_v21_top.png'))
    fig.savefig(out[-1], dpi=80, bbox_inches='tight')
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(16, 11))
    axo(ax, new, F, W, 'S07 V2.1, axonometric from the road side over the core (orthographic, 36 deg)')
    out.append(os.path.join(DOCS, 'setdress_v2_S07_WaitingWater_v21_axo.png'))
    fig.savefig(out[-1], dpi=90, bbox_inches='tight')
    plt.close(fig)
    fig, axs = plt.subplots(2, 2, figsize=(24, 20))
    topdown(axs[0][0], old, F, 'BEFORE: V2.0 as placed (%s)\n%s' % (args.old, stats(old)), window=CORE)
    topdown(axs[0][1], new, F, 'AFTER: V2.1\n' + stats(new), window=CORE)
    axo(axs[1][0], old, F, W, 'BEFORE: V2.0, axonometric')
    axo(axs[1][1], new, F, W, 'AFTER: V2.1, axonometric')
    out.append(os.path.join(DOCS, 'setdress_v2_S07_compare.png'))
    fig.savefig(out[-1], dpi=65, bbox_inches='tight')
    plt.close(fig)
    for o in out:
        print('plot', o)
    return out


if __name__ == '__main__':
    main()
