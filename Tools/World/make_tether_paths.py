"""Tether paths and exploration zones for the six reachable off-road POIs (task TETHER).

The road tether (BPC_RoadTether + USaskartaTetherSubsystem) measures the carrier's distance to the
nearest ALLOWED line: the road spline plus every actor tagged Saskarta.TetherPath, and reports 0
inside any actor tagged Saskarta.ExploreZone. This tool turns the layer-2 spurs into those actors.

Inputs (offline, no editor):
  Tools/World/offroad_poi_locations.json   which POIs are reachable (O01, O03, O06, O09, O10, O14)
  Tools/World/setdress_sites.json          each POI's spur polyline (poi.spur.waypoints_cm, point 0
                                           on the road centreline), its site centre and its
                                           exploration_zone_radius_m
  Saved/TerrainRebuild/Current_u16.png     the terrain (Tools/Story/build_road_profile.py Terrain)

Outputs:
  Tools/World/tether_paths.json            the paths (ground-snapped points, cm), the zones, the
                                           grades and, for rerouted spurs, new way-marker spots
  Saved/Tether/scripts/tether_*.py         one small editor script per actor, for Hayba python_run
                                           (5 s deadline; none of try / getattr / open( / .replace(
                                           / new_level( / unreal.Guid( ). Each script deletes the
                                           actor it made before (tag TETHER_<poi>) and spawns it
                                           again, so a rerun is safe.

A spur whose max grade (20 m windows, as setdress_offroad.spur measures it) is over MAX_GRADE_PCT
is rerouted by a grade-limited A* over the heightmap: it finds switchbacks from the same road
junction to the site centre. O01 (49 %) is the one that needs it.

    python Tools/World/make_tether_paths.py            # build tether_paths.json + the editor scripts
    python Tools/World/make_tether_paths.py --check    # build in memory, print the table, write nothing
    python Tools/World/make_tether_paths.py send --owner LANE_SD [--only O01] [--port N]
        # the SETDRESS lane: send the scripts to the live editor (needs the post-build plugin and
        # the editor gate held by --owner; sends paths, then zones, then a save per actor)
"""
import argparse
import heapq
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, 'Tools', 'Story'))
import build_road_profile as brp  # noqa: E402

LOCATIONS = os.path.join(HERE, 'offroad_poi_locations.json')
SITES = os.path.join(HERE, 'setdress_sites.json')
OUT_JSON = os.path.join(HERE, 'tether_paths.json')
SCRIPT_DIR = os.path.join(ROOT, 'Saved', 'Tether', 'scripts')

MAX_GRADE_PCT = 20.0      # the target for every path (task TETHER: O01 rerouted to <= 20 %)
REROUTE_OVER_PCT = 20.5   # reroute only spurs clearly over the target (O10 reads 20 % rounded)
CELL_M = 5.0              # A* grid
MARGIN_M = 220.0          # A* search box around junction + centre
MAX_SLOPE = 0.70          # terrain gradient (rise/run) the path may cross: ~35 deg, walkable 44.7
SPLINE_STEP_M = 10.0      # spline point spacing (Linear points, each ground-snapped)
PROFILE_STEP_M = 10.0     # grade sampling (setdress_offroad.spur)
SMOOTH_M = 4.0            # Ground.zs sample offset
MARK_M = 70.0             # way-marker spacing (setdress_offroad.SPUR_MARK_M)
WARN_M = 10.0             # BPC_RoadTether.WarnDistance
BREACH_M = 20.0           # BPC_RoadTether.BreachDistance
BANNED = ('try', 'getattr', 'open(', '.replace(', 'new_level(', 'unreal.Guid(')
TAG_PATH = 'Saskarta.TetherPath'
TAG_ZONE = 'Saskarta.ExploreZone'


# ------------------------------------------------------------------------------------------ terrain

