"""Ambience placement plan for /Game/level/Saskarta_WP, plus an offline level simulation.

The plan is the single source of truth for the AmbientSound actors that carry the zone beds,
the moody layers, the spatial site loops and the Geiger hotspots (Tools/Audio/AMBIENCE_MIX.md).

    python Tools/Audio/place_ambience.py            # simulate: level of every sound along the road vs target
    python Tools/Audio/place_ambience.py --json out.json   # write the resolved actor list for the editor script
    python Tools/Audio/place_ambience.py --md       # print the PLACEMENT.md tables

Positions come from docs/story/road-profile.json: an emitter is given as a road metre (0 = boot point,
spline point 54) plus a lateral offset (+ = right of travel) and a height above the road.
The simulation mirrors UE's FBaseAttenuationSettings::AttenuationEval for a sphere shape:
inside the inner radius gain is 1; across the falloff it is 1 - t (Linear) or 10^(t*dBAtMax/20)
(Natural Sound); beyond it the sound is silent. Overlapping instances of one sound are power-summed
(they start at different times, so they are uncorrelated).
"""
import argparse
import json
import math
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROFILE = os.path.join(ROOT, 'docs', 'story', 'road-profile.json')

# Master offset: the mix doc's "0 dB" (the zone's main bed) becomes this AmbientSound volume.
MASTER_DB = -15.0

AMB = '/Game/SaskartaGaea/Audio/Ambience/'
ATT = '/Game/SaskartaGaea/Audio/Attenuation/'

# Shared attenuation presets. 2D = spatialisation off, distance attenuation on (linear, so two
# neighbours cross-fade in amplitude); 3D = spatialised site loops (natural falloff, air absorption,
# non-spatialised radius so the stereo bed surrounds the listener inside the site).
PRESETS = {
    'ATT_2D_XL':   dict(spatial=False, radius_m=700, falloff_m=400, model='Linear'),
    'ATT_2D_L':    dict(spatial=False, radius_m=320, falloff_m=300, model='Linear'),
    'ATT_2D_M':    dict(spatial=False, radius_m=150, falloff_m=220, model='Linear'),
    'ATT_2D_S':    dict(spatial=False, radius_m=50, falloff_m=120, model='Linear'),
    'ATT_3D_Site': dict(spatial=True, radius_m=22, falloff_m=100, model='NaturalSound', db_at_max=-50,
                        non_spatial_m=22, stereo_spread_cm=600),
    'ATT_3D_Near': dict(spatial=True, radius_m=8, falloff_m=60, model='NaturalSound', db_at_max=-50,
                        non_spatial_m=8, stereo_spread_cm=400),
}

