"""gen_boot_pacing: a slower first-boot terminal, each line carrying its CV_BOOT voice (user, 2026-09-28).

    python Tools/GameFlow/gen_boot_pacing.py   # patches specs/BPC_CarrierVision.json + specs/WBP_Saskarta_BootLog.graph.json
    node Tools/GameFlow/bpgraph.mjs build --reset-graphs Tools/GameFlow/specs/BPC_CarrierVision.json

Idempotent. Changes:
- typing 40 chars/s (was 55) in both the component and the widget;
- each line holds at least MinLineTime 1.8 s (was ~1.2); the blinking cursor shows in the gap;
- first boot: lines 1-3 play VO_Carrier_CV_BOOT_01..03 as they start, and the next line waits for
  that voice + VoiceTail 0.4 s (durations baked from the takes: 1.09 / 2.965 / 2.405 s);
  CV_BOOT_04 stays with CIN_01 (story-events.json);
- first boot: RouteLockPause 2.5 s before line 4 (ROUTE LOCK - ÂLAAWB);
- FinalHold 1.5 s (was 0.35) on the last line before PowerOn / the handover.
Reboots keep their old, quick pace (no voice, no pause).
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
COMP = HERE / "specs" / "BPC_CarrierVision.json"
WIDGET = HERE / "specs" / "WBP_Saskarta_BootLog.graph.json"
KML = "/Script/Engine.KismetMathLibrary"
GPS = "/Script/Engine.GameplayStatics"
VO = "/Game/SaskartaGaea/Audio/CarrierVoice/"
VOICES = [("VO_Carrier_CV_BOOT_01", 1.09), ("VO_Carrier_CV_BOOT_02", 2.965), ("VO_Carrier_CV_BOOT_03", 2.405)]


def setvar(spec, name, typ, default):
    for v in spec["variables"]:
        if v["name"] == name:
            v["type"] = typ
            v["default"] = default
            return
    spec["variables"].append({"name": name, "type": typ, "default": default})


def patch_component(s):
    setvar(s, "CharsPerSecond", "float", "40.0")
    setvar(s, "FinalHold", "float", "1.5")
    setvar(s, "MinLineTime", "float", "1.8")
    setvar(s, "VoiceTail", "float", "0.4")
    setvar(s, "RouteLockPause", "float", "2.5")
    setvar(s, "VoiceHold", "float", "0.0")
    for i, (n, dur) in enumerate(VOICES, 1):
        setvar(s, f"BootVoice{i}", "object:/Script/Engine.SoundBase", f"{VO}{n}.{n}")
        setvar(s, f"BootVoice{i}Time", "float", str(dur))
    g = next(g for g in s["graphs"] if g["graph"] == "BootLineStep")
    N, L, D = g["nodes"], g["links"], g.setdefault("defaults", {})
    if "vIf" in N:
        return s

    def link(a, b):
        L.append([a, b])

    # voice: first boot and BootLine < 3 (read before the increment)
    N.update({
        "vLine": {"get": "BootLine"}, "vFirst": {"call": "Not_PreBool", "class": KML},
        "vLt": {"call": "Less_IntInt", "class": KML}, "vAnd": {"call": "BooleanAND", "class": KML},
        "vIf": {"branch": True}, "vPick": {"select": 3}, "vTime": {"select": 3},
        "vPlay": {"call": "SpawnSound2D", "class": GPS}, "vTail": {"get": "VoiceTail"},
        "vHold": {"call": "Add_DoubleDouble", "class": KML}, "vSet": {"set": "VoiceHold"}, "vZero": {"set": "VoiceHold"},
    })
    for i in range(1, 4):
        N[f"vS{i}"] = {"get": f"BootVoice{i}"}
        N[f"vT{i}"] = {"get": f"BootVoice{i}Time"}
        link(f"vS{i}.BootVoice{i}", f"vPick.Option {i - 1}")
        link(f"vT{i}.BootVoice{i}Time", f"vTime.Option {i - 1}")
    D["vLt.B"] = "3"
    D["vZero.VoiceHold"] = "0.0"
    for a, b in [("isReboot.ReturnValue", "vFirst.A"), ("vLine.BootLine", "vLt.A"), ("vFirst.ReturnValue", "vAnd.A"),
                 ("vLt.ReturnValue", "vAnd.B"), ("vAnd.ReturnValue", "vIf.Condition"), ("vLine.BootLine", "vPick.Index"),
                 ("vLine.BootLine", "vTime.Index"), ("vPick.ReturnValue", "vPlay.Sound"), ("vTime.ReturnValue", "vHold.A"),
                 ("vTail.VoiceTail", "vHold.B"), ("vHold.ReturnValue", "vSet.VoiceHold")]:
        link(a, b)
    L.remove(["playBurst.then", "setHold.execute"])
    for a, b in [("playBurst.then", "vIf.execute"), ("vIf.then", "vPlay.execute"), ("vPlay.then", "vSet.execute"),
                 ("vSet.then", "setHold.execute"), ("vIf.else", "vZero.execute"), ("vZero.then", "setHold.execute")]:
        link(a, b)

    # next line: max(LineHold + LineGap, MinLineTime, VoiceHold) + (first boot and next is line 4 ? RouteLockPause : 0)
    N.update({
        "nMin": {"get": "MinLineTime"}, "nVoice": {"get": "VoiceHold"}, "nMax1": {"call": "FMax", "class": KML},
        "nMax2": {"call": "FMax", "class": KML}, "nIdx": {"get": "BootLine"}, "nIs3": {"call": "EqualEqual_IntInt", "class": KML},
        "nFirst": {"call": "Not_PreBool", "class": KML}, "nAnd": {"call": "BooleanAND", "class": KML},
        "nPause": {"get": "RouteLockPause"}, "nSel": {"call": "SelectFloat", "class": KML}, "nAdd": {"call": "Add_DoubleDouble", "class": KML},
    })
    D["nIs3.B"] = "3"
    D["nSel.B"] = "0.0"
    L.remove(["untilNext.ReturnValue", "safeNext.Value"])
    for a, b in [("untilNext.ReturnValue", "nMax1.A"), ("nMin.MinLineTime", "nMax1.B"), ("nMax1.ReturnValue", "nMax2.A"),
                 ("nVoice.VoiceHold", "nMax2.B"), ("nIdx.BootLine", "nIs3.A"), ("isReboot.ReturnValue", "nFirst.A"),
                 ("nIs3.ReturnValue", "nAnd.A"), ("nFirst.ReturnValue", "nAnd.B"), ("nPause.RouteLockPause", "nSel.A"),
                 ("nAnd.ReturnValue", "nSel.bPickA"), ("nMax2.ReturnValue", "nAdd.A"), ("nSel.ReturnValue", "nAdd.B"),
                 ("nAdd.ReturnValue", "safeNext.Value")]:
        link(a, b)

    # power-on: max(LineHold, VoiceHold) + FinalHold
    N["pVoice"] = {"get": "VoiceHold"}
    N["pMax"] = {"call": "FMax", "class": KML}
    L.remove(["getHold.LineHold", "untilPowerOn.A"])
    for a, b in [("getHold.LineHold", "pMax.A"), ("pVoice.VoiceHold", "pMax.B"), ("pMax.ReturnValue", "untilPowerOn.A")]:
        link(a, b)
    return s


def patch_widget(s):
    setvar(s, "CharsPerSecond", "float", "40.0")
    return s


if __name__ == "__main__":
    for path, fn in ((COMP, patch_component), (WIDGET, patch_widget)):
        spec = json.loads(path.read_text(encoding="utf-8"))
        path.write_text(json.dumps(fn(spec), indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        print("patched", path.name)
    # timing table for the first boot (typing at 40 cps, stall + status 0.26 s, gap 0.08 s)
    lines = ["CONTACTOR - CLOSING", "HANDOVER - CARRIER 07 / UNITS 01-06 LOST", "LOAD - 1 CAPSULE / ARCHIVE / 36.6 C", "ROUTE LOCK - ÂLAAWB"]
    t = 1.25
    for i, ln in enumerate(lines):
        hold = len(ln) / 40 + 0.26
        voice = VOICES[i][1] + 0.4 if i < 3 else 0.0
        print(f"line {i + 1} at {t:5.2f} s  typing {len(ln) / 40:.2f} s  voice {voice:.2f} s  {ln}")
        nxt = max(hold + 0.08, 1.8, voice) + (2.5 if i == 2 else 0.0)
        t += nxt if i < 3 else max(hold, voice) + 1.5
    print(f"PowerOn at {t:5.2f} s (was ~5.8 s)")