class Ground:
    """Heights in metres from the planned terrain (build_road_profile.Terrain); XY in metres."""

    def __init__(self, terrain=None):
        self.T = terrain if terrain is not None else brp.Terrain(brp.HEIGHTMAP)

    def z(self, x_m, y_m):
        return np.asarray(self.T.height(np.asarray(x_m) * 100.0, np.asarray(y_m) * 100.0), float)

    def zs(self, x_m, y_m):
        """Height averaged over a 9 x 9 m patch (3 x 3 samples, 4 m apart): the ground a walker
        feels over a 20 m window, without the 1 m heightmap's micro-relief (which alone reads as
        25-35 % on any 5 m step of the O01 bench)."""
        x_m, y_m = np.asarray(x_m, float), np.asarray(y_m, float)
        acc = 0.0
        for dx in (-SMOOTH_M, 0.0, SMOOTH_M):
            for dy in (-SMOOTH_M, 0.0, SMOOTH_M):
                acc = acc + self.z(x_m + dx, y_m + dy)
        return acc / 9.0

    def slope(self, x_m, y_m):
        return np.asarray(self.T.gradient(np.asarray(x_m) * 100.0, np.asarray(y_m) * 100.0), float)


def road_polyline_m():
    return brp.Road(brp.SPLINE_POINTS_CM).P[:, :2] / 100.0


def resample(pts, step):
    """Points every `step` metres along a polyline (N,2), ends kept."""
    pts = np.asarray(pts, float)
    out = [pts[0]]
    for a, b in zip(pts[:-1], pts[1:]):
        L = float(np.linalg.norm(b - a))
        n = max(1, int(math.ceil(L / step)))
        for k in range(1, n + 1):
            out.append(a + (b - a) * (k / n))
    return np.array(out)


def resample_arc(pts, step):
    """Points every `step` metres of arc length along the whole polyline (corners not kept), end kept."""
    pts = np.asarray(pts, float)
    d = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])
    s = np.append(np.arange(0.0, d[-1], step), d[-1])
    x = np.interp(s, d, pts[:, 0])
    y = np.interp(s, d, pts[:, 1])
    return np.stack([x, y], axis=1), s


def max_grade_pct(pts, ground, smooth=True):
    """setdress_offroad.spur's measure (10 m samples, grade per step, 2-step = 20 m window mean), with
    the samples spaced by arc length over the whole path, so short corner-to-corner pieces of a
    switchback don't turn 1 m heightmap relief into false spikes. For the original 1-3 segment spurs
    it gives the same figures. smooth=True reads Ground.zs (the criterion); smooth=False the raw
    heightmap (reported as raw_grade_pct)."""
    seg, s = resample_arc(pts, PROFILE_STEP_M)
    z = ground.zs(seg[:, 0], seg[:, 1]) if smooth else ground.z(seg[:, 0], seg[:, 1])
    d = np.diff(s)                   # walked distance (a hairpin's chord is shorter than its arc)
    g = np.abs(np.diff(z)) / np.maximum(d, 1e-3)
    g20 = np.convolve(g, np.ones(2) / 2, mode='same') if len(g) > 1 else g
    return float(g20.max()) * 100.0


def length_m(pts):
    return float(np.linalg.norm(np.diff(np.asarray(pts, float), axis=0), axis=1).sum())


# ------------------------------------------------------------------------------------ switchbacks

_MOVES = [(1, 0), (0, 1), (-1, 0), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1),
          (2, 1), (1, 2), (-1, 2), (-2, 1), (-2, -1), (-1, -2), (1, -2), (2, -1)]


