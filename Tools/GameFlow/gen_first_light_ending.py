"""The First Light ending's data (storyline-first-light.md section 5, VOICE_GUIDE 6.2), written into the story files.

    python Tools/GameFlow/gen_first_light_ending.py            # write story-events.json, the TSV, carrier-voice-lines.json
    python Tools/GameFlow/gen_first_light_ending.py --check    # exit 1 if any of them is out of date
    python Tools/GameFlow/gen_first_light_ending.py --print    # the cue sheet, one line per cue
    python Tools/GameFlow/gen_first_light_ending.py --hatch-only  # update only CIN_19_HATCH

The chain after the hatch (B19 -> B20 -> B21 walk):
  B22H_HUT_NIGHT  road 4,950 (pass:human): the hut speaker (the relay's monitor, spatial) starts the night from the
                  top: HUT_NIGHT_A1, Act I in order with the station's static gaps (Tools/Audio/mix_hut_night.py).
  B23_LAST_ENTRY  hut approach volume: prompt "Leave a light on." (polled E / pad A), next B23L_LAMP. RADIO_B23_01 retired.
  B23L_LAMP       the lantern on the hut post lights (SpawnOrReveal HutLamp: a hidden warm point light, placed by
                  ending_editor.py lamp), the lamp click; prompt "Lay your hand on the mark.", next B24.
  B24_TRANSMISSION CIN_24 (the cue sheet below, t = 0 the hand), then CIN_25 (the continuous title track rises).
Only the words come from VOICE_GUIDE 6.2 and the show draft's tail; nothing here rewrites them.
"""
from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "Tools" / "Cinematics"))
import build_cinematics as bc  # noqa: E402

STORY = REPO / "docs" / "story" / "story-events.json"
TSV = REPO / "docs" / "story" / "radio-lines-for-translation.tsv"
CARRIER = REPO / "docs" / "story" / "carrier-voice-lines.json"
HV = "Saskarta.HighVoice"
STATUS = "NEW 2026-09-29: First Light ending (VOICE_GUIDE 6.2)"

