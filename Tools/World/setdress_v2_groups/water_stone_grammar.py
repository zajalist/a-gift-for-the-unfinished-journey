"""Set dressing V2, group 'water and stone features': the small shared grammar of this group's recipes (stones set
in the ground, packing stones, erosion spills, plant clumps, verge links, rectangular courses, ground bands).
Everything is built from setdress_v2.Composer primitives; nothing here talks to Unreal.
"""
import math

import setdress_v2 as V
from setdress_v2 import PIECE_M, terrace_frame

STONES, COBBLES, SHRUBS, TUFTS = V.STONES, V.COBBLES, V.SHRUBS, V.TUFTS
BASE_SETTLE = V.RUBBLE_SETTLE


# ---------------------------------------------------------------------------- small shared grammar

def road_pt(C, u, v):
    """The nearest road-centreline point to (u, v), in site metres."""
    _, q = C.F.W.road_distance([C.F.world(u, v)])
    return C.F.site(float(q[0]), float(q[1]))


def face(u, v, tu, tv):
    return math.degrees(math.atan2(tv - v, tu - u))


def rigid(C, key, u, v, yaw, group, block, sink, scale=1.0, state='stone', mat='stone', **kw):
    """A plumb architectural piece (z so no sample floats; the uphill side buried), with its visible height."""
    H = V.CAT[key]['size_cm'][2] / 100.0 * (max(scale) if isinstance(scale, (tuple, list)) else scale)
    return C.add(key, u, v, yaw, group, 'rigid', scale=scale, block=block, sink_cm=round(sink, 1), material_set=mat,
                 state=state, vis_h=round(H - sink / 100.0, 2), **kw)


def bed(C, u, v, r, n, group='rubble_ism', keys=None, scale=(0.6, 1.2)):
    """Packing stones round the foot of a standing stone or a post: it was set in the ground, not dropped."""
    keys = keys or STONES + COBBLES
    for k in range(n):
        a = 2 * math.pi * (k + C.rng.uniform(-0.3, 0.3)) / n
        rr = r * C.rng.uniform(0.9, 1.35)
        C.add(C.rng.choice(keys), u + rr * math.cos(a), v + rr * math.sin(a), C.rng.uniform(0, 360), group,
              scale=scale, ism=True, settle_over=BASE_SETTLE, block='base')


def spill(C, u, v, n, mean_d=1.2, spread=40.0, lat=0.8, max_d=4.0):
    """A fan of small stones washed DOWNHILL of (u, v): erosion off a cairn, a stone, a wall end."""
    du, dv = C.F.downhill(u, v)
    C.fans.append((u, v, du, dv, 0.3))
    C.scatter_fan(u, v, du, dv, math.degrees(math.atan2(du, -dv)), n, mean_d, spread, lat, max_d=max_d)


def clump(C, u, v, r, n, shrub_p=0.3, avoid=0.4):
    """Dry tufts (and some dead shrubs) in a loose clump: the lee of a stone, a wall foot, a basin corner."""
    for _ in range(n):
        a = C.rng.uniform(0, 2 * math.pi)
        d = r * math.sqrt(C.rng.random())
        pu, pv = u + d * math.cos(a), v + d * math.sin(a)
        if C.on_lane(pu, pv, avoid) or C.near_door(pu, pv, 1.0) or C.F.road_dist(pu, pv) < 6.0:
            continue
        if C.rng.random() < shrub_p:
            C.add(C.rng.choice(SHRUBS), pu, pv, C.rng.uniform(0, 360), 'creep', scale=(0.9, 1.5), ism=True, block='creep')
        else:
            C.add(C.rng.choice(TUFTS), pu, pv, C.rng.uniform(0, 360), 'creep_grass', scale=(0.8, 1.3), ism=True,
                  block='creep')


def verge_link(C, target, width=2.2, strength=0.9, apron=(6.0, 4.5), wander=0.35):
    """A worn path from the road verge (6.5 m off the centreline) to target, with a trodden apron where it
    leaves the road. Returns the path points (a lane), or None when target is already at the verge."""
    W = C.F.W
    d, q = W.road_distance([C.F.world(*target)])
    qu, qv = C.F.site(float(q[0]), float(q[1]))
    du, dv = target[0] - qu, target[1] - qv
    n = math.hypot(du, dv) or 1.0
    du, dv = du / n, dv / n
    start = (qu + du * 6.3, qv + dv * 6.3)
    if apron:
        C.patch('packed_earth', start[0] + du * 1.2, start[1] + dv * 1.2, math.degrees(math.atan2(dv, du)) + 90.0,
                apron[0], apron[1], 0.9, order=1)
    if d < 7.5:
        return None
    return C.path([start, target], width, wander=wander if d > 12 else 0.0, strength=strength)


