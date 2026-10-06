"""Paging and timing logic of caption_cues.py (pure: synthetic speech activity, no audio files).

    python -m pytest Tools/Audio/tests/test_caption_cues.py -q
"""
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import caption_cues as c  # noqa: E402


def test_clean_spoken_matches_the_importer():
    raw = '"There it is. The storm." (beat) "Seven cups now."'
    assert c.clean_spoken(raw) == "There it is. The storm. Seven cups now."


def test_marker_chunks_cut_at_voice_directions_only():
    raw = '"Mm." (pause) "Hang on." (faster) "There." (2 s pause) "No."'
    assert c.marker_chunks(raw) == ["Mm.", "Hang on. There.", "No."]


def test_pages_fit_and_spell_the_text():
    text = ("For the tape: this is Ilaawb, the back room of the post office, on the last night. The year is "
            "eighteen-forty. The works, the mining company, sent us a letter today, and I have read it four times "
            "over, very slowly, by the lamp, twice with my glasses and twice without them.")
    pages = c.page_text([text])
    assert len(pages) >= 3
    assert all(len(p) <= c.MAX_CHARS for p in pages)
    assert c.squash(" ".join(pages)) == c.squash(text)


def test_marker_cut_is_never_spanned():
    pages = c.page_text(["All night.", "Tonight we can."])
    assert pages == ["All night.", "Tonight we can."]


def test_long_sentence_splits_at_a_clause():
    s = ("Upper fields on Monday and Thursday from first light till the bell, the Long Field on Tuesday, "
         "the lower gate on Wednesday at noon")
    parts = c.split_long(s)
    assert len(parts) == 2 and parts[0].endswith(",")


def _activity(speech):
    return c.Activity(duration=speech[-1][1] + 0.5, speech=speech,
                      pauses=[(speech[i][1], speech[i + 1][0]) for i in range(len(speech) - 1)])


def test_align_snaps_each_page_to_its_pause():
    # Three equal pages spoken as three equal runs with a pause after each: pages start at the pauses' ends.
    act = _activity([(0.2, 4.0), (5.5, 9.3), (10.0, 13.8)])
    times = c.time_pages(["a" * 40, "b" * 40, "c" * 40], [40, 40, 40], act)
    assert times[0] == 0.0
    assert abs(times[1] - (5.5 - c.LEAD_S)) < 1e-6
    assert abs(times[2] - (10.0 - c.LEAD_S)) < 1e-6


def test_align_prefers_the_nearest_pause_and_skips_extra_ones():
    # Many pauses; the page boundary at half the text lands on the pause nearest half the speaking time.
    act = _activity([(0.0, 2.0), (2.4, 4.0), (4.5, 6.1), (6.5, 8.0)])
    times = c.time_pages(["x" * 50, "y" * 50], [50, 50], act)
    assert abs(times[1] - (4.5 - c.LEAD_S)) < 1e-6


def test_align_without_pauses_follows_speaking_time():
    act = _activity([(1.0, 11.0)])
    times = c.time_pages(["x" * 30, "y" * 30], [30, 30], act)
    assert abs(times[1] - (6.0 - c.LEAD_S)) < 1e-6


def test_detect_finds_a_pause_with_room_tone():
    rng = np.random.default_rng(1)
    sr = c.SR
    tone = lambda s: 0.3 * np.sin(2 * np.pi * 220 * np.arange(int(s * sr)) / sr)
    room = lambda s: 0.001 * rng.standard_normal(int(s * sr))
    x = np.concatenate([room(0.3), tone(2.0), room(0.6), tone(1.5), room(0.4)]).astype(np.float32)
    act = c.detect(c.frame_db(x), len(x) / sr)
    assert len(act.speech) == 2
    assert len(act.pauses) == 1
    a, b = act.pauses[0]
    assert 2.2 < a < 2.45 and 2.8 < b < 3.0


def test_merge_short_joins_a_flash_page():
    pages, sks, times = c.merge_short(["One.", "Two.", "Three and four."], None, [0.0, 3.0, 3.3], 6.0)
    assert pages == ["One.", "Two. Three and four."]
    assert times == [0.0, 3.0]


def test_flag_rates_marks_an_outlier():
    rows = [{"id": f"L{i}", "letters": 60, "rate": 13.0 + (i % 3) * 0.3} for i in range(12)]
    rows.append({"id": "SLOW", "letters": 60, "rate": 6.0})
    flagged = c.flag_rates(rows)
    assert [r["id"] for r in flagged] == ["SLOW"]


def test_protected_saskartan_name_restores_script_spelling():
    said = "It's at Ta'andedya, above Olaawb."
    script = "It's at Ta'handedya, above Âlaawb."
    assert c.apply_protected_names(said, script, ["Ta'handedya", "Âlaawb"]) == script


def test_word_timestamps_start_next_page_on_spoken_word():
    timed = [
        {"word": "One", "start": 0.2, "end": 0.5},
        {"word": "two.", "start": 0.6, "end": 1.0},
        {"word": "Three", "start": 2.1, "end": 2.4},
        {"word": "four.", "start": 2.5, "end": 2.8},
    ]
    assert c.time_pages_from_words(["One two.", "Three four."], timed, 3.5) == [0.0, 1.98]