# ---------------------------------------------------------------- the lines (VOICE_GUIDE 6.2; the text as written)
# (id, speaker, [spoken parts; "(…)" parts are directions], delivery, target s)
SAMYOR = [
    ("SAMYOR_B24_01", ["(breath)", "Ilaawb. Ilaawb, this is… five-eight-two. Sector—", "(breath)", "No. Samyor. I'm at the top. At the relay."],
     "His first words on air. The number by habit, the section by habit; he stops himself and gives the name. Dry, close.", 9.0),
    ("SAMYOR_B24_02", ["I'm meant to say what I found. I had it up on the screen."], "Report form. Flat.", 4.5),
    ("SAMYOR_B24_03", ["The gate's two posts. No wall. I don't know if there was a wall.", "(breath)",
                       "Ta'handedya has a plate on it now. Six-eight. Like he said."], "Roll call. One breath per phrase.", 11.0),
    ("SAMYOR_B24_04", ["The step's there, the fourth one. I counted. No water."], "The one proud line: 'I counted.'", 5.0),
    ("SAMYOR_B24_05", ["There was a goat, I think. A horn, anyhow."], "The correction makes it smaller.", 4.0),
    ("SAMYOR_B24_06", ["The kettle—", "(breath)", "I don't know. There's a stone with rust on it. I stood there a while."],
     "The one place the report form breaks, on a small thing. Not sad; stuck.", 9.0),
    ("SAMYOR_B24_07", ["That's what I've got."], "End of report.", 2.0),
    ("SAMYOR_B24_08", ["(long pause)", "Hold on."], "Barely voiced; the sun's rim, off-mic of his attention.", 2.0),
    ("SAMYOR_B24_09", ["…It's come up.", "(breath)", "It's like the shift lamps when they—", "(breath)", "No.", "(breath)",
                       "It's warm. This side."], "One comparison from below's machinery, dropped; then the body. No wonder performed.", 11.0),
    ("SAMYOR_B24_10", ["(breath)", "I can't. You'd have to see it."], "Last line. Plain. Then he sits.", 4.0),
]
# (id, voice, parts, delivery, target s). Captions name nobody (FSaskartaFirstLight::CaptionSpeaker: ILAAWB · LIVE).
BELOW = [
    ("BELOW_R01", "UNATTRIBUTED", ["Is it on? Is that him?"], "A click, a room, someone too close to the mic. Chairs.", 2.0),
    ("BELOW_R02", "RSÎSH", ["Five-eight-two, you're faint. Say again. Say again, five-eight—"], "Runs the set; procedure he half knows.", 4.0),
    ("BELOW_R03", "EHB", ["Give it here.", "(close)", "Samyor? It's Ehb. We heard you. Rsîsh has got it all written down."],
     "Takes the mic; close, careful.", 7.0),
    ("BELOW_R04", "TMAZ", ["(off, coughing)", "Is he there?"], "Off-mic, the cough first.", 2.0),
    ("BELOW_R05", "EHB", ["He's not answering."], "Plain.", 1.5),
    ("BELOW_R06", "TMAZ", ["Give him a minute. It's a long way up."], "Dry, fond.", 3.0),
    ("BELOW_R07", "NRINUB", ["Ask him about the goat."], "Too close to the mic.", 1.5),
    ("BELOW_R08", "ILSÎS", ["Nrinub—"], "A step away; the correction.", 0.8),
    ("BELOW_R09", "NRINUB", ["Ask him."], "Over her.", 1.0),
    ("BELOW_R10", "EHB", ["He said a horn. He said he thinks."], "Reading it back.", 3.0),
    ("BELOW_R11", "NRINUB", ["That's her."], "Possessive, certain.", 1.0),
    ("BELOW_R12", "TMAZ", ["There's a wall on the tape. At the gate."], "The quarrel starts, checked against the tape.", 3.0),
    ("BELOW_R13", "RSÎSH", ["He said no wall."], "Blunt.", 1.5),
    ("BELOW_R14", "TMAZ", ["Well, where's it gone?"], "Genuinely asking.", 1.5),
    ("BELOW_R15", "ILSÎS", ["It'll have fallen down, Tmaz."], "Logistics, not comfort.", 2.0),
    ("BELOW_R16", "TMAZ", ["(cough)", "Fifty years I've had that wall."], "Humour from the cough, never a punchline.", 3.0),
    ("BELOW_R17", "RSÎSH", ["He can't hear us."], "The true thing nobody answers.", 1.5),
    ("BELOW_R18", "EB", ["(off-mic)", "Keep talking. Keep talking to him."], "Off-mic; two-to-four-word authority.", 2.5),
    ("BELOW_R19", "ILSÎS", ["Who's moved his chair? Put it back. By the pipe."], "Care as logistics.", 3.5),
    ("BELOW_R20", "EHB", ["We're all here, Samyor. Tmaz is here. Ilsîs. Rsîsh. Nrinub. They carried Eb down. It took—", "(hiss)",
                          "Nobody touch the set. We're leaving it on."], "The one unfinished sentence is hers; then an instruction to the room.", 18.23),
    ("BELOW_R21", "WALLA", ["—is it still—", "—it's on—", "—somebody get Eb a—", "—leave it—"],
     "The room murmurs and thins, unattributed, overlapping; under the wind. 3-5 of the voices.", 3.57),
]
# The tail of the tape, in a robotic narrator's voice (the author, 2026-09-29; Tools/Audio/robot_narrator.py renders
# both clips). Split in two so the long pause is timed and the last line gets its own caption.
TAIL_STATUS = "RECAST 2026-09-29: robotic narrator (the author); rendered, not recorded"
TAIL = [
    ("SHOW_A5_TAIL_01", ["Every house. They've all left one on."],
     "A narrator voice with a light robotic edge (not the author): ElevenLabs 'Brian', Tools/Audio/robot_narrator.py. The first half; a long pause follows. Never scheduled.", 4.0),
    ("SHOW_A5_TAIL_02", ["The world swallowed its pride, and became pious in its sleep."],
     "A narrator voice with a light robotic edge (not the author): ElevenLabs 'Brian', Tools/Audio/robot_narrator.py. The last line of the game, after a long pause. Plain; no music, nobody reacts.", 5.0),
]