# label, sound, road metre, lateral m (+right), preset, doc dB (relative to the zone's main bed), note
# Geiger volumes are absolute (not offset by MASTER_DB) because they are the counter, not a bed.
PLAN = [
    # --- zone beds (2D) ---
    ('AMB_Z1_ValleyWind',      'AMB_Valley_Wind',     760,  0, 'ATT_2D_XL', 0,   'Valley floor bed, 0-1,550 m'),
    ('AMB_Z2_RidgeWind',       'AMB_Valley_Wind',    1830,  0, 'ATT_2D_M',  +3,  'Ridge: Valley_Wind +3 dB, crest 1,980 m'),
    ('AMB_Z3_BasinWind',       'AMB_Valley_Wind',    2420,  0, 'ATT_2D_L',  -4,  'Descent and basin floor: Valley_Wind -3/-4 dB'),
    ('AMB_Z4_FootWindLow',     'AMB_Valley_Wind',    3050,  0, 'ATT_2D_M',  -4,  'Mountain foot, lower half (cistern): wind still low'),
    ('AMB_Z4_FootWindHigh',    'AMB_Valley_Wind',    3300,  0, 'ATT_2D_M',  0,   'Mountain foot, upper half: "wind rising" to 0 dB'),
    ('AMB_Z5_CloudWind',       'AMB_Cloud_Wind',     3850,  0, 'ATT_2D_M',  0,   'Switchbacks in the cloud, 3,540-4,250 m'),
    ('AMB_Z6_SummitWind',      'AMB_Summit_Wind',    4680,  0, 'ATT_2D_L',  0,   'Above the cloud, the shoulder and (about -3 dB by distance) the human walk'),
    # --- moody 2D layers ---
    ('AMB_Z1_ValleyLife',      'AMB_Valley_Life',     650,  0, 'ATT_2D_XL', -3,  'Life layer, fades out by ~1,700 m'),
    ('AMB_Z3_BasinRumble',     'AMB_Mountain_Rumble', 2100, 0, 'ATT_2D_XL', -17, 'Mountain rumble: ridge -16, descent and basin -18'),
    ('AMB_Z5_MountainRumble',  'AMB_Mountain_Rumble', 3600, 0, 'ATT_2D_XL', -14, 'Mountain foot to the cloud top'),
    ('AMB_Z4_ThunderFar',      'AMB_Thunder_Far_Loop', 2850, 0, 'ATT_2D_L', -11, 'Far dry thunder, basin and mountain foot'),
    ('AMB_Z5_CloudDrizzle',    'AMB_Cloud_Drizzle',  3850,  0, 'ATT_2D_M',  -6,  'Drizzle inside the cloud'),
    # --- spatial site loops ---
    ('AMB_V4_ReedMarsh',       'AMB_Reed_Marsh',     1220,  0, 'ATT_3D_Near', -4, 'Waiting Water dry channel (crosses under the road). No water sound'),
    ('AMB_V5_SettlementCreaks', 'AMB_Settlement_Creaks', 2560, -18, 'ATT_3D_Site', -2, 'Numbered Stop: V5 gutted buildings, left side'),
    ('AMB_V5_WorksInfra',      'AMB_Infrastructure', 2600,  30, 'ATT_3D_Site', +2, 'The works by the platform, right of the road'),
    ('AMB_V5_RuinsMoan',       'AMB_Ruins_Wind_Moan', 2540, 10, 'ATT_3D_Near', -8, 'Broken arch / gutted building'),
    ('AMB_V6_CisternInfra',    'AMB_Infrastructure', 3050,  15, 'ATT_3D_Site', -4, 'Dry cistern, right 15 m'),
    ('AMB_V6_CisternMoan',     'AMB_Ruins_Wind_Moan', 3060, 22, 'ATT_3D_Near', -10, 'Cistern walls'),
    ('AMB_V10_HutMoan',        'AMB_Ruins_Wind_Moan', 4990, 8, 'ATT_3D_Near', -12, 'Relay hut walls'),
    ('AMB_V10_TransmitterHum', 'AMB_Transmitter_Electrical', 4995, 8, 'ATT_3D_Near', 0, 'Relay hut and mast foot'),
    # --- Geiger hotspots (2D: the counter rides on the carrier) ---
    ('GEI_B07_BasinMedium',    'SFX_Geiger_Medium',  2600,  0, 'ATT_2D_L',  None, 'B07 ramp 2,150-2,600 m and the basin tail'),
    ('GEI_B09_WorksHigh',      'SFX_Geiger_High',    2585,  0, 'ATT_2D_S',  None, 'Peak 10 cps at the platform and works'),
    ('GEI_B10_CisternMedium',  'SFX_Geiger_Medium',  3050, 15, 'ATT_2D_S',  None, 'Bump to ~4 cps within 60 m of the cistern'),
    ('GEI_B18_SummitMedium',   'SFX_Geiger_Medium',  4850,  0, 'ATT_2D_M',  None, 'Summit approach 2-4 cps, collapse, walk'),
    ('GEI_B23_HutHigh',        'SFX_Geiger_High',    5000,  0, 'ATT_2D_S',  None, 'Hut: 8 cps (High at -8 dB over Medium)'),
]
GEIGER_DB = {'GEI_B07_BasinMedium': -12, 'GEI_B09_WorksHigh': -14, 'GEI_B10_CisternMedium': -14,
             'GEI_B18_SummitMedium': -14, 'GEI_B23_HutHigh': -22}
HEIGHT_CM = {'2D': 300.0, '3D': 250.0}

# Target curves from AMBIENCE_MIX.md, doc dB by road metre (None = silent). Linear between knots.
TARGETS = {
    'AMB_Valley_Wind': [(0, 0), (1520, 0), (1580, 3), (1990, 3), (2050, -3), (2480, -3), (2540, -4),
                        (2810, -4), (3490, 0), (3540, None)],
    'AMB_Cloud_Wind': [(3490, None), (3540, 0), (4250, 0), (4460, None)],
    'AMB_Summit_Wind': [(4250, None), (4460, 0), (4790, 0), (4830, -3), (5009, -3)],
    'AMB_Valley_Life': [(0, -3), (1550, -3), (1700, None)],
    'AMB_Mountain_Rumble': [(0, -20), (1550, -20), (1600, -16), (2020, -16), (2080, -18), (2810, -18),
                            (3490, -14), (4250, -14), (4460, -20), (5009, -20)],
    'AMB_Thunder_Far_Loop': [(2150, None), (2250, -12), (2510, -12), (2550, -10), (2810, -10),
                             (2850, -12), (3490, -12), (3540, None)],
    'AMB_Cloud_Drizzle': [(3540, None), (3600, -6), (4250, -6), (4300, None)],
}


