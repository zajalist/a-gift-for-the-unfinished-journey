"""Choose the locations of the off-road points of interest (layer 2) on the Gaea heightmap.

    python Tools/World/select_offroad_pois.py      # writes Tools/World/offroad_poi_locations.json

Each POI concept states the terrain it wants (a hilltop, a dry valley floor, a cliff face, flat
ground, a hillside facing the road), a road-metre sector and a distance band from the road
(200-2,000 m). Candidates on a 20 m grid that match the terrain are ranked by their terrain
fit, then the best 60 are tested for SIGHTLINES: from the carrier eye (2.5 m) at road samples
every 25 m, is the POI's top (ground + its silhouette height) above the terrain horizon? The
winner maximises the road length that sees it (within 2.5 km), subject to spacing (>= 450 m
between POIs, >= 250 m from every road-side site). Terrain only: foliage and props are not in
the line-of-sight test (the editor capture pass checks the real view).
"""
import json
import math
import os
import sys

import numpy as np
from scipy import ndimage as nd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, 'Tools', 'Story'))
import build_road_profile as brp  # noqa: E402

OUT = os.path.join(HERE, 'offroad_poi_locations.json')
SITES = os.path.join(HERE, 'setdress_sites.json')
GRID = 20.0            # m
EYE = 2.5
OBS_STEP = 25.0        # road sample spacing, m
VIS_MAX = 2500.0       # a silhouette further than this does not count as "seen from the road"
SPACING = 450.0
SITE_SPACING = 250.0

# id, concept, terrain, (road_m from, to), (dist from, to), top_m, reachable
CONCEPTS = [
    ('O01', 'The Low Voice post (the old post office and its radio room)', 'bench', (250, 1300), (250, 700), 14, True),
    ('O12', 'The old relay (the first High Voice)', 'hilltop', (3300, 5000), (300, 2000), 24, False),
    ('O02', 'The hilltop biofuel refinery', 'hilltop', (1900, 3100), (400, 1600), 26, False),
    ('O03', 'The broken bridge over the dry river', 'valley', (500, 3300), (250, 900), 9, True),
    ('O04', 'The downed airship', 'flat', (0, 5000), (700, 1900), 16, False),
    ('O05', 'The cliff dwellings', 'cliff', (0, 5000), (300, 1600), 22, False),
    ('O06', 'The old dam and the dry reservoir', 'valley', (2400, 4000), (250, 800), 12, True),
    ('O07', 'The observatory', 'peak', (0, 5000), (800, 2000), 15, False),
    ('O08', 'The wind-pump ridge', 'hilltop', (1200, 2400), (400, 1500), 14, False),
    ('O09', 'The caravan graveyard', 'flat', (1400, 2700), (200, 550), 5, True),
    ('O10', "The chemist's workshop", 'bench', (2900, 3700), (250, 650), 9, True),
    ('O11', 'The signal-mirror hill', 'hilltop', (2500, 5000), (500, 2000), 7, False),
    ('O13', 'The terrace orchards', 'hillside', (0, 1600), (300, 1000), 5, False),
    ('O14', 'The granary hamlet (dovecote, bread oven, pens)', 'flat', (300, 1400), (250, 750), 9, True),
    ('O15', 'The great quarry', 'slope', (2500, 3500), (500, 1500), 18, False),
]