# Actual selected takes, confirmed against each imported SoundWave's AssetImportData MD5
# on 2026-10-01. Target delivery lengths above are writing guidance, not playback cut points.
# Keep every sentence intact on EventRunner's single cinematic voice component.
TAKE_SECONDS = {
    "SAMYOR_B24_01": 13.19, "SAMYOR_B24_02": 4.79, "SAMYOR_B24_03": 13.035,
    "SAMYOR_B24_04": 6.03, "SAMYOR_B24_05": 4.61, "SAMYOR_B24_06": 7.225,
    "SAMYOR_B24_07": 1.355, "SAMYOR_B24_08": 1.01, "SAMYOR_B24_09": 7.775,
    "SAMYOR_B24_10": 3.31,
    "BELOW_R01": 2.285, "BELOW_R02": 7.16, "BELOW_R03": 8.85, "BELOW_R04": 1.08,
    "BELOW_R05": 1.55, "BELOW_R06": 2.88, "BELOW_R07": 1.45, "BELOW_R08": 0.92,
    "BELOW_R09": 0.78, "BELOW_R10": 3.725, "BELOW_R11": 0.725, "BELOW_R12": 3.025,
    "BELOW_R13": 1.415, "BELOW_R14": 1.975, "BELOW_R15": 2.55, "BELOW_R16": 2.26,
    "BELOW_R17": 1.34, "BELOW_R18": 3.695, "BELOW_R19": 5.25, "BELOW_R20": 18.23,
    "BELOW_R21": 3.57, "SHOW_A5_TAIL_01": 2.857, "SHOW_A5_TAIL_02": 4.372,
}

# ---------------------------------------------------------------- CIN_24's cue sheet (t = 0: the hand on the mark)
def _line(t, i):
    return {"at_s": t, "type": "PlayRadioLine", "id": i}


