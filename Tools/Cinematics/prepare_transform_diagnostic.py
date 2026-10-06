"""Prepare read-only channel diagnostics from the frozen installed v2 scripts."""
import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKET = ROOT / 'Saved/Verification/ending_body_fix_20261001_v2'
OUT = ROOT / 'Saved/Verification/ending_body_acceptance_20261001_v3'


def transform_rows(path):
    tree = ast.parse(path.read_text())
    names = [ast.literal_eval(n.args[0]) for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == 'set_display_name']
    rows = [ast.literal_eval(n.iter) for n in ast.walk(tree)
            if isinstance(n, ast.For) and isinstance(n.target, ast.Tuple)
            and [x.id for x in n.target.elts] == ['tick', 'vals', 'mode']]
    return (names[0], rows[0]) if names and rows else None


def prepare():
    manifest = json.loads((PACKET / 'manifest.json').read_text())
    for folder in ('CIN_24_TRANSMISSION', 'CIN_25_END_CARD'):
        read_tree = ast.parse((PACKET / folder / '99_read.py').read_text())
        expected = next(ast.literal_eval(n.value) for n in read_tree.body
                        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name)
                        and t.id == 'EXPECTED' for t in n.targets))
        values = {}
        for path in (PACKET / folder).glob('*.py'):
            relative = str(path.relative_to(PACKET)).replace('\\', '/')
            if hashlib.sha256(path.read_bytes()).hexdigest() != manifest['script_sha256'][relative]:
                raise RuntimeError('Frozen source changed: ' + str(path))
            row = transform_rows(path)
            if row:
                values[row[0]] = row[1]
        code = '''import json
import struct
import unreal
ASSET = %r
WANTED = %r
def f32(value):
    return struct.unpack('<f', struct.pack('<f', float(value)))[0]
seq = unreal.load_asset(ASSET)
print('ENDING_TRANSFORM_DIAGNOSTIC_BEGIN ' + ASSET)
for binding in seq.get_bindings():
    name = str(binding.get_display_name())
    if name not in WANTED:
        continue
    wanted = WANTED[name]
    for track_index, track in enumerate(binding.get_tracks()):
        if track.get_class().get_name() != 'MovieScene3DTransformTrack':
            continue
        for section_index, section in enumerate(track.get_sections()):
            for channel_index, channel in enumerate(section.get_all_channels()):
                keys = list(channel.get_keys())
                rows = []
                for key_index, key in enumerate(keys):
                    actual = float(key.get_value())
                    authored = float(wanted[key_index][1][channel_index]) if channel_index < 6 and key_index < len(wanted) else None
                    rows.append(dict(index=key_index, actual=actual, wanted=authored,
                        delta=None if authored is None else actual-authored,
                        float32_wanted=None if authored is None else f32(authored),
                        float32_delta=None if authored is None else actual-f32(authored)))
                print('ENDING_TRANSFORM_CHANNEL ' + json.dumps(dict(binding=name,
                    track=track_index, section=section_index, channel=channel_index,
                    channel_type=channel.get_class().get_name(),
                    actual_count=len(keys), expected_count=len(wanted) if channel_index < 6 else 0,
                    values=rows)))
print('ENDING_TRANSFORM_DIAGNOSTIC_END ' + ASSET)
''' % (expected['asset'], values)
        compile(code, folder, 'exec')
        target = OUT / (folder + '_transform_diagnostic.py')
        target.write_text(code)
        print(target.relative_to(ROOT))


if __name__ == '__main__':
    prepare()
