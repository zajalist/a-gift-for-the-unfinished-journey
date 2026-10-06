"""Coordinates for the final storyline beats and vignette anchors (terrain-only analysis)."""
import sys, math, json
import numpy as np
sys.path.insert(0, r"D:\UnrealEngine\saskartarad\Tools\Story")
import build_road_profile as brp

T = brp.Terrain(brp.HEIGHTMAP)
R = brp.Road(brp.SPLINE_POINTS_CM)
P0 = (298079.6, 483050.0)
G0 = float(T.height(*P0))
MAST_TOP = G0 + 30.0
SUM = T.peak_near(*brp.SUMMIT_HINT_CM)

def at(s, lateral_m=0.0):
    s = float(s)
    xy = R.xy(np.array([s]))[0]
    k, t = R.locate(np.array([s]))
    k = int(np.ravel(k)[0])
    f = R.P[k + 1, :2] - R.P[k, :2]
    f = f / np.linalg.norm(f)
    right = np.array([-f[1], f[0]])
    p = xy + right * lateral_m * 100.0
    z = float(T.height(p[0], p[1]))
    yaw = math.degrees(math.atan2(f[1], f[0]))
    return dict(s=s, x=round(float(p[0])), y=round(float(p[1])), z_cm=round(z * 100),
                ue_m=round(float(R.ue_spline_distance(np.array([s]))[0]), 1),
                key=round(float(R.input_key(np.array([s]))[0]), 3), yaw=round(yaw, 1))

def mast_info(s):
    xy = R.xy(np.array([float(s)]))[0]
    eye = float(T.height(*xy)) + 1.7
    tan, _ = T.horizon_tan(np.array([xy[0]]), np.array([xy[1]]), np.array([eye]), np.array([P0[0]]), np.array([P0[1]]))
    D = math.hypot(P0[0] - xy[0], P0[1] - xy[1]) / 100.0
    t = float(tan[0])
    sky = eye + t * D if np.isfinite(t) else -1e9
    brg = math.degrees(math.atan2(P0[0] - xy[0], -(P0[1] - xy[1]))) % 360
    rel = float(brp.wrap180(brg - float(R.heading(np.array([float(s)]))[0])))
    return dict(mast_rel=round(rel), mast_vis=bool(sky <= MAST_TOP), mast_dist=round(D))

beats = [0, 150, 300, 450, 490, 810, 1220, 1400, 1980, 2150, 2560, 2600, 2760, 2900, 3050, 3200, 3360, 3400, 3440,
         3600, 3650, 3700, 3850, 4015, 4250, 4460, 4520, 4600, 4760, 4790, 4840, 4877, 4950, 5009.2]
for s in beats:
    a = at(s); m = mast_info(s)
    print("%7.1f  x %7d y %7d z %7d  ue %7.1f key %6.3f yaw %6.1f | mast rel %+4d vis %s d %4d" % (
        s, a['x'], a['y'], a['z_cm'], a['ue_m'], a['key'], a['yaw'], m['mast_rel'], m['mast_vis'], m['mast_dist']))

print("\nside probes (terrain z at +-8/15 m) for placement")
for s in (0, 300, 460, 810, 1220, 1400, 1980, 2580, 2900, 3050, 3400, 4460, 4840, 4877, 4950, 5009.2):
    row = []
    for lat in (-15, -8, 0, 8, 15):
        row.append("%+d:%.1f" % (lat, at(s, lat)['z_cm'] / 100))
    print("%6.0f " % s + "  ".join(row))
