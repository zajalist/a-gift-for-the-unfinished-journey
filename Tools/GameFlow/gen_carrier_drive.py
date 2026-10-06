"""gen_carrier_drive: the carrier's drive model, vehicle audio, anti-stuck and anim debug line (LANE3, 2026-09-28).

    python Tools/GameFlow/gen_carrier_drive.py        # patches Tools/GameFlow/specs/BP_Saskarta_Carrier.json
    node Tools/GameFlow/bpgraph.mjs build --reset-graphs Tools/GameFlow/specs/BP_Saskarta_Carrier.json

Idempotent: every graph and variable it owns is replaced on each run. No Tick anywhere: DriveStep runs on
a 30 Hz timer started at the end of StartAnimDriver (on possession), DebugAnim on a 2 s timer.

Drive model (DriveStep, 30 Hz). The pawn keeps CharacterMovement; DriveStep sets its limits and Move
feeds scaled input every frame:
- Throttle ramps 0 -> 1 in 0.6 s while W is held (Move stamps MoveTime; input older than 0.15 s is
  released), and falls back at the same rate; releasing W coasts at 150 cm/s^2 (separate braking friction
  0, so only the constant deceleration applies).
- Torque: MaxAcceleration = 190 -> 25 cm/s^2 linearly over 0 -> 500 cm/s; the 520 cm/s
  flat cap keeps the familiar pace while shortening the empty stretch of road.
- Slope (from the velocity's climb angle, smoothed): top speed x (1 -> 0.55 from 3 to 25 deg uphill),
  acceleration x (1 -> 0.50 from 0 to 20 deg), downhill assist up to x1.2 from -2 to -12 deg.
  A steep climb still asks for Shift boost, which spends the carrier's main charge.
- S while rolling forward (> 20 cm/s) brakes at 600 cm/s^2 with no drive input; after 0.35 s stopped it
  reverses slowly (max 120 cm/s) without turning round (orient-to-movement off while reversing).
- Steering: A/D turn the carrier at 75 deg/s when slow, 28 deg/s at top speed (applied every frame in
  Move from the smoothed Steer, 5/s self-centring); in reverse the turn is mirrored.
- Anti-stuck: throttle held, speed < 20 cm/s for 3 s -> a small backward-and-up launch (logged).
- Exposed for audio/anim: Throttle, DriveSpeed, DriveAccel, RPM (800..3200, +flare on throttle-up,
  sag under strain), EngineLoad 0..1, bBraking, Surface (0 dirt, 1 gravel, 2 slabs, from the distance
  to the road spline every 0.5 s: < 2.5 m slabs, < 6 m gravel).

Audio (CarrierAudioStep, same 30 Hz pass): the MetaSound design of task-CARRIERSFX-brief.md, as looping
AudioComponents on the mesh whose volume and pitch are set each pass (the brief allows a SoundCue or
component hook-up; MetaSound graphs cannot be authored by the tools). Motor layers follow RPM (as an
equivalent speed), not raw speed. One-shots: steering servos on steer onsets, suspension clunks on
vertical-speed jumps (the stomp, scaled), drawbar clanks on hard throttle/brake changes, knee grinds on
strain onset, mast ticks when the look turns 25 deg, state one-shots on AnimMode changes. Scrub: a second
gravel wheel loop, pitched down, whose gain follows the yaw rate at speed (no dedicated scrub asset).
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = HERE / "specs" / "BP_Saskarta_Carrier.json"
KML = "/Script/Engine.KismetMathLibrary"
KSL = "/Script/Engine.KismetSystemLibrary"
KSTR = "/Script/Engine.KismetStringLibrary"
GPS = "/Script/Engine.GameplayStatics"
ACTOR = "/Script/Engine.Actor"
PAWN = "/Script/Engine.Pawn"
CHAR = "/Script/Engine.Character"
CMC = "/Script/Engine.CharacterMovementComponent"
AC = "/Script/Engine.AudioComponent"
SPL = "/Script/Engine.SplineComponent"
SKM = "/Script/Engine.SkeletalMeshComponent"
CAI = "/Script/SaskartaCore.SaskartaCarrierAnimInstance"
SND = "/Game/SaskartaGaea/Audio/Carrier/"
DT = 1.0 / 30.0
PIN_RE = __import__("re").compile(r"^[A-Za-z_]\w*\.[A-Za-z_][\w /]*$")
# Keep speech and songs in front of the carrier, including under uphill strain.
# These are mix trims, independent of the player's volume setting and loop crossfades.
MOTOR_MIX_DB = -9.0
DETAIL_MIX_DB = -5.0
MOTOR_COMPONENTS = {"AC_Idle", "AC_Low", "AC_High", "AC_Strain"}

# ── sounds ───────────────────────────────────────────────────────────────────
LOOPS = {  # component var: (sound, attach bone, trim dB)
    "AC_Idle": ("SFX_Carrier_Motor_Idle_Loop", "body", -12),
    "AC_Low": ("SFX_Carrier_Motor_Low_Loop", "body", 0),
    "AC_High": ("SFX_Carrier_Motor_High_Loop", "body", 0),
    "AC_Strain": ("SFX_Carrier_Motor_Strain_Loop", "body", 0),
    "AC_WDirt": ("SFX_Carrier_Wheels_Dirt_Loop", "root", -6),
    "AC_WGravel": ("SFX_Carrier_Wheels_Gravel_Loop", "root", -6),
    "AC_WSlabs": ("SFX_Carrier_Wheels_Slabs_Loop", "root", -6),
    "AC_Creak": ("SFX_Carrier_Chassis_Creak_Loop", "body", -14),
    "AC_TWDirt": ("SFX_Carrier_Trailer_Wheels_Dirt_Loop", "capsule_root", -13),
    "AC_TWGravel": ("SFX_Carrier_Trailer_Wheels_Gravel_Loop", "capsule_root", -13),
    "AC_TWSlabs": ("SFX_Carrier_Trailer_Wheels_Slabs_Loop", "capsule_root", -13),
    "AC_Rattle": ("SFX_Carrier_Drawbar_Rattle_Loop", "coupler", -14),
    "AC_Scrub": ("SFX_Carrier_Wheels_Gravel_Loop", "root", -8),
}
ONESHOTS = {  # group: list of sounds
    "ServoL": [f"SFX_Carrier_Steer_Servo_L_0{i}" for i in (1, 2, 3)],
    "ServoR": [f"SFX_Carrier_Steer_Servo_R_0{i}" for i in (1, 2, 3)],
    "Clunk": [f"SFX_Carrier_Suspension_Clunk_0{i}" for i in range(1, 9)],
    "Clank": [f"SFX_Carrier_Drawbar_Clank_0{i}" for i in (1, 2, 3, 4)],
    "Knee": [f"SFX_Carrier_Knee_Grind_0{i}" for i in (1, 2, 3, 4)],
    "Tick": [f"SFX_Carrier_Mast_Tick_0{i}" for i in (1, 2, 3, 4)],
}
# Lights (user: "flashing lights where the car's headlights are"): at the eye lamps, mesh space (+Y forward).
LIGHTS = {  # comp: (location, class, shadows)
    # ahead of all carrier geometry (the eye lamps are at Y 75; the nose ends near Y 95), ~0.4 m up,
    # so no part of the carrier sits between a lamp and the road (user: "they cast shadows of the mast")
    "HeadlightL": ((-22.0, 102.0, 40.0), "spot", False),
    "HeadlightR": ((22.0, 102.0, 40.0), "spot", False),
    "HazardL": ((-27.0, 90.0, 58.0), "point", False),
    "HazardR": ((27.0, 90.0, 58.0), "point", False),
}
HEADLIGHT_CD = 350.0    # candela (user: 6000, then 1000, still too strong): old warm lamps in dust
HAZARD_CD = 50.0        # candela at the top of the pulse
STATES = {"Start": "SFX_Carrier_State_Start", "StartStop": "SFX_Carrier_State_StartStop", "Shutdown": "SFX_Carrier_State_Shutdown"}


def db(x):
    return 10 ** (x / 20.0)


def snd_path(n):
    return f"{SND}{n}.{n}"


# ── a tiny graph builder with exec joining ───────────────────────────────────
class G:
    def __init__(self, name, entry=True):
        self.name = name
        self.nodes = {}
        self.links = []
        self.defaults = {}
        self.n = 0
        self.pending = []
        if entry:
            self.nodes["entry"] = {"entry": True}
            self.pending = [("entry", "then")]

    def key(self, base):
        self.n += 1
        return f"{base}{self.n}"

    def node(self, spec, base="n"):
        k = self.key(base)
        self.nodes[k] = spec
        return k

    def arg(self, target, value):
        """value: a pin 'node.Pin' (linked) or a literal (default)."""
        if isinstance(value, str) and PIN_RE.match(value):
            self.links.append([value, target])
        else:
            self.defaults[target] = str(value) if not isinstance(value, bool) else ("true" if value else "false")

    def call(self, fn, cls=None, args=None, exec_=False, base=None):
        k = self.node({"call": fn, "class": cls} if cls else {"call": fn}, base or fn[:6])
        for p, v in (args or {}).items():
            self.arg(f"{k}.{p}", v)
        if exec_:
            self.then(k)
        return k

    def get(self, var):
        k = self.node({"get": var}, "g")
        return f"{k}.{var}"

    def me(self):
        if "me" not in self.nodes:
            self.nodes["me"] = {"self": True}
        return "me.self"

    def set(self, var, value):
        k = self.node({"set": var}, "s")
        self.arg(f"{k}.{var}", value)
        self.then(k)
        return k

    def then(self, k):
        for (a, pin) in self.pending:
            self.links.append([f"{a}.{pin}", f"{k}.execute"])
        self.pending = [(k, "then")]

    def branch(self, cond):
        k = self.node({"branch": True}, "if")
        self.arg(f"{k}.Condition", cond)
        self.then(k)
        self.pending = [(k, "then")]
        return k

    def join_else(self, br):
        self.pending.append((br, "else"))

    def cast(self, cls, obj):
        k = self.node({"cast": cls}, "cast")
        self.arg(f"{k}.Object", obj)
        self.then(k)
        return k

    # pure math
    def f(self, fn, **a):
        k = self.call(fn, KML, a)
        return f"{k}.ReturnValue"

    def add(self, a, b): return self.f("Add_DoubleDouble", A=a, B=b)
    def sub(self, a, b): return self.f("Subtract_DoubleDouble", A=a, B=b)
    def mul(self, a, b): return self.f("Multiply_DoubleDouble", A=a, B=b)
    def div(self, a, b): return self.f("Divide_DoubleDouble", A=a, B=b)
    def fmax(self, a, b): return self.f("FMax", A=a, B=b)
    def fmin(self, a, b): return self.f("FMin", A=a, B=b)
    def abs(self, a): return self.f("Abs", A=a)
    def gt(self, a, b): return self.f("Greater_DoubleDouble", A=a, B=b)
    def lt(self, a, b): return self.f("Less_DoubleDouble", A=a, B=b)
    def band(self, a, b): return self.f("BooleanAND", A=a, B=b)
    def bor(self, a, b): return self.f("BooleanOR", A=a, B=b)
    def bnot(self, a): return self.f("Not_PreBool", A=a)
    def sel(self, a, b, pick_a): return self.f("SelectFloat", A=a, B=b, bPickA=pick_a)
    def mr(self, v, ia, ib, oa, ob): return self.f("MapRangeClamped", Value=v, InRangeA=ia, InRangeB=ib, OutRangeA=oa, OutRangeB=ob)
    def interp(self, cur, tgt, speed): return self.f("FInterpTo", Current=cur, Target=tgt, DeltaTime=DT, InterpSpeed=speed)
    def interpc(self, cur, tgt, speed): return self.f("FInterpTo_Constant", Current=cur, Target=tgt, DeltaTime=DT, InterpSpeed=speed)

    def spec(self):
        return {"graph": self.name, "nodes": self.nodes, "links": self.links, "defaults": self.defaults}


def cmc(g):
    """CharacterMovement of self, cast. Returns the cast node (exec in the chain)."""
    get = g.call("GetComponentByClass", ACTOR, {"ComponentClass": CMC})
    return g.cast(CMC, f"{get}.ReturnValue")


def setprop(g, obj, kind, name, value):
    fn = {"float": "SetDoublePropertyByName", "bool": "SetBoolPropertyByName"}[kind]
    return g.call(fn, KSL, {"Object": obj, "PropertyName": name, "Value": value}, exec_=True)


# ── variables ────────────────────────────────────────────────────────────────
def variables():
    v = [
        ("MoveX", "float", "0.0"), ("MoveY", "float", "0.0"), ("MoveTime", "float", "-10.0"),
        ("Throttle", "float", "0.0"), ("Steer", "float", "0.0"), ("DriveSpeed", "float", "0.0"),
        ("SignedSpeed", "float", "0.0"), ("PrevSigned", "float", "0.0"), ("DriveAccel", "float", "0.0"),
        ("Slope", "float", "0.0"), ("RPM", "float", "800.0"), ("EngineLoad", "float", "0.0"),
        ("bBraking", "bool", "false"), ("bReversing", "bool", "false"), ("StopHold", "float", "0.0"),
        ("TurnRateNow", "float", "75.0"), ("InputScale", "float", "0.0"), ("StuckTime", "float", "0.0"),
        ("Surface", "int", "0"), ("SurfaceClock", "float", "0.0"), ("RoadSpline", f"object:{SPL}"),
        ("DriveTimer", "struct:/Script/Engine.TimerHandle"), ("DebugTimer", "struct:/Script/Engine.TimerHandle"),
        ("bDebugAnim", "bool", "false"),
        ("StrainW", "float", "0.0"), ("W0", "float", "1.0"), ("W1", "float", "0.0"), ("W2", "float", "0.0"),
        ("PrevSteer", "float", "0.0"), ("PrevVz", "float", "0.0"), ("PrevThrottle", "float", "0.0"),
        ("PrevStrain", "bool", "false"), ("LastTickYaw", "float", "0.0"), ("LastAnimMode", "name", "None"),
        ("Flare", "float", "0.0"), ("bHazardOverride", "bool", "false"), ("AudioGate", "float", "0.0"),
        ("bAudioControllerReady", "bool", "false"), ("HazardPhase", "float", "0.0"),
    ]
    out = []
    for item in v:
        n, t = item[0], item[1]
        e = {"name": n, "type": t}
        if len(item) > 2:
            e["default"] = item[2]
        out.append(e)
    for comp in LOOPS:
        out.append({"name": comp, "type": f"object:{AC}"})
    for comp, (s, _, _) in LOOPS.items():
        out.append({"name": "S_" + comp[3:], "type": "object:/Script/Engine.SoundBase", "default": snd_path(s)})
    for grp, sounds in ONESHOTS.items():
        for i, s in enumerate(sounds):
            out.append({"name": f"S_{grp}{i}", "type": "object:/Script/Engine.SoundBase", "default": snd_path(s)})
    for st, s in STATES.items():
        out.append({"name": f"S_State{st}", "type": "object:/Script/Engine.SoundBase", "default": snd_path(s)})
    return out


# ── StartCarrierExtras: CMC setup, audio components, timers ──────────────────
def start_extras():
    g = G("StartCarrierExtras")
    mv = cmc(g)
    m = f"{mv}.AsCharacter Movement Component"
    setprop(g, m, "bool", "bUseSeparateBrakingFriction", True)
    setprop(g, m, "float", "BrakingFriction", 0.0)
    setprop(g, m, "float", "MaxStepHeight", 55.0)
    g.call("SetWalkableFloorAngle", CMC, {"self": m, "InWalkableFloorAngle": 50.0}, exec_=True)
    getm = g.call("GetComponentByClass", ACTOR, {"ComponentClass": SKM})
    mesh = g.cast(SKM, f"{getm}.ReturnValue")
    meshp = f"{mesh}.AsSkeletal Mesh Component"
    for comp, (s, bone, _) in LOOPS.items():
        dur_rand = g.call("RandomFloatInRange", KML, {"Min": 0.0, "Max": 6.0})
        sp = g.call("SpawnSoundAttached", GPS, {
            "Sound": g.get("S_" + comp[3:]), "AttachToComponent": meshp, "AttachPointName": bone,
            "VolumeMultiplier": 0.0, "PitchMultiplier": 1.0, "StartTime": f"{dur_rand}.ReturnValue",
            "bAutoDestroy": False, "bStopWhenAttachedToDestroyed": True}, exec_=True)
        g.set(comp, f"{sp}.ReturnValue")
    snap = {"LocationRule": "SnapToTarget", "RotationRule": "SnapToTarget", "ScaleRule": "KeepWorld", "bWeldSimulatedBodies": False}
    LC = "/Script/Engine.LightComponent"
    LLC = "/Script/Engine.LocalLightComponent"
    SLC = "/Script/Engine.SpotLightComponent"
    for comp, ((x, y, z), kind, shadows) in LIGHTS.items():
        lp = g.get(comp)
        g.call("K2_AttachToComponent", "/Script/Engine.SceneComponent", {"self": lp, "Parent": meshp, **snap}, exec_=True)
        g.call("K2_SetRelativeLocationAndRotation", "/Script/Engine.SceneComponent", {
            "self": lp, "NewLocation": f"(X={x},Y={y},Z={z})", "NewRotation": "-8.0,90.0,0.0",
            "bSweep": False, "bTeleport": True}, exec_=True)
        g.call("SetIntensityUnits", LLC, {"self": lp, "NewIntensityUnits": "Candelas"}, exec_=True)
        if kind == "spot":
            g.call("SetLightColor", LC, {"self": lp, "NewLightColor": "(R=1.0,G=0.86,B=0.68,A=1.0)", "bSRGB": True}, exec_=True)
            g.call("SetAttenuationRadius", LLC, {"self": lp, "NewRadius": 2000.0}, exec_=True)
            g.call("SetUseTemperature", LC, {"self": lp, "bNewValue": True}, exec_=True)
            g.call("SetTemperature", LC, {"self": lp, "NewTemperature": 3200.0}, exec_=True)
            g.call("SetOuterConeAngle", SLC, {"self": lp, "NewOuterConeAngle": 35.0}, exec_=True)
            g.call("SetInnerConeAngle", SLC, {"self": lp, "NewInnerConeAngle": 12.0}, exec_=True)
            g.call("SetVolumetricScatteringIntensity", LC, {"self": lp, "NewIntensity": 0.3}, exec_=True)
        else:
            g.call("SetLightColor", LC, {"self": lp, "NewLightColor": "(R=1.0,G=0.42,B=0.04,A=1.0)", "bSRGB": True}, exec_=True)
            g.call("SetAttenuationRadius", LLC, {"self": lp, "NewRadius": 150.0}, exec_=True)
            g.call("SetVolumetricScatteringIntensity", LC, {"self": lp, "NewIntensity": 0.0}, exec_=True)
        g.call("SetCastShadows", LC, {"self": lp, "bNewValue": shadows}, exec_=True)
        g.call("SetBoolPropertyByName", KSL, {"Object": lp, "PropertyName": "bCastVolumetricShadow", "Value": False}, exec_=True)
        g.call("SetDoublePropertyByName", KSL, {"Object": lp, "PropertyName": "SpecularScale", "Value": 0.3}, exec_=True)
        g.call("SetIntensity", LC, {"self": lp, "NewIntensity": 0.0}, exec_=True)
    road = g.call("GetActorOfClass", GPS, {"ActorClass": "/Game/SaskartaGaea/Road/BP_Saskarta_Road.BP_Saskarta_Road_C"}, exec_=True)
    rs = g.call("GetComponentByClass", ACTOR, {"self": f"{road}.ReturnValue", "ComponentClass": SPL})
    c = g.cast(SPL, f"{rs}.ReturnValue")
    g.set("RoadSpline", f"{c}.AsSpline Component")
    g.pending.append((c, "CastFailed"))  # no road loaded yet: the timers still start
    t = g.node({"timer": True}, "timer")
    g.arg(f"{t}.Object", g.me())
    g.defaults.update({f"{t}.FunctionName": "DriveStep", f"{t}.Time": str(round(DT, 4)), f"{t}.bLooping": "true"})
    g.then(t)
    g.set("DriveTimer", f"{t}.ReturnValue")
    t2 = g.node({"timer": True}, "timer")
    g.arg(f"{t2}.Object", g.me())
    g.defaults.update({f"{t2}.FunctionName": "DebugAnim", f"{t2}.Time": "2.0", f"{t2}.bLooping": "true"})
    g.then(t2)
    g.set("DebugTimer", f"{t2}.ReturnValue")
    return g


# ── Move: store the input; add scaled movement and the steering yaw every frame ──
def move():
    g = G("Move")
    now = g.call("GetTimeSeconds", GPS)
    g.set("MoveX", "entry.Left / Right")
    g.set("MoveY", "entry.Forward / Backward")
    g.set("MoveTime", f"{now}.ReturnValue")
    fwd = g.call("GetActorForwardVector", ACTOR)
    neg = g.call("Multiply_VectorFloat", KML, {"A": f"{fwd}.ReturnValue", "B": -1.0})
    dirv = g.call("SelectVector", KML, {"A": f"{neg}.ReturnValue", "B": f"{fwd}.ReturnValue", "bPickA": g.get("bReversing")})
    g.call("AddMovementInput", PAWN, {"WorldDirection": f"{dirv}.ReturnValue", "ScaleValue": g.get("InputScale")}, exec_=True)
    dt = g.call("GetWorldDeltaSeconds", GPS)
    sign = g.sel(-1.0, 1.0, g.get("bReversing"))
    yaw = g.mul(g.mul(g.mul(g.get("Steer"), g.get("TurnRateNow")), f"{dt}.ReturnValue"), sign)
    rot = g.call("MakeRotator", KML, {"Roll": 0.0, "Pitch": 0.0, "Yaw": yaw})
    g.call("K2_AddActorWorldRotation", ACTOR, {"DeltaRotation": f"{rot}.ReturnValue", "bSweep": False, "bTeleport": False}, exec_=True)
    return g


# ── DriveStep (30 Hz) ────────────────────────────────────────────────────────
def drive_step():
    g = G("DriveStep")
    now = g.call("GetTimeSeconds", GPS)
    fresh = g.lt(g.sub(f"{now}.ReturnValue", g.get("MoveTime")), 0.15)
    mx = g.sel(g.get("MoveX"), 0.0, fresh)
    my = g.sel(g.get("MoveY"), 0.0, fresh)
    vel = g.call("GetVelocity", ACTOR)
    fwd = g.call("GetActorForwardVector", ACTOR)
    signed = g.f("Dot_VectorVector", A=f"{vel}.ReturnValue", B=f"{fwd}.ReturnValue")
    speed = g.f("VSizeXY", A=f"{vel}.ReturnValue")
    vb = g.call("BreakVector", KML, {"InVec": f"{vel}.ReturnValue"})
    # climb angle of the motion (positive uphill while moving forward)
    climb = g.f("DegAtan2", Y=f"{vb}.Z", X=g.fmax(speed, 30.0))
    climb_dir = g.mul(climb, g.sel(-1.0, 1.0, g.lt(signed, -10.0)))
    g.set("Slope", g.interp(g.get("Slope"), climb_dir, 3.0))
    g.set("DriveAccel", g.interp(g.get("DriveAccel"), g.div(g.sub(signed, g.get("PrevSigned")), DT), 6.0))
    g.set("PrevSigned", signed)
    g.set("SignedSpeed", signed)
    g.set("DriveSpeed", speed)
    wants_fwd = g.gt(my, 0.05)
    wants_back = g.lt(my, -0.1)
    g.set("Throttle", g.interpc(g.get("Throttle"), g.sel(1.0, 0.0, wants_fwd), 1.0 / 0.6))
    braking = g.band(wants_back, g.gt(signed, 20.0))
    g.set("bBraking", braking)
    stopped = g.lt(speed, 25.0)
    g.set("StopHold", g.sel(g.add(g.get("StopHold"), DT), 0.0, g.band(wants_back, stopped)))
    rev = g.bor(g.band(wants_back, g.gt(g.get("StopHold"), 0.35)), g.band(wants_back, g.lt(signed, -10.0)))
    g.set("bReversing", rev)
    up = g.mr(g.get("Slope"), 3.0, 25.0, 1.0, 0.55)
    down = g.mr(g.get("Slope"), -2.0, -12.0, 1.0, 1.2)
    grip = g.sel(0.85, 1.0, g.f("EqualEqual_IntInt", A=g.get("Surface"), B=0))  # loose dirt: -15 %
    top = g.mul(g.mul(g.mul(520.0, up), down), g.sel(0.92, 1.0, g.f("EqualEqual_IntInt", A=g.get("Surface"), B=1)))
    steer_only = g.band(g.lt(my, 0.05), g.gt(g.abs(mx), 0.1))
    # steering without throttle creeps at most 80 cm/s, and a faster carrier keeps coasting down at 150 cm/s^2
    top2 = g.sel(g.fmax(80.0, g.sub(speed, 150.0 * DT)), top, steer_only)
    acc = g.mul(g.mul(g.mr(speed, 0.0, 500.0, 190.0, 25.0), g.mr(g.get("Slope"), 0.0, 20.0, 1.0, 0.50)), grip)
    mv = cmc(g)
    m = f"{mv}.AsCharacter Movement Component"
    setprop(g, m, "float", "MaxWalkSpeed", g.sel(120.0, top2, rev))
    setprop(g, m, "float", "MaxAcceleration", g.sel(100.0, acc, rev))
    roll = g.sel(170.0, 150.0, g.f("EqualEqual_IntInt", A=g.get("Surface"), B=0))
    setprop(g, m, "float", "BrakingDecelerationWalking", g.sel(600.0, roll, braking))
    # Never orient to movement: Move rotates the actor itself, and CharacterMovement turning the carrier
    # back toward its (lagging) velocity cancelled A/D while accelerating (user: "can't turn while
    # accelerating"). The velocity follows the new heading through the forward input and ground friction.
    setprop(g, m, "bool", "bOrientRotationToMovement", False)
    fwd_scale = g.fmax(g.get("Throttle"), g.mul(g.abs(mx), 0.25))
    g.set("InputScale", g.sel(1.0, g.sel(0.0, fwd_scale, braking), rev))
    # steer ramps in over 0.15 s and out over 0.25 s; it only self-centres with no input
    ramping_in = g.gt(g.abs(mx), g.abs(g.get("Steer")))
    g.set("Steer", g.interpc(g.get("Steer"), mx, g.sel(1.0 / 0.15, 1.0 / 0.25, ramping_in)))
    # a clear turn at every speed: 90 deg/s standing (it pivots), 45 deg/s at top speed
    g.set("TurnRateNow", g.mr(speed, 0.0, 500.0, 90.0, 45.0))
    # RPM: 800 idle -> 3200 at top, + a throttle-up flare, - a sag under strain
    g.set("Flare", g.interp(g.get("Flare"), g.fmax(g.sub(g.get("Throttle"), g.get("PrevThrottle")), 0.0), 4.0))
    rpm = g.add(g.add(800.0, g.mul(g.mr(speed, 0.0, 500.0, 0.0, 2400.0), 1.0)), g.sub(g.mul(g.get("Throttle"), 250.0), g.mul(g.get("StrainW"), 300.0)))
    g.set("RPM", g.add(rpm, g.mul(g.get("Flare"), 6000.0)))
    g.set("EngineLoad", g.f("FClamp", Value=g.add(g.mul(g.get("Throttle"), 0.5), g.add(g.mr(g.get("Slope"), 0.0, 20.0, 0.0, 0.5), g.mr(g.abs(g.get("DriveAccel")), 0.0, 200.0, 0.0, 0.2))), Min=0.0, Max=1.0))
    # Automatic hill torque runs after the normal CMC limits. Its floor normal
    # remains meaningful at a standstill, unlike the velocity-derived Slope.
    assist = g.call("UpdateCarrier", "/Script/SaskartaCore.SaskartaMotorAssistSubsystem",
                    {"Carrier": g.me(), "DeltaSeconds": DT, "Throttle": g.get("Throttle"),
                     "bReversing": g.get("bReversing"), "bBraking": g.get("bBraking")}, exec_=True)
    # A difficult climb must never trigger the old automatic backwards launch.
    stuck = g.band(g.band(g.gt(g.get("Throttle"), 0.6), g.lt(speed, 20.0)),
                   g.bnot(f"{assist}.ReturnValue"))
    g.set("StuckTime", g.sel(g.add(g.get("StuckTime"), DT), 0.0, stuck))
    br = g.branch(g.gt(g.get("StuckTime"), 3.0))
    back = g.call("Multiply_VectorFloat", KML, {"A": f"{fwd}.ReturnValue", "B": -220.0})
    upv = g.call("Add_VectorVector", KML, {"A": f"{back}.ReturnValue", "B": "(X=0.0,Y=0.0,Z=180.0)"})
    g.call("LaunchCharacter", CHAR, {"LaunchVelocity": f"{upv}.ReturnValue", "bXYOverride": False, "bZOverride": False}, exec_=True)
    g.call("PrintString", KSL, {"InString": "Saskarta carrier: unstuck nudge (throttle held, no motion for 3 s)", "bPrintToScreen": False, "bPrintToLog": True}, exec_=True)
    g.set("StuckTime", 0.0)
    g.join_else(br)
    # surface every 0.5 s
    g.set("SurfaceClock", g.add(g.get("SurfaceClock"), DT))
    br2 = g.branch(g.gt(g.get("SurfaceClock"), 0.5))
    g.set("SurfaceClock", 0.0)
    valid = g.call("IsValid", KSL, {"Object": g.get("RoadSpline")})
    br3 = g.branch(f"{valid}.ReturnValue")
    loc = g.call("K2_GetActorLocation", ACTOR)
    near = g.call("FindLocationClosestToWorldLocation", SPL, {"self": g.get("RoadSpline"), "WorldLocation": f"{loc}.ReturnValue", "CoordinateSpace": "World"})
    dist = g.f("Vector_Distance2D", v1=f"{near}.ReturnValue", v2=f"{loc}.ReturnValue")
    s = g.f("SelectInt", A=2, B=g.f("SelectInt", A=1, B=0, bPickA=g.lt(dist, 600.0)), bPickA=g.lt(dist, 250.0))
    g.set("Surface", s)
    g.join_else(br2)
    g.join_else(br3)
    g.set("PrevThrottle", g.get("Throttle"))
    lights_step(g)
    g.call("CarrierAudioStep", None, {}, exec_=True)
    return g


def lights_step(g):
    """Headlights on unless the carrier is Off / Shutdown; amber hazards pulse at 1 Hz at boot (Start),
    under strain, or while bHazardOverride is set (faults, the storm: set it from those systems)."""
    LC = "/Script/Engine.LightComponent"
    mode = g.get("AnimMode")
    off = g.bor(g.f("EqualEqual_NameName", A=mode, B="Off"), g.f("EqualEqual_NameName", A=mode, B="Shutdown"))
    head = g.sel(0.0, HEADLIGHT_CD, off)
    for comp in ("HeadlightL", "HeadlightR"):
        g.call("SetIntensity", LC, {"self": g.get(comp), "NewIntensity": head}, exec_=True)
    boot = g.f("EqualEqual_NameName", A=mode, B="Start")
    hz_on = g.bor(g.bor(boot, g.gt(g.get("StrainW"), 0.5)), g.get("bHazardOverride"))
    g.set("HazardPhase", g.f("FWrap", Value=g.add(g.get("HazardPhase"), DT), Min=0.0, Max=1.0))
    wave = g.add(0.5, g.mul(0.5, g.f("Sin", A=g.mul(g.get("HazardPhase"), 6.2831853))))
    pulse = g.mul(g.mul(wave, wave), HAZARD_CD)
    val = g.sel(pulse, 0.0, hz_on)
    for comp in ("HazardL", "HazardR"):
        g.call("SetIntensity", LC, {"self": g.get(comp), "NewIntensity": val}, exec_=True)


# ── CarrierAudioStep ─────────────────────────────────────────────────────────
def audio_step():
    g = G("CarrierAudioStep")
    ok = g.call("IsValid", KSL, {"Object": g.get("AC_Idle")})
    g.branch(f"{ok}.ReturnValue")
    # Normal driving or this exact carrier's unsuppressed automatic pursuit.
    # The pursuit owns IgnoreMoveInput while it drives: that flag alone muted
    # every regular vehicle loop. Native flow/owner gates still silence the title,
    # menus, cinematic, prompts and parked tuning. One-shots share the gate.
    ready = g.call("ShouldPlayDriveAudio", "/Script/SaskartaCore.SaskartaMotorAssistSubsystem",
                   {"Carrier": g.me()})
    g.set("bAudioControllerReady", f"{ready}.ReturnValue")
    handed = g.get("bAudioControllerReady")
    g.set("AudioGate", g.interpc(g.get("AudioGate"), g.sel(1.0, 0.0, handed), 1.0))
    # the motor layers follow RPM, expressed as the equivalent speed (cm/s) of the recorded loops
    rs = g.mul(g.sub(g.get("RPM"), 800.0), 500.0 / 2400.0)
    rs = g.fmax(rs, 0.0)
    speed = g.get("DriveSpeed")
    thr = g.get("Throttle")
    strain_now = g.gt(g.get("Slope"), 12.0)
    g.set("StrainW", g.interp(g.get("StrainW"), g.sel(1.0, 0.0, strain_now), 2.0))
    for k in (0, 1, 2):
        g.set(f"W{k}", g.interp(g.get(f"W{k}"), g.f("SelectFloat", A=1.0, B=0.0, bPickA=g.f("EqualEqual_IntInt", A=g.get("Surface"), B=k)), 3.0))
    sw = g.get("StrainW")
    load = g.mul(g.add(0.75, g.mul(thr, 0.25)), g.add(0.45, g.mul(g.mr(rs, 0.0, 500.0, 0.0, 1.0), 0.55)))
    duck = g.sub(1.0, g.mul(sw, 1.0 - db(-4)))
    rough = g.add(g.add(g.mul(g.get("W0"), 0.45), g.mul(g.get("W1"), 0.75)), g.get("W2"))

    def setac(comp, vol, pitch):
        trim = db(MOTOR_MIX_DB if comp in MOTOR_COMPONENTS else DETAIL_MIX_DB)
        g.call("SetVolumeMultiplier", AC, {"self": g.get(comp), "NewVolumeMultiplier": g.mul(g.mul(vol, trim), g.get("AudioGate"))}, exec_=True)
        g.call("SetPitchMultiplier", AC, {"self": g.get(comp), "NewPitchMultiplier": pitch}, exec_=True)

    tr = {c: db(t) for c, (_, _, t) in LOOPS.items()}
    setac("AC_Idle", g.mul(g.sub(1.0, g.mul(g.mr(speed, 0.0, 150.0, 0.0, 1.0), 0.5)), tr["AC_Idle"]), g.add(1.0, g.mul(thr, 0.03)))
    low_g = g.mul(g.mul(g.mul(g.mr(rs, 3.0, 60.0, 0.0, 1.0), g.mr(rs, 210.0, 310.0, 1.0, 0.0)), load), duck)
    setac("AC_Low", low_g, g.f("FClamp", Value=g.div(rs, 157.1), Min=0.3, Max=2.0))
    high_g = g.mul(g.mul(g.mr(rs, 210.0, 310.0, 0.0, 1.0), load), duck)
    setac("AC_High", high_g, g.f("FClamp", Value=g.div(rs, 392.7), Min=0.5, Max=1.3))
    setac("AC_Strain", g.add(sw, g.mul(g.get("EngineLoad"), 0.25)), g.f("FClamp", Value=g.div(speed, 117.8), Min=0.6, Max=1.5))
    wheel_amp = g.mul(g.mr(speed, 2.0, 90.0, 0.0, 1.0), g.add(0.55, g.mul(speed, 0.45 / 500)))
    wpitch = g.add(0.8, g.mul(speed, 0.4 / 500))
    for k, comp in enumerate(["AC_WDirt", "AC_WGravel", "AC_WSlabs"]):
        setac(comp, g.mul(g.mul(g.get(f"W{k}"), wheel_amp), tr[comp]), wpitch)
    setac("AC_Creak", g.mul(g.add(g.mul(rough, g.mr(speed, 20.0, 250.0, 0.0, 1.0)), g.mul(sw, 0.6)), tr["AC_Creak"]), 1.0)
    tpitch = g.add(0.85, g.mul(speed, 0.45 / 500))
    for k, comp in enumerate(["AC_TWDirt", "AC_TWGravel", "AC_TWSlabs"]):
        setac(comp, g.mul(g.mul(g.get(f"W{k}"), wheel_amp), tr[comp]), tpitch)
    setac("AC_Rattle", g.mul(g.mul(rough, g.mr(speed, 30.0, 320.0, 0.0, 1.0)), tr["AC_Rattle"]), g.add(0.9, g.mul(speed, 0.2 / 500)))
    # scrub: yaw rate at speed
    scrub = g.mul(g.mr(g.mul(g.abs(g.get("Steer")), g.get("TurnRateNow")), 10.0, 60.0, 0.0, 1.0), g.mr(speed, 120.0, 400.0, 0.0, 1.0))
    setac("AC_Scrub", g.mul(scrub, tr["AC_Scrub"]), 0.72)

    def oneshot(cond, group, vol):
        br = g.branch(g.band(cond, g.gt(g.get("AudioGate"), 0.5)))
        sounds = ONESHOTS[group]
        s = g.node({"select": len(sounds)}, "pick")
        for i in range(len(sounds)):
            g.links.append([g.get(f"S_{group}{i}"), f"{s}.Option {i}"])
        ri = g.call("RandomIntegerInRange", KML, {"Min": 0, "Max": len(sounds) - 1})
        g.links.append([f"{ri}.ReturnValue", f"{s}.Index"])
        g.call("SpawnSound2D", GPS, {"Sound": f"{s}.ReturnValue", "VolumeMultiplier": g.mul(vol, db(DETAIL_MIX_DB))}, exec_=True)
        g.join_else(br)

    # steering servos: a steer onset (|steer| crosses 0.25 upward), direction = real side
    st, pst = g.get("Steer"), g.get("PrevSteer")
    onset_r = g.band(g.gt(st, 0.25), g.lt(pst, 0.25))
    onset_l = g.band(g.lt(st, -0.25), g.gt(pst, -0.25))
    oneshot(onset_r, "ServoR", db(-6))
    oneshot(onset_l, "ServoL", db(-6))
    g.set("PrevSteer", g.get("Steer"))
    # suspension clunk: a vertical-speed jump (landing / stomp), scaled
    vel = g.call("GetVelocity", ACTOR)
    vb = g.call("BreakVector", KML, {"InVec": f"{vel}.ReturnValue"})
    jump = g.abs(g.sub(f"{vb}.Z", g.get("PrevVz")))
    oneshot(g.band(g.gt(jump, 120.0), g.gt(speed, 20.0)), "Clunk", g.mr(jump, 120.0, 600.0, db(-10), db(0)))
    g.set("PrevVz", f"{vb}.Z")
    # drawbar clank: a hard throttle / brake change
    oneshot(g.band(g.gt(g.abs(g.sub(g.get("Throttle"), g.get("PrevThrottle"))), 0.04), g.gt(g.abs(g.get("DriveAccel")), 120.0)), "Clank", db(-8))
    # knee grind: strain onset
    oneshot(g.band(strain_now, g.bnot(g.get("PrevStrain"))), "Knee", db(-6))
    g.set("PrevStrain", strain_now)
    # mast tick: the look turned 25 deg since the last tick
    crot = g.call("GetControlRotation", PAWN)
    cb = g.call("BreakRotator", KML, {"InRot": f"{crot}.ReturnValue"})
    dyaw = g.abs(g.f("NormalizeAxis", Angle=g.sub(f"{cb}.Yaw", g.get("LastTickYaw"))))
    brt = g.branch(g.band(g.gt(dyaw, 25.0), g.gt(g.get("AudioGate"), 0.5)))
    s = g.node({"select": 4}, "pick")
    for i in range(4):
        g.links.append([g.get(f"S_Tick{i}"), f"{s}.Option {i}"])
    ri = g.call("RandomIntegerInRange", KML, {"Min": 0, "Max": 3})
    g.links.append([f"{ri}.ReturnValue", f"{s}.Index"])
    g.call("SpawnSound2D", GPS, {"Sound": f"{s}.ReturnValue", "VolumeMultiplier": db(-12 + DETAIL_MIX_DB)}, exec_=True)
    g.set("LastTickYaw", f"{cb}.Yaw")
    g.join_else(brt)
    # state one-shots on AnimMode changes
    mode = g.get("AnimMode")
    changed = g.f("NotEqual_NameName", A=mode, B=g.get("LastAnimMode"))
    for st_name in STATES:
        br = g.branch(g.band(g.band(changed, g.f("EqualEqual_NameName", A=mode, B=st_name)), g.bor(handed, g.gt(g.get("AudioGate"), 0.5))))
        g.call("SpawnSound2D", GPS, {"Sound": g.get(f"S_State{st_name}"), "VolumeMultiplier": db(-4 + DETAIL_MIX_DB)}, exec_=True)
        g.join_else(br)
    g.set("LastAnimMode", g.get("AnimMode"))
    return g


# ── DebugAnim (2 s): proves in the PIE log that the instance runs ───────────
def debug_anim():
    g = G("DebugAnim")
    g.branch(g.get("bDebugAnim"))
    getm = g.call("GetComponentByClass", ACTOR, {"ComponentClass": SKM})
    mesh = g.cast(SKM, f"{getm}.ReturnValue")
    ai = g.call("GetAnimInstance", SKM, {"self": f"{mesh}.AsSkeletal Mesh Component"})
    c = g.cast(CAI, f"{ai}.ReturnValue")
    inst = f"{c}.AsSaskarta Carrier Anim Instance"
    name = g.call("GetDisplayName", KSL, {"Object": f"{ai}.ReturnValue"})
    state = g.call("GetDriveState", CAI, {"self": inst})
    hitch = g.call("GetHitchAngle", CAI, {"self": inst})

    def s(x):
        return f"{g.call('Conv_DoubleToString', KSTR, {'InDouble': x})}.ReturnValue"

    parts = ["Saskarta carrier anim: ", f"{name}.ReturnValue", " state ", f"{g.call('Conv_NameToString', KSTR, {'InName': f'{state}.ReturnValue'})}.ReturnValue",
             " speed ", s(g.get("DriveSpeed")), " rpm ", s(g.get("RPM")), " throttle ", s(g.get("Throttle")), " steer ", s(g.get("Steer")),
             " hitch ", s(f"{hitch}.ReturnValue"), " slope ", s(g.get("Slope"))]
    acc = None
    for p in parts:
        if acc is None:
            acc = p
            continue
        k = g.call("Concat_StrStr", KSTR, {"A": acc, "B": p})
        acc = f"{k}.ReturnValue"
    g.call("PrintString", KSL, {"InString": acc, "bPrintToScreen": True, "bPrintToLog": True, "Duration": 5.0}, exec_=True)
    return g


def patch(spec):
    owned = {"StartCarrierExtras", "Move", "DriveStep", "CarrierAudioStep", "DebugAnim"}
    names = {v["name"] for v in variables()}
    spec["variables"] = [v for v in spec["variables"] if v["name"] not in names] + variables()
    spec["functions"] = [f for f in spec["functions"] if f["name"] not in owned] + [
        {"name": "StartCarrierExtras", "pure": False, "inputs": [], "outputs": []},
        # Move is the template's function; declared with its exact input names so only its graph is rebuilt.
        {"name": "Move", "pure": False, "inputs": [{"name": "Left / Right", "type": "double"}, {"name": "Forward / Backward", "type": "double"}], "outputs": []},
        {"name": "DriveStep", "pure": False, "inputs": [], "outputs": []},
        {"name": "CarrierAudioStep", "pure": False, "inputs": [], "outputs": []},
        {"name": "DebugAnim", "pure": False, "inputs": [], "outputs": []},
    ]
    spec["graphs"] = [g for g in spec["graphs"] if g["graph"] not in owned] + [
        start_extras().spec(), move().spec(), drive_step().spec(), audio_step().spec(), debug_anim().spec()]
    # StartAnimDriver ends with StartCarrierExtras
    sad = next(g for g in spec["graphs"] if g["graph"] == "StartAnimDriver")
    if "extras" not in sad["nodes"]:
        sad["nodes"]["extras"] = {"call": "StartCarrierExtras"}
        sad["links"].append(["keepGround.then", "extras.execute"])
    return spec


def simulate():
    """0 -> 500 on the flat with W held: the torque curve and the throttle ramp."""
    v, thr, t = 0.0, 0.0, 0.0
    rows, marks = [], {}
    while t < 9.0:
        thr = min(1.0, thr + DT / 0.6)
        a = (190.0 + (25.0 - 190.0) * min(v, 500.0) / 500.0) * thr
        v = min(500.0, v + a * DT)
        t += DT
        for m in (100, 200, 300, 400, 480):
            if v >= m and m not in marks:
                marks[m] = round(t, 2)
        if abs(t * 2 - round(t * 2)) < DT:
            rpm = 800 + v / 500 * 2400 + thr * 250
            rows.append((round(t, 1), round(thr, 2), round(v), round(a), round(rpm)))
    print("t s | throttle | speed cm/s | accel cm/s2 | rpm")
    for r in rows:
        print(" | ".join(str(x) for x in r))
    print("reached", marks)
    v, t = 500.0, 0.0
    while v > 0:
        v -= 150.0 * DT
        t += DT
    print("coast 500 -> 0:", round(t, 1), "s;  brake 500 -> 0 at 600 cm/s2:", round(500 / 600, 2), "s")


if __name__ == "__main__":
    if "--sim" in sys.argv:
        simulate()
        sys.exit(0)
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    SPEC.write_text(json.dumps(patch(spec), indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print("patched", SPEC.name)
