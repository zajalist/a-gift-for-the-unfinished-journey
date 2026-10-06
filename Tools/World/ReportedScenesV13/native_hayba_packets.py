"""Offline Hayba inspection packets bound to an actual descriptor receipt.

No editor connection, mutation, height estimate or save is performed here.
"""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
import prepare


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    data = prepare.receipt(args.receipt, 'REPORTED_DESCRIPTORS')
    hosts = [row for row in data['rows'] if row['label'].startswith('SD_R03_Verge3300_')]
    assert len(hosts) == 6, 'Require all five bags and the cart from the actual receipt'
    commands = []
    for host in sorted(hosts, key=lambda row: row['label']):
        commands.append({'command': 'actor_inspect', 'params': {'actor_id': host['actor']}, 'expected_guid': host['guid'], 'expected_package': host['package']})
        commands.append({'command': 'actor_get_components', 'params': {'actor_id': host['actor'], 'include_internal': False}, 'expected_guid': host['guid']})
    commands.append({'command': 'scene_validate_physics', 'params': {'deep_check': False, 'window': {'min': [383200,375700,-33400], 'max': [383800,376100,-32900]}}, 'role': 'screening_only_not_support_height'})
    prepare.write(args.out/'native_inspections.json', {'status': 'prepared_not_executed', 'source_receipt': str(args.receipt.resolve()), 'source_sha256': prepare.sha(args.receipt), 'commands': commands, 'root_only': True, 'editor_calls': 0})
    source = json.loads((prepare.ROOT/'Tools/World/setdress_v2_sites.json').read_bytes())
    point = (308467.5947066,465653.3895016)
    candidates = []
    for site in source['sites']:
        for placement in site['placements']:
            if not any(word in str(placement).lower() for word in ('fence','palisade')):
                continue
            distance = math.hypot(placement['x_cm']-point[0],placement['y_cm']-point[1])
            candidates.append({'site':site['id'], 'road_m':site['road_m'], 'distance_cm':distance, 'placement':placement})
    candidates.sort(key=lambda row: row['distance_cm'])
    prepare.write(args.out/'mountain_fence_source_candidates.json', {'actual_carrier_xy_cm':point, 'warning':'Source proximity selects queries only; does not identify the screenshot or determine a repaired height.', 'nearest':candidates[:12]})
    # A bounded query at the actual ending carrier position, including all authored
    # nearby actors and exact Landscape descriptors. No map or cell is loaded.
    box = [307000,464000,310000,467000]
    prepare.write(args.out/'00_mountain_fence_descriptors.py', prepare.HEAD+f'BOX={box!r}\nCOHORT="ending_carrier_fence"\n'+prepare.DESCRIPTORS)
    print(json.dumps({'out':str(args.out), 'native_inspections':len(commands), 'first_actual_bag_guid':hosts[0]['guid'], 'nearest_source_fence_cm':candidates[0]['distance_cm'] if candidates else None}))


if __name__ == '__main__':
    main()
