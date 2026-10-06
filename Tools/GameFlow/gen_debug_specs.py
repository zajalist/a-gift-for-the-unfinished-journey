"""Generate the debug-mode specs (LANE5, README_Debug.md).

    python Tools/GameFlow/gen_debug_specs.py            # writes the three specs
    python Tools/GameFlow/gen_debug_specs.py --table    # prints the teleport table

Outputs (Tools/GameFlow/specs/):
  CM_Saskarta.json                 the cheat manager (exec functions + debug logic), bpgraph spec
  CM_Saskarta.post.json            its exec flags and baked beat arrays (not expressible in bpgraph)
  WBP_Saskarta_Debug.tree.json     the debug menu's designer tree (ui_build_tree)
  WBP_Saskarta_Debug.graph.json    the debug menu's graph (bound button events), bpgraph spec

The beat list is baked from docs/story/story-events.json (every beat with a road metre, in road
order) plus the checkpoints (FSaskartaEventLogic::CheckpointRoadM). Re-run after the story data
changes, then rebuild both Blueprints.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPECS = ROOT / "Tools" / "GameFlow" / "specs"

CM = "/Game/SaskartaGaea/GameFlow/Debug/CM_Saskarta"
CM_C = CM + ".CM_Saskarta_C"
WBP = "/Game/SaskartaGaea/GameFlow/Debug/WBP_Saskarta_Debug"
WBP_C = WBP + ".WBP_Saskarta_Debug_C"
PC_C = "/Game/SaskartaGaea/GameFlow/PC_Saskarta.PC_Saskarta_C"
TETHER_C = "/Game/SaskartaGaea/GameFlow/BPC_RoadTether.BPC_RoadTether_C"
ROAD_C = "/Game/SaskartaGaea/Road/BP_Saskarta_Road.BP_Saskarta_Road_C"
BFL_ROAD_C = "/Game/SaskartaGaea/GameFlow/BFL_SaskartaRoad.BFL_SaskartaRoad_C"
MPC_SKY = "/Game/SaskartaGaea/Look/MPC_Saskarta_Sky.MPC_Saskarta_Sky"

RUNNER = "/Script/SaskartaCore.SaskartaEventRunner"
EVLIB = "/Script/SaskartaCore.SaskartaEventLibrary"
DIRECTOR = "/Script/SaskartaCore.SaskartaLightingDirector"
DEBUGLIB = "/Script/SaskartaCore.SaskartaDebugLibrary"
KSL = "/Script/Engine.KismetSystemLibrary"
KML = "/Script/Engine.KismetMathLibrary"
KSTR = "/Script/Engine.KismetStringLibrary"
KTXT = "/Script/Engine.KismetTextLibrary"
KARR = "/Script/Engine.KismetArrayLibrary"
KMAT = "/Script/Engine.KismetMaterialLibrary"
GS = "/Script/Engine.GameplayStatics"
WBL = "/Script/UMG.WidgetBlueprintLibrary"
ACTOR = "/Script/Engine.Actor"
CTRL = "/Script/Engine.Controller"
CHEAT = "/Script/Engine.CheatManager"

BACK_M = 30.0          # teleport this far before the beat's trigger
ARM_BEHIND_M = 5.0     # the armed beat fires only after road m was seen this far behind it
LOOK_KEYS = [("Valley", 0), ("Basin", 2300), ("Climb", 3800), ("InCloud", 4350), ("PreDawn", 4550)]
CHECKPOINTS = [("CP0_DOCK", 0.0), ("CP1_CREST", 1990.0), ("CP2_WAYSTATION", 3420.0), ("CP3_SHOULDER", 4465.0)]


# ============================================================================ data

def beat_table() -> list[dict]:
    """Every beat with a road metre, in road order (story, optional, then ties by id)."""
    d = json.loads((ROOT / "docs" / "story" / "story-events.json").read_text(encoding="utf-8"))
    out = []
    for group in ("beats", "optional_beats"):
        for b in d.get(group, []):
            road = b.get("distance_m")
            if road is None:
                continue
            kind = b.get("trigger", "")
            out.append({"id": b["id"], "road_m": float(road), "optional": group == "optional_beats",
                        "trigger": kind if isinstance(kind, str) else json.dumps(kind)})
    out.sort(key=lambda r: (r["road_m"], r["optional"], r["id"]))
    return out


# ============================================================================ tiny graph builder

class G:
    """One graph: nodes, links, defaults, with automatic node names."""

    def __init__(self, name: str):
        self.name = name
        self.nodes: dict = {}
        self.links: list = []
        self.defaults: dict = {}
        self.n = 0

    def add(self, kind: dict, name: str | None = None) -> str:
        self.n += 1
        key = name or f"n{self.n}"
        assert key not in self.nodes, key
        self.nodes[key] = kind
        return key

    def call(self, fn: str, cls: str | None = None, name: str | None = None, **defaults) -> str:
        node = {"call": fn}
        if cls:
            node["class"] = cls
        k = self.add(node, name)
        for pin, v in defaults.items():
            self.defaults[f"{k}.{pin}"] = v
        return k

    def get(self, var: str) -> str:
        return self.add({"get": var})

    def set(self, var: str, value: str | None = None) -> str:
        k = self.add({"set": var})
        if value is not None:
            self.defaults[f"{k}.{var}"] = value
        return k

    def link(self, a: str, b: str):
        self.links.append([a, b])

    def chain(self, *execs: str):
        """entry.then -> a.execute -> a.then -> b.execute ... (a pin name may be given as 'x.else')."""
        for a, b in zip(execs, execs[1:]):
            src = a if "." in a else f"{a}.then"
            dst = b if "." in b else f"{b}.execute"
            self.link(src, dst)

    def spec(self) -> dict:
        return {"graph": self.name, "nodes": self.nodes, "links": self.links, "defaults": self.defaults}


def fn(name, inputs=(), outputs=(), pure=False):
    return {"name": name, "inputs": [{"name": n, "type": t} for n, t in inputs],
            "outputs": [{"name": n, "type": t} for n, t in outputs], "pure": pure}


def runner(g: G) -> str:
    """GetEventRunner(self) -> ReturnValue."""
    me = g.add({"self": True})
    r = g.call("GetEventRunner", RUNNER)
    g.link(f"{me}.self", f"{r}.WorldContextObject")
    return r


def pc(g: G) -> str:
    return g.call("GetPlayerController", CHEAT)


def pawn(g: G) -> str:
    p = pc(g)
    k = g.call("K2_GetPawn", CTRL)
    g.link(f"{p}.ReturnValue", f"{k}.self")
    return k


def log_line(g: G, text_pin: str | None = None, literal: str | None = None) -> str:
    """AddLog(Line) with either a linked string or a literal. Returns the call node."""
    k = g.call("AddLog")
    if text_pin:
        g.link(text_pin, f"{k}.Line")
    else:
        g.defaults[f"{k}.Line"] = literal
    return k


def concat(g: G, a: str | None, b: str | None, a_lit: str | None = None, b_lit: str | None = None) -> str:
    k = g.call("Concat_StrStr", KSTR)
    if a:
        g.link(a, f"{k}.A")
    else:
        g.defaults[f"{k}.A"] = a_lit
    if b:
        g.link(b, f"{k}.B")
    else:
        g.defaults[f"{k}.B"] = b_lit
    return f"{k}.ReturnValue"


def float_str(g: G, pin: str) -> str:
    """Rounded to whole metres: Round -> Conv_IntToString."""
    r = g.call("Round", KML)
    g.link(pin, f"{r}.A")
    s = g.call("Conv_IntToString", KSTR)
    g.link(f"{r}.ReturnValue", f"{s}.InInt")
    return f"{s}.ReturnValue"


def console(g: G, command: str) -> str:
    p = pc(g)
    k = g.call("ExecuteConsoleCommand", KSL, Command=command)
    g.link(f"{p}.ReturnValue", f"{k}.SpecificPlayer")
    return k


# ============================================================================ CM_Saskarta

def build_cm(beats: list[dict]) -> dict:
    variables = [
        {"name": "DebugWidget", "type": f"object:{WBP_C}"},
        {"name": "bMenuOpen", "type": "bool", "default": "false"},
        {"name": "BeatIds", "type": "array<name>"},
        {"name": "BeatRoadMs", "type": "array<float>"},
        {"name": "SelIndex", "type": "int", "default": "0"},
        {"name": "ArmedBeat", "type": "name", "default": "None"},
        {"name": "ArmedRoadM", "type": "float", "default": "0.0"},
        {"name": "bArmReady", "type": "bool", "default": "false"},
        {"name": "ArmTimer", "type": "struct:/Script/Engine.TimerHandle"},
        {"name": "bAutoTrigger", "type": "bool", "default": "false"},
        {"name": "BackCm", "type": "float", "default": str(BACK_M * 100.0)},
        {"name": "PlaceStepCm", "type": "float", "default": "0.0"},
        {"name": "PlaceTries", "type": "int", "default": "0"},
        {"name": "PlaceTimer", "type": "struct:/Script/Engine.TimerHandle"},
        {"name": "SpeedMul", "type": "float", "default": "1.0"},
        {"name": "bGod", "type": "bool", "default": "false"},
        {"name": "GodTimer", "type": "struct:/Script/Engine.TimerHandle"},
        {"name": "StormOverride", "type": "float", "default": "-1.0"},
        {"name": "StormTimer", "type": "struct:/Script/Engine.TimerHandle"},
        {"name": "DebugLog", "type": "string"},
        {"name": "SavedLocation", "type": "vector"},
        {"name": "SavedRotation", "type": "rotator"},
    ]
    functions = [
        # exec (console) functions: README_Debug.md
        fn("SaskartaDebug"),
        fn("SaskartaTP", [("Target", "string")]),
        fn("SaskartaBeat", [("BeatId", "name")]),
        fn("SaskartaSkip"),
        fn("SaskartaResetBeats"),
        fn("SaskartaSpeed", [("Multiplier", "float")]),
        fn("SaskartaGod"),
        fn("SaskartaFly"),
        fn("SaskartaNext"),
        fn("SaskartaPrev"),
        fn("SaskartaStorm", [("Intensity", "float")]),
        fn("SaskartaLook", [("RoadM", "float")]),
        # helpers the widget calls
        fn("DebugGoTo", [("BeatId", "name"), ("RoadM", "float")]),
        fn("DebugGoToRoad", [("RoadM", "float")]),
        fn("SelectIndex", [("Index", "int")]),
        fn("TriggerSelected"),
        fn("SetAutoTrigger", [("bOn", "bool")]),
        fn("StatUnit"),
        fn("RestartFlow"),
        fn("AddLog", [("Line", "string")]),
        fn("GetStatusText", outputs=[("Text", "string")], pure=False),
        # timers (no inputs)
        fn("PlaceOnRoad", [("StepCm", "float")]),
        fn("TryPlace"),
        fn("CheckArmed"),
        fn("KeepGod"),
        fn("ApplyStorm"),
    ]
    graphs = []

    # ---- EventGraph: InitCheatManager -> log capture note
    g = G("EventGraph")
    ev = g.add({"event": "ReceiveInitCheatManager"}, "init")
    lg = log_line(g, literal="debug ready: F9 or SaskartaDebug opens the menu")
    g.chain(ev, lg)
    graphs.append(g.spec())

    # ---- AddLog(Line): DebugLog = Line + "\n" + Left(DebugLog, 900)   (newest first)
    g = G("AddLog")
    e = g.add({"entry": True}, "entry")
    old = g.get("DebugLog")
    left = g.call("Left", KSTR, Count="900")
    g.link(f"{old}.DebugLog", f"{left}.SourceString")
    nl = concat(g, f"{e}.Line", None, b_lit="\n")
    full = concat(g, nl, f"{left}.ReturnValue")
    s = g.set("DebugLog")
    g.link(full, f"{s}.DebugLog")
    g.chain(e, s)
    graphs.append(g.spec())

    # ---- SaskartaDebug: toggle the menu
    g = G("SaskartaDebug")
    e = g.add({"entry": True}, "entry")
    isOpen = g.get("bMenuOpen")
    br = g.add({"branch": True}, "ifOpen")
    g.link(f"{isOpen}.bMenuOpen", f"{br}.Condition")
    # close
    w1 = g.get("DebugWidget")
    rm = g.call("RemoveFromParent", "/Script/UMG.Widget")
    g.link(f"{w1}.DebugWidget", f"{rm}.self")
    p1 = pc(g)
    gm = g.call("SetInputMode_GameOnly", WBL)
    g.link(f"{p1}.ReturnValue", f"{gm}.PlayerController")
    p2 = pc(g)
    cur0 = g.call("SetBoolPropertyByName", KSL, PropertyName="bShowMouseCursor", Value="false")
    g.link(f"{p2}.ReturnValue", f"{cur0}.Object")
    closed = g.set("bMenuOpen", "false")
    g.chain(e, br)
    g.chain(f"{br}.then", rm, gm, cur0, closed)
    # open (create once)
    w2 = g.get("DebugWidget")
    valid = g.call("IsValid", KSL)
    g.link(f"{w2}.DebugWidget", f"{valid}.Object")
    have = g.add({"branch": True}, "ifHave")
    g.link(f"{valid}.ReturnValue", f"{have}.Condition")
    p3 = pc(g)
    cw = g.add({"create_widget": WBP_C}, "create")
    g.link(f"{p3}.ReturnValue", f"{cw}.OwningPlayer")
    st = g.set("DebugWidget")
    g.link(f"{cw}.ReturnValue", f"{st}.DebugWidget")
    w3 = g.get("DebugWidget")
    me = g.add({"self": True})
    init = g.call("InitDebug", WBP_C)
    g.link(f"{w3}.DebugWidget", f"{init}.self")
    g.link(f"{me}.self", f"{init}.InCM")
    w4 = g.get("DebugWidget")
    show = g.call("AddToViewport", "/Script/UMG.UserWidget", ZOrder="500")
    g.link(f"{w4}.DebugWidget", f"{show}.self")
    p4 = pc(g)
    w5 = g.get("DebugWidget")
    mode = g.call("SetInputMode_GameAndUIEx", WBL, InMouseLockMode="DoNotLock", bHideCursorDuringCapture="false")
    g.link(f"{p4}.ReturnValue", f"{mode}.PlayerController")
    g.link(f"{w5}.DebugWidget", f"{mode}.InWidgetToFocus")
    p5 = pc(g)
    cur1 = g.call("SetBoolPropertyByName", KSL, PropertyName="bShowMouseCursor", Value="true")
    g.link(f"{p5}.ReturnValue", f"{cur1}.Object")
    opened = g.set("bMenuOpen", "true")
    g.chain(f"{br}.else", have)
    g.chain(f"{have}.else", cw, st, init)
    g.chain(f"{have}.then", show)
    g.link(f"{init}.then", f"{show}.execute")
    g.chain(show, mode, cur1, opened)
    graphs.append(g.spec())

    # ---- PlaceOnRoad(StepCm): PlaceStepCm = StepCm, PlaceTries = 0, TryPlace
    g = G("PlaceOnRoad")
    e = g.add({"entry": True}, "entry")
    s1 = g.set("PlaceStepCm")
    g.link(f"{e}.StepCm", f"{s1}.PlaceStepCm")
    s2 = g.set("PlaceTries", "0")
    t = g.call("TryPlace")
    g.chain(e, s1, s2, t)
    graphs.append(g.spec())

    # ---- TryPlace: BFL.ComputeRoadRespawn from the pawn; grounded -> teleport + walk, else hold and retry
    g = G("TryPlace")
    e = g.add({"entry": True}, "entry")
    road = g.call("GetActorOfClass", GS, ActorClass=ROAD_C)
    comp = g.call("GetComponentByClass", ACTOR, ComponentClass="/Script/Engine.SplineComponent")
    g.link(f"{road}.ReturnValue", f"{comp}.self")
    cs = g.add({"cast": "/Script/Engine.SplineComponent"}, "castSpline")
    g.link(f"{comp}.ReturnValue", f"{cs}.Object")
    pw = pawn(g)
    cap = g.call("GetComponentByClass", ACTOR, ComponentClass="/Script/Engine.CapsuleComponent")
    g.link(f"{pw}.ReturnValue", f"{cap}.self")
    cc = g.add({"cast": "/Script/Engine.CapsuleComponent"}, "castCapsule")
    g.link(f"{cap}.ReturnValue", f"{cc}.Object")
    half = g.call("GetScaledCapsuleHalfHeight", "/Script/Engine.CapsuleComponent")
    g.link(f"{cc}.AsCapsule Collision", f"{half}.self")
    loc = g.call("K2_GetActorLocation", ACTOR)
    g.link(f"{pw}.ReturnValue", f"{loc}.self")
    step = g.get("PlaceStepCm")
    rs = g.call("ComputeRoadRespawn", BFL_ROAD_C, TravelSign="-1.0")
    g.link(f"{cs}.AsSpline Component", f"{rs}.Road")
    g.link(f"{loc}.ReturnValue", f"{rs}.From")
    g.link(f"{half}.ReturnValue", f"{rs}.CapsuleHalfHeight")
    g.link(f"{step}.PlaceStepCm", f"{rs}.StepCm")
    tries = g.get("PlaceTries")
    giveUp = g.call("GreaterEqual_IntInt", KML, B="40")
    g.link(f"{tries}.PlaceTries", f"{giveUp}.A")
    orr = g.call("BooleanOR", KML)
    g.link(f"{rs}.Found", f"{orr}.A")
    g.link(f"{giveUp}.ReturnValue", f"{orr}.B")
    br = g.add({"branch": True}, "ifGround")
    g.link(f"{orr}.ReturnValue", f"{br}.Condition")
    # grounded (or gave up): teleport, face up-road, walk
    tp = g.call("K2_TeleportTo", ACTOR)
    g.link(f"{pw}.ReturnValue", f"{tp}.self")
    g.link(f"{rs}.Location", f"{tp}.DestLocation")
    g.link(f"{rs}.Rotation", f"{tp}.DestRotation")
    p1 = pc(g)
    rot = g.call("SetControlRotation", CTRL)
    g.link(f"{p1}.ReturnValue", f"{rot}.self")
    g.link(f"{rs}.Rotation", f"{rot}.NewRotation")
    mv = g.call("GetComponentByClass", ACTOR, ComponentClass="/Script/Engine.CharacterMovementComponent")
    g.link(f"{pw}.ReturnValue", f"{mv}.self")
    cm = g.add({"cast": "/Script/Engine.CharacterMovementComponent"}, "castMove")
    g.link(f"{mv}.ReturnValue", f"{cm}.Object")
    walk = g.call("SetMovementMode", "/Script/Engine.CharacterMovementComponent", NewMovementMode="MOVE_Walking")
    g.link(f"{cm}.AsCharacter Movement Component", f"{walk}.self")
    f1 = g.call("Conv_BoolToString", KSTR)
    g.link(f"{rs}.Found", f"{f1}.InBool")
    msg = concat(g, None, f"{f1}.ReturnValue", a_lit="placed on the road, ground trace hit: ")
    lg = log_line(g, msg)
    # not yet: hold (MOVE_None), retry in 0.25 s
    mv2 = g.call("GetComponentByClass", ACTOR, ComponentClass="/Script/Engine.CharacterMovementComponent")
    g.link(f"{pw}.ReturnValue", f"{mv2}.self")
    cm2 = g.add({"cast": "/Script/Engine.CharacterMovementComponent"}, "castMove2")
    g.link(f"{mv2}.ReturnValue", f"{cm2}.Object")
    hold = g.call("SetMovementMode", "/Script/Engine.CharacterMovementComponent", NewMovementMode="MOVE_None")
    g.link(f"{cm2}.AsCharacter Movement Component", f"{hold}.self")
    tries2 = g.get("PlaceTries")
    inc = g.call("Add_IntInt", KML, B="1")
    g.link(f"{tries2}.PlaceTries", f"{inc}.A")
    st = g.set("PlaceTries")
    g.link(f"{inc}.ReturnValue", f"{st}.PlaceTries")
    tm = g.add({"timer": True}, "retry")
    g.defaults.update({f"{tm}.FunctionName": "TryPlace", f"{tm}.Time": "0.25", f"{tm}.bLooping": "false"})
    stt = g.set("PlaceTimer")
    g.link(f"{tm}.ReturnValue", f"{stt}.PlaceTimer")
    g.chain(e, road, cs)
    g.chain(f"{cs}.then", cc)
    g.chain(f"{cc}.then", rs, br)
    g.chain(f"{br}.then", tp, rot, cm)
    g.chain(f"{cm}.then", walk, lg)
    g.chain(f"{br}.else", cm2)
    g.chain(f"{cm2}.then", hold, st, tm, stt)
    graphs.append(g.spec())

    # ---- DebugGoTo(BeatId, RoadM): USaskartaDebugLibrary::ArmBeat (the runner puts the carrier BACK_M before the
    #      beat on the ground and re-arms it; a flow beat fires on its next flow report); auto-trigger fires it now.
    g = G("DebugGoTo")
    e = g.add({"entry": True}, "entry")
    me = g.add({"self": True})
    arm = g.call("ArmBeat", DEBUGLIB, LeadM=str(BACK_M))
    g.link(f"{me}.self", f"{arm}.WorldContext")
    g.link(f"{e}.BeatId", f"{arm}.BeatId")
    idn = g.call("Conv_NameToString", KSTR)
    g.link(f"{e}.BeatId", f"{idn}.InName")
    m1 = concat(g, None, f"{idn}.ReturnValue", a_lit="tp before ")
    m1b = concat(g, m1, None, b_lit=" at ")
    m2 = concat(g, m1b, float_str(g, f"{e}.RoadM"), None)
    m3 = concat(g, m2, None, b_lit=" m (armed)")
    lg = log_line(g, m3)
    auto = g.get("bAutoTrigger")
    br = g.add({"branch": True}, "ifAuto")
    g.link(f"{auto}.bAutoTrigger", f"{br}.Condition")
    r2 = runner(g)
    fire = g.call("FireBeat", RUNNER, bForce="true")
    g.link(f"{r2}.ReturnValue", f"{fire}.self")
    g.link(f"{e}.BeatId", f"{fire}.BeatId")
    lg2 = log_line(g, literal="auto-trigger: fired now")
    g.chain(e, arm, lg, br)
    g.chain(f"{br}.then", fire, lg2)
    graphs.append(g.spec())

    # ---- DebugGoToRoad(RoadM): plain teleport (checkpoints, numbers)
    g = G("DebugGoToRoad")
    e = g.add({"entry": True}, "entry")
    r = runner(g)
    go = g.call("GoToRoadM", RUNNER)
    g.link(f"{r}.ReturnValue", f"{go}.self")
    g.link(f"{e}.RoadM", f"{go}.RoadM")
    place = g.call("PlaceOnRoad", StepCm="0.0")
    msg = concat(g, None, float_str(g, f"{e}.RoadM"), a_lit="tp to road ")
    lg = log_line(g, msg)
    g.chain(e, go, place, lg)
    graphs.append(g.spec())

    # ---- CheckArmed: fire the armed beat when road m reaches it (after first seeing it behind)
    g = G("CheckArmed")
    e = g.add({"entry": True}, "entry")
    ab = g.get("ArmedBeat")
    isNone = g.call("EqualEqual_NameName", KML, B="None")
    g.link(f"{ab}.ArmedBeat", f"{isNone}.A")
    brNone = g.add({"branch": True}, "ifNone")
    g.link(f"{isNone}.ReturnValue", f"{brNone}.Condition")
    t1 = g.get("ArmTimer")
    clr = g.call("K2_ClearAndInvalidateTimerHandle", KSL)
    g.link(f"{t1}.ArmTimer", f"{clr}.Handle")
    r = runner(g)
    rm = g.call("GetRoadM", RUNNER)
    g.link(f"{r}.ReturnValue", f"{rm}.self")
    arm = g.get("ArmedRoadM")
    armMinus = g.call("Subtract_DoubleDouble", KML, B=str(ARM_BEHIND_M))
    g.link(f"{arm}.ArmedRoadM", f"{armMinus}.A")
    behind = g.call("Less_DoubleDouble", KML)
    g.link(f"{rm}.ReturnValue", f"{behind}.A")
    g.link(f"{armMinus}.ReturnValue", f"{behind}.B")
    brBehind = g.add({"branch": True}, "ifBehind")
    g.link(f"{behind}.ReturnValue", f"{brBehind}.Condition")
    ready = g.set("bArmReady", "true")
    rdy = g.get("bArmReady")
    arm2 = g.get("ArmedRoadM")
    reached = g.call("GreaterEqual_DoubleDouble", KML)
    g.link(f"{rm}.ReturnValue", f"{reached}.A")
    g.link(f"{arm2}.ArmedRoadM", f"{reached}.B")
    both = g.call("BooleanAND", KML)
    g.link(f"{rdy}.bArmReady", f"{both}.A")
    g.link(f"{reached}.ReturnValue", f"{both}.B")
    brFire = g.add({"branch": True}, "ifReached")
    g.link(f"{both}.ReturnValue", f"{brFire}.Condition")
    r2 = runner(g)
    ab2 = g.get("ArmedBeat")
    fire = g.call("FireBeat", RUNNER, bForce="true")
    g.link(f"{r2}.ReturnValue", f"{fire}.self")
    g.link(f"{ab2}.ArmedBeat", f"{fire}.BeatId")
    ab3 = g.get("ArmedBeat")
    nm = g.call("Conv_NameToString", KSTR)
    g.link(f"{ab3}.ArmedBeat", f"{nm}.InName")
    msg = concat(g, None, f"{nm}.ReturnValue", a_lit="armed beat reached, fired ")
    lg = log_line(g, msg)
    dis = g.set("ArmedBeat", "None")
    t2 = g.get("ArmTimer")
    clr2 = g.call("K2_ClearAndInvalidateTimerHandle", KSL)
    g.link(f"{t2}.ArmTimer", f"{clr2}.Handle")
    g.chain(e, brNone)
    g.chain(f"{brNone}.then", clr)
    g.chain(f"{brNone}.else", brBehind)
    g.chain(f"{brBehind}.then", ready)
    g.chain(f"{brBehind}.else", brFire)
    g.chain(f"{brFire}.then", fire, lg, dis, clr2)
    graphs.append(g.spec())

    # ---- SaskartaTP(Target): a number -> road m; otherwise a beat id (road m from BeatRoadMs)
    g = G("SaskartaTP")
    e = g.add({"entry": True}, "entry")
    num = g.call("IsNumeric", KSTR)
    g.link(f"{e}.Target", f"{num}.SourceString")
    br = g.add({"branch": True}, "ifNumber")
    g.link(f"{num}.ReturnValue", f"{br}.Condition")
    toF = g.call("Conv_StringToDouble", KSTR)
    g.link(f"{e}.Target", f"{toF}.InString")
    road = g.call("DebugGoToRoad")
    g.link(f"{toF}.ReturnValue", f"{road}.RoadM")
    toN = g.call("Conv_StringToName", KSTR)
    g.link(f"{e}.Target", f"{toN}.InString")
    ids = g.get("BeatIds")
    find = g.call("Array_Find", KARR)
    g.link(f"{ids}.BeatIds", f"{find}.TargetArray")
    g.link(f"{toN}.ReturnValue", f"{find}.ItemToFind")
    found = g.call("GreaterEqual_IntInt", KML, B="0")
    g.link(f"{find}.ReturnValue", f"{found}.A")
    brF = g.add({"branch": True}, "ifFound")
    g.link(f"{found}.ReturnValue", f"{brF}.Condition")
    sel = g.call("SelectIndex")
    g.link(f"{find}.ReturnValue", f"{sel}.Index")
    msg = concat(g, None, f"{e}.Target", a_lit="SaskartaTP: no beat named ")
    lg = log_line(g, msg)
    g.chain(e, br)
    g.chain(f"{br}.then", road)
    g.chain(f"{br}.else", brF)
    g.chain(f"{brF}.then", sel)
    g.chain(f"{brF}.else", lg)
    graphs.append(g.spec())

    # ---- SelectIndex(Index): clamp, SelIndex = i, DebugGoTo(BeatIds[i], BeatRoadMs[i])
    g = G("SelectIndex")
    e = g.add({"entry": True}, "entry")
    ids = g.get("BeatIds")
    ln = g.call("Array_Length", KARR)
    g.link(f"{ids}.BeatIds", f"{ln}.TargetArray")
    last = g.call("Subtract_IntInt", KML, B="1")
    g.link(f"{ln}.ReturnValue", f"{last}.A")
    cl = g.call("Clamp", KML, Min="0")
    g.link(f"{e}.Index", f"{cl}.Value")
    g.link(f"{last}.ReturnValue", f"{cl}.Max")
    s = g.set("SelIndex")
    g.link(f"{cl}.ReturnValue", f"{s}.SelIndex")
    si = g.get("SelIndex")
    ids2 = g.get("BeatIds")
    getId = g.call("Array_Get", KARR)
    g.link(f"{ids2}.BeatIds", f"{getId}.TargetArray")
    g.link(f"{si}.SelIndex", f"{getId}.Index")
    rms = g.get("BeatRoadMs")
    getRm = g.call("Array_Get", KARR)
    g.link(f"{rms}.BeatRoadMs", f"{getRm}.TargetArray")
    g.link(f"{si}.SelIndex", f"{getRm}.Index")
    go = g.call("DebugGoTo")
    g.link(f"{getId}.Item", f"{go}.BeatId")
    g.link(f"{getRm}.Item", f"{go}.RoadM")
    g.chain(e, s, go)
    graphs.append(g.spec())

    # ---- SaskartaNext / SaskartaPrev
    for name, delta in (("SaskartaNext", "1"), ("SaskartaPrev", "-1")):
        g = G(name)
        e = g.add({"entry": True}, "entry")
        si = g.get("SelIndex")
        add = g.call("Add_IntInt", KML, B=delta)
        g.link(f"{si}.SelIndex", f"{add}.A")
        sel = g.call("SelectIndex")
        g.link(f"{add}.ReturnValue", f"{sel}.Index")
        g.chain(e, sel)
        graphs.append(g.spec())

    # ---- SaskartaBeat(BeatId): trigger now (forced)
    g = G("SaskartaBeat")
    e = g.add({"entry": True}, "entry")
    r = runner(g)
    fire = g.call("FireBeat", RUNNER, bForce="true")
    g.link(f"{r}.ReturnValue", f"{fire}.self")
    g.link(f"{e}.BeatId", f"{fire}.BeatId")
    nm = g.call("Conv_NameToString", KSTR)
    g.link(f"{e}.BeatId", f"{nm}.InName")
    ok = g.call("Conv_BoolToString", KSTR)
    g.link(f"{fire}.ReturnValue", f"{ok}.InBool")
    m1 = concat(g, None, f"{nm}.ReturnValue", a_lit="trigger ")
    m2 = concat(g, m1, None, b_lit=" queued: ")
    m3 = concat(g, m2, f"{ok}.ReturnValue")
    lg = log_line(g, m3)
    g.chain(e, fire, lg)
    graphs.append(g.spec())

    # ---- TriggerSelected: SaskartaBeat(BeatIds[SelIndex])
    g = G("TriggerSelected")
    e = g.add({"entry": True}, "entry")
    ids = g.get("BeatIds")
    si = g.get("SelIndex")
    getId = g.call("Array_Get", KARR)
    g.link(f"{ids}.BeatIds", f"{getId}.TargetArray")
    g.link(f"{si}.SelIndex", f"{getId}.Index")
    b = g.call("SaskartaBeat")
    g.link(f"{getId}.Item", f"{b}.BeatId")
    g.chain(e, b)
    graphs.append(g.spec())

    # ---- SaskartaSkip: allow any skip rule, then skip
    g = G("SaskartaSkip")
    e = g.add({"entry": True}, "entry")
    allow = console(g, "Saskarta.Cine.AllowSkipAll 1")
    me = g.add({"self": True})
    skip = g.call("SkipCurrentCinematic", EVLIB)
    g.link(f"{me}.self", f"{skip}.WorldContext")
    lg = log_line(g, literal="skip cinematic")
    g.chain(e, allow, skip, lg)
    graphs.append(g.spec())

    # ---- SaskartaResetBeats: USaskartaDebugLibrary::ResetAllBeats (every one-shot flag; the Continue save is not touched)
    g = G("SaskartaResetBeats")
    e = g.add({"entry": True}, "entry")
    me = g.add({"self": True})
    ra = g.call("ResetAllBeats", DEBUGLIB)
    g.link(f"{me}.self", f"{ra}.WorldContext")
    lg = log_line(g, literal="reset all beats")
    g.chain(e, ra, lg)
    graphs.append(g.spec())

    # ---- SaskartaSpeed(Multiplier): the pawn's CustomTimeDilation (carrier only; the world clock is untouched)
    g = G("SaskartaSpeed")
    e = g.add({"entry": True}, "entry")
    s = g.set("SpeedMul")
    g.link(f"{e}.Multiplier", f"{s}.SpeedMul")
    pw = pawn(g)
    setp = g.call("SetDoublePropertyByName", KSL, PropertyName="CustomTimeDilation")
    g.link(f"{pw}.ReturnValue", f"{setp}.Object")
    g.link(f"{e}.Multiplier", f"{setp}.Value")
    msg = concat(g, None, float_str(g, f"{e}.Multiplier"), a_lit="carrier speed x")
    lg = log_line(g, msg)
    g.chain(e, s, setp, lg)
    graphs.append(g.spec())

    # ---- SaskartaGod: toggle; on = tether stopped (no warning, no breach, no reboot), re-stopped every 1 s
    g = G("SaskartaGod")
    e = g.add({"entry": True}, "entry")
    gd = g.get("bGod")
    nt = g.call("Not_PreBool", KML)
    g.link(f"{gd}.bGod", f"{nt}.A")
    s = g.set("bGod")
    g.link(f"{nt}.ReturnValue", f"{s}.bGod")
    gd2 = g.get("bGod")
    br = g.add({"branch": True}, "ifOn")
    g.link(f"{gd2}.bGod", f"{br}.Condition")
    keep = g.call("KeepGod")
    tm = g.add({"timer": True}, "godTimer")
    g.defaults.update({f"{tm}.FunctionName": "KeepGod", f"{tm}.Time": "1.0", f"{tm}.bLooping": "true"})
    st = g.set("GodTimer")
    g.link(f"{tm}.ReturnValue", f"{st}.GodTimer")
    lgOn = log_line(g, literal="god mode ON (tether off)")
    t1 = g.get("GodTimer")
    clr = g.call("K2_ClearAndInvalidateTimerHandle", KSL)
    g.link(f"{t1}.GodTimer", f"{clr}.Handle")
    p = pc(g)
    tc = g.call("GetComponentByClass", ACTOR, ComponentClass=TETHER_C)
    g.link(f"{p}.ReturnValue", f"{tc}.self")
    ct = g.add({"cast": TETHER_C}, "castTether")
    g.link(f"{tc}.ReturnValue", f"{ct}.Object")
    start = g.call("StartTether", TETHER_C)
    g.link(f"{ct}.AsBPC Road Tether", f"{start}.self")
    lgOff = log_line(g, literal="god mode OFF (tether on)")
    g.chain(e, s, br)
    g.chain(f"{br}.then", keep, tm, st, lgOn)
    g.chain(f"{br}.else", clr, ct)
    g.chain(f"{ct}.then", start, lgOff)
    graphs.append(g.spec())

    g = G("KeepGod")
    e = g.add({"entry": True}, "entry")
    p = pc(g)
    tc = g.call("GetComponentByClass", ACTOR, ComponentClass=TETHER_C)
    g.link(f"{p}.ReturnValue", f"{tc}.self")
    ct = g.add({"cast": TETHER_C}, "castTether")
    g.link(f"{tc}.ReturnValue", f"{ct}.Object")
    stop = g.call("StopTether", TETHER_C)
    g.link(f"{ct}.AsBPC Road Tether", f"{stop}.self")
    g.chain(e, ct)
    g.chain(f"{ct}.then", stop)
    graphs.append(g.spec())

    # ---- SaskartaFly: the engine's debug camera (free fly; the game keeps running)
    g = G("SaskartaFly")
    e = g.add({"entry": True}, "entry")
    c = console(g, "ToggleDebugCamera")
    lg = log_line(g, literal="free camera toggled")
    g.chain(e, c, lg)
    graphs.append(g.spec())

    g = G("StatUnit")
    e = g.add({"entry": True}, "entry")
    c = console(g, "stat unit")
    g.chain(e, c)
    graphs.append(g.spec())

    # ---- RestartFlow: PC_Saskarta.QuitToTitle reopens the level (intro -> loading -> title)
    g = G("RestartFlow")
    e = g.add({"entry": True}, "entry")
    p = pc(g)
    cp = g.add({"cast": PC_C}, "castPC")
    g.link(f"{p}.ReturnValue", f"{cp}.Object")
    q = g.call("QuitToTitle", PC_C)
    g.link(f"{cp}.AsPC Saskarta", f"{q}.self")
    g.chain(e, cp)
    g.chain(f"{cp}.then", q)
    graphs.append(g.spec())

    g = G("SetAutoTrigger")
    e = g.add({"entry": True}, "entry")
    s = g.set("bAutoTrigger")
    g.link(f"{e}.bOn", f"{s}.bAutoTrigger")
    g.chain(e, s)
    graphs.append(g.spec())

    # ---- SaskartaStorm(Intensity): the lighting director's SetStormOverride (< 0 releases it)
    g = G("SaskartaStorm")
    e = g.add({"entry": True}, "entry")
    me = g.add({"self": True})
    dr = g.call("GetLightingDirector", DIRECTOR)
    g.link(f"{me}.self", f"{dr}.WorldContextObject")
    so = g.call("SetStormOverride", DIRECTOR)
    g.link(f"{dr}.ReturnValue", f"{so}.self")
    g.link(f"{e}.Intensity", f"{so}.Intensity")
    msg = concat(g, None, float_str(g, f"{e}.Intensity"), a_lit="storm override ")
    lg = log_line(g, msg)
    g.chain(e, so, lg)
    graphs.append(g.spec())

    g = G("ApplyStorm")  # kept (empty) so older timers bound to it stay valid
    e = g.add({"entry": True}, "entry")
    graphs.append(g.spec())

    # ---- SaskartaLook(RoadM): the director holds the road's look at RoadM (PushLookOverrideAtRoadM, 1 s blend)
    g = G("SaskartaLook")
    e = g.add({"entry": True}, "entry")
    me = g.add({"self": True})
    dr = g.call("GetLightingDirector", DIRECTOR)
    g.link(f"{me}.self", f"{dr}.WorldContextObject")
    sp = g.call("PushLookOverrideAtRoadM", DIRECTOR, BlendS="1.0")
    g.link(f"{dr}.ReturnValue", f"{sp}.self")
    g.link(f"{e}.RoadM", f"{sp}.RoadM")
    msg = concat(g, None, float_str(g, f"{e}.RoadM"), a_lit="look pinned to road ")
    lg = log_line(g, msg)
    g.chain(e, sp, lg)
    graphs.append(g.spec())

    # ---- GetStatusText: the overlay (road, flow, cinematic, voice, next beat, armed, speed, god) + DebugLog
    g = G("GetStatusText")
    e = g.add({"entry": True}, "entry")
    res = g.add({"result": True}, "result")
    r = runner(g)
    rm = g.call("GetRoadM", RUNNER)
    g.link(f"{r}.ReturnValue", f"{rm}.self")
    fs = g.call("GetFlowState", RUNNER)
    g.link(f"{r}.ReturnValue", f"{fs}.self")
    fsn = g.call("Conv_NameToString", KSTR)
    g.link(f"{fs}.ReturnValue", f"{fsn}.InName")
    ci = g.call("IsCinematicActive", RUNNER)
    g.link(f"{r}.ReturnValue", f"{ci}.self")
    cis = g.call("Conv_BoolToString", KSTR)
    g.link(f"{ci}.ReturnValue", f"{cis}.InBool")
    vb = g.call("IsVoiceBusy", RUNNER)
    g.link(f"{r}.ReturnValue", f"{vb}.self")
    vbs = g.call("Conv_BoolToString", KSTR)
    g.link(f"{vb}.ReturnValue", f"{vbs}.InBool")
    nx = g.call("GetSecondsToNextBeat", RUNNER)
    g.link(f"{r}.ReturnValue", f"{nx}.self")
    spd = g.call("GetSpeedMps", RUNNER)
    g.link(f"{r}.ReturnValue", f"{spd}.self")
    ab = g.get("ArmedBeat")
    abs_ = g.call("Conv_NameToString", KSTR)
    g.link(f"{ab}.ArmedBeat", f"{abs_}.InName")
    sm = g.get("SpeedMul")
    gd = g.get("bGod")
    gds = g.call("Conv_BoolToString", KSTR)
    g.link(f"{gd}.bGod", f"{gds}.InBool")
    lg = g.get("DebugLog")
    parts = [
        ("lit", "road "), ("pin", float_str(g, f"{rm}.ReturnValue")), ("lit", " m   "),
        ("pin", float_str(g, f"{spd}.ReturnValue")), ("lit", " m/s   flow "), ("pin", f"{fsn}.ReturnValue"),
        ("lit", "\ncinematic "), ("pin", f"{cis}.ReturnValue"), ("lit", "   voice busy "), ("pin", f"{vbs}.ReturnValue"),
        ("lit", "   next beat in "), ("pin", float_str(g, f"{nx}.ReturnValue")), ("lit", " s"),
        ("lit", "\narmed "), ("pin", f"{abs_}.ReturnValue"), ("lit", "   speed x"), ("pin", float_str(g, f"{sm}.SpeedMul")),
        ("lit", "   god "), ("pin", f"{gds}.ReturnValue"), ("lit", "\n\n"), ("pin", f"{lg}.DebugLog"),
    ]
    acc = None
    pending = None  # a leading literal waits for the first pin
    for kind, v in parts:
        if acc is None:
            if kind == "lit":
                pending = (pending or "") + v
                continue
            acc = concat(g, None, v, a_lit=pending) if pending else v
        elif kind == "pin":
            acc = concat(g, acc, v)
        else:
            acc = concat(g, acc, None, b_lit=v)
    ev = g.call("GetRecentEventLog", DEBUGLIB, MaxLines="10")
    acc = concat(g, acc, None, b_lit="\n-- events --\n")
    acc = concat(g, acc, f"{ev}.ReturnValue")
    g.link(acc, f"{res}.Text")
    g.chain(e, ev, res)  # GetRecentEventLog is impure: on the exec chain
    graphs.append(g.spec())

    return {
        "asset": CM,
        "create": {"parent": "/Script/Engine.CheatManager"},
        "description": "LANE5 debug mode: exec functions for the console (SaskartaDebug, SaskartaTP, SaskartaBeat, SaskartaSkip, "
                       "SaskartaResetBeats, SaskartaSpeed, SaskartaGod, SaskartaFly, SaskartaNext, SaskartaPrev, SaskartaStorm, "
                       "SaskartaLook) and the logic behind WBP_Saskarta_Debug. PC_Saskarta.CheatClass = this. README_Debug.md.",
        "variables": variables,
        "functions": functions,
        "graphs": graphs,
    }


def build_cm_post(beats: list[dict], cm: dict) -> dict:
    """What bpgraph cannot express: the exec flag and the baked beat arrays (apply_debug_post.py)."""
    return {
        "asset": CM,
        "exec_functions": [f["name"] for f in cm["functions"] if f["name"].startswith("Saskarta")],
        "array_defaults": {
            "BeatIds": [b["id"] for b in beats],
            "BeatRoadMs": [b["road_m"] for b in beats],
        },
    }


# ============================================================================ WBP_Saskarta_Debug

FONT = "/Game/SaskartaGaea/GameFlow/UI/Fonts/F_ArefRuqaa.F_ArefRuqaa"
MONO = "/Game/SaskartaGaea/GameFlow/UI/Fonts/Font_Terminal.Font_Terminal"
IVORY = [0.8469, 0.7835, 0.7011, 1]
EMBER = [0.91, 0.62, 0.35, 1]


def text(name, s, size=15, color=IVORY, font=MONO, slot=None):
    n = {"class": "TextBlock", "name": name,
         "properties": {"Text": s, "Font": {"FontObject": font, "Size": size}, "ColorAndOpacity": {"SpecifiedColor": color}}}
    if slot:
        n["slot_props"] = slot
    return n


def button(name, label, size=15, color=IVORY):
    return {
        "class": "Button", "name": name,
        "properties": {"BackgroundColor": [0.08, 0.07, 0.06, 0.85]},
        "slot_props": {"padding": [0, 1, 0, 1]},
        "children": [text(name + "Label", label, size, color)],
    }


ACTIONS = [
    # (widget name, label, CM function, literal args)
    ("PrevBtn", "<  Previous beat", "SaskartaPrev", {}),
    ("NextBtn", "Next beat  >", "SaskartaNext", {}),
    ("TriggerBtn", "Trigger selected beat now", "TriggerSelected", {}),
    ("SkipBtn", "Skip current cinematic", "SaskartaSkip", {}),
    ("ResetBtn", "Reset all beats", "SaskartaResetBeats", {}),
    ("Speed1Btn", "Carrier speed x1", "SaskartaSpeed", {"Multiplier": "1.0"}),
    ("Speed3Btn", "Carrier speed x3", "SaskartaSpeed", {"Multiplier": "3.0"}),
    ("Speed10Btn", "Carrier speed x10", "SaskartaSpeed", {"Multiplier": "10.0"}),
    ("GodBtn", "God mode (no tether / reboot)", "SaskartaGod", {}),
    ("FlyBtn", "Free-fly camera", "SaskartaFly", {}),
    ("StatBtn", "stat unit", "StatUnit", {}),
    ("RestartBtn", "Restart: intro > loading > title", "RestartFlow", {}),
    ("StormOffBtn", "Storm: release override", "SaskartaStorm", {"Intensity": "-1.0"}),
] + [(f"Look{n}Btn", f"Look: {n} ({m} m)", "SaskartaLook", {"RoadM": f"{float(m)}"}) for n, m in LOOK_KEYS]


def build_widget(beats: list[dict]) -> tuple[dict, dict]:
    rows = []
    for i, b in enumerate(beats):
        label = f"{b['id']:<24}{int(b['road_m']):>5} m" + ("  (opt)" if b["optional"] else "")
        rows.append(button(f"Beat{i:02d}", label, 14))
    for j, (cp, m) in enumerate(CHECKPOINTS):
        rows.append(button(f"Cp{j}", f"{cp:<24}{int(m):>5} m  checkpoint", 14, EMBER))
    actions = [button(n, l, 14) for n, l, _, _ in ACTIONS]
    tree = {
        "asset": WBP,
        "tree": [
            {"class": "Border", "name": "Panel",
             "properties": {"BrushColor": [0.02, 0.018, 0.015, 0.82], "Padding": {"Left": 14, "Top": 10, "Right": 14, "Bottom": 10}},
             "children": [
                 {"class": "VerticalBox", "name": "Layout", "children": [
                     text("Heading", "Saskarta debug  (F9 closes)", 24, EMBER, FONT),
                     text("Hint", "Click or arrow keys + Enter. A beat: teleport 30 m before it and re-arm it.", 12),
                     {"class": "HorizontalBox", "name": "Columns", "slot_props": {"type": "Fill", "fill": 1}, "children": [
                         {"class": "ScrollBox", "name": "BeatList", "slot_props": {"type": "Fill", "padding": [0, 6, 10, 0]},
                          "children": rows},
                         {"class": "ScrollBox", "name": "ActionList", "slot_props": {"padding": [0, 6, 10, 0]}, "children": [
                             {"class": "HorizontalBox", "name": "AutoRow", "children": [
                                 {"class": "CheckBox", "name": "AutoTrigger"},
                                 text("AutoLabel", " trigger on teleport", 14),
                             ]},
                             *actions,
                             text("StormLabel", "Storm intensity override", 14, slot={"padding": [0, 8, 0, 0]}),
                             {"class": "Slider", "name": "StormSlider", "properties": {"Value": 0.5}},
                         ]},
                         {"class": "VerticalBox", "name": "LogColumn", "slot_props": {"type": "Fill", "padding": [0, 6, 0, 0]}, "children": [
                             text("StatusTitle", "Event log", 18, EMBER, FONT),
                             text("StatusText", "(waiting)", 13),
                         ]},
                     ]},
                 ]},
             ]},
        ],
        "slots": {"Panel": {"anchors": [0.02, 0.04, 0.98, 0.96], "position": [0, 0], "size": [0, 0]}},
        "variables": ["StatusText", "AutoTrigger", "StormSlider"] + [f"Beat{i:02d}" for i in range(len(beats))]
                     + [f"Cp{j}" for j in range(len(CHECKPOINTS))] + [n for n, _, _, _ in ACTIONS],
    }

    variables = [{"name": "CM", "type": f"object:{CM_C}"}, {"name": "RefreshTimer", "type": "struct:/Script/Engine.TimerHandle"}]
    functions = [fn("InitDebug", [("InCM", f"object:{CM_C}")]), fn("Refresh")]
    graphs = []

    g = G("InitDebug")
    e = g.add({"entry": True}, "entry")
    s = g.set("CM")
    g.link(f"{e}.InCM", f"{s}.CM")
    tm = g.add({"timer": True}, "timer")
    g.defaults.update({f"{tm}.FunctionName": "Refresh", f"{tm}.Time": "0.25", f"{tm}.bLooping": "true"})
    st = g.set("RefreshTimer")
    g.link(f"{tm}.ReturnValue", f"{st}.RefreshTimer")
    first = g.get("Beat00")
    focus = g.call("SetKeyboardFocus", "/Script/UMG.Widget")
    g.link(f"{first}.Beat00", f"{focus}.self")
    g.chain(e, s, tm, st, focus)
    graphs.append(g.spec())

    g = G("Refresh")
    e = g.add({"entry": True}, "entry")
    cm = g.get("CM")
    valid = g.call("IsValid", KSL)
    g.link(f"{cm}.CM", f"{valid}.Object")
    br = g.add({"branch": True}, "ifCM")
    g.link(f"{valid}.ReturnValue", f"{br}.Condition")
    st = g.call("GetStatusText", CM_C)
    g.link(f"{cm}.CM", f"{st}.self")
    tx = g.call("Conv_StringToText", KTXT)
    g.link(f"{st}.Text", f"{tx}.InString")
    tb = g.get("StatusText")
    set_ = g.call("SetText", "/Script/UMG.TextBlock")
    g.link(f"{tb}.StatusText", f"{set_}.self")
    g.link(f"{tx}.ReturnValue", f"{set_}.InText")
    g.chain(e, br)
    g.chain(f"{br}.then", st, set_)
    graphs.append(g.spec())

    g = G("EventGraph")
    cm = g.get("CM")

    def on_click(widget, func, args):
        ev = g.add({"bound_event": {"target": widget, "event": "OnClicked"}}, f"on{widget}")
        c = g.call(func, CM_C, **args)
        g.link(f"{cm}.CM", f"{c}.self")
        g.chain(ev, c)
        return c

    for i, b in enumerate(beats):
        on_click(f"Beat{i:02d}", "SelectIndex", {"Index": str(i)})
    for j, (cp, m) in enumerate(CHECKPOINTS):
        on_click(f"Cp{j}", "DebugGoToRoad", {"RoadM": f"{m}"})
    for n, _, func, args in ACTIONS:
        on_click(n, func, args)
    ev = g.add({"bound_event": {"target": "AutoTrigger", "event": "OnCheckStateChanged"}}, "onAuto")
    c = g.call("SetAutoTrigger", CM_C)
    g.link(f"{cm}.CM", f"{c}.self")
    g.link(f"{ev}.bIsChecked", f"{c}.bOn")
    g.chain(ev, c)
    ev = g.add({"bound_event": {"target": "StormSlider", "event": "OnValueChanged"}}, "onStorm")
    c = g.call("SaskartaStorm", CM_C)
    g.link(f"{cm}.CM", f"{c}.self")
    g.link(f"{ev}.Value", f"{c}.Intensity")
    g.chain(ev, c)
    graphs.append(g.spec())

    graph_spec = {
        "asset": WBP,
        "description": "LANE5 debug menu. CM_Saskarta creates it and calls InitDebug(self). Every button calls CM_Saskarta. README_Debug.md.",
        "variables": variables,
        "functions": functions,
        "graphs": graphs,
    }
    return tree, graph_spec


POST_TEMPLATE = """# python_run (Hayba) after a bpgraph build of CM_Saskarta and fix_array_nodes.py. Generated by
# Tools/GameFlow/gen_debug_specs.py: marks the console functions Exec and bakes the beat table.
import unreal
BEL = unreal.BlueprintEditorLibrary
bp = unreal.load_asset('{asset}')
for name in {execs!r}:
    ge = unreal.BlueprintGraphEditor.get_graph_editor(BEL.find_graph(bp, name))
    ge.set_is_exec_function(True)
