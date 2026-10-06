"""Install the five authored Traveller staff clips, one guarded editor packet at a time.

Run `preflight` offline first. `install` requires an existing Hayba editor lease and
stopped PIE. A successful packet gets a receipt; an uncertain/failed packet stops
the run for inspection so the destructive create step is never blindly replayed.
The Blend Space, profile certification, and rendered acceptance are separate.
"""

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
PACKET = ROOT / 'Saved/Verification/ending_focus_20261001/staff_contact_authoring_30fps'
RECEIPTS = ROOT / 'Saved/Verification/ending_focus_20261001/staff_contact_install_30fps_receipts'
sys.path.insert(0, str(ROOT / 'Tools/GameFlow'))
import editor_gate  # noqa: E402

CLIPS = ('A_Traveller_StaffEnter', 'A_Traveller_StaffHoldLeft',
         'A_Traveller_StaffHoldCentre', 'A_Traveller_StaffHoldRight',
         'A_Traveller_StaffRecover')
OWNER = 'codex-saskarta-goal'


def steps():
    for clip in CLIPS:
        folder = PACKET / clip
        yield folder / '00_create.py'
        yield from sorted(folder.glob('10_keys_*.py'))
        yield folder / '90_save.py'


def preflight():
    manifest = json.loads((PACKET / 'manifest.json').read_text(encoding='utf-8'))
    files = manifest['files']
    ordered = list(steps())
    assert len(ordered) == 55, len(ordered)
    for path in ordered:
        rel = str(path.relative_to(PACKET)).replace('/', '\\')
        assert rel in files, rel
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        assert actual == files[rel], (rel, actual, files[rel])
    print(f'PREPARED {len(ordered)} immutable clip packets across {len(CLIPS)} clips')
    return ordered


def editor_script(path):
    return path.read_text(encoding='utf-8')


def install(ordered, through=None):
    if editor_gate.pie_running():
        raise RuntimeError('PIE is running; leave the game session undisturbed')
    token = editor_gate.mirrored_token(OWNER)
    if not token:
        raise RuntimeError('Acquire the Hayba editor lease before installation')
    RECEIPTS.mkdir(parents=True, exist_ok=True)
    for i, path in enumerate(ordered):
        if through is not None and i >= through:
            break
        receipt = RECEIPTS / f'{i:02d}_{path.parent.name}_{path.stem}.json'
        if receipt.exists():
            prior = json.loads(receipt.read_text(encoding='utf-8'))
            assert prior['ok'] is True and prior['source_sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
            print(f'SKIP_VERIFIED {i+1}/{len(ordered)} {path.parent.name}/{path.name}')
            continue
        result = editor_gate.hayba('python_run', {'script': editor_script(path)},
                                   owner=OWNER, lease=token, timeout_s=30)
        if not result.get('ok') or result.get('stderr'):
            raise RuntimeError(f'Packet {i+1} uncertain/failed: {path}: {result}')
        output = result.get('stdout', '')
        if path.name == '90_save.py' and 'saved True' not in output:
            raise RuntimeError(f'Clip save was not confirmed: {path}: {output}')
        receipt.write_text(json.dumps({'ok': True, 'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                                       'stdout': output}, indent=2), encoding='utf-8')
        print(f'INSTALLED {i+1}/{len(ordered)} {path.parent.name}/{path.name}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('preflight', 'install'))
    parser.add_argument('--through', type=int, help='Stop after this many ordered packets for guarded review')
    args = parser.parse_args()
    ordered = preflight()
    if args.mode == 'install':
        install(ordered, args.through)


if __name__ == '__main__':
    main()