def fl_timeline() -> list[dict]:
    c = [
        {"at_s": 0.0, "type": "SetFlowState", "id": "Transmit"},
        {"at_s": 0.0, "type": "CallHook", "id": "StopHumanWalk", "target_tag": "PC", "note": "the walking breath and steps stop"},
        {"at_s": 0.0, "type": "StopSfx", "id": "HUT_NIGHT_A1", "duration_s": 0.0, "note": "hard cut, mid-word"},
        {"at_s": 0.0, "type": "CallHook", "id": "SnapKeeperToPlate", "target_tag": HV},
        {"at_s": 0.0, "type": "CallHook", "id": "HideKeeper", "target_tag": HV,
         "note": "the sequence owns the visible body entering the hut; the playable pawn stays hidden"},
        {"at_s": 0.0, "type": "PlayDawn", "duration_s": 120.0, "value": 62.0, "pitch": -0.5, "yaw": 18.66,
         "keep_on_skip": True, "note": "the disc clears the cloud sea at 62 s (after 'Hold on.'); measure pitch on the bearing"},
        {"at_s": 0.2, "type": "PlaySfx", "id": "SFX_RelayClunk", "target_tag": HV},
        {"at_s": 0.8, "type": "PlayCarrierLine", "id": "CV_TRANSMIT_01"},
        {"at_s": 1.0, "type": "PlaySfx", "id": "SFX_OpenChannelHiss", "note": "Ilaawb's static bed; looping; stopped at the cut"},
    ]
    t = 6.0  # Samyor reaches the hidden hut interior at 5.8 s; his report starts from inside.
    for lid, _parts, _d, _target_s in SAMYOR:
        # He notices warm light through the window, then responds to the sunrise and comes out.
        # These three anchors stay aligned to dawn62 / supported exit84, with the report inside.
        t = {"SAMYOR_B24_08": 59.5, "SAMYOR_B24_09": 64.0, "SAMYOR_B24_10": 76.0}.get(lid, t)
        c.append(_line(round(t, 2), lid))
        t += TAKE_SECONDS[lid] + 0.3
    # After B24_10 (ends ~83), the sequence body exits into the drone's locked view.
    # His breath slows and stops as he reaches the overlook.
    c += [
        {"at_s": bc.FL_SEATED_AT + 0.5, "type": "PlaySfx", "id": "BREATH_06", "note": "recorded breathing composite (18.8 s): cough aligns with collapse at 99.5 s; final recorded breath tail ends at 103.3 s, quiet before the 107 s click; listening acceptance pending"},
        {"at_s": 60.0, "type": "PlaySfx", "id": "SFX_WindLift", "note": "the wind lifts a little as the disc clears"},
    ]
    # The recorded breath tails out at 103.3; a quiet 3.7 s gap precedes the room click.
    t = 107.0
    c.append({"at_s": t, "type": "PlaySfx", "id": "SFX_LiveRoomClick", "note": "a click, a room, chairs"})
    t += 1.0
    for lid, _v, _p, _d, _target_s in BELOW:
        c.append(_line(round(t, 2), lid))
        t += TAKE_SECONDS[lid] + 0.18
    # The whole live room fits before the tape without truncation; retain the long final pause.
    t = 186.5
    c += [
        {"at_s": t, "type": "PlaySfx", "id": "SFX_RelayClunk", "target_tag": HV, "note": "the live channel drops back to the tape"},
        {"at_s": t + 0.3, "type": "PlaySfx", "id": "SFX_TapeRoom_A5", "note": "under the hiss, the host's room: a cup, a chair, a window latch, wind"},
        _line(187.2, "SHOW_A5_TAIL_01"),
        _line(197.7, "SHOW_A5_TAIL_02"),                              # (long pause, wind)
        {"at_s": 203.0, "type": "PlaySfx", "id": "SFX_RelaySwitch", "note": "a switch; only the relay's hiss"},
        {"at_s": bc.FL_END_S, "type": "StopSfx", "id": "SFX_OpenChannelHiss", "duration_s": 0.0, "note": "the cut"},
    ]
    return sorted(c, key=lambda x: x["at_s"])


# ---------------------------------------------------------------- story-events.json
def human_interactions_patch(d: dict) -> None:
    """One-shot, non-blocking offers; acceptance alone runs the existing breath/rest/look action."""
    import copy

    beats = d["beats"]
    choices = (("B20_REST_BOULDER", "B20R_REST", "Rest.", "BREATH_04A"),
               ("B21_LAST_LOOK_BACK", "B21L_LOOK_BACK", "Look back.", "BREATH_04B"),
               ("B22_REST_HANDRAIL", "B22R_REST", "Catch your breath.", "BREATH_04C"))
    for offer_id, response_id, text, sound in choices:
        ids = [b["id"] for b in beats]
        offer = beats[ids.index(offer_id)]
        response = copy.deepcopy(beats[ids.index(response_id)] if response_id in ids else offer)
        response.update(id=response_id, trigger="prompt:poll_key", one_shot=True, priority="Story",
                        radio_line_ids=[], carrier_line_ids=[],
                        notes="Optional human interaction, accepted with polled E / pad A. Existing breath/foley only; no new speech.")
        response.pop("tier", None)
        response.pop("requires_tags", None)
        response.pop("prompts", None)
        if response_id == "B21L_LOOK_BACK":
            response["actions"] = [{"type": "PlaySfx", "id": sound, "parallel": True},
                                   {"type": "Glance", "id": "G21_LAST_LOOK",
                                    "note": "Existing valley look and 10 s hold, only when the player asks."}]
        else:
            response["actions"] = [{"type": "SetInputLock", "value": 1},
                                   {"type": "PlaySfx", "id": sound, "parallel": True},
                                   {"type": "Wait", "duration_s": 4},
                                   {"type": "SetInputLock", "value": 0}]
        offer.update(priority="Hint", one_shot=True,
                     notes="Optional offer while walking. Move on to ignore it; the next offer or mandatory hut prompt replaces it. "
                           "Parallel Prompt keeps the story lane free; no movement lock until accepted.",
                     actions=[{"type": "Prompt", "text": text, "next_beat": response_id, "parallel": True}])
        offer.pop("tier", None)
        offer.pop("requires_tags", None)
        if response_id in ids:
            beats[ids.index(response_id)] = response
        else:
            beats.insert(ids.index(offer_id) + 1, response)