def main():
    T = brp.Terrain(brp.HEIGHTMAP)
    R = brp.Road(brp.SPLINE_POINTS_CM)
    step = int(GRID)
    hs = T.h[::step, ::step]
    ys, xs = np.mgrid[0:hs.shape[0], 0:hs.shape[1]]
    X = brp.LAND_X0_CM / 100.0 + xs * GRID
    Y = brp.LAND_Y0_CM / 100.0 + ys * GRID
    prom = hs - nd.uniform_filter(hs, size=15)          # vs the 300 m neighbourhood mean
    gy, gx = np.gradient(hs, GRID)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    local_max = nd.maximum_filter(hs, size=21) == hs

    P = R.P[:, :2] / 100.0
    pts = np.stack([X.ravel(), Y.ravel()], 1)
    D = np.full(len(pts), 1e9)
    S = np.zeros(len(pts))
    Q = np.zeros((len(pts), 2))
    for i in range(len(P) - 1):
        a, b = P[i], P[i + 1]
        ab = b - a
        L2 = ab @ ab
        t = np.clip(((pts - a) @ ab) / L2, 0, 1)
        q = a + t[:, None] * ab
        d = np.linalg.norm(pts - q, axis=1)
        m = d < D
        D[m], S[m], Q[m] = d[m], R.arc[i] + t[m] * math.sqrt(L2), q[m]
    D, S = D.reshape(hs.shape), S.reshape(hs.shape)
    # direction to the road (for "facing the road" hillsides)
    to_road = (Q - pts).reshape(hs.shape + (2,))
    n_down = -np.stack([gx, gy], -1)                     # downhill direction
    facing = np.sum(n_down * to_road, -1) / (np.linalg.norm(n_down, axis=-1) * np.linalg.norm(to_road, axis=-1) + 1e-6)

    obs_s = np.arange(0, R.length, OBS_STEP)
    obs = R.xy(obs_s)                                    # cm
    obs_z = T.height(obs[:, 0], obs[:, 1]) + EYE

    taken = []
    existing = []
    if os.path.exists(SITES):
        for s in json.load(open(SITES, encoding='utf8'))['sites']:
            if s.get('layer', 'road') == 'road':
                existing.append((s['centre_cm'][0] / 100.0, s['centre_cm'][1] / 100.0))
    out = []
    queue = [(c, None) for c in CONCEPTS]
    while queue:
        (cid, name, terrain, (s0, s1), (d0, d1), top, reach), relaxed_from = queue.pop(0)
        m = (S >= s0) & (S <= s1) & (D >= d0) & (D <= d1)
        if terrain == 'hilltop':
            m &= local_max & (prom > 10)
            fit = prom
        elif terrain == 'peak':
            m &= local_max & (prom > 25)
            fit = prom + 0.2 * hs
        elif terrain == 'valley':
            m &= (prom < -6) & (slope < 8)
            fit = -prom - slope
        elif terrain == 'cliff':
            m &= slope > 38
            fit = slope
        elif terrain == 'slope':
            m &= (slope > 22) & (slope < 38) & (facing > 0.5)
            fit = slope * facing
        elif terrain == 'hillside':
            m &= (slope > 10) & (slope < 22) & (facing > 0.6)
            fit = facing * 10 - np.abs(slope - 16)
        elif terrain == 'bench':
            m &= (prom > 4) & (slope < 9)
            fit = prom - slope
        else:  # flat
            m &= slope < 5
            fit = -slope + 0.02 * np.minimum(prom, 10)
        idx = np.argwhere(m)
        ok = []
        for r_, c_ in idx:
            x, y = X[r_, c_], Y[r_, c_]
            if any(math.hypot(x - a, y - b) < SPACING for a, b in taken):
                continue
            if any(math.hypot(x - a, y - b) < SITE_SPACING for a, b in existing):
                continue
            ok.append((fit[r_, c_], r_, c_))
        ok.sort(reverse=True)
        best = None
        for f, r_, c_ in ok[:250 if terrain in ('cliff', 'hillside', 'slope') else 80]:
            x, y = X[r_, c_], Y[r_, c_]
            zt = float(T.height(x * 100, y * 100)) + top
            dist = np.hypot(obs[:, 0] / 100 - x, obs[:, 1] / 100 - y)
            # readable range: a silhouette h metres tall stays above ~0.4 deg out to ~143 h metres
            vis_max = 1200.0 if terrain == 'cliff' else min(VIS_MAX, max(700.0, 143.0 * top))
            if cid == 'O11':
                vis_max = VIS_MAX    # a mirror glint reads far beyond its size
            near = dist < vis_max
            if not near.any():
                continue
            tan, _ = T.horizon_tan(obs[near, 0], obs[near, 1], obs_z[near], np.full(near.sum(), x * 100),
                                   np.full(near.sum(), y * 100), skip_far_m=GRID, step_m=4.0)
            vis = (zt - obs_z[near]) / dist[near] > tan
            seen = obs_s[near][vis]
            k0 = int(np.argmin(dist))
            at_junction = np.sum(np.abs(seen - obs_s[k0]) < 300.0) * OBS_STEP
            score = len(seen) * OBS_STEP + 5.0 * f + (3.0 * at_junction if reach else 0.0)
            if best is None or score > best[0]:
                best = (score, x, y, zt - top, seen, dist[near][vis], f, at_junction, vis_max)
        if best is None or len(best[4]) == 0:
            nxt = {'hilltop': 'bench', 'peak': 'hilltop', 'cliff': 'slope', 'slope': 'hillside', 'bench': 'flat'}.get(terrain)
            if nxt:
                print('%s: nothing seen on %s ground; relaxing to %s' % (cid, terrain, nxt))
                queue.insert(0, ((cid, name, nxt, (s0, s1), (d0, d1), top, reach), relaxed_from or terrain))
                continue
            print('%s: no candidate' % cid)
            continue
        score, x, y, gz, seen, sd, f, at_junction, vis_max = best
        taken.append((x, y))
        # the nearest road metre and the direction from it
        k = int(np.argmin(np.hypot(obs[:, 0] / 100 - x, obs[:, 1] / 100 - y)))
        near_m = float(obs_s[k])
        rp = obs[k] / 100
        bearing = (math.degrees(math.atan2(x - rp[0], -(y - rp[1]))) + 360) % 360
        heading = float(R.heading(near_m))
        rel = (bearing - heading + 540) % 360 - 180
        runs, start, prev = [], None, None
        for s_ in seen:
            if start is None:
                start = prev = s_
            elif s_ - prev > OBS_STEP * 1.5:
                runs.append((start, prev))
                start = prev = s_
            else:
                prev = s_
        if start is not None:
            runs.append((start, prev))
        best_run = max(runs, key=lambda r: r[1] - r[0]) if runs else None
        rec = dict(id=cid, name=name, terrain=terrain, relaxed_from=relaxed_from, reachable=reach, top_m=top,
                   x_m=round(float(x), 1), y_m=round(float(y), 1), ground_z_m=round(float(gz), 1),
                   nearest_road_m=round(near_m), distance_m=round(float(np.hypot(x - rp[0], y - rp[1]))),
                   side='right' if rel > 0 else 'left', relative_deg=round(rel), bearing_deg=round(bearing),
                   visible_road_m=round(len(seen) * OBS_STEP), visible_runs=[[round(a), round(b)] for a, b in runs],
                   best_view_run=[round(best_run[0]), round(best_run[1])] if best_run else None,
                   view_distance_m=[round(float(sd.min())), round(float(sd.max()))] if len(sd) else None,
                   terrain_fit=round(float(f), 1), readable_within_m=round(vis_max),
                   seen_near_junction_m=round(float(at_junction)))
        out.append(rec)
        print('%s %-48s x%6.0f y%6.0f  road %4d m, %4d m %-5s  seen over %4d m of road  %s' % (
            cid, name[:48], x, y, near_m, rec['distance_m'], rec['side'], rec['visible_road_m'], rec['best_view_run']))
    json.dump(dict(generated_by='Tools/World/select_offroad_pois.py', eye_m=EYE, obs_step_m=OBS_STEP,
                   vis_max_m=VIS_MAX, pois=out), open(OUT, 'w', encoding='utf8'), indent=1)
    print('wrote', OUT)


if __name__ == '__main__':
    main()
