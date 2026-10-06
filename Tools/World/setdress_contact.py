"""Set dressing V2: the physical-correctness judge (pure Python; place_setdress.py 'check2' feeds it).

The editor side only MEASURES: for every placed actor it reports its transform, its local bounds, and the
gap between its bottom and the ground at a 3 x 3 grid under the footprint (landscape-only traces), plus what
the first trace hit under each corner was. Everything is judged here, so the rules are unit-tested.

Violations (SETDRESS_V2.md section 3):
  FLOAT        rigid architecture: ANY footprint sample more than TOL_FLOAT (5 cm) above the ground
               rest / lie / channel props: NO sample within TOL_FLOAT of the ground (nothing touches)
  ON_ACTOR     a unit member or a rigid piece whose feet land on another actor, not the landscape
               (the tarp poles on the wall top)
  CLASH        two solids of DIFFERENT blocks interpenetrate by more than TOL_CLASH (10 cm) in plan and in
               height (shared walls of one block overlap by design and are exempt)
  INSIDE       a prop whose centre is inside a wall piece
  UNIT_CLASH   a composite unit's box intersects any solid that is not part of it
  bear pieces  (a lintel on its two jambs; contact 'bear', bears_on = the jamb ids): measured on an oriented
               3 x 3 grid with first-hit traces. FLOAT when either END has no sample within TOL_FLOAT of what is
               under it (a see-saw), ON_ACTOR when an end rests on anything but its named supports, CLASH when it
               cuts more than TOL_CLASH into any other rigid piece
  DETACHED     a unit's cover (the awning cloth, unit_role 'cover') whose pivot or rotation is not its frame's:
               kits share one pivot, so the cloth sits on the frame only when the transforms are equal
  DETACHED     an attached item whose named parent is missing or whose measured transform is not the
               transform prescribed by its attachment
A site with violations is not saved (place_setdress.py 'save' refuses), unless a violation is listed in the
site's `waivers` with a reason.
"""
import math

TOL_FLOAT = 5.0       # cm
TOL_CLASH = 10.0      # cm
RIGID = ('rigid',)
LOOSE = ('rest', 'lie', 'channel', 'stack')
BEAR = 'bear'
TOL_PIVOT = 3.0       # cm: a kit cover must share its frame's pivot
TOL_ROT = 1.0         # deg
TOL_SCALE = 0.01      # absolute actor scale difference
GROUND_COVER_KEYS = {'B01_floor01', 'AB_Planks_150_A', 'AB_Planks_150_B', 'B01_rail01'}
THIN_WALL_M = 1.0     # a wall piece thinner than this: its box is (nearly) all solid, so INSIDE is meaningful


def axes(yaw, pitch, roll):
    """UE FRotationMatrix axes (X forward, Y right, Z up) for a rotator in degrees (same as MATH_SRC)."""
    cy, sy = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    cp, sp = math.cos(math.radians(pitch)), math.sin(math.radians(pitch))
    cr, sr = math.cos(math.radians(roll)), math.sin(math.radians(roll))
    X = (cp * cy, cp * sy, sp)
    Y = (sr * sp * cy - cr * sy, sr * sp * sy + cr * cy, -sr * cp)
    Z = (-(cr * sp * cy + sr * sy), cy * sr - cr * sp * sy, cr * cp)
    return X, Y, Z


def to_world(ax, loc, p):
    X, Y, Z = ax
    return (loc[0] + p[0] * X[0] + p[1] * Y[0] + p[2] * Z[0],
            loc[1] + p[0] * X[1] + p[1] * Y[1] + p[2] * Z[1],
            loc[2] + p[0] * X[2] + p[1] * Y[2] + p[2] * Z[2])


def grid_local(origin, extent, scale, n=3, inset=0.08):
    """n x n points on the bottom face of the scaled local box (corners first, then the rest)."""
    o = [c * scale for c in origin]
    e = [c * scale for c in extent]
    z0 = o[2] - e[2]
    ks = [-(1 - inset) + 2 * (1 - inset) * i / (n - 1) for i in range(n)]
    pts = [(o[0] + a * e[0], o[1] + b * e[1], z0) for a in ks for b in ks]
    corners = [p for p in pts if abs(abs(p[0] - o[0]) - (1 - inset) * e[0]) < 1e-6 and abs(abs(p[1] - o[1]) - (1 - inset) * e[1]) < 1e-6]
    rest = [p for p in pts if p not in corners]
    return corners + rest