def load_samples():
    with open(PROFILE, encoding='utf-8') as f:
        prof = json.load(f)
    return prof['samples']


def at_metre(samples, m):
    """Interpolated road point at road metre m: x, y (cm), z (cm, road height), UE yaw of travel."""
    m = max(0.0, min(m, samples[-1]['dist_m']))
    for a, b in zip(samples, samples[1:]):
        if a['dist_m'] <= m <= b['dist_m']:
            t = (m - a['dist_m']) / max(b['dist_m'] - a['dist_m'], 1e-6)
            x = a['x_cm'] + (b['x_cm'] - a['x_cm']) * t
            y = a['y_cm'] + (b['y_cm'] - a['y_cm']) * t
            z = (a['terrain_z_m'] + (b['terrain_z_m'] - a['terrain_z_m']) * t) * 100.0
            yaw = math.degrees(math.atan2(b['y_cm'] - a['y_cm'], b['x_cm'] - a['x_cm']))
            return x, y, z, yaw
    s = samples[-1]
    return s['x_cm'], s['y_cm'], s['terrain_z_m'] * 100.0, s['heading_ue_yaw']


def resolve():
    samples = load_samples()
    out = []
    for label, sound, metre, lat, preset, doc_db, note in PLAN:
        x, y, z, yaw = at_metre(samples, metre)
        r = math.radians(yaw)
        # UE is left-handed: facing yaw, the right vector is (-sin, cos).
        x += -math.sin(r) * lat * 100.0
        y += math.cos(r) * lat * 100.0
        p = PRESETS[preset]
        z += HEIGHT_CM['3D' if p['spatial'] else '2D']
        vol_db = GEIGER_DB[label] if doc_db is None else MASTER_DB + doc_db
        path = ('/Game/SaskartaGaea/Audio/Ambience/' + sound + '.' + sound)
        out.append(dict(label=label, sound=sound, sound_path=path, road_m=metre, lateral_m=lat,
                        x=round(x), y=round(y), z=round(z), preset=preset,
                        attenuation_path=ATT + preset + '.' + preset,
                        radius_m=p['radius_m'], falloff_m=p['falloff_m'], spatial=p['spatial'],
                        doc_db=doc_db, volume_db=vol_db, volume=round(10 ** (vol_db / 20.0), 4), note=note))
    return out


def gain(p, d_cm):
    d = d_cm / 100.0
    if d <= p['radius_m']:
        return 1.0
    t = (d - p['radius_m']) / p['falloff_m']
    if t >= 1.0:
        return 0.0
    if p['model'] == 'Linear':
        return 1.0 - t
    return 10 ** (t * p['db_at_max'] / 20.0)


def simulate(actors, step=50):
    samples = load_samples()
    sounds = sorted({a['sound'] for a in actors})
    rows = []
    m = 0.0
    end = samples[-1]['dist_m']
    while m <= end + 1e-6:
        x, y, z, _ = at_metre(samples, m)
        z += 300.0  # listener: camera a few metres over the road
        lv = {}
        for s in sounds:
            pw = 0.0
            for a in actors:
                if a['sound'] != s:
                    continue
                d = math.dist((x, y, z), (a['x'], a['y'], a['z']))
                g = gain(PRESETS[a['preset']], d) * a['volume']
                pw += g * g
            lv[s] = 10 * math.log10(pw) if pw > 1e-12 else None
        rows.append((m, lv))
        m = min(m + step, end) if m < end else end + 1
    return rows


def target_at(curve, m):
    if m < curve[0][0] or m > curve[-1][0]:
        return None
    for (m0, v0), (m1, v1) in zip(curve, curve[1:]):
        if m0 <= m <= m1:
            if v0 is None and v1 is None:
                return None
            if v0 is None:
                return v1 - 60 * (m1 - m) / max(m1 - m0, 1) if m1 > m0 else v1
            if v1 is None:
                return v0 - 60 * (m - m0) / max(m1 - m0, 1) if m1 > m0 else v0
            return v0 + (v1 - v0) * (m - m0) / max(m1 - m0, 1)
    return curve[-1][1]


