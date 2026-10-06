"""Verify ending-staging claims for the final storyline (terrain-only LOS, eye 1.7 m)."""
import sys, math
import numpy as np
sys.path.insert(0, r"D:\UnrealEngine\saskartarad\Tools\Story")
import build_road_profile as brp

T = brp.Terrain(brp.HEIGHTMAP)
R = brp.Road(brp.SPLINE_POINTS_CM)
EYE = 1.7

def ground(x, y):
    return float(T.height(x, y))

def top_hidden(ox, oy, oz_eye, tx, ty, tz_top):
    """metres of the target top below the terrain skyline (<=0 means visible)."""
    tan, _ = T.horizon_tan(np.array([ox]), np.array([oy]), np.array([oz_eye]), np.array([tx]), np.array([ty]))
    D = math.hypot(tx - ox, ty - oy) / 100.0
    t = float(tan[0])
    if not np.isfinite(t):
        return -999.0
    sky = oz_eye + t * D
    return sky - tz_top

def vis_ranges(target_xy, top_z, step=10.0, s0=0.0, s1=None):
    s1 = R.length if s1 is None else s1
    ss = np.arange(s0, s1 + 1e-6, step)
    xy = R.xy(ss)
    eye = T.height(xy[:, 0], xy[:, 1]) + EYE
    tan, _ = T.horizon_tan(xy[:, 0], xy[:, 1], eye, target_xy[0], target_xy[1])
    D = np.hypot(target_xy[0] - xy[:, 0], target_xy[1] - xy[:, 1]) / 100.0
    sky = np.where(np.isfinite(tan), eye + np.where(np.isfinite(tan), tan, 0) * D, -1e9)
    seen = sky <= top_z
    out = []
    for a, b in brp.runs(seen):
        out.append((float(ss[a]), float(ss[b - 1])))
    return out, ss, seen

def rel_angle(s, tx, ty):
    xy = R.xy(np.array([s]))[0]
    brg = math.degrees(math.atan2(tx - xy[0], -(ty - xy[1]))) % 360
    return float(brp.wrap180(brg - float(R.heading(np.array([s]))[0])))

P0 = (298079.6, 483050.0)
g0 = ground(*P0)
SUM = T.peak_near(*brp.SUMMIT_HINT_CM)
print("point0 ground %.1f m; summit %s" % (g0, SUM))

for h in (20, 30, 40):
    rng, _, _ = vis_ranges(P0, g0 + h)
    print("mast at point 0, %d m: top visible on road" % h, [(round(a), round(b)) for a, b in rng])
for h in (30, 40, 50):
    rng, _, _ = vis_ranges(SUM[:2], SUM[2] + h)
    print("mast on summit, %d m: top visible on road" % h, [(round(a), round(b)) for a, b in rng])

print("\nrelative angle to point-0 mast and summit (deg, + right) over the last stretch")
for s in range(4400, 5010, 30):
    print(s, "p0 %+5.0f" % rel_angle(s, *P0), " summit %+5.0f" % rel_angle(s, SUM[0], SUM[1]),
          " dist p0 %4.0f m" % (math.hypot(*(R.xy(np.array([s]))[0] - np.array(P0))) / 100))

# boot point LOS from candidate look-back spots
boot = R.xy(np.array([0.0]))[0]
bz = ground(*boot) + 3.0
for s in (4450, 4500, 4650, 4790, 4840, 4877, 4900, 4950, 5009):
    xy = R.xy(np.array([float(s)]))[0]
    h = top_hidden(xy[0], xy[1], ground(*xy) + EYE, boot[0], boot[1], bz)
    print("from road %d m: boot point (3 m target) %s" % (s, "VISIBLE" if h <= 0 else "hidden by %.0f m" % h))

# other valley landmarks from the high point
for s_obs in (4460, 4877):
    o = R.xy(np.array([float(s_obs)]))[0]
    oz = ground(*o) + EYE
    row = []
    for s_t in (0, 450, 810, 1220, 1980, 2604, 3000, 3400):
        t = R.xy(np.array([float(s_t)]))[0]
        h = top_hidden(o[0], o[1], oz, t[0], t[1], ground(*t) + 3.0)
        row.append("%d:%s" % (s_t, "V" if h <= 0 else "-%d" % h))
    print("from", s_obs, " ".join(row))
