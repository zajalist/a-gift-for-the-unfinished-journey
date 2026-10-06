"""Top-down review plots of the planned set dressing (offline, no editor).

    python Tools/World/plot_setdress_sites.py                 # docs/world/setdress_overview.png
    python Tools/World/plot_setdress_sites.py S07_WaitingWater  # docs/world/setdress_<site>.png (footprints on hillshade)
"""
import json
import math
import os
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import build_setdress_sites as b  # noqa: E402

COL = {'building': '#8a5a3c', 'wall': '#b0875a', 'stone': '#7c7c7c', 'prop': '#3c6ea8', 'rubble': '#c9b28f',
       'rubble_big': '#a08c6c', 'wood': '#6b4a2a', 'wood_post': '#6b4a2a', 'cloth': '#b04a4a', 'veg': '#4a6b3c',
       'hero_tree': '#2d4a22', 'shrub': '#7a8a5a', 'bpp': '#5a3c8a', 'bp': '#5a3c8a', 'fx': '#ff7a00',
       'fx_card': '#cccccc', 'prop_static': '#3c6ea8'}


def main():
    doc = json.load(open(b.OUT, encoding='utf8'))
    W = b.World()
    out = os.path.join(ROOT, 'docs', 'world')
    os.makedirs(out, exist_ok=True)
    want = sys.argv[1:]
    if not want:
        fig, ax = plt.subplots(figsize=(11, 9))
        xs = np.concatenate([W.P[:, 0], [s['centre_cm'][0] / 100 for s in doc['sites']]])
        ys = np.concatenate([W.P[:, 1], [s['centre_cm'][1] / 100 for s in doc['sites']]])
        x0, x1, y0, y1 = xs.min() - 300, xs.max() + 300, ys.min() - 300, ys.max() + 300
        gx = np.arange(x0, x1, 8.0)
        gy = np.arange(y0, y1, 8.0)
        X, Y = np.meshgrid(gx, gy)
        Z = W.T.height(X * 100, Y * 100)
        ax.imshow(Z, extent=(x0, x1, y1, y0), cmap='gray', alpha=0.8)
        ax.contour(X, Y, Z, levels=np.arange(-450, 220, 20), colors='#8899aa', linewidths=0.3)
        ax.plot(W.P[:, 0], W.P[:, 1], color='#e8b070', lw=1.5)
        for s in doc['sites']:
            cx, cy = s['centre_cm'][0] / 100, s['centre_cm'][1] / 100
            if s.get('layer') == 'offroad':
                p = s['poi']
                ax.plot(cx, cy, marker='*', ms=13, color='#ffd24a' if p['reachable'] else '#c890ff', mec='black')
                ax.text(cx + 40, cy - 40, s['id'], fontsize=7, color='#ffd24a' if p['reachable'] else '#e0c8ff')
                if p.get('spur'):
                    w = np.array(p['spur']['waypoints_cm']) / 100.0
                    ax.plot(w[:, 0], w[:, 1], '--', color='#ffd24a', lw=1.2)
                continue
            lone = s['id'][0] in 'LR'
            ax.add_patch(plt.Circle((cx, cy), max(8, s['radius_m']), fill=False, lw=1,
                                    color='#6ec1ff' if lone else '#ff6e6e'))
            ax.text(cx + 12, cy, s['id'].split('_')[0], fontsize=6, color='white')
        ax.set_title('Set dressing: red = road POIs, blue = lone sites, stars = off-road POIs (gold = reachable, dashed = spur)')
        ax.set_aspect('equal')
        fig.savefig(os.path.join(out, 'setdress_overview.png'), dpi=110, bbox_inches='tight')
        print('wrote setdress_overview.png')
        return
    for sid in want:
        s = next(x for x in doc['sites'] if x['id'] == sid)
        cx, cy = s['centre_cm'][0] / 100, s['centre_cm'][1] / 100
        R = s['radius_m'] + 15
        fig, ax = plt.subplots(figsize=(9, 9))
        gx = np.arange(cx - R, cx + R, 0.5)
        gy = np.arange(cy - R, cy + R, 0.5)
        X, Y = np.meshgrid(gx, gy)
        Z = W.T.height(X * 100, Y * 100)
        dzdx, dzdy = np.gradient(Z, 0.5)
        shade = np.clip(0.6 - 0.8 * (dzdx * 0.7 + dzdy * 0.7), 0, 1)
        ax.imshow(shade, extent=(cx - R, cx + R, cy + R, cy - R), cmap='gray', vmin=0, vmax=1)
        ax.contour(X, Y, Z, levels=20, colors='#556', linewidths=0.4)
        seg = W.P
        ax.plot(seg[:, 0], seg[:, 1], color='#e8b070', lw=9 * 72 / (2 * R) * 9 / 9 * 4, alpha=0.5)
        ax.plot(seg[:, 0], seg[:, 1], color='#e8b070', lw=0.8)
        for p in s['placements']:
            c = b.rect_corners(p['x_cm'] / 100, p['y_cm'] / 100, p['yaw'], max(p['size_m'][0], 0.2), max(p['size_m'][1], 0.2))
            ax.add_patch(plt.Polygon(c, closed=True, fc=COL.get(p['cat'], '#999'), ec='black', lw=0.3, alpha=0.85))
        for v in s['views']:
            ax.plot(v['cam_cm'][0] / 100, v['cam_cm'][1] / 100, 'c^', ms=5)
        ax.set_xlim(cx - R, cx + R)
        ax.set_ylim(cy + R, cy - R)
        ax.set_aspect('equal')
        ax.set_title('%s (%d placements)' % (sid, len(s['placements'])))
        fig.savefig(os.path.join(out, 'setdress_%s.png' % sid), dpi=100, bbox_inches='tight')
        print('wrote setdress_%s.png' % sid)


if __name__ == '__main__':
    main()
