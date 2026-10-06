"""Generate the scoped BPC_RoadTether change for task TETHER (the six reachable off-road POIs).

    python Tools/GameFlow/gen_tether_specs.py   # -> specs/BPC_RoadTether.tether.json
    node Tools/GameFlow/bpgraph.mjs check Tools/GameFlow/specs/BPC_RoadTether.tether.json

Reads the full spec (specs/BPC_RoadTether.json) and rewrites two of its graphs:
- CheckRoad: the distance is USaskartaTetherSubsystem.GetTetherDistance(pawn location), the nearest road
  or tether path (0 inside an exploration zone), instead of the road spline's closest point. The Road
  guard stays and also needs the subsystem. After HandleZoneChanged, a change to Warning calls
  GetRadioStation -> NotifyOffroad (the radio's OFFROAD reaction; README_Radio.md), which the C++ also
  ignores unless the carrier is truly off every allowed line.
- ComputeRespawn: USaskartaTetherSubsystem.ComputeRespawn(BreachLocation, capsule half height,
  TravelSign, StepCm, pawn) -> Found, Location, Rotation: the nearest road or path point, traced to the
  ground, facing up-road (on the road) or back toward the junction (on a path).
WarnDistance 10 m, ClearDistance 9 m and BreachDistance 20 m are unchanged. The build steps are in
specs/README_Tether.md.
"""
from __future__ import annotations

import copy
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
FULL = os.path.join(HERE, 'specs', 'BPC_RoadTether.json')
OUT = os.path.join(HERE, 'specs', 'BPC_RoadTether.tether.json')
SUB = '/Script/SaskartaCore.SaskartaTetherSubsystem'
KSL = '/Script/Engine.KismetSystemLibrary'
KML = '/Script/Engine.KismetMathLibrary'


def check_road(full):
    g = copy.deepcopy(next(x for x in full['graphs'] if x['graph'] == 'CheckRoad'))
    n = g['nodes']
    gone = ('closestKey', 'roadPoint', 'distance')
    for k in gone:
        del n[k]
    links = [l for l in g['links'] if not any(l[0].startswith(k + '.') or l[1].startswith(k + '.') for k in gone)]
    links.remove(['roadValid.ReturnValue', 'ifRoad.Condition'])
    n.update({
        'me': {'self': True},
        'tether': {'call': 'GetTether', 'class': SUB},
        'tetherValid': {'call': 'IsValid', 'class': KSL},
        'bothValid': {'call': 'BooleanAND', 'class': KML},
        'distance': {'call': 'GetTetherDistance', 'class': SUB},
        'isWarn': {'call': 'EqualEqual_NameName', 'class': KML},
        'ifWarn': {'branch': True},
        'station': {'call': 'GetRadioStation', 'class': '/Script/SaskartaCore.SaskartaRadioStation'},
        'stationValid': {'call': 'IsValid', 'class': KSL},
        'ifStation': {'branch': True},
        'notify': {'call': 'NotifyOffroad', 'class': '/Script/SaskartaCore.SaskartaRadioStation'},
    })
    links += [
        ['me.self', 'tether.WorldContextObject'],
        ['tether.ReturnValue', 'tetherValid.Object'],
        ['roadValid.ReturnValue', 'bothValid.A'],
        ['tetherValid.ReturnValue', 'bothValid.B'],
        ['bothValid.ReturnValue', 'ifRoad.Condition'],
        ['tether.ReturnValue', 'distance.self'],
        ['pawnLocation.ReturnValue', 'distance.Location'],
        ['distance.ReturnValue', 'setLast.LastDistance'],
        ['handleZone.then', 'ifWarn.execute'],
        ['newZone.Zone', 'isWarn.A'],
        ['isWarn.ReturnValue', 'ifWarn.Condition'],
        ['ifWarn.then', 'ifStation.execute'],
        ['me.self', 'station.WorldContextObject'],
        ['station.ReturnValue', 'stationValid.Object'],
        ['stationValid.ReturnValue', 'ifStation.Condition'],
        ['ifStation.then', 'notify.execute'],
        ['station.ReturnValue', 'notify.self'],
    ]
    g['links'] = links
    g['defaults'].pop('roadPoint.CoordinateSpace', None)
    g['defaults']['isWarn.B'] = 'Warning'
    return g