def fmt(v):
    return '   .  ' if v is None or v < -75 else '%6.1f' % v


def print_sim(actors):
    rows = simulate(actors)
    beds = ['AMB_Valley_Wind', 'AMB_Cloud_Wind', 'AMB_Summit_Wind', 'AMB_Valley_Life', 'AMB_Mountain_Rumble',
            'AMB_Thunder_Far_Loop', 'AMB_Cloud_Drizzle']
    spots = ['AMB_Reed_Marsh', 'AMB_Settlement_Creaks', 'AMB_Infrastructure', 'AMB_Ruins_Wind_Moan',
             'AMB_Transmitter_Electrical', 'SFX_Geiger_Medium', 'SFX_Geiger_High']
    short = {'AMB_Valley_Wind': 'VWind', 'AMB_Cloud_Wind': 'CWind', 'AMB_Summit_Wind': 'SWind',
             'AMB_Valley_Life': 'Life', 'AMB_Mountain_Rumble': 'Rumbl', 'AMB_Thunder_Far_Loop': 'Thndr',
             'AMB_Cloud_Drizzle': 'Drizz', 'AMB_Reed_Marsh': 'Reed', 'AMB_Settlement_Creaks': 'Creak',
             'AMB_Infrastructure': 'Infra', 'AMB_Ruins_Wind_Moan': 'Moan', 'AMB_Transmitter_Electrical': 'Xmit',
             'SFX_Geiger_Medium': 'GeiM', 'SFX_Geiger_High': 'GeiH'}
    print('Levels are AmbientSound volume in dB after attenuation (doc dB = level - (%.0f)); '
          'target in brackets.' % MASTER_DB)
    print('   m  ' + ''.join('%13s' % short[b] for b in beds) + ' | bedsum |' + ''.join('%7s' % short[s] for s in spots))
    worst = {}
    for m, lv in rows:
        cells = []
        for b in beds:
            t = target_at(TARGETS[b], m)
            t = None if t is None else t + MASTER_DB
            v = lv.get(b)
            cells.append('%6s[%5s]' % (fmt(v).strip(), '' if t is None or t < -75 else '%.0f' % t))
            steady = all(target_at(TARGETS[b], mm) is not None for mm in (m - 100, m + 100))
            quiet = all(target_at(TARGETS[b], mm) is None for mm in (m - 150, m, m + 150))
            if steady and t is not None:
                err = (v if v is not None else -99) - t
                if abs(err) > abs(worst.get(b, (0, 0))[1]):
                    worst[b] = (m, err)
            elif quiet and v is not None and v > MASTER_DB - 20:
                if abs(v - MASTER_DB + 20) > abs(worst.get(b, (0, 0))[1]):
                    worst[b] = (m, v - (MASTER_DB - 20))
        main = [lv.get(b) for b in beds[:3]]
        pw = sum(10 ** (v / 10) for v in main if v is not None)
        bedsum = 10 * math.log10(pw) if pw else None
        print('%5d ' % m + ''.join('%13s' % c for c in cells) + ' | %s |' % fmt(bedsum)
              + ''.join('%7s' % fmt(lv.get(s)) for s in spots))
    print('\nWorst deviation from target (where target is audible):')
    for b, (m, e) in worst.items():
        print('  %-22s %+5.1f dB at %d m' % (b, e, m))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json')
    ap.add_argument('--md', action='store_true')
    args = ap.parse_args()
    actors = resolve()
    if args.json:
        with open(args.json, 'w', encoding='utf-8') as f:
            json.dump(dict(presets=PRESETS, actors=actors), f, indent=1)
        print('wrote', args.json, len(actors), 'actors')
        return
    if args.md:
        for a in actors:
            print('| `%s` | `%s` | %d m, %+d m | (%d, %d, %d) | %s: %d m + %d m | %.0f dB (%.3f) | %s |' % (
                a['label'], a['sound'], a['road_m'], a['lateral_m'], a['x'], a['y'], a['z'], a['preset'],
                a['radius_m'], a['falloff_m'], a['volume_db'], a['volume'], a['note']))
        return
    print_sim(actors)


if __name__ == '__main__':
    main()