def standing_stone(C, key, u, v, yaw, scale, sink, lean=0.0, lean_dir=None, group='stone', block='stone', **kw):
    """A stone SET in the ground: plumb or leaning (pitch), sunk, with packing stones at its foot."""
    kw2 = dict(kw)
    if lean:
        # pitch leans the stone's local X; point X at lean_dir (deg, site frame)
        yaw = lean_dir if lean_dir is not None else yaw
        kw2['pitch'] = -abs(lean)
    it = rigid(C, key, u, v, yaw, group, block, sink, scale=scale, **kw2)
    sx, sy = [c / 100.0 * scale for c in V.CAT[key]['size_cm'][:2]]
    bed(C, u, v, 0.5 * max(sx, sy) + 0.12, C.rng.randint(4, 6))
    return it


def pebble_cap(C, u, v, n, top_drop=90.0, group='cap', note='pebbles set on top'):
    """Pebbles stacked on top of a stone by physics (stack=True: single actors, settled in order)."""
    for i in range(n):
        C.add(C.rng.choice(['LF_Rock_07', 'LF_Rock_06', 'LF_Rock_07']), u + C.rng.uniform(-0.06, 0.06),
              v + C.rng.uniform(-0.06, 0.06), C.rng.uniform(0, 360), group, 'rest', scale=(0.8, 1.1), stack=True,
              drop_cm=top_drop + 12 * i, note=note)


def ring_rect(C, O, ang, hx, hy, name, states, group, face_in=True, stair=None, sides='ufdb'):
    """One rectangular course of wall pieces round (O, ang): x along the contour, y uphill (terrace frame).
    states(side, i, n) -> a decay state; stair=(x0, x1): the opening in the uphill side for the stair.
    Returns the block name. Pieces of one course share a block (their corners overlap by design)."""
    K = terrace_frame(ang, O)
    C.nblock += 1
    blk = '%s_%d' % (name, C.nblock)
    ca, sa = math.cos(math.radians(ang)), math.sin(math.radians(ang))
    up = (-sa, ca)
    runs = []
    if 'u' in sides:
        if stair:
            runs.append(('u', K(-hx, hy), K(stair[0], hy), (-up[0], -up[1])))
            runs.append(('u', K(stair[1], hy), K(hx, hy), (-up[0], -up[1])))
        else:
            runs.append(('u', K(-hx, hy), K(hx, hy), (-up[0], -up[1])))
    if 'd' in sides:
        runs.append(('d', K(-hx, -hy), K(hx, -hy), up))
    if 'f' in sides:
        runs.append(('f', K(-hx, -hy), K(-hx, hy), (ca, sa)))
    if 'b' in sides:
        runs.append(('b', K(hx, -hy), K(hx, hy), (-ca, -sa)))
    for side, a, b, fin in runs:
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        n = max(1, int(L / PIECE_M + 0.02))
        fo = fin if face_in else (-fin[0], -fin[1])
        C.wall_line(a, b, [states(side, i, n) for i in range(n)], blk, group, fo)
    return blk


def band(C, O, ang, hx0, hy0, hx1, hy1, surface, strength, order=1, skip_up=None):
    """Ground decals over the band between two nested rectangles (four capsules, one per side)."""
    K = terrace_frame(ang, O)
    w_y, w_x = hy0 - hy1, hx0 - hx1
    mid_y, mid_x = (hy0 + hy1) / 2, (hx0 + hx1) / 2
    for (x, y, L, Wd, a) in ((0, mid_y, 2 * hx0 - w_x, w_y, 0.0), (0, -mid_y, 2 * hx0 - w_x, w_y, 0.0),
                             (mid_x, 0, 2 * hy1 + w_y, w_x, 90.0), (-mid_x, 0, 2 * hy1 + w_y, w_x, 90.0)):
        if skip_up and y > 0 and a == 0.0:
            # the uphill band is cut by the stair: two halves
            for sx in (-1, 1):
                xs = (skip_up + hx0) / 2 * sx
                C.patch(surface, *K(xs, y), ang, hx0 - skip_up, Wd * 0.9, strength, 'capsule', order)
            continue
        C.patch(surface, *K(x, y), ang + a, L, Wd * 0.9, strength, 'capsule', order)