def beats_patch(d: dict) -> dict:
    human_interactions_patch(d)
    beats = d["beats"]
    ids = [b["id"] for b in beats]
    b22 = beats[ids.index("B22_REST_HANDRAIL")]
    hut = {"id": "B22H_HUT_NIGHT", "distance_m": 4950, "ue_distance_from_p0_m": b22["ue_distance_from_p0_m"], "world": b22["world"],
           "trigger": "pass:human", "radio_line_ids": [], "carrier_line_ids": [], "one_shot": True,
           "notes": "First Light (draft section 5): the hut speaker (the relay's monitor, spatial, about -14 dB in the cue's "
                    "attenuation) starts the night again from the top: HUT_NIGHT_A1 = Act I in order from SHOW_A1_01 with the "
                    "station's 4-12 s static gaps (Tools/Audio/mix_hut_night.py). It runs for as long as the player takes; "
                    "CIN_24 cuts it at the hand (StopSfx, mid-word).",
           "actions": [{"type": "PlaySfx", "id": "HUT_NIGHT_A1", "target_tag": HV, "parallel": True}]}
    b23 = beats[ids.index("B23_LAST_ENTRY")]
    b23["trigger"] = "volume:SUMMIT_HUT_APPROACH"
    b23["radio_line_ids"] = []
    b23["prompts"] = ["Leave a light on.", "Lay your hand on the mark."]
    b23["notes"] = ("First Light: relay hut at the mast foot; the plate carries the capsule's mark (an open palm in a ring). "
                    "RADIO_B23_01 retired (draft 4.1). Prompt 'Leave a light on.' (polled E / pad A), then B23L_LAMP. "
                    "The SUMMIT_HUT_APPROACH pawn-only volume gates the prompt beside the actual hut doorway; "
                    "road 4,990 remains map metadata, not the trigger.")
    b23["actions"] = [{"type": "Prompt", "text": "Leave a light on.", "next_beat": "B23L_LAMP"}]
    lamp = {"id": "B23L_LAMP", "distance_m": 4990, "ue_distance_from_p0_m": b23["ue_distance_from_p0_m"], "world": b23["world"],
            "trigger": "prompt:poll_key", "radio_line_ids": [], "carrier_line_ids": [], "one_shot": True,
            "notes": "The lantern on the hut post lights: SpawnOrReveal HutLamp shows the actors tagged Saskarta.Reveal.HutLamp "
                     "(a warm point light and its flame card, hidden in game until now; ending_editor.py lamp). The lamp click; "
                     "the host goes on underneath. Then 'Lay your hand on the mark.'",
            "actions": [{"type": "SpawnOrReveal", "id": "HutLamp", "reapply_on_load": True},
                        {"type": "PlaySfx", "id": "SFX_LampClick", "target_tag": HV, "parallel": True},
                        {"type": "Wait", "duration_s": 1.5},
                        {"type": "Prompt", "text": "Lay your hand on the mark.", "next_beat": "B24_TRANSMISSION"}]}
    for new, after in ((hut, "B22_REST_HANDRAIL"), (lamp, "B23_LAST_ENTRY")):
        ids = [b["id"] for b in beats]
        if new["id"] in ids:
            beats[ids.index(new["id"])] = new
        else:
            beats.insert(ids.index(after) + 1, new)
    b24 = beats[[b["id"] for b in beats].index("B24_TRANSMISSION")]
    b24["radio_line_ids"] = [s[0] for s in SAMYOR] + [b[0] for b in BELOW] + [t[0] for t in TAIL]
    b24["carrier_line_ids"] = ["CV_TRANSMIT_01"]
    b24.pop("clip", None)
    b24["notes"] = ("First Light (VOICE_GUIDE 6.2; exterior staging updated 2026-09-30): the companion drone descends "
                    "outside the relay hut as Samyor enters. His report (SAMYOR_B24_01-10) comes from inside, unseen; "
                    "He notices brightening light through the window at 'Hold on.' (59.5 s); PlayDawn clears the disc at 62 s. "
                    "His warm-light response stays inside, then he returns at 84 s to see the sun in person, walks toward "
                    "the valley, coughs and collapses. The drone settles on that view and stays locked through the replies "
                    "and credits. BREATH_06 slows and stops; wind and hiss; Qahtîb answers a dead man (BELOW_R01-R21, a timed "
                    "chain on the cine lane, captioned ILAAWB · LIVE); the relay drops back to the tape: the host's tail "
                    "(SHOW_A5_TAIL_01/02); a switch; fade to black over 3 s. The title track continues softly from the human "
                    "walk, yields under the transmission and rises smoothly into CIN_25 without restarting. "
                    "CHORUS_B24, CV_TRANSMIT_02 and TRANSMISSION COMPLETE are retired.")
    b24["final_shot"] = {"view": "CIN24_GroundedDrone outside the relay hut, locked on Samyor and the valley; continued by CIN25",
                         "hold_s": round(bc.FL_FADE_AT - bc.FL_SEATED_AT, 1),
                         "audio": "the breath stopping, wind, hiss, the replies, the tape's tail; the continuous title track remains subdued under the words"}
    return d


