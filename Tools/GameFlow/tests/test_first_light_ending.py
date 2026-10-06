"""First Light ending data (gen_first_light_ending.py): the words are VOICE_GUIDE 6.2's, the chain is whole, the clock fits."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "Tools" / "GameFlow"))
import gen_first_light_ending as g  # noqa: E402

STORY = json.loads((ROOT / "docs/story/story-events.json").read_text(encoding="utf-8"))
GUIDE = (ROOT / "docs/story/VOICE_GUIDE.md").read_text(encoding="utf-8")
SHOW = (ROOT / "docs/story/drafts/show-acts-2-5-dostoevsky.md").read_text(encoding="utf-8")


def _spoken(parts):
    return [p for p in parts if not p.startswith("(")]


def _norm(s):
    return re.sub(r"\s+", " ", s)


def test_generated_files_are_current():
    assert g.main(["--check"]) == 0


def test_pre_dawn_and_play_dawn_face_the_fitted_window():
    looks = json.loads((ROOT / "Tools/Look/look_keys.json").read_text(encoding="utf-8"))
    pre_dawn = next(key for key in looks if key["name"] == "PreDawn")
    dawn = next(cue for cue in STORY["cinematics"]["CIN_24_TRANSMISSION"]["cues"]
                if cue.get("type") == "PlayDawn")
    assert pre_dawn["sun"]["yaw"] == dawn["yaw"] == 18.66
    assert abs((dawn["yaw"] + 180.0) % 360.0 - 198.66) < 1e-9


def test_scoped_dawn_packet_preserves_detached_rows_and_other_fields():
    import ast
    import copy
    import hashlib
    import struct
    sys.path.insert(0, str(ROOT / "Tools/GameFlow/editor"))
    import install_dawn_bearing as packet
    class Row:
        def __init__(self, **fields): self.fields = fields
        def copy(self): return copy.deepcopy(self)
        def get_editor_property(self, name): return self.fields[name]
        def set_editor_property(self, name, value): self.fields[name] = value
        def export_text(self): return json.dumps(self.fields, sort_keys=True, default=lambda row: row.fields)
    class Unreal:
        class SaskartaActionType:
            PLAY_DAWN = "PlayDawn"
    tree = ast.parse(packet.HEAD)
    helpers = ast.Module(body=[node for node in tree.body if isinstance(node, ast.FunctionDef)], type_ignores=[])
    scope = dict(unreal=Unreal, json=json, struct=struct, hashlib=hashlib)
    exec(compile(helpers, "<dawn detached structs>", "exec"), scope)
    cases = {
        "story": [Row(id="OTHER", cues=[Row(type="Other", yaw=99.)]),
                  Row(id="CIN_24_TRANSMISSION", cues=[Row(type="PlayDawn", yaw=176.5, at_s=0.),
                       Row(type="PlayRadioLine", id="SAMYOR_B24_01", at_s=6.)], final_state=["preserved"])],
        "look": [Row(name="OTHER", sun_yaw=50., sun_pitch=-3.),
                 Row(name="PreDawn", sun_yaw=176.5, sun_pitch=3., fog_density=.003)]}
    for kind, rows in cases.items():
        scope["KIND"] = kind
        before = [row.export_text() for row in rows]
        signature = scope["fingerprint"](rows)
        changed = scope["revised"](rows, 18.66)
        assert [row.export_text() for row in rows] == before
        assert scope["fingerprint"](changed) == signature
        assert scope["state"](changed)["yaw"] == 18.66
        changed[0].set_editor_property("unexpected_change", True)
        assert scope["fingerprint"](changed) != signature


def test_scoped_dawn_packet_is_bounded_and_source_aligned(tmp_path, monkeypatch):
    import ast
    sys.path.insert(0, str(ROOT / "Tools/GameFlow/editor"))
    import install_dawn_bearing as packet
    monkeypatch.setattr(packet, "PACKET", tmp_path / "bearing")
    packet.prepare()
    assert packet.source_bearing() == {"light_travel_yaw": 18.66, "visible_disc_yaw": 198.66}
    for kind in packet.TARGETS:
        assert len(packet.check(kind)["groups"]) == 1
        folder = packet.PACKET / kind
        assert "assert saved is True" in (folder / "90_save.py").read_text()
        for path in folder.glob("*.py"):
            ast.parse(path.read_text())
            assert not packet.bounded.editor.banned(path.read_text())
            assert "import_story_from_files" not in path.read_text()


def test_words_are_the_voice_guide_s_unchanged():
    sec = _norm(GUIDE.split("### 6.2", 1)[1].split("**Changes from the accepted sample.**", 1)[0])
    for _id, parts, _d, _t in g.SAMYOR:
        for p in _spoken(parts):
            assert p in sec, p
    for _id, _v, parts, _d, _t in g.BELOW:
        for p in _spoken(parts):
            assert p.strip("—") in sec, p
    for _id, parts, _d, _t in g.TAIL:
        for p in _spoken(parts):
            assert p in SHOW, p


def test_only_pious_and_no_music_words():
    words = " ".join(" ".join(_spoken(x[-3])) for x in g.SAMYOR + g.BELOW + g.TAIL).lower()
    for bad in ("god", "pray", "holy", "heaven", "soul", "bless", "amen", "sacred", "beautiful", "dead", "passed away", "peace"):
        assert not re.search(rf"\b{bad}\b", words), bad
    assert "pious" in " ".join(g.TAIL[-1][1])


def test_chain_lamp_then_hand_then_cin24():
    beats = {b["id"]: b for b in STORY["beats"]}
    order = [b["id"] for b in STORY["beats"]]
    assert order.index("B22H_HUT_NIGHT") < order.index("B23_LAST_ENTRY") < order.index("B23L_LAMP") < order.index("B24_TRANSMISSION")
    p1 = beats["B23_LAST_ENTRY"]["actions"][-1]
    assert p1 == {"type": "Prompt", "text": "Leave a light on.", "next_beat": "B23L_LAMP"}
    lamp = beats["B23L_LAMP"]
    assert lamp["trigger"].startswith("prompt:")
    assert lamp["actions"][0]["type"] == "SpawnOrReveal" and lamp["actions"][0]["id"] == "HutLamp"
    assert lamp["actions"][-1] == {"type": "Prompt", "text": "Lay your hand on the mark.", "next_beat": "B24_TRANSMISSION"}
    assert [a["id"] for a in beats["B24_TRANSMISSION"]["actions"]] == ["CIN_24_TRANSMISSION", "CIN_25_END_CARD"]


def test_cin24_clock():
    c = STORY["cinematics"]["CIN_24_TRANSMISSION"]
    cues = c["cues"]
    at = {q.get("id"): q["at_s"] for q in cues}
    assert c["duration_s"] == 207.0
    assert all(0.0 <= q["at_s"] <= c["duration_s"] for q in cues)
    dawn = next(q for q in cues if q["type"] == "PlayDawn")
    assert dawn["at_s"] == 0.0 and at["SAMYOR_B24_08"] < dawn["value"] < at["SAMYOR_B24_09"]
    assert at["HUT_NIGHT_A1"] == 0.0 and at["CV_TRANSMIT_01"] < at["SAMYOR_B24_01"]
    # Samyor finishes before the cut to his eyes; the replies only after the breath and 8 s of nothing
    assert at["SAMYOR_B24_10"] + 4.0 <= 84.0 <= at["BREATH_06"]
    assert at["BELOW_R01"] - (at["BREATH_06"] + 14.0) >= 8.0
    assert at["BELOW_R21"] < at["SHOW_A5_TAIL_01"] < at["SHOW_A5_TAIL_02"] < 204.0
    lines = [q["id"] for q in cues if q["type"] in ("PlayRadioLine", "PlayCarrierLine")]
    tsv = (ROOT / "docs/story/radio-lines-for-translation.tsv").read_text(encoding="utf-8")
    for lid in lines:
        assert f"\t{lid}\t" in tsv, lid


def test_samyor_report_is_inside_and_finishes_before_his_exit():
    post = g.bc.radio_post()
    keys = g.bc.radio_body_transform(post, g.bc.FL_END_S)
    inside_at = min(k[0] for k in keys if tuple(k[1:4]) == tuple(post["inside"]))
    exit_at = max(k[0] for k in keys if tuple(k[1:4]) == tuple(post["inside"]))
    at = {q.get("id"): q["at_s"] for q in g.fl_timeline()}
    for lid, _parts, _direction, duration in g.SAMYOR:
        assert inside_at <= at[lid], lid
        assert at[lid] + duration <= exit_at, lid

    # Keep the sunrise response and the death/replies clock intact.
    assert at["SAMYOR_B24_09"] == 64.0
    assert at["SAMYOR_B24_10"] == 76.0
    # Ground contact is baked into the body; the actor no longer rolls in air.
    fallen_at = g.bc.dawn.COLLAPSE_END
    assert next(k for k in keys if k[0] == fallen_at)[4:6] == (0.0, 0.0)
    assert fallen_at < at["BELOW_R01"] < at["SHOW_A5_TAIL_01"]


def test_reply_twenty_finishes_before_twenty_one_and_tail_fits_fade():
    cues = g.fl_timeline()
    at = {q.get("id"): q["at_s"] for q in cues}

    # These authored recordings are 18.23 s and 3.57 s in Saved/RadioRecordings/selected.
    assert at["BELOW_R21"] == 182.75
    assert at["SHOW_A5_TAIL_01"] == 187.2
    assert at["SHOW_A5_TAIL_02"] == 197.7
    assert at["SHOW_A5_TAIL_02"] + 5.0 <= 204.0


def test_title_track_cue_reuses_continuous_score():
    c25 = STORY["cinematics"]["CIN_25_END_CARD"]["cues"]
    assert c25[0]["id"] == "End" and c25[1] == {**c25[1], "at_s": 0.0, "type": "PlaySfx", "id": "eyetae_title"}
    assert not any(q.get("id") == "SFX_ValleyWindBed" for q in c25)
    assert "without restarting" in c25[1]["note"]
    fade = next(q for q in c25 if q["type"] == "StopSfx" and q["id"] == "eyetae_title")
    assert fade["at_s"] == 99.0 and fade["duration_s"] == 3.0


def test_transmission_to_credits_preserves_black_frame_and_drone_view():
    cin24 = g.bc.plan_cin24()
    cin25 = g.bc.plan_cin25()
    story24 = STORY["cinematics"]["CIN_24_TRANSMISSION"]
    story25 = STORY["cinematics"]["CIN_25_END_CARD"]
    assert cin24["duration"] == story24["duration_s"] == 207.0
    assert cin25["duration"] == story25["duration_s"] == 102.0
    assert cin24["cams"][0]["keys"][-1][1:-1] == cin25["cams"][0]["keys"][0][1:-1]
    assert cin24["fade"]["keys"][-1][1] == cin25["fade"]["keys"][0][1] == 1.0
    assert cin25["fade"]["keys"][-1][1] == 1.0
    assert story25["final_state"] == [{"type": "OpenLevel", "id": "Title"}]


def test_actual_recorded_sentences_fit_single_cinematic_voice_lane():
    import wave
    cues = [q for q in g.fl_timeline() if q["type"] == "PlayRadioLine"]
    for cue, following in zip(cues, cues[1:]):
        assert cue["at_s"] + g.TAKE_SECONDS[cue["id"]] <= following["at_s"], cue["id"]
    for lid, duration in g.TAKE_SECONDS.items():
        source = ROOT / "Saved/RadioRecordings/selected" / f"{lid}.wav"
        if source.exists():
            with wave.open(str(source)) as take:
                actual = take.getnframes() / take.getframerate()
            assert abs(actual - duration) <= 0.002, f"{lid}: update cue timing for the new take"


def test_carrier_relay_line():
    cv = json.loads((ROOT / "docs/story/carrier-voice-lines.json").read_text(encoding="utf-8"))
    line = next(x for x in cv["lines"] if x["id"] == "CV_TRANSMIT_01")
    assert line["text"] == "Âlaawb. Live."


def test_human_interactions_are_optional_and_reuse_existing_rest_sounds():
    beats = {b["id"]: b for b in STORY["beats"]}
    pairs = [("B20_REST_BOULDER", "B20R_REST", "Rest.", "BREATH_04A"),
             ("B21_LAST_LOOK_BACK", "B21L_LOOK_BACK", "Look back.", "BREATH_04B"),
             ("B22_REST_HANDRAIL", "B22R_REST", "Catch your breath.", "BREATH_04C")]
    for offer_id, response_id, text, sound in pairs:
        offer, response = beats[offer_id], beats[response_id]
        assert offer["trigger"] == "pass:human" and offer["one_shot"]
        assert offer["actions"] == [{"type": "Prompt", "text": text, "next_beat": response_id, "parallel": True}]
        assert response["trigger"] == "prompt:poll_key" and response["one_shot"]
        assert response["radio_line_ids"] == [] and response["carrier_line_ids"] == []
        assert [a["id"] for a in response["actions"] if a["type"] == "PlaySfx"] == [sound]
        assert not any(a["type"] in ("PlayRadioLine", "PlayCarrierLine") for a in response["actions"])
        if response_id != "B21L_LOOK_BACK":
            assert response["actions"][-1] == {"type": "SetInputLock", "value": 0}
            assert next(a["duration_s"] for a in response["actions"] if a["type"] == "Wait") == 4
    assert beats["B21L_LOOK_BACK"]["actions"][-1]["id"] == "G21_LAST_LOOK"
    assert beats["B23_LAST_ENTRY"]["actions"] == [{"type": "Prompt", "text": "Leave a light on.", "next_beat": "B23L_LAMP"}]
    # Ignoring an offer blocks no beat or movement. Hut playback and mandatory entry remain independently triggered.
    assert beats["B22H_HUT_NIGHT"]["trigger"] == "pass:human"
    assert beats["B23_LAST_ENTRY"]["trigger"] == "volume:SUMMIT_HUT_APPROACH"


def test_human_interaction_generation_is_idempotent():
    import copy
    first = g.beats_patch(copy.deepcopy(STORY))
    second = g.beats_patch(copy.deepcopy(first))
    assert first == second
    ids = [b["id"] for b in second["beats"]]
    for response_id in ("B20R_REST", "B21L_LOOK_BACK", "B22R_REST"):
        assert ids.count(response_id) == 1


def test_hatch_uses_existing_recorded_body_sounds_and_one_latch_release():
    cues = STORY['cinematics']['CIN_19_HATCH']['cues']
    sounds = {(q['at_s'], q['id']) for q in cues if q['type'] == 'PlaySfx'}
    assert (24.6, 'SFX_Cloth_Rustle_03') in sounds
    assert (32.6, 'SFX_Cloth_Rustle_01') in sounds
    assert (6.1, 'SFX_Carrier_Hatch_LockRelease') in sounds
    assert not any(sound in ('FOLEY_01', 'FOLEY_02') for _, sound in sounds)
    for sound in ('SFX_Cloth_Rustle_01', 'SFX_Cloth_Rustle_03'):
        assert (ROOT / f'Content/SaskartaGaea/Audio/Foley/{sound}.uasset').is_file()
    assert (29.8, 'SFX_WalkingAid_Tap_Gravel_01') in sounds
    assert (33.4, 'SFX_WalkingAid_Tap_Gravel_03') in sounds


def test_hatch_breath_stops_bound_long_source_takes_before_next_gesture():
    c19 = STORY['cinematics']['CIN_19_HATCH']
    cues = c19['cues']
    # Simulate the original requested clip lengths. StopSfx fade completion is
    # the effective end; cue duration alone does not constrain PlaySfx.
    durations = {'BREATH_01': 3.0, 'BREATH_05': 8.0, 'BREATH_02': 5.0, 'BREATH_04A': 3.0}
    starts = [q for q in cues if q['type'] == 'PlaySfx' and q['id'] in durations]
    for index, cue in enumerate(starts):
        natural_end = cue['at_s'] + durations[cue['id']]
        stops = [q['at_s'] + q.get('duration_s', 0) for q in cues
                 if q['type'] == 'StopSfx' and q['id'] == cue['id'] and q['at_s'] >= cue['at_s']]
        effective_end = min([natural_end] + stops)
        next_start = starts[index + 1]['at_s'] if index + 1 < len(starts) else c19['duration_s']
        assert effective_end <= next_start + 1e-6, cue
    assert all(q.get('after_prompt') for q in cues if q['type'] == 'StopSfx' and q['at_s'] > 30.5)
    stops = c19['final_state'][:4]
    assert {q['id'] for q in stops} == set(durations)
    assert all(q['type'] == 'StopSfx' and q['duration_s'] == 0 for q in stops)
    assert [q['id'] for q in c19['final_state'][4:]] == ['PossessTraveller', 'Human', 'StartHumanWalk', 'CP4_HUMAN']


def test_hatch_patch_is_idempotent_and_scoped_to_its_cinematic():
    import copy
    first = g.hatch_patch(copy.deepcopy(STORY['cinematics']['CIN_19_HATCH']))
    assert g.hatch_patch(copy.deepcopy(first)) == first
    assert first == STORY['cinematics']['CIN_19_HATCH']
