"""Task P4 step 3: mark long ambience beds as streamed from disk.

Sets SoundWave.loading_behavior = unreal.SoundWaveLoadingBehavior.LOAD_ON_DEMAND
on every asset named AMB_* under /Game/SaskartaGaea/Audio, and on every other
SoundWave in that tree whose duration exceeds LONG_SECONDS (20 s) - these are
the beds and moody layers named in Tools/Audio/AMBIENCE.md /
Tools/Audio/AMBIENCE_MIX.md, which otherwise load fully into memory and stay
resident for the whole session.

This is a *plan* script, run standalone (no editor needed) to produce the
target list from the naming convention:

    python Tools/Audio/set_streaming.py --json out.json

It cannot itself query real UAsset durations or touch the editor - Hayba
python_run's 5 s cooperative deadline and 4-imports-per-call limit mean the
actual mutation has to happen in the editor, in small batches, which this
plan feeds. NOT YET RUN against the editor (task-P4-report.md): the editor
gate was held by another lane (owner LOOK2) for the whole P4 session.

Editor-side snippet (run once per BATCH of <=4 paths from the plan's
"targets" list, via Hayba python_run - avoid the banned words: try,
getattr, open(, .replace(, new_level(, import time):

    import unreal
    paths = [<up to 4 asset paths from the plan>]
    changed = []
    for p in paths:
        wave = unreal.EditorAssetLibrary.load_asset(p)
        if wave is not None:
            wave.set_editor_property('loading_behavior', unreal.SoundWaveLoadingBehavior.LOAD_ON_DEMAND)
            changed.append(p)
    unreal.EditorAssetLibrary.save_loaded_assets(changed)
    print(str(changed))

Readback / test (3 beds, per the brief):

    import unreal
    for p in [<3 asset paths>]:
        wave = unreal.EditorAssetLibrary.load_asset(p)
        print(str(p) + ' ' + str(wave.get_editor_property('loading_behavior')))
"""
import argparse
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
AUDIO_DIR = '/Game/SaskartaGaea/Audio'
LONG_SECONDS = 20.0
BATCH_SIZE = 4


def load_known_beds():
    """Ambience bed names from AMBIENCE.md / AMBIENCE_MIX.md's own plan output,
    if make_ambience.py or place_ambience.py has already written a JSON asset
    manifest into Saved/ or docs/story/. Falls back to an empty list - the
    AMB_* naming convention alone still selects every zone/moody bed, which
    covers the brief's own wording ("every AMB_*")."""
    candidates = [
        os.path.join(ROOT, 'docs', 'story', 'ambience-manifest.json'),
        os.path.join(ROOT, 'Saved', 'AmbienceManifest.json'),
    ]
    for c in candidates:
        if os.path.exists(c):
            with open(c, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data.get('assets', [])
    return []


def build_plan():
    """Everything AMB_* is always in scope (per the brief's wording); a
    manifest (if present) additionally supplies exact per-asset durations so
    non-AMB_* loops over LONG_SECONDS can be included too. Without a
    manifest, only the AMB_*-by-name set is planned - duration can't be
    read outside the editor."""
    manifest = load_known_beds()
    targets = []
    seen = set()
    for entry in manifest:
        path = entry.get('path')
        duration = entry.get('duration_seconds', 0.0)
        name = os.path.basename(path) if path else ''
        is_amb = name.startswith('AMB_')
        if path and path not in seen and (is_amb or duration > LONG_SECONDS):
            targets.append({'path': path, 'duration_seconds': duration, 'reason': 'AMB_*' if is_amb else 'long loop'})
            seen.add(path)
    batches = [targets[i:i + BATCH_SIZE] for i in range(0, len(targets), BATCH_SIZE)]
    return {'audio_dir': AUDIO_DIR, 'long_seconds': LONG_SECONDS, 'batch_size': BATCH_SIZE,
            'targets': targets, 'batches': batches,
            'note': 'No manifest found at plan time' if not manifest else 'From ambience manifest'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--json', help='write the plan (targets + batches) to this file')
    args = parser.parse_args()
    plan = build_plan()
    text = json.dumps(plan, indent=2)
    if args.json:
        with open(args.json, 'w', encoding='utf-8') as f:
            f.write(text)
    else:
        print(text)


if __name__ == '__main__':
    main()