def hatch_patch(c19: dict) -> dict:
    """Keep hatch sounds on the measured action clock, including eventual performer takes."""
    replacements = {24.6: "SFX_Cloth_Rustle_03", 32.6: "SFX_Cloth_Rustle_01"}
    breath_ids = ("BREATH_01", "BREATH_05", "BREATH_02", "BREATH_04A")
    cues = []
    for cue in c19["cues"]:
        cue = dict(cue)
        if cue.get("id") == "FOLEY_02" and cue.get("at_s") == 1.2:
            continue  # The measured latch release already plays at 6.1, after contact.
        if cue.get("id") == "FOLEY_01" and cue.get("at_s") in replacements:
            cue["id"] = replacements[cue["at_s"]]
        if cue.get("type") == "StopSfx" and cue.get("id") in breath_ids:
            continue
        cues.append(cue)
    # PlaySfx does not trim to an action duration. End each outgoing performance
    # before the next voice gesture/handoff, rather than layering two Samyors.
    for at, sound in ((12.3, "BREATH_01"), (16.9, "BREATH_05"),
                      (34.9, "BREATH_02"), (35.9, "BREATH_04A")):
        stop = {"at_s": at, "type": "StopSfx", "id": sound, "duration_s": 0.1}
        if at > 30.5:
            stop["after_prompt"] = True
        cues.append(stop)
    c19["cues"] = sorted(cues, key=lambda cue: cue["at_s"])
    # Skipping can bypass those timed stops. Clear them before StartHumanWalk
    # starts the walking-breath component; retain every original handoff action.
    final = [cue for cue in c19["final_state"]
             if not (cue.get("type") == "StopSfx" and cue.get("id") in breath_ids)]
    c19["final_state"] = [{"type": "StopSfx", "id": sound, "duration_s": 0.0}
                          for sound in breath_ids] + final
    c19["note"] = (
        "Exterior drone hatch reveal (author direction 2026-09-30): the sole camera cut is CIN19_ExteriorDrone, "
        "looking at the latch side of the capsule. An uncut body-motion anchor preserves the measured hand, "
        "foot and staff contacts of the five A_Samyor clips; the neck and head retain full scale. "
        "The existing 36-second action clock is retained: latch 6.1, opening 8.2, staff grip 29.8, "
        "Rise prompt 30.5, closing 34.4, then a 0.6-second handoff to the third-person Traveller camera. "
        "One escort drone follows Samyor during the walk and the other stays with the carrier. "
        "Recorded jacket gestures cover the leg-over-rim and rise; the single latch release stays at 6.1. "
        "Timed breath stops prevent overlapping performances and final-state stops cover skipping; "
        "dedicated breath recordings remain required.")
    return c19


