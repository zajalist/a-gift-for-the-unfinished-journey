import hashlib
import json
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audit_host_recordings import audit  # noqa: E402


def test_plain_author_import_is_not_a_tts_fallback(tmp_path):
    station = tmp_path / "docs/story/station.json"
    station.parent.mkdir(parents=True)
    station.write_text(json.dumps({"segments": [
        {"id": "SHOW_A1_01", "category": "SHOW"},
        {"id": "SHOW_A1_02", "category": "SHOW"},
    ]}), encoding="utf-8")
    selected = tmp_path / "Saved/RadioRecordings/selected"
    selected.mkdir(parents=True)
    selected.joinpath("_tts_manifest.json").write_text('[{"id":"SHOW_A1_02"}]', encoding="utf-8")
    author_bytes = b"author wav bytes"
    selected.joinpath("SHOW_A1_01.wav").write_bytes(author_bytes)
    selected.joinpath("SHOW_A1_02.wav").write_bytes(b"tts wav bytes")
    host = tmp_path / "Content/SaskartaGaea/Audio/Station/Host"
    host.mkdir(parents=True)
    md5 = hashlib.md5(author_bytes).hexdigest()
    host.joinpath("VO_Station_SHOW_A1_01.uasset").write_bytes(f'AssetImportData [{{"FileMD5":"{md5}"}}]'.encode())

    report = audit(tmp_path)
    assert report["summary"] == {
        "station_segments": 2,
        "source_counts": {"author": 1, "tts": 1},
        "author_plain_current": 1,
        "author_recorded_current": 0,
        "author_missing_both": 0,
        "recorded_import_jobs": 1,
    }
    assert report["segments"][0]["plain_matches_selected"]
    assert report["recorded_import_manifest"][0]["destination_folder"].endswith("/Recorded")


def test_stale_plain_and_current_recorded_are_detected(tmp_path):
    station = tmp_path / "docs/story/station.json"
    station.parent.mkdir(parents=True)
    station.write_text(json.dumps({"segments": [{"id": "FILL_A1_01", "category": "FILL"}]}), encoding="utf-8")
    selected = tmp_path / "Saved/RadioRecordings/selected"
    selected.mkdir(parents=True)
    selected.joinpath("_tts_manifest.json").write_text("[]", encoding="utf-8")
    wav = selected / "FILL_A1_01.wav"
    wav.write_bytes(b"new take")
    host = tmp_path / "Content/SaskartaGaea/Audio/Station/Host"
    recorded = host / "Recorded"
    recorded.mkdir(parents=True)
    host.joinpath("VO_Station_FILL_A1_01.uasset").write_bytes(b'"FileMD5":"00000000000000000000000000000000"')
    md5 = hashlib.md5(wav.read_bytes()).hexdigest()
    recorded.joinpath("VO_Station_FILL_A1_01.uasset").write_bytes(f'"FileMD5":"{md5}"'.encode())

    report = audit(tmp_path)
    assert report["summary"]["author_plain_current"] == 0
    assert report["summary"]["author_recorded_current"] == 1
    assert report["summary"]["recorded_import_jobs"] == 0
