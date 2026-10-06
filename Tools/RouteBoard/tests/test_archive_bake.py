import importlib.util
from pathlib import Path
import struct
import wave

import pytest

SPEC = importlib.util.spec_from_file_location("archive_bake", Path(__file__).resolve().parents[1] / "bake_archive.py")
BAKE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BAKE)


def test_waveform_is_audio_and_preserves_silence(tmp_path):
    path = tmp_path / "voice.wav"
    with wave.open(str(path), "wb") as audio:
        audio.setparams((2, 2, 8, 0, "NONE", "not compressed"))
        audio.writeframes(b"".join(struct.pack("<hh", s, -s) for s in [0, 0, 1000, -1000, 2000, -2000, 0, 0]))
    result = BAKE.envelope(path, 4)
    assert result["duration_s"] == 1
    assert result["peaks"] == [0, 0.5, 1, 0]
    assert len(result["source_sha256"]) == 64


def test_silent_audio_is_not_fabricated(tmp_path):
    path = tmp_path / "silence.wav"
    with wave.open(str(path), "wb") as audio:
        audio.setparams((1, 2, 8, 0, "NONE", "not compressed"))
        audio.writeframes(bytes(16))
    assert BAKE.envelope(path, 4)["peaks"] == [0, 0, 0, 0]


def test_24_bit_signed_and_bin_limit(tmp_path):
    path = tmp_path / "song.wav"
    with wave.open(str(path), "wb") as audio:
        audio.setparams((1, 3, 4, 0, "NONE", "not compressed"))
        audio.writeframes(b"".join(s.to_bytes(3, "little", signed=True) for s in [0, -8388608, 4194304, 0]))
    assert BAKE.envelope(path, 4)["peaks"] == [0, 1, 0.5, 0]
    with pytest.raises(ValueError):
        BAKE.envelope(path, 129)
