"""Render exactly six new synthetic carrier warnings and prepare bounded editor chunks.

--render uses the existing Daniel/ElevenLabs/heaviest carrier pipeline, in an isolated
verification folder. Without it, preparation is offline from the six rendered WAVs.
Never runs Unreal or modifies existing carrier recordings/assets.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import wave

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "Saved/Verification/storm_panic_20261001"
LINES = ROOT / "docs/story/carrier-voice-lines.json"
IDS = tuple(f"CV_STORM_PANIC_{i:02d}" for i in range(1, 7))
DEST = "/Game/SaskartaGaea/Audio/CarrierVoice"
VOICE_CLASS = "/Game/SaskartaGaea/Audio/SC_Voice"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def jobs() -> list[dict]:
    rows = json.loads(LINES.read_text(encoding="utf-8"))["lines"]
    result = [row for row in rows if row["id"] in IDS]
    assert tuple(row["id"] for row in result) == IDS
    assert sum(len(row["text"]) for row in result) <= 240
    return result


def render(out: Path, rows: list[dict]) -> None:
    import carrier_elevenlabs as voice
    import make_carrier_voice as mcv

    provenance = json.loads((ROOT / "Saved/GameAudio/CarrierVoice/elevenlabs.json").read_text())
    assert provenance["voice_id"] == voice.DEFAULT_VOICE
    assert provenance["model"] == voice.MODEL and provenance["settings"] == voice.VOICE_SETTINGS
    assert provenance["strength"] == voice.DEFAULT_STRENGTH == "heaviest"
    for row in rows:
        line = mcv.Line(row["id"], row["text"], row["style"])
        audio, alignment = voice.tts_raw(voice.DEFAULT_VOICE, line.text, cache=out / "cache")
        words = voice.words_from_alignment(alignment)
        voice.write(out / "clean" / line.filename, voice.loudnorm(voice.trim_clean(audio)), root=out)
        processed = voice.post(voice.robotise(line, audio, words, "heaviest"), "heaviest")
        duration = voice.write(out / "wav" / line.filename, processed, root=out)
        assert 0.5 <= duration <= 6.0, (line.id, duration)
    (out / "render-provenance.json").write_text(json.dumps({
        "voice": "Daniel", "voice_id": voice.DEFAULT_VOICE, "model": voice.MODEL,
        "settings": voice.VOICE_SETTINGS, "strength": "heaviest", "lines": rows,
        "new_api_requests": voice.Usage.fetched, "new_characters": voice.Usage.characters,
        "cached": voice.Usage.cached, "carrier_pipeline_sha256": sha(Path(voice.__file__)),
        "vocoder_sha256": sha(Path(mcv.__file__)),
    }, indent=2) + "\n", encoding="utf-8")


def prepare(out: Path, rows: list[dict], allow_partial: bool = False) -> dict:
    scripts = out / "install_v2"
    scripts.mkdir(exist_ok=True)
    emitted = {}

    def emit(name, code):
        ast.parse(code)
        path = scripts / name
        path.write_text(code, encoding="utf-8")
        emitted[name] = sha(path)

    emit("00_preflight.py", f"""import unreal
assert isinstance(unreal.load_asset({VOICE_CLASS!r}),unreal.SoundClass)
print('STORM_PANIC_PREFLIGHT',[(i,unreal.EditorAssetLibrary.does_asset_exist({DEST!r}+'/VO_Carrier_'+i)) for i in {IDS!r}])
""")
    entries = []
    for i, row in enumerate(rows):
        name = "VO_Carrier_" + row["id"]
        wav = out / "wav" / (name + ".wav")
        if allow_partial and not wav.is_file():
            continue
        with wave.open(str(wav), "rb") as data:
            assert (data.getnchannels(), data.getsampwidth(), data.getframerate()) == (1, 2, 48000)
            duration = data.getnframes() / data.getframerate()
        assert 0.5 <= duration <= 6.0
        asset = DEST + "/" + name
        import_step = f"{i+1:02d}_apply_{row['id']}.py"
        save_step = f"90_save_{row['id']}.py"
        emit(import_step, f"""import unreal
