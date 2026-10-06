"""Generate WBP_Saskarta_TitleRadio: the radio that keeps playing on the title screen (LANE5, the user 2026-09-28).

    python Tools/GameFlow/gen_titleradio_specs.py   # -> specs/WBP_Saskarta_TitleRadio.{tree,graph}.json + editor/titleradio_playlist.py

Behaviour (a hidden widget, created by BP_Saskarta_HUD; timers only, no tick):
- While FlowState is Title: when the title song (PC_Saskarta's only AudioComponent, eyetae_title, routed through
  the station's radio chain) has finished, or after START_S of title idle, a tune-over (RADIOFX sweep) moves to the
  Low Voice: a looped playlist of station IDs, weather, kitchen, talk and letter segments and song blocks
  (intro, Hayaa / Malak / Weli, outro), with 1.2-3 s gaps. Nothing zone- or journey-specific.
  If the title song is still playing at the tune-over, it fades out under the sweep.
- Settings open (a WBP_Saskarta_Settings on screen): -6 dB. The station volume setting (saskarta.volume.station)
  scales everything; with the radio setting off (saskarta.radio 0) the title radio stays silent.
- Leaving Title (Begin): a static collapse and a 1 s fade-out; it never plays again that session. The start
  sequence (fire card, cards) stays fire-only.
The playlist is a hard-referenced array on the class defaults (editor/titleradio_playlist.py), loaded with the HUD
at level start: nothing loads synchronously on the title.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from gen_debug_specs import G, KML, KSL, KSTR, GS, RUNNER, fn, runner

ROOT = Path(__file__).resolve().parents[2]
WBP = "/Game/SaskartaGaea/GameFlow/UI/WBP_Saskarta_TitleRadio"
KARR = "/Script/Engine.KismetArrayLibrary"
AC = "/Script/Engine.AudioComponent"
SETTINGS_C = "/Game/SaskartaGaea/GameFlow/UI/WBP_Saskarta_Settings.WBP_Saskarta_Settings_C"
RFX = "/Game/SaskartaGaea/Audio/Radio"
SWEEP = f"{RFX}/SFX_Radio_Tune_Sweep_03.SFX_Radio_Tune_Sweep_03"
COLLAPSE = f"{RFX}/SFX_Radio_Power_Off_Collapse.SFX_Radio_Power_Off_Collapse"
HOST = "/Game/SaskartaGaea/Audio/Station/Host"
SONGS = "/Game/SaskartaGaea/Audio/Station/Songs"
START_S = 80.0
POLL_S = 0.25
DUCK = 0.5


def playlist(seed: int = 7) -> list[str]:
    """~45 items: talk from the journey-free categories, a song block every 3 talk items."""
    st = json.loads((ROOT / "docs/story/station.json").read_text(encoding="utf-8"))
    segs = []

    def walk(o):
        if isinstance(o, dict):
            if "id" in o and "category" in o:
                segs.append(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(st)
    have = {p.stem for p in (ROOT / "Content/SaskartaGaea/Audio/Station/Host").glob("VO_Station_*.uasset")}
    rng = random.Random(seed)

    def pool(cat, no_hint=True):
        ids = [s["id"] for s in segs if s["category"] == cat and f"VO_Station_{s['id']}" in have
               and not (no_hint and s.get("tags", {}).get("leaving_hint"))]
        rng.shuffle(ids)
        return ids
    ids, talk = pool("ID"), pool("WEATHER") + pool("KITCHEN") + pool("TALK") + pool("LETTER")
    rng.shuffle(talk)
    intros, outros = pool("INTRO"), pool("OUTRO")
    songs = ["hayaa", "malak", "weli"]
    out = []
    t = s = 0
    while t < len(talk):
        out.append(f"{HOST}/VO_Station_{ids[len(out) % len(ids)]}")
        for _ in range(3):
            if t < len(talk):
                out.append(f"{HOST}/VO_Station_{talk[t]}")
                t += 1
        out.append(f"{HOST}/VO_Station_{intros[s % len(intros)]}")
        out.append(f"{SONGS}/SONG_{songs[s % len(songs)]}")
        out.append(f"{HOST}/VO_Station_{outros[s % len(outros)]}")
        s += 1
    return out


def tree() -> dict:
    return {"asset": WBP, "tree": [], "variables": []}


def build() -> dict:
    variables = [
        {"name": "Playlist", "type": "array<object:/Script/Engine.SoundBase>"},
        {"name": "Index", "type": "int", "default": "0"},
        {"name": "Phase", "type": "int", "default": "0"},         # 0 waiting, 1 on air, 2 done
        {"name": "TitleSince", "type": "float", "default": "-1.0"},
        {"name": "NextAt", "type": "float", "default": "0.0"},
        {"name": "bWasPlaying", "type": "bool", "default": "false"},
        {"name": "Comp", "type": "object:/Script/Engine.AudioComponent"},
        {"name": "PollTimer", "type": "struct:/Script/Engine.TimerHandle"},
    ]
    functions = [fn("Poll"), fn("PlayNext", [("Vol", "float")]), fn("GoOff"),
                 fn("Now", outputs=[("T", "float")], pure=True), fn("Volume", outputs=[("V", "float")], pure=True)]
    graphs = []

    g = G("EventGraph")
    ev = g.add({"event": "Construct"}, "construct")
    tm = g.add({"timer": True}, "timer")
    g.defaults.update({f"{tm}.FunctionName": "Poll", f"{tm}.Time": str(POLL_S), f"{tm}.bLooping": "true"})
    st = g.set("PollTimer")
    g.link(f"{tm}.ReturnValue", f"{st}.PollTimer")
    g.chain(ev, tm, st)
    graphs.append(g.spec())

    # Now() = world time
    g = G("Now")
    e = g.add({"entry": True}, "entry")
    r = g.add({"result": True}, "result")
    me = g.add({"self": True})
    t = g.call("GetTimeSeconds", GS)
    g.link(f"{me}.self", f"{t}.WorldContextObject")
    g.link(f"{t}.ReturnValue", f"{r}.T")
    g.chain(e, r)
    graphs.append(g.spec())

    # Volume() = station volume x (0.5 while the settings are open)
    g = G("Volume")
    e = g.add({"entry": True}, "entry")
    r = g.add({"result": True}, "result")
    vol = g.call("GetConsoleVariableFloatValue", KSL, VariableName="saskarta.volume.station")
    me = g.add({"self": True})
    ws = g.call("GetAllWidgetsOfClass", "/Script/UMG.WidgetBlueprintLibrary", WidgetClass=SETTINGS_C, TopLevelOnly="true")
    g.link(f"{me}.self", f"{ws}.WorldContextObject")
    ln = g.call("Array_Length", KARR)
    g.link(f"{ws}.FoundWidgets", f"{ln}.TargetArray")
    open_ = g.call("Greater_IntInt", KML, B="0")
    g.link(f"{ln}.ReturnValue", f"{open_}.A")
    duck = g.call("SelectFloat", KML, A=str(DUCK), B="1.0")
    g.link(f"{open_}.ReturnValue", f"{duck}.bPickA")
    mul = g.call("Multiply_DoubleDouble", KML)
    g.link(f"{vol}.ReturnValue", f"{mul}.A")
    g.link(f"{duck}.ReturnValue", f"{mul}.B")
    g.link(f"{mul}.ReturnValue", f"{r}.V")
    g.chain(e, vol, ws, r)  # the cvar getter is impure: on the exec chain
    graphs.append(g.spec())

    # PlayNext(Vol): Comp = SpawnSound2D(Playlist[Index % Len]); Index++
    g = G("PlayNext")
    e = g.add({"entry": True}, "entry")
    pl = g.get("Playlist")
    ln = g.call("Array_Length", KARR)
    g.link(f"{pl}.Playlist", f"{ln}.TargetArray")
    idx = g.get("Index")
    mod = g.call("Percent_IntInt", KML)
    g.link(f"{idx}.Index", f"{mod}.A")
    mx = g.call("Max", KML, B="1")
    g.link(f"{ln}.ReturnValue", f"{mx}.A")
    g.link(f"{mx}.ReturnValue", f"{mod}.B")
    pl2 = g.get("Playlist")
    get = g.call("Array_Get", KARR)
    g.link(f"{pl2}.Playlist", f"{get}.TargetArray")
    g.link(f"{mod}.ReturnValue", f"{get}.Index")
    me = g.add({"self": True})
    sp = g.call("SpawnSound2D", GS, bPersistAcrossLevelTransition="false", bAutoDestroy="true")
    g.link(f"{me}.self", f"{sp}.WorldContextObject")
    g.link(f"{get}.Item", f"{sp}.Sound")
    g.link(f"{e}.Vol", f"{sp}.VolumeMultiplier")
    sc = g.set("Comp")
    g.link(f"{sp}.ReturnValue", f"{sc}.Comp")
    inc = g.call("Add_IntInt", KML, B="1")
    g.link(f"{g.get('Index')}.Index", f"{inc}.A")
    si = g.set("Index")
    g.link(f"{inc}.ReturnValue", f"{si}.Index")
    sw = g.set("bWasPlaying", "true")
    g.chain(e, sp, sc, si, sw)
    graphs.append(g.spec())

    # GoOff: leaving the title: static collapse, fade out, done
    g = G("GoOff")
    e = g.add({"entry": True}, "entry")
    me = g.add({"self": True})
    col = g.call("PlaySound2D", GS, Sound=COLLAPSE, VolumeMultiplier="0.5")
    g.link(f"{me}.self", f"{col}.WorldContextObject")
    c = g.get("Comp")
    ok = g.call("IsValid", KSL)
    g.link(f"{c}.Comp", f"{ok}.Object")
    br = g.add({"branch": True}, "ifComp")
    g.link(f"{ok}.ReturnValue", f"{br}.Condition")
    fo = g.call("FadeOut", AC, FadeOutDuration="1.0", FadeVolumeLevel="0.0")
    g.link(f"{g.get('Comp')}.Comp", f"{fo}.self")
    ph = g.set("Phase", "2")
    g.chain(e, col, br)
    g.chain(f"{br}.then", fo, ph)
    g.chain(f"{br}.else", ph)
    graphs.append(g.spec())

    # Poll
    g = G("Poll")
    e = g.add({"entry": True}, "entry")
    r = runner(g)
    fs = g.call("GetFlowState", RUNNER)
    g.link(f"{r}.ReturnValue", f"{fs}.self")
    isT = g.call("EqualEqual_NameName", KML, B="Title")
    g.link(f"{fs}.ReturnValue", f"{isT}.A")
    brT = g.add({"branch": True}, "ifTitle")
    g.link(f"{isT}.ReturnValue", f"{brT}.Condition")
    # not title: once on air -> GoOff
    onAir = g.call("EqualEqual_IntInt", KML, B="1")
    g.link(f"{g.get('Phase')}.Phase", f"{onAir}.A")
    brOff = g.add({"branch": True}, "ifOnAir")
    g.link(f"{onAir}.ReturnValue", f"{brOff}.Condition")
    goOff = g.call("GoOff")
    g.chain(e, brT)
    g.chain(f"{brT}.else", brOff)
    g.chain(f"{brOff}.then", goOff)
    # title: remember when it began
    now = g.call("Now")
    first = g.call("Less_DoubleDouble", KML, B="0.0")
    g.link(f"{g.get('TitleSince')}.TitleSince", f"{first}.A")
    brF = g.add({"branch": True}, "ifFirst")
    g.link(f"{first}.ReturnValue", f"{brF}.Condition")
    sTs = g.set("TitleSince")
    g.link(f"{now}.T", f"{sTs}.TitleSince")
    nx = g.call("Add_DoubleDouble", KML, B=str(START_S))
    g.link(f"{now}.T", f"{nx}.A")
    sNx = g.set("NextAt")
    g.link(f"{nx}.ReturnValue", f"{sNx}.NextAt")
    # phase switch
    ph0 = g.call("EqualEqual_IntInt", KML, B="0")
    g.link(f"{g.get('Phase')}.Phase", f"{ph0}.A")
    br0 = g.add({"branch": True}, "ifWaiting")
    g.link(f"{ph0}.ReturnValue", f"{br0}.Condition")
    g.chain(f"{brT}.then", brF)
    g.chain(f"{brF}.then", sTs, sNx, br0)
    g.chain(f"{brF}.else", br0)
    # waiting: start when the title song has ended (PC's AudioComponent not playing) or NextAt passed, radio on
    pc = g.call("GetOwningPlayer", "/Script/UMG.UserWidget")
    me2 = g.add({"self": True})
    g.link(f"{me2}.self", f"{pc}.self")
    mus = g.call("GetComponentByClass", "/Script/Engine.Actor", ComponentClass="/Script/Engine.AudioComponent")
    g.link(f"{pc}.ReturnValue", f"{mus}.self")
    musCast = g.add({"cast": AC}, "castMusic")
    g.link(f"{mus}.ReturnValue", f"{musCast}.Object")
    playing = g.call("IsPlaying", AC)
    g.link(f"{musCast}.As", f"{playing}.self")
    now2 = g.call("Now")
    due = g.call("GreaterEqual_DoubleDouble", KML)
    g.link(f"{now2}.T", f"{due}.A")
    g.link(f"{g.get('NextAt')}.NextAt", f"{due}.B")
    since = g.call("Subtract_DoubleDouble", KML)
    g.link(f"{now2}.T", f"{since}.A")
    g.link(f"{g.get('TitleSince')}.TitleSince", f"{since}.B")
    settled = g.call("Greater_DoubleDouble", KML, B="8.0")   # the song has had time to start
    g.link(f"{since}.ReturnValue", f"{settled}.A")
    notPlaying = g.call("Not_PreBool", KML)
    g.link(f"{playing}.ReturnValue", f"{notPlaying}.A")
    songDone = g.call("BooleanAND", KML)
    g.link(f"{notPlaying}.ReturnValue", f"{songDone}.A")
    g.link(f"{settled}.ReturnValue", f"{songDone}.B")
    go = g.call("BooleanOR", KML)
    g.link(f"{due}.ReturnValue", f"{go}.A")
    g.link(f"{songDone}.ReturnValue", f"{go}.B")
    radio = g.call("GetConsoleVariableBoolValue", KSL, VariableName="saskarta.radio")
    goOn = g.call("BooleanAND", KML)
    g.link(f"{go}.ReturnValue", f"{goOn}.A")
    g.link(f"{radio}.ReturnValue", f"{goOn}.B")
    brGo = g.add({"branch": True}, "ifGo")
    g.link(f"{goOn}.ReturnValue", f"{brGo}.Condition")
    vol = g.call("Volume")
    me3 = g.add({"self": True})
    sweep = g.call("PlaySound2D", GS, Sound=SWEEP)
    g.link(f"{me3}.self", f"{sweep}.WorldContextObject")
    g.link(f"{vol}.V", f"{sweep}.VolumeMultiplier")
    fade = g.call("FadeOut", AC, FadeOutDuration="2.0", FadeVolumeLevel="0.0")
    g.link(f"{musCast}.As", f"{fade}.self")
    s1 = g.set("Phase", "1")
    now3 = g.call("Now")
    n2 = g.call("Add_DoubleDouble", KML, B="0.6")
    g.link(f"{now3}.T", f"{n2}.A")
    sN2 = g.set("NextAt")
    g.link(f"{n2}.ReturnValue", f"{sN2}.NextAt")
    sW = g.set("bWasPlaying", "false")
    g.chain(f"{br0}.then", radio, musCast, brGo)
    g.chain(f"{musCast}.castfailed", brGo)
    g.chain(f"{brGo}.then", sweep, fade, s1, sN2, sW)
    # on air: keep the volume; when an item ends, wait a gap, then the next
    ph1 = g.call("EqualEqual_IntInt", KML, B="1")
    g.link(f"{g.get('Phase')}.Phase", f"{ph1}.A")
    br1 = g.add({"branch": True}, "ifOnAir2")
    g.link(f"{ph1}.ReturnValue", f"{br1}.Condition")
    g.chain(f"{br0}.else", br1)
    c = g.get("Comp")
    cv = g.call("IsValid", KSL)
    g.link(f"{c}.Comp", f"{cv}.Object")
    brV = g.add({"branch": True}, "ifCompValid")
    g.link(f"{cv}.ReturnValue", f"{brV}.Condition")
    cp = g.call("IsPlaying", AC)
    g.link(f"{g.get('Comp')}.Comp", f"{cp}.self")
    brP = g.add({"branch": True}, "ifPlaying")
    g.link(f"{cp}.ReturnValue", f"{brP}.Condition")
    vol2 = g.call("Volume")
    sv = g.call("SetVolumeMultiplier", AC)
    g.link(f"{g.get('Comp')}.Comp", f"{sv}.self")
    g.link(f"{vol2}.V", f"{sv}.NewVolumeMultiplier")
    # not playing: just ended -> NextAt = now + gap; else when due -> PlayNext
    brW = g.add({"branch": True}, "ifJustEnded")
    g.link(f"{g.get('bWasPlaying')}.bWasPlaying", f"{brW}.Condition")
    now4 = g.call("Now")
    gap = g.call("RandomFloatInRange", KML, Min="1.2", Max="3.0")
    n3 = g.call("Add_DoubleDouble", KML)
    g.link(f"{now4}.T", f"{n3}.A")
    g.link(f"{gap}.ReturnValue", f"{n3}.B")
    sN3 = g.set("NextAt")
    g.link(f"{n3}.ReturnValue", f"{sN3}.NextAt")
    sW2 = g.set("bWasPlaying", "false")
    now5 = g.call("Now")
    due2 = g.call("GreaterEqual_DoubleDouble", KML)
    g.link(f"{now5}.T", f"{due2}.A")
    g.link(f"{g.get('NextAt')}.NextAt", f"{due2}.B")
    brD = g.add({"branch": True}, "ifDue")
    g.link(f"{due2}.ReturnValue", f"{brD}.Condition")
    vol3 = g.call("Volume")
    pn = g.call("PlayNext")
    g.link(f"{vol3}.V", f"{pn}.Vol")
    g.chain(f"{br1}.then", brV)
    g.chain(f"{brV}.then", brP)
    g.chain(f"{brV}.else", brW)
    g.chain(f"{brP}.then", sv)
    g.chain(f"{brP}.else", brW)
    g.chain(f"{brW}.then", sN3, sW2)
    g.chain(f"{brW}.else", brD)
    g.chain(f"{brD}.then", pn)
    graphs.append(g.spec())

    return {"asset": WBP, "description": "LANE5 title radio (gen_titleradio_specs.py).", "variables": variables,
            "functions": functions, "graphs": graphs}


PLAYLIST_SCRIPT = """# python_run (Hayba), LANE5: WBP_Saskarta_TitleRadio's Playlist (class defaults), generated by gen_titleradio_specs.py.
import unreal
eal = unreal.EditorAssetLibrary
P = '/Game/SaskartaGaea/GameFlow/UI/WBP_Saskarta_TitleRadio'
items = [eal.load_asset(p) for p in __LIST__]
d = unreal.get_default_object(unreal.load_object(None, P + '.WBP_Saskarta_TitleRadio_C'))
d.set_editor_property('playlist', [x for x in items if x is not None])
bp = unreal.load_asset(P)
unreal.BlueprintEditorLibrary.compile_blueprint(bp)
d = unreal.get_default_object(unreal.load_object(None, P + '.WBP_Saskarta_TitleRadio_C'))
print('playlist', len(d.get_editor_property('playlist')), '/', len(items), str(bp.get_editor_property('status')))
print('saved', eal.save_asset(P, False))
"""


if __name__ == "__main__":
    specs = ROOT / "Tools" / "GameFlow" / "specs"
    (specs / "WBP_Saskarta_TitleRadio.tree.json").write_text(json.dumps(tree(), indent=1) + "\n", encoding="utf-8")
    (specs / "WBP_Saskarta_TitleRadio.graph.json").write_text(json.dumps(build(), indent=1) + "\n", encoding="utf-8")
    pl = playlist()
    (ROOT / "Tools/GameFlow/editor/titleradio_playlist.py").write_text(PLAYLIST_SCRIPT.replace("__LIST__", repr(pl)), encoding="utf-8")
    print("wrote tree + graph + playlist", len(pl))