def cinematics_patch(d: dict) -> dict:
    hatch_patch(d["cinematics"]["CIN_19_HATCH"])
    c24 = d["cinematics"]["CIN_24_TRANSMISSION"]
    c24["duration_s"] = bc.FL_END_S
    c24["skip"] = "HoldAfterSeen"
    c24["note"] = ("First Light. Camera plan: build_cinematics.py plan CIN_24_TRANSMISSION (WORLD frame): one exterior "
                   "drone camera descends at the hut, holds while Samyor speaks inside, follows his exit after 84 s, then "
                   "locks through collapse, replies and the 204-207 s fade. CIN25 keeps this camera behind its opaque end card. "
                   "The cues are gen_first_light_ending.py's "
                   "cue sheet, fitted to the imported recordings so the single cine voice lane never cuts a sentence. "
                   "Window light notice59.5, dawn62, warm-light response64 and supported exit84 stay aligned.")
    c24["cues"] = fl_timeline()
    c24["final_state"] = []
    c25 = d["cinematics"]["CIN_25_END_CARD"]
    c25["note"] = (
        "The 102 s ending card keeps the same grounded-drone view as CIN24 in a second world-frame "
        "camera sequence, while the playtest-approved UMG backing stays opaque black through the "
        "logo, short credits, 82 s roll and final three seconds. The camera and Fade track remain "
        "hidden behind that backing. "
        "The calligraphy is the only title. The roll text comes from CREDITS_SCREEN.md. "
        "A sequence is required so the runner waits for the complete card before OpenLevel Title."
    )
    # A deliberate hold keeps a stray key during the logo from skipping the
    # entire credit roll; the usual skip prompt still appears after 3 seconds.
    c25["skip"] = "HoldAlways"
    cues = [q for q in c25["cues"] if not (q["type"] in ("PlaySfx", "StopSfx") and q["id"] in ("SFX_ValleyWindBed", "eyetae_title"))]
    cues.insert(1, {"at_s": 0.0, "type": "PlaySfx", "id": "eyetae_title",
                    "note": "2026-10-01: reuse the station's continuous title-track player from the human walk; End raises it smoothly for credits without restarting"})
    cues.append({"at_s": c25["duration_s"] - 3.0, "type": "StopSfx", "id": "eyetae_title", "duration_s": 3.0,
                 "note": "the one intentional score fade after the complete roll, before returning to the title menu"})
    c25["cues"] = cues
    fs = [q for q in c25.get("final_state", []) if not (q["type"] == "StopSfx" and q["id"] == "eyetae_title")]
    c25["final_state"] = fs      # The timed fade ends at OpenLevel Title; no second music player is created here.
    hooks = d["ending_hooks"]
    hooks["Saskarta.HighVoice (BP_Saskarta_HighVoice)"] = ["SnapKeeperToPlate", "HideKeeper"]
    return d


# ---------------------------------------------------------------- the TSV
def _english(parts: list[str]) -> str:
    """The TSV's English cell before CSV quoting: spoken parts in "…", directions bare."""
    return " ".join(p if p.startswith("(") else f'"{p}"' for p in parts)


def tsv_rows() -> list[list[str]]:
    rows = []
    for lid, parts, deliv, dur in SAMYOR:
        rows.append([lid, "Ending", "SAMYOR", "B24 First Light, live on the Âlaawb relay (VOICE_GUIDE 6.2). Caption: no speaker label.",
                     _english(parts), deliv + " Dry, close; one breath per phrase.", f"{dur:g} s", "EN", "", "", "", STATUS])
    for lid, voice, parts, deliv, dur in BELOW:
        rows.append([lid, "Ending", voice, "B24 First Light, Qahtîb answers (VOICE_GUIDE 6.2). Caption: ILAAWB · LIVE (names nobody).",
                     _english(parts), deliv + " Record dry; the relay filter is added in the mix.", f"{dur:g} s", "EN", "", "", "", STATUS])
    for lid, parts, deliv, dur in TAIL:
        rows.append([lid, "Show", "NARRATOR", "B24 First Light, the tail of the tape after the live channel drops (show draft 'The tail').",
                     _english(parts), deliv, f"{dur:g} s", "EN", "", "", "", TAIL_STATUS])
    return rows