BEL.compile_blueprint(bp)
cdo = unreal.get_default_object(BEL.generated_class(bp))
cdo.set_editor_property('BeatIds', [unreal.Name(n) for n in {ids!r}])
cdo.set_editor_property('BeatRoadMs', {roads!r})
status = str(bp.get_editor_property('status'))
if 'ERROR' not in status.upper():
    unreal.EditorAssetLibrary.save_loaded_asset(bp, False)
print('status', status, 'beats', len(cdo.get_editor_property('BeatIds')))
"""


def main():
    beats = beat_table()
    if "--table" in sys.argv:
        for b in beats:
            print(f"{b['id']:<26}{b['road_m']:>7.0f}  {b['trigger']}")
        return
    cm = build_cm(beats)
    tree, graph = build_widget(beats)
    for name, obj in (("CM_Saskarta.json", cm), ("CM_Saskarta.post.json", build_cm_post(beats, cm)), ("WBP_Saskarta_Debug.tree.json", tree), ("WBP_Saskarta_Debug.graph.json", graph)):
        (SPECS / name).write_text(json.dumps(obj, indent=1) + "\n", encoding="utf-8")
        print("wrote", SPECS / name)
    post = build_cm_post(beats, cm)
    script = POST_TEMPLATE.format(asset=CM, execs=post["exec_functions"], ids=post["array_defaults"]["BeatIds"],
                                  roads=post["array_defaults"]["BeatRoadMs"])
    out = ROOT / "Tools" / "GameFlow" / "editor" / "cm_saskarta_post.py"
    out.write_text(script, encoding="utf-8")
    print("wrote", out)


if __name__ == "__main__":
    main()