def plan_switchbacks(a, b, ground, max_grade=MAX_GRADE_PCT / 100.0):
    """Grade-limited A* from a to b (metres). Every edge climbs <= max_grade and crosses terrain no
    steeper than MAX_SLOPE; the cheapest such route zig-zags up a steep face (switchbacks)."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    x0, y0 = min(a[0], b[0]) - MARGIN_M, min(a[1], b[1]) - MARGIN_M
    nx = int((max(a[0], b[0]) + MARGIN_M - x0) / CELL_M) + 1
    ny = int((max(a[1], b[1]) + MARGIN_M - y0) / CELL_M) + 1
    # heights on a half-cell grid, so every move's midpoint is a sample too (a knight move's midpoint
    # falls between nodes; checking it keeps the 10 m profile under the limit, not just the nodes)
    hx, hy = np.meshgrid(x0 + np.arange(2 * nx - 1) * CELL_M / 2, y0 + np.arange(2 * ny - 1) * CELL_M / 2)
    # smoothed (Ground.zs) like the grade measure: the 1 m heightmap's micro-relief would otherwise
    # wall off every route on a bench
    ZH = ground.zs(hx, hy)
    SH = ground.slope(hx, hy)

    def node(p):
        return (int(round((p[0] - x0) / CELL_M)), int(round((p[1] - y0) / CELL_M)))

    start, goal = node(a), node(b)
    gi, gj = goal

    def h(i, j):
        return math.hypot(i - gi, j - gj) * CELL_M

    best = {start: 0.0}
    came = {}
    heap = [(h(*start), 0.0, start)]
    while heap:
        _, cost, cur = heapq.heappop(heap)
        if cur == goal:
            break
        if cost > best.get(cur, math.inf) + 1e-9:
            continue
        i, j = cur
        z0 = ZH[2 * j, 2 * i]
        for di, dj in _MOVES:
            ni, nj = i + di, j + dj
            if ni < 0 or nj < 0 or ni >= nx or nj >= ny:
                continue
            L = math.hypot(di, dj) * CELL_M
            zm, z1 = ZH[2 * j + dj, 2 * i + di], ZH[2 * nj, 2 * ni]
            gr = max(abs(z1 - z0) / L, 0.5 * (abs(zm - z0) + abs(z1 - zm)) / L)
            if gr > max_grade:
                continue
            # the ground under the edge (its midpoint and far end) must be walkable
            if (ni, nj) != goal and (SH[2 * nj, 2 * ni] > MAX_SLOPE or SH[2 * j + dj, 2 * i + di] > MAX_SLOPE):
                continue
            nc = cost + L * (1.0 + 2.0 * gr)
            if nc < best.get((ni, nj), math.inf):
                best[(ni, nj)] = nc
                came[(ni, nj)] = cur
                heapq.heappush(heap, (nc + h(ni, nj), nc, (ni, nj)))
    if goal not in came and goal != start:
        return None
    path = [goal]
    while path[-1] != start:
        path.append(came[path[-1]])
    path.reverse()
    pts = np.array([(x0 + i * CELL_M, y0 + j * CELL_M) for i, j in path])
    pts[0], pts[-1] = a, b
    return pts


def simplify(pts, ground, max_grade_pct=MAX_GRADE_PCT, tol_m=4.0):
    """Greedy: from each kept point, reach as far as possible while the straight chord stays within
    tol_m of the A* route and its own 20 m-window grade stays under max_grade_pct."""
    pts = np.asarray(pts, float)
    out = [pts[0]]
    i = 0
    while i < len(pts) - 1:
        j = i + 1
        k = j
        while k < len(pts):
            a, b = pts[i], pts[k]
            ab = b - a
            L2 = float(ab @ ab) or 1e-9
            mid = pts[i:k + 1]
            t = np.clip(((mid - a) @ ab) / L2, 0, 1)
            dev = float(np.max(np.linalg.norm(mid - (a + t[:, None] * ab), axis=1)))
            if dev > tol_m or max_grade_pct_seg(a, b, ground) > max_grade_pct:
                break
            j = k
            k += 1
        out.append(pts[j])
        i = j
    return np.array(out)


def max_grade_pct_seg(a, b, ground):
    return max_grade_pct(np.array([a, b]), ground) if np.linalg.norm(b - a) > 1e-6 else 0.0


# ------------------------------------------------------------------------------------------- build

def load_inputs():
    locs = json.load(open(LOCATIONS, encoding='utf8'))
    reach = [p['id'] for p in locs['pois'] if p.get('reachable')]
    sites = {s['id'].split('_')[0]: s for s in json.load(open(SITES, encoding='utf8'))['sites']}
    out = []
    for pid in reach:
        s = sites.get(pid)
        if s is None or not s.get('poi', {}).get('spur'):
            raise SystemExit('%s is reachable but setdress_sites.json has no spur for it' % pid)
        p = s['poi']
        out.append(dict(id=pid, site=s['id'], name=p.get('name', s['name']),
                        centre_m=[s['centre_cm'][0] / 100.0, s['centre_cm'][1] / 100.0],
                        radius_m=float(p['exploration_zone_radius_m']),
                        spur_m=[[x / 100.0, y / 100.0] for x, y in p['spur']['waypoints_cm']],
                        junction_road_m=p['spur']['junction_road_m'],
                        spur_grade_pct=p['spur']['max_grade_pct']))
    return out


def markers_along(pts, stop_before_m):
    """Way-marker spots every MARK_M (from 8 m), 2 m to the right of the path, up to the zone edge."""
    seg = resample(pts, 1.0)
    d = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(seg, axis=0), axis=1))])
    out = []
    for m in np.arange(8.0, max(8.0, d[-1] - stop_before_m), MARK_M):
        k = min(int(np.searchsorted(d, m)), len(seg) - 1)
        nxt = seg[min(k + 1, len(seg) - 1)] - seg[max(k - 1, 0)]
        nxt = nxt / (np.linalg.norm(nxt) or 1.0)
        p = seg[k] + np.array([-nxt[1], nxt[0]]) * 2.0
        out.append([round(float(p[0]) * 100.0, 1), round(float(p[1]) * 100.0, 1)])
    return out


def build(ground=None):
    ground = ground or Ground()
    paths, zones = [], []
    for poi in load_inputs():
        centre = np.array(poi['centre_m'])
        pts = np.array(poi['spur_m'], float)
        if np.linalg.norm(pts[-1] - centre) > poi['radius_m'] - 10.0:
            pts = np.vstack([pts, centre])       # the spur must end well inside the zone
        grade = max_grade_pct(pts, ground)
        rerouted = False
        if grade > REROUTE_OVER_PCT:
            for limit in (MAX_GRADE_PCT * 0.9, MAX_GRADE_PCT * 0.8, MAX_GRADE_PCT * 0.7):
                raw = plan_switchbacks(pts[0], centre, ground, limit / 100.0)
                if raw is None or max_grade_pct(raw, ground) > MAX_GRADE_PCT:
                    continue
                # fewer corners where the chord still holds the grade; else the raw A* nodes (5-11 m)
                cand = simplify(raw, ground, MAX_GRADE_PCT - 1.0, tol_m=3.0)
                if max_grade_pct(cand, ground) > MAX_GRADE_PCT:
                    cand = raw
                pts, grade, rerouted = cand, max_grade_pct(cand, ground), True
                break
            if not rerouted:
                raise SystemExit('%s: no route under %.0f %% found' % (poi['id'], MAX_GRADE_PCT))
        dense = resample(pts, SPLINE_STEP_M)
        z = ground.z(dense[:, 0], dense[:, 1])
        points_cm = [[round(float(x) * 100.0, 1), round(float(y) * 100.0, 1), round(float(zz) * 100.0, 1)]
                     for (x, y), zz in zip(dense, z)]
        path = dict(id=poi['id'], site=poi['site'], name=poi['name'], junction_road_m=poi['junction_road_m'],
                    rerouted=rerouted, spur_grade_pct=poi['spur_grade_pct'], max_grade_pct=round(grade, 1),
                    raw_grade_pct=round(max_grade_pct(pts, ground, smooth=False), 1),
                    length_m=round(length_m(pts)), corners_cm=[[round(float(x) * 100, 1), round(float(y) * 100, 1)]
                                                               for x, y in pts],
                    points_cm=points_cm)
        if rerouted:
            path['markers_cm'] = markers_along(pts, poi['radius_m'] - 25.0)
        paths.append(path)
        cz = float(ground.z(centre[0], centre[1]))
        zones.append(dict(id=poi['id'], site=poi['site'], centre_cm=[round(centre[0] * 100, 1), round(centre[1] * 100, 1),
                                                                     round(cz * 100, 1)],
                          radius_cm=round(poi['radius_m'] * 100.0, 1)))
    return dict(generated_by='Tools/World/make_tether_paths.py',
                conventions=dict(xy='world cm', z='heightmap ground cm (the scripts re-snap to the landscape by trace)',
                                 point0='each path starts on the road centreline at its junction',
                                 tags=[TAG_PATH, TAG_ZONE], warn_m=WARN_M, breach_m=BREACH_M,
                                 max_grade_pct=MAX_GRADE_PCT),
                paths=paths, zones=zones)


# ------------------------------------------------------------------------------ reference tether
# The same rules as USaskartaTetherSubsystem, on polylines, for the offline tests and --check.

def dist_to_polyline(p, poly):
    p = np.asarray(p, float)[:2]
    a, b = poly[:-1], poly[1:]
    ab = b - a
    t = np.clip(np.sum((p - a) * ab, axis=1) / np.maximum(np.sum(ab * ab, axis=1), 1e-9), 0, 1)
    q = a + ab * t[:, None]
    d = np.linalg.norm(q - p, axis=1)
    k = int(np.argmin(d))
    return float(d[k]), k, float(t[k]), q[k]


def tether_query(p, road, paths, zones):
    """(tether_m, road_m_dist, nearest_is_path, in_zone): min over road + paths, 0 inside a zone."""
    rd = dist_to_polyline(p, road)[0]
    best, on_path = rd, False
    for poly in paths:
        d = dist_to_polyline(p, poly)[0]
        if d < best:
            best, on_path = d, True
    in_zone = any(math.hypot(p[0] - c[0], p[1] - c[1]) <= r for c, r in zones)
    return (0.0 if in_zone else best), rd, on_path, in_zone


def holds_road_progress(road_dist_m, nearest_is_path, in_zone, hold_m=WARN_M):
    """USaskartaTetherSubsystem::IsDetour: off the road by more than the warn band, on a path/zone."""
    return road_dist_m > hold_m and (nearest_is_path or in_zone)


def road_m_at(p, road):
    """Road metre (walk order, from point 54) of the nearest road point."""
    _, k, t, _ = dist_to_polyline(p, road)
    seg = np.linalg.norm(np.diff(road, axis=0), axis=1)
    return float(seg[:k].sum() + seg[k] * t)


# ----------------------------------------------------------------------------------- editor script

PATH_SCRIPT = r'''
world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
syslib = unreal.SystemLibrary


def ground_z(x, y, z):
    r = syslib.line_trace_single(world, unreal.Vector(x, y, z + 3000.0), unreal.Vector(x, y, z - 3000.0),
                                 unreal.TraceTypeQuery.TRACE_TYPE_QUERY1, True, [], unreal.DrawDebugTrace.NONE, True)
    h = r
    if isinstance(r, tuple) and len(r) == 2 and not isinstance(r[0], unreal.HitResult):
        h = r[1] if r[0] else None
    if h is None:
        return z, 0
    t = h.to_tuple()
    if not t[0] or not isinstance(t[9], unreal.LandscapeProxy):
        return z, 0
    return t[5].z, 1


old = 0
CLS = unreal.SaskartaTetherPath if KIND == 'path' else unreal.SaskartaExploreZone
for a in unreal.GameplayStatics.get_all_actors_with_tag(world, 'TETHER_' + POI):
    if not isinstance(a, CLS):
        continue  # a POI's path and zone share the tag: replace only this kind
    eas.destroy_actor(a)
    old += 1
x0, y0, z0 = POINTS[0]
if KIND == 'path':
    a = eas.spawn_actor_from_class(unreal.SaskartaTetherPath, unreal.Vector(x0, y0, z0), unreal.Rotator())
    sp = a.get_editor_property('path')
    sp.clear_spline_points(False)
    snapped = 0
    for x, y, z in POINTS:
        gz, ok = ground_z(x, y, z)
        snapped += ok
        sp.add_spline_point(unreal.Vector(x, y, gz + 20.0), unreal.SplineCoordinateSpace.WORLD, False)
    for i in range(len(POINTS)):
        sp.set_spline_point_type(i, unreal.SplinePointType.LINEAR, False)
    sp.update_spline()
    a.set_folder_path('Tether/Paths')
    a.set_actor_label('TetherPath_' + POI)
    tag = 'Saskarta.TetherPath'
else:
    gz, snapped = ground_z(x0, y0, z0)
    a = eas.spawn_actor_from_class(unreal.SaskartaExploreZone, unreal.Vector(x0, y0, gz), unreal.Rotator())
    a.set_editor_property('radius_cm', RADIUS_CM)
    a.set_folder_path('Tether/Zones')
    a.set_actor_label('ExploreZone_' + POI)
    tag = 'Saskarta.ExploreZone'
a.set_editor_property('poi_id', POI)
a.set_editor_property('is_spatially_loaded', False)
a.set_editor_property('tags', [unreal.Name(tag), unreal.Name('TETHER_' + POI), unreal.Name('TetherGen')])
print('TETHER ' + KIND + ' ' + POI + ' replaced=' + str(old) + ' points=' + str(len(POINTS)) + ' snapped=' + str(snapped) + ' DONE')
'''

SAVE_SCRIPT = r'''
world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
pkgs = [a.get_package() for a in unreal.GameplayStatics.get_all_actors_with_tag(world, 'TetherGen')]
ok = unreal.EditorLoadingAndSavingUtils.save_packages(pkgs, True) if len(pkgs) > 0 else True
print('TETHER save ' + str(len(pkgs)) + ' ok=' + str(ok) + ' DONE')
'''


def editor_script(kind, poi, points, radius_cm=0.0):
    head = ['import unreal', 'KIND = %r' % kind, 'POI = %r' % poi,
            'POINTS = %r' % [tuple(float(v) for v in p) for p in points], 'RADIUS_CM = %r' % float(radius_cm)]
    return validate('\n'.join(head) + '\n' + PATH_SCRIPT)


def validate(script):
    bad = [b for b in BANNED if b in script]
    if bad:
        raise SystemExit('refusing: the script contains banned text %s' % bad)
    compile(script, '<tether>', 'exec')
    return script


def scripts_for(doc):
    out = []
    for p in doc['paths']:
        out.append(('tether_%s_path' % p['id'], editor_script('path', p['id'], p['points_cm'])))
    for z in doc['zones']:
        out.append(('tether_%s_zone' % z['id'], editor_script('zone', z['id'], [z['centre_cm']], z['radius_cm'])))
    out.append(('tether_save', validate('import unreal\n' + SAVE_SCRIPT)))
    return out


# ------------------------------------------------------------------------------------------- main

def table(doc):
    rows = ['| POI | junction road m | spur grade % | path grade % | length m | points | rerouted | zone r m |',
            '|---|---|---|---|---|---|---|---|']
    zr = {z['id']: z['radius_cm'] / 100.0 for z in doc['zones']}
    for p in doc['paths']:
        rows.append('| %s | %d | %d | %.1f | %d | %d | %s | %.0f |' % (
            p['id'], p['junction_road_m'], p['spur_grade_pct'], p['max_grade_pct'], p['length_m'],
            len(p['points_cm']), 'yes' if p['rerouted'] else 'no', zr[p['id']]))
    return '\n'.join(rows)


def send(args):
    sys.path.insert(0, HERE)
    import place_setdress as ps  # the Hayba socket client and the editor-gate rule
    import subprocess
    out = subprocess.run([sys.executable, os.path.join(ROOT, 'Tools', 'GameFlow', 'editor_gate.py'), 'status'],
                         capture_output=True, text=True)
    if args.owner not in (out.stdout or ''):
        raise SystemExit('the editor gate is not held by %s (editor_gate.py status); acquire it first' % args.owner)
    doc = json.load(open(OUT_JSON, encoding='utf8'))
    h = ps.Hayba(args.port)
    h.connect()
    for name, script in scripts_for(doc):
        if args.only and not any(o in name for o in args.only.split(',')) and name != 'tether_save':
            continue
        msg = h.run(script)
        print(name, json.dumps(msg)[:400])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', nargs='?', default='build', choices=('build', 'send'))
    ap.add_argument('--check', action='store_true', help='build in memory and print; write nothing')
    ap.add_argument('--owner', help='editor-gate owner (send)')
    ap.add_argument('--only', help='comma list of POI ids (send)')
    ap.add_argument('--port', type=int, default=int(os.environ.get('HAYBA_PORT', '52342')))
    args = ap.parse_args()
    if args.cmd == 'send':
        if not args.owner:
            raise SystemExit('send: pass --owner <gate owner>')
        return send(args)
    doc = build()
    print(table(doc))
    if args.check:
        return
    with open(OUT_JSON, 'w', encoding='utf8') as fh:
        json.dump(doc, fh, indent=1)
    os.makedirs(SCRIPT_DIR, exist_ok=True)
    for name, script in scripts_for(doc):
        with open(os.path.join(SCRIPT_DIR, name + '.py'), 'w', encoding='utf8') as fh:
            fh.write(script)
    print('wrote %s and %d scripts in %s' % (os.path.relpath(OUT_JSON, ROOT), len(scripts_for(doc)),
                                             os.path.relpath(SCRIPT_DIR, ROOT)))


if __name__ == '__main__':
    main()