def obb(rep):
    """World oriented box of a report: (centre, half-axes list [(axis_vec, half_len)x3])."""
    ax = axes(*rep['rot'])
    s = rep['scale']
    c = to_world(ax, rep['loc'], [v * s for v in rep['origin']])
    return c, [(ax[i], rep['extent'][i] * s) for i in range(3)]


def obb_depth(A, B):
    """Minimum penetration depth (cm) of two oriented boxes by the separating-axis test; 0 when apart."""
    ca, ha = A
    cb, hb = B
    d = [cb[i] - ca[i] for i in range(3)]
    axes_ = [a for a, _ in ha] + [b for b, _ in hb]
    for a, _ in ha:
        for b, _ in hb:
            cx = (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
            L = math.sqrt(sum(v * v for v in cx))
            if L > 1e-6:
                axes_.append(tuple(v / L for v in cx))
    best = 1e18
    for n in axes_:
        ra = sum(abs(sum(n[k] * a[k] for k in range(3))) * h for a, h in ha)
        rb = sum(abs(sum(n[k] * b[k] for k in range(3))) * h for b, h in hb)
        dist = abs(sum(n[k] * d[k] for k in range(3)))
        o = ra + rb - dist
        if o <= 0:
            return 0.0
        best = min(best, o)
    return best


def point_in_obb(p, B, shrink=0.0):
    c, h = B
    d = [p[i] - c[i] for i in range(3)]
    for a, L in h:
        if abs(sum(a[k] * d[k] for k in range(3))) > max(0.0, L - shrink):
            return False
    return True


def bear_ends(rep):
    """Sample indices of the two ends of a bearing piece (check2 grid order: 3 * ix + iy, ix along local X)."""
    ext = rep['extent']
    if ext[0] >= ext[1]:
        return [0, 1, 2], [6, 7, 8]
    return [0, 3, 6], [2, 5, 8]


def bear_violations(rep, item):
    """A lintel must rest on BOTH ends, and only on its named supports."""
    out = []
    gaps, hits = rep.get('gaps', []), rep.get('hits', [])
    allowed = {'SD_' + b for b in item.get('bears_on', [])}
    for name, idx in zip(('A', 'B'), bear_ends(rep)):
        sup = [k for k in idx if k < len(gaps) and gaps[k] is not None and abs(gaps[k]) <= TOL_FLOAT]
        if not sup:
            g = [gaps[k] for k in idx if k < len(gaps) and gaps[k] is not None]
            out.append(('FLOAT', 'end %s carried by nothing (gaps %s cm)' % (name, [round(x) for x in g])))
            continue
        on = {hits[k] for k in sup if k < len(hits)}
        if not (on & allowed):
            out.append(('ON_ACTOR', 'end %s rests on %s, not on its supports %s' % (
                name, ', '.join(sorted(on)) or 'nothing', ', '.join(sorted(allowed)))))
    return out


def contact_violations(rep, item):
    """FLOAT / ON_ACTOR for one actor from its measured gaps (cm) and first-hit kinds."""
    out = []
    contact = item.get('contact') or ('rigid' if item.get('cat') in ('wall', 'building') else 'rest')
    if item.get('attach') or item.get('unit_role') == 'cover':
        return out            # carried pieces are validated against their frame/parent below
    if contact == BEAR:
        return bear_violations(rep, item)
    gaps = [g for g in rep.get('gaps', []) if g is not None]
    if item.get('cat') in ('fx', 'fx_card', 'rubble', 'shrub'):
        return out
    if not gaps:
        return [('NOGROUND', 'no landscape contact samples')]
    if contact in RIGID:
        if max(gaps) > TOL_FLOAT:
            out.append(('FLOAT', 'max gap %.0f cm under the footprint (rigid: every sample must touch)' % max(gaps)))
    elif min(gaps) > TOL_FLOAT:
        out.append(('FLOAT', 'nothing touches: min gap %.0f cm' % min(gaps)))
    if (contact in RIGID or item.get('unit')) and any(k not in ('landscape', 'none', 'self') for k in rep.get('hits', [])):
        bad = [k for k in rep.get('hits', []) if k not in ('landscape', 'none', 'self')]
        out.append(('ON_ACTOR', 'feet land on %s, not the ground' % ', '.join(sorted(set(bad)))))
    return out


def solid(item):
    return item.get('cat') not in ('rubble', 'shrub', 'fx', 'fx_card') and item['key'] not in GROUND_COVER_KEYS \
        and item.get('block') not in ('fan', 'base', 'creep')


def thin(box):
    """A box whose smaller plan extent is under THIN_WALL_M: (nearly) all solid, so an overlap is real."""
    return min(h for _, h in box[1][:2]) * 2 < THIN_WALL_M * 100


def pair_violations(reps, items):
    """CLASH / INSIDE / UNIT_CLASH over every pair of solids."""
    out = []
    ids = [i for i in reps if i in items and solid(items[i])]
    boxes = {i: obb(reps[i]) for i in ids}
    for a in range(len(ids)):
        ia = ids[a]
        A, ta = boxes[ia], items[ia]
        for b in range(a + 1, len(ids)):
            ib = ids[b]
            B, tb = boxes[ib], items[ib]
            # quick reject on the bounding spheres
            ra = math.sqrt(sum(h * h for _, h in A[1]))
            rb = math.sqrt(sum(h * h for _, h in B[1]))
            if sum((A[0][k] - B[0][k]) ** 2 for k in range(3)) > (ra + rb) ** 2:
                continue
            ca, cb = ta.get('contact'), tb.get('contact')
            rig_a, rig_b = ca == 'rigid', cb == 'rigid'
            bear_a, bear_b = ca == BEAR, cb == BEAR
            # a bearing piece may rest on its named supports only, whatever block the other piece is in
            if ((bear_a and rig_b and ib not in ta.get('bears_on', ())) or
                    (bear_b and rig_a and ia not in tb.get('bears_on', ()))):
                d = obb_depth(A, B)
                if d > TOL_CLASH:
                    out.append(('CLASH', '%s x %s (%.0f cm)' % ((ia, ib, d) if bear_a else (ib, ia, d))))
                continue
            if bear_a or bear_b:
                continue
            if ta.get('block') and ta.get('block') == tb.get('block'):
                continue
            unit = ta.get('unit') or tb.get('unit')
            d = obb_depth(A, B)
            if unit and d > 0 and ta.get('unit') != tb.get('unit'):
                out.append(('UNIT_CLASH', '%s x %s (%.0f cm)' % (ia, ib, d)))
                continue
            if rig_a and rig_b and d > TOL_CLASH:
                # big hollow shells (houses, the tower) have empty boxes; only thin pieces clash reliably
                if thin(A) or thin(B):
                    out.append(('CLASH', '%s x %s (%.0f cm)' % (ia, ib, d)))
            elif rig_a != rig_b:
                wall, prop, pid = (A, B, ib) if rig_a else (B, A, ia)
                w_it = ta if rig_a else tb
                p_it = tb if rig_a else ta
                if not (thin(wall) and w_it.get('cat') == 'wall'):
                    continue
                if point_in_obb(prop[0], wall, shrink=2.0):
                    out.append(('INSIDE', '%s inside the wall %s' % (pid, ia if rig_a else ib)))
                elif p_it.get('contact') in ('rest', 'lie') and d > TOL_CLASH:
                    # a fallen beam through a standing wall, a table half inside one
                    out.append(('CLASH', '%s x %s (%.0f cm, loose piece into a wall)' % (pid, ia if rig_a else ib, d)))
    return out


def unit_violations(reps, items):
    """DETACHED: a unit's cover must share its frame's pivot and rotation (kit pieces share one pivot)."""
    out = []
    frames = {it['unit']: i for i, it in items.items() if it.get('unit') and it.get('unit_role') in ('frame', 'whole')}
    for i, it in items.items():
        if it.get('unit_role') != 'cover' or i not in reps:
            continue
        f = frames.get(it['unit'])
        if f is None or f not in reps:
            out.append((i, 'DETACHED', 'no frame of unit %s was measured' % it['unit']))
            continue
        a, b = reps[i], reps[f]
        dl = math.sqrt(sum((a['loc'][k] - b['loc'][k]) ** 2 for k in range(3)))
        dr = max(abs((a['rot'][k] - b['rot'][k] + 180.0) % 360.0 - 180.0) for k in range(3))
        if dl > TOL_PIVOT or dr > TOL_ROT:
            out.append((i, 'DETACHED', 'cover %.0f cm / %.1f deg off its frame %s' % (dl, dr, f)))
    return out


def attachment_violations(reps, items):
    """DETACHED when an attachment lacks its named parent or disagrees with its prescribed transform.

    Shared-pivot attachments follow the parent's location (plus the child's explicit Z offset), rotation,
    and scale. Other attachments retain their authored XY/rotation/scale and inherit only parent Z plus offset,
    matching place_setdress.py's settle behavior.
    """
    out = []
    for i, it in items.items():
        if not it.get('attach'):
            continue
        if it.get('unit_role') == 'cover':
            continue            # unit_violations validates this established frame/cover relationship
        parent_id = it.get('parent')
        if not parent_id:
            out.append((i, 'DETACHED', 'attachment has no named parent'))
            continue
        if parent_id not in items:
            out.append((i, 'DETACHED', 'named parent %s is not selected' % parent_id))
            continue
        child_rep = reps.get(i)
        parent_rep = reps.get(parent_id)
        if child_rep is None or parent_rep is None:
            missing = i if child_rep is None else parent_id
            out.append((i, 'DETACHED', 'no transform measured for %s' % missing))
            continue

        offset = float((it.get('settle') or {}).get('z_offset_cm', 0.0))
        if it.get('shares_pivot'):
            expected_loc = list(parent_rep['loc'])
            expected_rot = list(parent_rep['rot'])
            expected_scale = float(parent_rep.get('scale', 1.0))
            expected_loc[2] += offset
        else:
            expected_loc = [float(it['x_cm']), float(it['y_cm']), float(parent_rep['loc'][2]) + offset]
            expected_rot = [float(it.get(k, 0.0)) for k in ('yaw', 'pitch', 'roll')]
            expected_scale = float(it.get('scale', 1.0))

        actual_loc = child_rep['loc']
        actual_rot = child_rep['rot']
        distance = math.sqrt(sum((float(actual_loc[k]) - expected_loc[k]) ** 2 for k in range(3)))
        rotation_error = max(abs((float(actual_rot[k]) - expected_rot[k] + 180.0) % 360.0 - 180.0)
                             for k in range(3))
        scale_error = abs(float(child_rep.get('scale', 1.0)) - expected_scale)
        if distance > TOL_PIVOT or rotation_error > TOL_ROT or scale_error > TOL_SCALE:
            out.append((i, 'DETACHED', '%.1f cm / %.1f deg / %.3f scale off parent %s' %
                        (distance, rotation_error, scale_error, parent_id)))
    return out


def judge(reps, items, waivers=()):
    """reps: id -> report; items: id -> placement. Returns (violations, waived) as lists of (id, code, why)."""
    v = []
    for i, rep in reps.items():
        if i in items:
            for code, why in contact_violations(rep, items[i]):
                v.append((i, code, why))
    for code, why in pair_violations(reps, items):
        v.append((why.split(' ')[0], code, why))
    v += unit_violations(reps, items)
    v += attachment_violations(reps, items)
    w = {(x['id'], x['code']) for x in waivers}
    return [x for x in v if (x[0], x[1]) not in w], [x for x in v if (x[0], x[1]) in w]


# ---------------------------------------------------------------------------- the offline estimate

def _plan_contains(box, x, y, pad=0.0):
    c, h = box
    d = (x - c[0], y - c[1], 0.0)
    for a, L in h[:2]:
        n = math.hypot(a[0], a[1]) or 1.0
        if abs((a[0] * d[0] + a[1] * d[1]) / n) > L * n - pad:
            return False
    return True


def offline_reports(placements, ground):
    """Estimate what check2 will measure, from the composed placements alone (no editor), so the composer can
    run judge() before anything is placed. ground(x_cm, y_cm) -> z_cm (the Gaea heightmap).

    The estimate follows the settle rules: a rigid piece stands plumb with its lowest footprint sample sunk by
    sink_cm (z_rule 'min'); rest / lie / channel pieces sit on the mean ground less their sink; a bearing piece
    rests on the highest top of what is under its samples (its jambs, if the composer levelled them); a unit's
    cover sits on its frame with the frame's pivot and rotation only if the composer gave it the same ones.
    Corner hits (ON_ACTOR) and bearing hits are what a trace from 30-40 cm above the sample meets first among
    the other non-ISM pieces (hollow shells excepted), else the landscape. ISM instances are not measured by
    check2 and are left out here too. Returns (reps, items) for judge()."""
    items = {p['id']: dict(p) for p in placements if not p.get('ism')}
    reps = {}

    # place_setdress.select resolves implicit attachments to the previous non-attached item in the same group.
    # Mirror that source rule here so offline estimates exercise the same parent contract as check2.
    last_solid = {}
    for p in items.values():
        group = p.get('group')
        if p.get('attach'):
            if not p.get('parent') and group in last_solid:
                parent = last_solid[group]
                p['parent'] = parent['id']
                p['shares_pivot'] = (abs(parent['x_cm'] - p['x_cm']) < 60.0 and
                                     abs(parent['y_cm'] - p['y_cm']) < 60.0 and
                                     abs((parent.get('yaw', 0.0) - p.get('yaw', 0.0) + 180.0) % 360.0 - 180.0) < 2.0)
        elif group:
            last_solid[group] = p

    def base(p):
        ext = [max(p['size_m'][k], 0.05) * 50.0 for k in range(3)]
        ax = axes(p['yaw'], 0.0, 0.0)
        loc0 = (p['x_cm'], p['y_cm'], 0.0)
        grid = [to_world(ax, loc0, (fx * ext[0], fy * ext[1], 0.0)) for fx in (-0.92, 0.0, 0.92) for fy in (-0.92, 0.0, 0.92)]
        return ext, grid

    def rep_of(p, zb, ext, gaps, hits):
        return dict(id=p['id'], loc=[p['x_cm'], p['y_cm'], zb + ext[2]], rot=[p['yaw'], 0.0, 0.0], scale=1.0,
                    origin=[0.0, 0.0, 0.0], extent=ext, gaps=gaps, hits=hits, zb=zb, zt=zb + 2 * ext[2])
    later = []
    for p in items.values():
        c = p.get('contact') or ('rigid' if p.get('cat') in ('wall', 'building') else 'rest')
        if c == 'bear' or p.get('unit_role') == 'cover' or p.get('attach'):
            later.append(p)
            continue
        ext, grid = base(p)
        g = [ground(x, y) for x, y, _ in grid]
        sink = p['settle'].get('sink_cm', 0.0) if p.get('settle') else 0.0
        zb = (min(g) if c == 'rigid' else sum(g) / len(g)) - sink
        reps[p['id']] = rep_of(p, zb, ext, [round(zb - gi, 1) for gi in g], [])
    boxes = {i: obb(r) for i, r in reps.items()}

    def first_hit(x, y, z_from, skip_block=None, skip_id=None):
        best = None
        for i in boxes:                      # pass-1 pieces only: covers and lintels carry nothing
            r, it = reps[i], items[i]
            if i == skip_id or (skip_block and it.get('block') == skip_block) or not solid(it):
                continue
            if it.get('cat') == 'building' and not thin(boxes[i]):
                continue                     # a hollow shell: the trace falls into it
            if r['zt'] <= z_from and _plan_contains(boxes[i], x, y) and (best is None or r['zt'] > best[1]):
                best = (i, r['zt'])
        return best
    for i, r in reps.items():
        p = items[i]
        if p.get('contact') == 'rigid' or p.get('unit'):
            _, grid = base(p)
            for k in (0, 2, 6, 8):
                x, y, _ = grid[k]
                h = first_hit(x, y, r['zb'] + 30.0, skip_block=p.get('block'), skip_id=i)
                r['hits'].append('SD_' + h[0] if h and h[1] > ground(x, y) + 2.0 else 'landscape')
    for p in later:
        ext, grid = base(p)
        if p.get('attach'):
            parent = reps.get(p.get('parent'))
            if parent is None:
                continue
            offset = float((p.get('settle') or {}).get('z_offset_cm', 0.0))
            if p.get('shares_pivot'):
                loc = list(parent['loc'])
                loc[2] += offset
                rot = list(parent['rot'])
                scale = float(parent.get('scale', 1.0))
            else:
                loc = [float(p['x_cm']), float(p['y_cm']), float(parent['loc'][2]) + offset]
                rot = [float(p.get(k, 0.0)) for k in ('yaw', 'pitch', 'roll')]
                scale = float(p.get('scale', 1.0))
            r = rep_of(p, loc[2] - ext[2], ext, [], [])
            r['loc'], r['rot'], r['scale'] = loc, rot, scale
            reps[p['id']] = r
            continue
        if p.get('unit_role') == 'cover':
            fr = [q for q in reps if items[q].get('unit') == p.get('unit') and items[q].get('unit_role') in ('frame', 'whole')]
            if not fr:
                continue
            # kit pieces share the frame's pivot: the cover's pivot IS the frame's when the composer gave it the
            # same position and yaw (the bounds centres then match too); DETACHED compares the two
            reps[p['id']] = rep_of(p, reps[fr[0]]['loc'][2] - ext[2], ext, [], [])
            continue
        sup = [reps[s]['zt'] for s in p.get('bears_on', []) if s in reps]
        zb = max(sup) if sup else sum(ground(x, y) for x, y, _ in grid) / 9.0
        gaps, hits = [], []
        for x, y, _ in grid:
            h = first_hit(x, y, zb + 40.0, skip_id=p['id'])
            gz = ground(x, y)
            if h and h[1] > gz:
                gaps.append(round(zb - h[1], 1))
                hits.append('SD_' + h[0])
            else:
                gaps.append(round(zb - gz, 1))
                hits.append('landscape')
        reps[p['id']] = rep_of(p, zb, ext, gaps, hits)
    for r in reps.values():
        r.pop('zb')
        r.pop('zt')
    return reps, items