def tsv_text(old: str) -> str:
    bom = old.startswith("﻿")
    body = old.lstrip("﻿")
    rdr = list(csv.reader(io.StringIO(body), delimiter="\t"))
    head, rows = rdr[0], rdr[1:]
    new = {r[0]: r for r in tsv_rows()}
    out, seen = [], set()
    for r in rows:
        if len(r) > 1 and r[1] in new:
            out.append([r[0]] + new[r[1]])
            seen.add(r[1])
            continue
        if len(r) > 5 and r[1] == "CV_TRANSMIT_01":
            r[5] = '"Âlaawb. Live."'
            r[4] = "B24 First Light, 0.8 s after the hand on the mark, spoken by the relay in the same system voice (quieter, from the hut)."
        if len(r) > 12 and r[1] == "CV_TRANSMIT_02" and not r[12].startswith("RETIRED"):
            r[12] = "RETIRED 2026-09-29: First Light has no TRANSMISSION COMPLETE"
        if len(r) > 12 and r[1] == "RADIO_B23_01" and not r[12].startswith("RETIRED"):
            r[12] = "RETIRED 2026-09-29: First Light (draft 4.1); the hut speaker plays the night instead"
        out.append(r)
    n = max(int(r[0]) for r in out if r and r[0].isdigit())
    for lid, r in new.items():
        if lid not in seen:
            n += 1
            out.append([str(n)] + r)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter="\t", lineterminator="\n")
    w.writerow(head)
    w.writerows(out)
    return ("﻿" if bom else "") + buf.getvalue()


def carrier_text(old: str) -> str:
    d = json.loads(old)
    for line in d["lines"]:
        if line["id"] == "CV_TRANSMIT_01":
            line["text"] = "Âlaawb. Live."
            line["when"] = "B24 First Light, 0.8 s after the hand on the mark, spoken by the relay in the same system voice (quieter, from the hut)."
        if line["id"] == "CV_TRANSMIT_02":
            line["record"] = "retired"
            line["when"] = "RETIRED 2026-09-29 (First Light has no TRANSMISSION COMPLETE)."
    return json.dumps(d, indent=2, ensure_ascii=False) + "\n"


def story_text(old: str) -> str:
    d = json.loads(old)
    cinematics_patch(beats_patch(d))
    return json.dumps(d, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str]) -> int:
    if "--hatch-only" in argv:
        old = STORY.read_text(encoding="utf-8")
        data = json.loads(old)
        hatch_patch(data["cinematics"]["CIN_19_HATCH"])
        new = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        changed = new != old
        if changed and "--check" not in argv:
            STORY.write_text(new, encoding="utf-8", newline="\n")
        print(("out of date: " if "--check" in argv else "wrote: ") + ("CIN_19_HATCH" if changed else "nothing"))
        return int(changed and "--check" in argv)
    if "--print" in argv:
        for c in fl_timeline():
            print(f"{c['at_s']:7.1f}  {c['type']:15s} {c.get('id', '')}")
        return 0
    stale = []
    for path, fn in ((STORY, story_text), (TSV, tsv_text), (CARRIER, carrier_text)):
        old = path.read_text(encoding="utf-8")
        new = fn(old)
        if new != old:
            stale.append(path.name)
            if "--check" not in argv:
                path.write_text(new, encoding="utf-8", newline="\n")
    print(("out of date: " if "--check" in argv else "wrote: ") + (", ".join(stale) or "nothing"))
    return 1 if ("--check" in argv and stale) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
