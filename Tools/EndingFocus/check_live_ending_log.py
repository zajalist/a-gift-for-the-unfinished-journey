"""Check one live B18-to-credits playthrough without relying on older log entries.

Run `python Tools/EndingFocus/check_live_ending_log.py mark` immediately before
starting PIE, then `... check` after reaching the credits. Read-only to Unreal.
"""
import argparse
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOG = ROOT / 'Saved/Logs/saskartarad.log'
MARK = ROOT / 'Saved/Verification/ending_focus_20261001/live_ending_log_mark.json'
EVENTS = (
    ('B18 armed', 'debug: armed B18_COLLAPSE'),
    ('CIN19 began', 'cinematic CIN_19_HATCH: begin'),
    ('live capsule origin', 'CIN19 capsule contact frame:'),
    ('Traveller possessed', 'CIN_19 Keeper handoff:'),
    ('CP4 saved', 'checkpoint CP4_HUMAN saved (ok)'),
    ('CIN19 finished', 'cinematic CIN_19_HATCH: finished'),
    ('CIN24 began', 'cinematic CIN_24_TRANSMISSION: begin'),
    ('CIN25 began', 'cinematic CIN_25_END_CARD: begin'),
)
ROAD_B18_CM = (308468.0, 465653.0, 10490.0)


def capsule_translation(lines, origin_index):
    if origin_index is None:
        return None
    for line in lines[origin_index + 1:origin_index + 5]:
        match = re.search(r'Translation:\s*([-+\d.]+)\s+([-+\d.]+)\s+([-+\d.]+)', line)
        if match:
            return tuple(float(value) for value in match.groups())
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('mark', 'check'))
    args = parser.parse_args()
    if args.action == 'mark':
        assert LOG.is_file(), LOG
        mark = {'log': str(LOG), 'offset_bytes': LOG.stat().st_size}
        MARK.parent.mkdir(parents=True, exist_ok=True)
        MARK.write_text(json.dumps(mark, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(mark))
        return

    mark = json.loads(MARK.read_text(encoding='utf-8'))
    assert mark['log'] == str(LOG), 'Log path changed since mark'
    data = LOG.read_bytes()
    assert len(data) >= mark['offset_bytes'], 'Log rotated or truncated; mark a new run'
    lines = data[mark['offset_bytes']:].decode('utf-8', errors='replace').splitlines()
    positions = {}
    for index, line in enumerate(lines):
        for name, text in EVENTS:
            if name not in positions and text in line:
                positions[name] = index
    ordered = [positions[name] for name, _ in EVENTS if name in positions]
    translation = capsule_translation(lines, positions.get('live capsule origin'))
    road_offset_cm = math.dist(translation, ROAD_B18_CM) if translation else None
    result = {
        'observed': [name for name, _ in EVENTS if name in positions],
        'missing': [name for name, _ in EVENTS if name not in positions],
        'ordered': ordered == sorted(ordered),
        'capsule_origin_log': next((line for line in lines if 'CIN19 capsule contact frame:' in line), None),
        'capsule_translation_cm': translation,
        'capsule_distance_from_b18_cm': road_offset_cm,
        'handoff_log': next((line for line in lines if 'CIN_19 Keeper handoff:' in line), None),
        'skipped_cin19': any('cinematic CIN_19_HATCH: skipped' in line for line in lines),
        'lines_checked': len(lines),
    }
    print(json.dumps(result, indent=2))
    if result['missing'] or not result['ordered'] or result['skipped_cin19'] or (
            road_offset_cm is None or road_offset_cm > 10000.0) or (
            result['handoff_log'] and 'possessed=yes' not in result['handoff_log']):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