assert not unreal.EditorAssetLibrary.does_asset_exist({asset!r}), 'Existing panic asset: inspect saved evidence before reimport'
voice=unreal.load_asset({VOICE_CLASS!r})
assert isinstance(voice,unreal.SoundClass)
t=unreal.AssetImportTask()
t.set_editor_property('filename',{wav.resolve().as_posix()!r})
t.set_editor_property('destination_path',{DEST!r})
t.set_editor_property('destination_name',{name!r})
t.set_editor_property('automated',True)
t.set_editor_property('replace_existing',False)
t.set_editor_property('save',False)
unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([t])
w=unreal.load_asset({asset!r})
assert isinstance(w,unreal.SoundWave)
w.set_editor_property('looping',False)
w.set_editor_property('sound_class_object',voice)
assert abs(w.get_editor_property('duration')-{duration!r})<0.02
print('STORM_PANIC_IMPORTED {row['id']}')
""")
        emit(save_step, f"""import unreal
w=unreal.load_asset({asset!r})
assert isinstance(w,unreal.SoundWave)
assert w.get_editor_property('looping') is False
assert w.get_editor_property('sound_class_object').get_path_name()=={(VOICE_CLASS+'.SC_Voice')!r}
assert unreal.EditorAssetLibrary.save_loaded_asset(w,False) is True
print('STORM_PANIC_SAVED {row['id']} saved True')
""")
        entries.append(dict(row, asset=asset, wav=str(wav.resolve()), wav_sha256=sha(wav), duration_s=duration,
                            import_step=import_step, save_step=save_step))
    emit("99_readback.py", "import unreal\n" + "\n".join(
        f"w=unreal.load_asset({e['asset']!r})\nassert isinstance(w,unreal.SoundWave)\n"
        f"assert abs(w.get_editor_property('duration')-{e['duration_s']!r})<0.02\n"
        f"assert w.get_editor_property('looping') is False\n"
        f"assert w.get_editor_property('sound_class_object').get_path_name()=={(VOICE_CLASS+'.SC_Voice')!r}\n"
        for e in entries) + f"print('STORM_PANIC_READBACK_OK {len(entries)} sounds, Voice class, finite duration, no loops')\n")
    assert len(entries) == 6 or allow_partial and len(entries) >= 2
    manifest = {"status": "prepared_not_installed", "install_folder": scripts.name, "rows": entries, "scripts_sha256": emitted,
                "missing_take_ids": [row["id"] for row in rows if row["id"] not in {entry["id"] for entry in entries}],
                "source_sha256": {str(LINES.relative_to(ROOT)): sha(LINES),
                                  str(Path(__file__).resolve().relative_to(ROOT)): sha(Path(__file__)),
                                  'Tools/Audio/carrier_elevenlabs.py': sha(ROOT / 'Tools/Audio/carrier_elevenlabs.py'),
                                  'Tools/Audio/make_carrier_voice.py': sha(ROOT / 'Tools/Audio/make_carrier_voice.py')},
                "requires": ["native build", "root bounded import/save", "DA_Story reimport for English captions"],
                "playback": {"gap_stages_m": [50, 25], "silence_after_warning_s": [16, 12, 8],
                             "first_delay_s": 3.5, "max_clip_s": 6, "initial_instruction_gate": True}}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--allow-partial", action="store_true", help="Prepare existing takes after a documented provider quota refusal")
    args = parser.parse_args()
    out = args.out.resolve()
    assert out.is_relative_to((ROOT / "Saved/Verification").resolve())
    out.mkdir(parents=True, exist_ok=True)
    rows = jobs()
    if args.render:
        render(out, rows)
    manifest = prepare(out, rows, args.allow_partial)
    print(json.dumps({"prepared": len(manifest["rows"]), "scripts": len(manifest["scripts_sha256"]), "out": str(out)}))


if __name__ == "__main__":
    main()