def compute_respawn():
    return {
        'graph': 'ComputeRespawn',
        'nodes': {
            'entry': {'entry': True},
            'result': {'result': True},
            'me': {'self': True},
            'tether': {'call': 'GetTether', 'class': SUB},
            'tetherValid': {'call': 'IsValid', 'class': KSL},
            'ifTether': {'branch': True},
            'owner': {'call': 'GetOwner', 'class': '/Script/Engine.ActorComponent'},
            'castPC': {'cast': '/Game/SaskartaGaea/GameFlow/PC_Saskarta.PC_Saskarta_C'},
            'pawn': {'call': 'K2_GetPawn', 'class': '/Script/Engine.Controller'},
            'capsuleComponent': {'call': 'GetComponentByClass', 'class': '/Script/Engine.Actor'},
            'castCapsule': {'cast': '/Script/Engine.CapsuleComponent'},
            'halfHeight': {'call': 'GetScaledCapsuleHalfHeight', 'class': '/Script/Engine.CapsuleComponent'},
            'from': {'get': 'BreachLocation'},
            'sign': {'get': 'TravelSign'},
            'respawn': {'call': 'ComputeRespawn', 'class': SUB},
        },
        'links': [
            ['entry.then', 'ifTether.execute'],
            ['me.self', 'tether.WorldContextObject'],
            ['tether.ReturnValue', 'tetherValid.Object'],
            ['tetherValid.ReturnValue', 'ifTether.Condition'],
            ['ifTether.then', 'castPC.execute'],
            ['ifTether.else', 'result.execute'],
            ['owner.ReturnValue', 'castPC.Object'],
            ['castPC.then', 'castCapsule.execute'],
            ['castPC.CastFailed', 'result.execute'],
            ['castPC.AsPC Saskarta', 'pawn.self'],
            ['pawn.ReturnValue', 'capsuleComponent.self'],
            ['capsuleComponent.ReturnValue', 'castCapsule.Object'],
            ['castCapsule.then', 'respawn.execute'],
            ['castCapsule.CastFailed', 'result.execute'],
            ['castCapsule.AsCapsule Collision', 'halfHeight.self'],
            ['tether.ReturnValue', 'respawn.self'],
            ['from.BreachLocation', 'respawn.From'],
            ['halfHeight.ReturnValue', 'respawn.CapsuleHalfHeight'],
            ['sign.TravelSign', 'respawn.TravelSign'],
            ['entry.StepCm', 'respawn.StepCm'],
            ['pawn.ReturnValue', 'respawn.IgnoreActor'],
            ['respawn.then', 'result.execute'],
            ['respawn.ReturnValue', 'result.Found'],
            ['respawn.Location', 'result.Location'],
            ['respawn.Rotation', 'result.Rotation'],
        ],
        'defaults': {'capsuleComponent.ComponentClass': '/Script/Engine.CapsuleComponent'},
    }


def main():
    full = json.load(open(FULL, encoding='utf8'))
    used = {'Road', 'Zone', 'WarnDistance', 'ClearDistance', 'BreachDistance', 'LastDistance', 'BreachLocation', 'TravelSign'}
    spec = {
        'asset': full['asset'],
        'description': 'Scoped tether change (task TETHER): CheckRoad measures GetTetherDistance (the nearest road or '
                       'tether path, 0 in an exploration zone) instead of the road-only closest point, and tells the '
                       'radio NotifyOffroad on a change to Warning; ComputeRespawn asks '
                       'USaskartaTetherSubsystem.ComputeRespawn (the nearest road or path). Thresholds unchanged '
                       '(10 m warn, 9 m clear, 20 m breach). Build with --reset-graphs after the SaskartaCore build; '
                       'see README_Tether.md.',
        'variables': [v for v in full['variables'] if v['name'] in used],
        'functions': [f for f in full['functions'] if f['name'] in ('CheckRoad', 'ComputeRespawn')],
        'graphs': [check_road(full), compute_respawn()],
    }
    with open(OUT, 'w', encoding='utf8') as fh:
        json.dump(spec, fh, indent=2)
        fh.write('\n')
    print('wrote', os.path.relpath(OUT, os.path.dirname(os.path.dirname(HERE))))


if __name__ == '__main__':
    main()
