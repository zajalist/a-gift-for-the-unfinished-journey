"""gen_ending_specs: the Blueprint side of the ending chain (task ENDING, 2026-09-27). Offline; writes specs only.

    python Tools/GameFlow/gen_ending_specs.py          # writes the five specs below
    node Tools/GameFlow/bpgraph.mjs check <each spec>  # offline format check
    # editor lane (task-ENDING-brief.md step 4), ONE run so cross-BP calls resolve in pass 1:
    node Tools/GameFlow/bpgraph.mjs build --reset-graphs \
        Tools/GameFlow/specs/BP_Saskarta_Traveller.json Tools/GameFlow/specs/BPC_CarrierVision.ending.json \
        Tools/GameFlow/specs/BP_Saskarta_Carrier.ending.json Tools/GameFlow/specs/PC_Saskarta.ending.json \
        Tools/GameFlow/specs/BP_Saskarta_HighVoice.json

Specs (README_Ending.md explains each function):
  BP_Saskarta_Traveller.json         the Keeper as a playable pawn (full spec; replaces the TRAV lane's)
  BP_Saskarta_Carrier.ending.json    scoped: SnapToRoad, FreezeCarrier, SpawnTravellerInCapsule, TravellerGripRim,
                                     TravellerStandBeside, GetTraveller (the rest of the carrier is untouched)
  BPC_CarrierVision.ending.json      scoped: ShowLogLine(Line, Result), ShowBlack, HideBlack
  PC_Saskarta.ending.json            scoped: the Cine_* wrappers, PossessTraveller, Start/StopHumanWalk
  BP_Saskarta_HighVoice.json         the relay set's logic: SnapKeeperToPlate, Start/ResetGlowAndColumn, HideKeeper

Rules kept: no Tick (every clock is a timer), no arrays, no spawn nodes (the traveller is PLACED hidden and moved),
no literal on a const-ref pin (vectors and colours are wired from Make nodes), timer targets take no parameters.
"""
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPECS = HERE / "specs"

KML = "/Script/Engine.KismetMathLibrary"
KSL = "/Script/Engine.KismetSystemLibrary"
GPS = "/Script/Engine.GameplayStatics"
ACTOR = "/Script/Engine.Actor"
PAWN = "/Script/Engine.Pawn"
CTRL = "/Script/Engine.Controller"
CMC = "/Script/Engine.CharacterMovementComponent"
MOVC = "/Script/Engine.MovementComponent"
SCENE = "/Script/Engine.SceneComponent"
PRIM = "/Script/Engine.PrimitiveComponent"
SPL = "/Script/Engine.SplineComponent"
SKM = "/Script/Engine.SkeletalMeshComponent"
ARM = "/Script/Engine.SpringArmComponent"
AC = "/Script/Engine.AudioComponent"
MID = "/Script/Engine.MaterialInstanceDynamic"
WIDGET = "/Script/UMG.Widget"

TRAV = "/Game/SaskartaGaea/Characters/Traveller/BP_Saskarta_Traveller"
TRAV_C = f"{TRAV}.BP_Saskarta_Traveller_C"
CARRIER = "/Game/SaskartaGaea/Characters/Carrier/BP_Saskarta_Carrier"
CARRIER_C = f"{CARRIER}.BP_Saskarta_Carrier_C"
PC = "/Game/SaskartaGaea/GameFlow/PC_Saskarta"
CV = "/Game/SaskartaGaea/GameFlow/BPC_CarrierVision"
CV_C = f"{CV}.BPC_CarrierVision_C"
TETHER_C = "/Game/SaskartaGaea/GameFlow/BPC_RoadTether.BPC_RoadTether_C"
BOOTLOG_C = "/Game/SaskartaGaea/GameFlow/UI/WBP_Saskarta_BootLog.WBP_Saskarta_BootLog_C"
ROAD_C = "/Game/SaskartaGaea/Road/BP_Saskarta_Road.BP_Saskarta_Road_C"
HV = "/Game/SaskartaGaea/Story/HighVoice/BP_Saskarta_HighVoice"
ANIMS = "/Game/SaskartaGaea/Characters/Traveller/Anims"
FOOT = "/Game/AzielArts_Material/Footsteps/SoundWav"
FOLEY = "/Game/SaskartaGaea/Audio/Foley"
CAR_SFX = "/Game/SaskartaGaea/Audio/Carrier"
CARRIER_FULL = "/Game/SaskartaGaea/Characters/Carrier/Full"

PIN_RE = re.compile(r"^[A-Za-z_]\w*\.[A-Za-z_][\w /]*$")


def asset(path):
    return f"{path}.{path.rsplit('/', 1)[1]}"


class G:
    """A small graph builder: nodes, links, literals and an exec chain (`pending` is what the next exec joins)."""

    def __init__(self, name, entry=True):
        self.name, self.nodes, self.links, self.defaults, self.n = name, {}, [], {}, 0
        self.pending = []
        if entry:
            self.nodes["entry"] = {"entry": True}
            self.pending = [("entry", "then")]

    def node(self, spec, base="n"):
        self.n += 1
        k = f"{base}{self.n}"
        self.nodes[k] = spec
        return k

    def arg(self, target, value):
        if isinstance(value, str) and PIN_RE.match(value):
            self.links.append([value, target])
        elif isinstance(value, bool):
            self.defaults[target] = "true" if value else "false"
        else:
            self.defaults[target] = str(value)

    def call(self, fn, cls=None, args=None, exec_=False, target=None, base=None):
        k = self.node({"call": fn, "class": cls} if cls else {"call": fn}, base or re.sub(r"\W", "", fn)[:8])
        if target is not None:
            self.links.append([target, f"{k}.self"])
        for p, v in (args or {}).items():
            self.arg(f"{k}.{p}", v)
        if exec_:
            self.then(k)
        return k

    def do(self, fn, cls=None, args=None, target=None):
        return self.call(fn, cls, args, exec_=True, target=target)

    def ret(self, fn, cls=None, args=None, target=None, out="ReturnValue"):
        return f"{self.call(fn, cls, args, target=target)}.{out}"

    def xret(self, fn, cls=None, args=None, target=None, out="ReturnValue"):
        """An impure (exec) call placed on the chain, returning its output pin. GetActorOfClass and
        CreateDynamicMaterialInstance are BlueprintCallable, not pure: off the chain the compiler prunes them and
        their output reads as None (editor lane, 2026-09-28)."""
        return f"{self.call(fn, cls, args, exec_=True, target=target)}.{out}"

    def get(self, var):
        return f"{self.node({'get': var}, 'g')}.{var}"

    def me(self):
        self.nodes.setdefault("me", {"self": True})
        return "me.self"

    def set(self, var, value):
        k = self.node({"set": var}, "s")
        self.arg(f"{k}.{var}", value)
        self.then(k)
        return k

    def then(self, k, pin="execute"):
        for a, p in self.pending:
            self.links.append([f"{a}.{p}", f"{k}.{pin}"])
        self.pending = [(k, "then")]

    def branch(self, cond):
        """Continue on `then`; returns the node so the caller can pick up `else`."""
        k = self.node({"branch": True}, "if")
        self.arg(f"{k}.Condition", cond)
        self.then(k)
        return k

    def cast(self, cls, obj, display):
        """Impure cast in the chain; returns the typed output pin ('As<display>')."""
        k = self.node({"cast": cls}, "as")
        self.arg(f"{k}.Object", obj)
        self.then(k)
        return f"{k}.As{display}"

    def timer(self, fn, interval, loop, store=None):
        k = self.node({"timer": True}, "t")
        self.links.append([self.me(), f"{k}.Object"])
        self.defaults[f"{k}.FunctionName"] = fn
        self.arg(f"{k}.Time", interval)
        self.defaults[f"{k}.bLooping"] = "true" if loop else "false"
        self.then(k)
        if store:
            self.set(store, f"{k}.ReturnValue")
        return k

    def f(self, fn, **a):
        return self.ret(fn, KML, a)

    def vec(self, x, y, z):
        return self.f("MakeVector", X=x, Y=y, Z=z)

    def spec(self):
        return {"graph": self.name, "nodes": self.nodes, "links": self.links, "defaults": self.defaults}


def comp(g, cls, display):
    """self's first component of `cls`, cast (exec in the chain). Returns the typed pin."""
    return g.cast(cls, g.ret("GetComponentByClass", ACTOR, {"ComponentClass": cls}, target=g.me()), display)


def movement_mode(g, mode):
    m = comp(g, CMC, "Character Movement Component")
    g.do("SetMovementMode", CMC, {"NewMovementMode": mode}, target=m)
    return m


def fn(name, inputs=(), outputs=(), pure=False):
    return {"name": name, "inputs": [{"name": n, "type": t} for n, t in inputs],
            "outputs": [{"name": n, "type": t} for n, t in outputs], "pure": pure}


def var(name, typ, default=None):
    v = {"name": name, "type": typ}
    if default is not None:
        v["default"] = default
    return v


# ============================================================================ BP_Saskarta_Traveller

def traveller():
    graphs = []
    variables = [
        var("AnimMode", "name", "Loco"), var("AnimTimer", "struct:/Script/Engine.TimerHandle"),
        var("AnimInterval", "float", "0.1"), var("MoveCancelSpeed", "float", "10.0"),
        # ending
        var("bStartHidden", "bool", "true"), var("HumanWalkSpeed", "float", "110.0"),
        var("bWalking", "bool", "false"),
        var("RoadSpline", "object:/Script/Engine.SplineComponent"),
        var("TetherTimer", "struct:/Script/Engine.TimerHandle"), var("TetherInterval", "float", "0.25"),
        var("TetherLimit", "float", "900.0"), var("HalfHeight", "float", "92.0"),
        var("StepAccum", "float", "0.0"), var("StepLength", "float", "44.0"), var("StepCount", "int", "0"),
        var("FootVolume", "float", "0.55"), var("StaffVolume", "float", "0.45"),
        var("SfxFootA", "object:/Script/Engine.SoundBase", asset(f"{FOOT}/Rock_Mono_01")),
        var("SfxFootB", "object:/Script/Engine.SoundBase", asset(f"{FOOT}/Rock_Mono_03")),
        var("SfxStaffA", "object:/Script/Engine.SoundBase", asset(f"{FOLEY}/SFX_WalkingAid_Tap_Gravel_01")),
        var("SfxStaffB", "object:/Script/Engine.SoundBase", asset(f"{FOLEY}/SFX_WalkingAid_Tap_Gravel_03")),
        var("SfxBreathLoop", "object:/Script/Engine.SoundBase"),
        var("BreathComp", "object:/Script/Engine.AudioComponent"),
        var("ArmLength", "float", "280.0"), var("ArmLagSpeed", "float", "6.0"),
        var("EyeForward", "float", "0.0"), var("EyeHeight", "float", "64.0"),
    ]
    functions = [
        fn("StartAnimDriver"), fn("UpdateAnim"), fn("EnterLoco"), fn("PlaySupportedIdle"), fn("PlayTransmit"),
        fn("PrepareHidden"), fn("ConfigureCamera"),
        fn("EnterCapsule", [("Location", "vector"), ("Rotation", "rotator")]), fn("GripRim"),
        fn("StandAt", [("Location", "vector"), ("Rotation", "rotator")]),
        fn("StartWalk"), fn("StopWalk"), fn("FindRoad"), fn("CheckTether"), fn("PlayFootstep"),
        fn("Move", [("Left / Right", "double"), ("Forward / Backward", "double")]),
    ]

    # StartAnimDriver: loco + the 0.1 s driver (as before), the camera, and the one-time hidden start
    g = G("StartAnimDriver")
    # keep SupportedIdle when this runs again on possession (the lean holds until the player moves)
    keep = g.branch(g.f("NotEqual_NameName", A=g.get("AnimMode"), B="SupportedIdle"))
    g.do("EnterLoco")
    g.pending.append((keep, "else"))
    g.timer("UpdateAnim", g.get("AnimInterval"), True, store="AnimTimer")
    g.do("ConfigureCamera")
    br = g.branch(g.get("bStartHidden"))
    g.do("PrepareHidden")
    graphs.append(g.spec())

    def play(name, anim, loop, mode):
        g = G(name)
        m = comp(g, SKM, "Skeletal Mesh Component")
        g.do("PlayAnimation", SKM, {"NewAnimToPlay": asset(f"{ANIMS}/{anim}"), "bLooping": loop}, target=m)
        g.set("AnimMode", mode)
        return g.spec()

    graphs.append(play("EnterLoco", "BS_Traveller_Locomotion", True, "Loco"))
    graphs.append(play("PlaySupportedIdle", "A_Traveller_SupportedIdle", True, "SupportedIdle"))
    graphs.append(play("PlayTransmit", "A_Traveller_Transmit", False, "Transmit"))

    # UpdateAnim: the blend-space position = speed (Rest 0 .. SlowWalk 110, RateScale 5 in the asset);
    # SupportedIdle hands over to Loco once the player moves; footsteps by distance walked.
    g = G("UpdateAnim")
    speed = g.f("VSizeXY", A=g.ret("GetVelocity", ACTOR, target=g.me()))
    is_loco = g.f("EqualEqual_NameName", A=g.get("AnimMode"), B="Loco")
    br_loco = g.branch(is_loco)
    m = comp(g, SKM, "Skeletal Mesh Component")
    inst = g.cast("/Script/Engine.AnimSingleNodeInstance", g.ret("GetAnimInstance", SKM, target=m), "Anim Single Node Instance")
    g.do("SetBlendSpacePosition", "/Script/Engine.AnimSingleNodeInstance", {"InPosition": g.vec(speed, 0.0, 0.0)}, target=inst)
    after_loco = list(g.pending)
    g.pending = [(br_loco, "else")]
    br_move = g.branch(g.f("Greater_DoubleDouble", A=speed, B=g.get("MoveCancelSpeed")))
    g.do("EnterLoco")
    g.pending = after_loco + [(br_move, "else")] + g.pending   # the three paths join here
    # footsteps (only while walking)
    br_walk = g.branch(g.get("bWalking"))
    acc = g.f("Add_DoubleDouble", A=g.get("StepAccum"), B=g.f("Multiply_DoubleDouble", A=speed, B=g.get("AnimInterval")))
    g.set("StepAccum", acc)
    br_step = g.branch(g.f("Greater_DoubleDouble", A=g.get("StepAccum"), B=g.get("StepLength")))
    g.set("StepAccum", g.f("Subtract_DoubleDouble", A=g.get("StepAccum"), B=g.get("StepLength")))
    g.do("PlayFootstep")
    graphs.append(g.spec())

    # PrepareHidden: placed in the level hidden, collision off, not falling (the terrain under it streams later)
    g = G("PrepareHidden")
    g.set("bStartHidden", False)
    g.do("SetActorHiddenInGame", ACTOR, {"bNewHidden": True}, target=g.me())
    g.do("SetActorEnableCollision", ACTOR, {"bNewActorEnableCollision": False}, target=g.me())
    movement_mode(g, "MOVE_None")
    graphs.append(g.spec())

    # Third person (2026-09-30): show the whole elder and staff, restore the head,
    # and let camera collision keep the following view outside nearby geometry.
    g = G("ConfigureCamera")
    arm = comp(g, ARM, "Spring Arm Component")
    g.do("SetDoublePropertyByName", KSL, {"Object": arm, "PropertyName": "TargetArmLength", "Value": g.get("ArmLength")})
    g.do("SetBoolPropertyByName", KSL, {"Object": arm, "PropertyName": "bEnableCameraLag", "Value": True})
    g.do("SetDoublePropertyByName", KSL, {"Object": arm, "PropertyName": "CameraLagSpeed", "Value": g.get("ArmLagSpeed")})
    g.do("SetBoolPropertyByName", KSL, {"Object": arm, "PropertyName": "bEnableCameraRotationLag", "Value": False})
    g.do("SetBoolPropertyByName", KSL, {"Object": arm, "PropertyName": "bDoCollisionTest", "Value": True})
    g.do("SetBoolPropertyByName", KSL, {"Object": arm, "PropertyName": "bUsePawnControlRotation", "Value": True})
    g.do("SetVectorPropertyByName", KSL, {"Object": arm, "PropertyName": "SocketOffset", "Value": g.vec(0.0, 35.0, 0.0)})
    g.do("K2_SetRelativeLocation", SCENE, {"NewLocation": g.vec(g.get("EyeForward"), 0.0, g.get("EyeHeight")),
                                            "bSweep": False, "bTeleport": True}, target=arm)
    g.do("SetBoolPropertyByName", KSL, {"Object": g.me(), "PropertyName": "bUseControllerRotationYaw", "Value": False})
    cm = comp(g, CMC, "Character Movement Component")
    g.do("SetBoolPropertyByName", KSL, {"Object": cm, "PropertyName": "bOrientRotationToMovement", "Value": True})
    m = comp(g, SKM, "Skeletal Mesh Component")
    g.do("UnHideBoneByName", SKM, {"BoneName": "Neck"}, target=m)
    graphs.append(g.spec())

    # EnterCapsule(Location, Rotation): lying in the lining, hidden, no collision, no movement
    g = G("EnterCapsule")
    g.do("K2_TeleportTo", ACTOR, {"DestLocation": "entry.Location", "DestRotation": "entry.Rotation"}, target=g.me())
    g.do("SetActorHiddenInGame", ACTOR, {"bNewHidden": True}, target=g.me())
    g.do("SetActorEnableCollision", ACTOR, {"bNewActorEnableCollision": False}, target=g.me())
    movement_mode(g, "MOVE_None")
    graphs.append(g.spec())

    # GripRim: visible inside the capsule, SupportedIdle (the insert only frames the hand on the rim)
    g = G("GripRim")
    g.do("SetActorHiddenInGame", ACTOR, {"bNewHidden": False}, target=g.me())
    g.do("PlaySupportedIdle")
    graphs.append(g.spec())

    # StandAt(Location, Rotation): beside the capsule, a hand on it, leaning; walking allowed
    g = G("StandAt")
    g.do("SetActorEnableCollision", ACTOR, {"bNewActorEnableCollision": True}, target=g.me())
    g.do("K2_TeleportTo", ACTOR, {"DestLocation": "entry.Location", "DestRotation": "entry.Rotation"}, target=g.me())
    g.do("SetActorHiddenInGame", ACTOR, {"bNewHidden": False}, target=g.me())
    movement_mode(g, "MOVE_Walking")
    g.do("PlaySupportedIdle")
    graphs.append(g.spec())

    # StartWalk: 110 cm/s, the road tether, the breath loop
    g = G("StartWalk")
    g.set("bWalking", True)
    g.set("StepAccum", 0.0)
    cm = comp(g, CMC, "Character Movement Component")
    g.do("SetDoublePropertyByName", KSL, {"Object": cm, "PropertyName": "MaxWalkSpeed", "Value": g.get("HumanWalkSpeed")})
    g.do("FindRoad")
    g.timer("CheckTether", g.get("TetherInterval"), True, store="TetherTimer")
    # Repeated start hooks keep the currently playing breath and its cursor.
    # Branch before IsPlaying so an absent component is never dereferenced.
    valid_breath = g.branch(g.ret("IsValid", KSL, {"Object": g.get("BreathComp")}))
    playing_breath = g.branch(g.ret("IsPlaying", AC, target=g.get("BreathComp")))
    g.pending = [(valid_breath, "else"), (playing_breath, "else")]
    root = g.ret("K2_GetRootComponent", ACTOR, target=g.me())
    snd = g.call("SpawnSoundAttached", GPS, {"Sound": g.get("SfxBreathLoop"), "AttachToComponent": root,
                 "bStopWhenAttachedToDestroyed": True, "bAutoDestroy": True}, exec_=True)
    g.set("BreathComp", f"{snd}.ReturnValue")
    graphs.append(g.spec())

    # StopWalk: the hand goes on the mark; the walking breath stops (storyline breath rule)
    g = G("StopWalk")
    g.set("bWalking", False)
    g.do("K2_ClearAndInvalidateTimerHandle", KSL, {"Handle": g.get("TetherTimer")})
    cm = comp(g, CMC, "Character Movement Component")
    g.do("StopMovementImmediately", MOVC, target=cm)
    br = g.branch(g.ret("IsValid", KSL, {"Object": g.get("BreathComp")}))
    g.do("FadeOut", AC, {"FadeOutDuration": 0.3, "FadeVolumeLevel": 0.0}, target=g.get("BreathComp"))
    g.pending.append((br, "else"))
    # The auto-destroying component owns its short fade. Release our reference
    # on both branches; repeated StopWalk is harmless and a new start is fresh.
    # An unconnected object input is null; the native setter rejects literal "None".
    g.then(g.node({"set": "BreathComp"}, "clear"))
    graphs.append(g.spec())

    # FindRoad: the same road actor the tether uses
    g = G("FindRoad")
    road = g.xret("GetActorOfClass", GPS, {"ActorClass": ROAD_C})
    br = g.branch(g.ret("IsValid", KSL, {"Object": road}))
    sp = g.cast(SPL, g.ret("GetComponentByClass", ACTOR, {"ComponentClass": SPL}, target=road), "Spline Component")
    g.set("RoadSpline", sp)
    graphs.append(g.spec())

    # CheckTether (0.25 s): more than TetherLimit from the spline -> back onto the road, facing up-road.
    # The V9 blocking volumes (8 m either side) are the soft edge; this is the safety net.
    g = G("CheckTether")
    br = g.branch(g.ret("IsValid", KSL, {"Object": g.get("RoadSpline")}))
    here = g.ret("K2_GetActorLocation", ACTOR, target=g.me())
    key = g.ret("FindInputKeyClosestToWorldLocation", SPL, {"WorldLocation": here}, target=g.get("RoadSpline"))
    onroad = g.ret("GetLocationAtSplineInputKey", SPL, {"InKey": key, "CoordinateSpace": "World"}, target=g.get("RoadSpline"))
    far = g.f("Greater_DoubleDouble", A=g.f("Vector_Distance2D", V1=here, V2=onroad), B=g.get("TetherLimit"))
    g.branch(far)
    dist = g.ret("GetDistanceAlongSplineAtSplineInputKey", SPL, {"InKey": key}, target=g.get("RoadSpline"))
    ahead_d = g.f("FMax", A=g.f("Subtract_DoubleDouble", A=dist, B=300.0), B=0.0)
    ahead = g.ret("GetLocationAtDistanceAlongSpline", SPL, {"Distance": ahead_d, "CoordinateSpace": "World"}, target=g.get("RoadSpline"))
    yaw = g.call("BreakRotator", KML, {"InRot": g.f("Conv_VectorToRotator", InVec=g.f("Subtract_VectorVector", A=ahead, B=onroad))})
    rot = g.f("MakeRotator", Roll=0.0, Pitch=0.0, Yaw=f"{yaw}.Yaw")
    dest = g.f("Add_VectorVector", A=onroad, B=g.vec(0.0, 0.0, g.get("HalfHeight")))
    g.do("K2_TeleportTo", ACTOR, {"DestLocation": dest, "DestRotation": rot}, target=g.me())
    graphs.append(g.spec())

    # PlayFootstep: alternate two rock steps; the staff taps on every second step (the walking aid)
    g = G("PlayFootstep")
    g.set("StepCount", g.f("Add_IntInt", A=g.get("StepCount"), B=1))
    here = g.ret("K2_GetActorLocation", ACTOR, target=g.me())
    feet = g.f("Subtract_VectorVector", A=here, B=g.vec(0.0, 0.0, g.get("HalfHeight")))
    even = g.f("EqualEqual_IntInt", A=g.f("Percent_IntInt", A=g.get("StepCount"), B=2), B=0)
    br = g.branch(even)
    pa = g.do("PlaySoundAtLocation", GPS, {"Sound": g.get("SfxFootA"), "Location": feet, "VolumeMultiplier": g.get("FootVolume"),
                                           "PitchMultiplier": g.f("RandomFloatInRange", Min=0.92, Max=1.06)})
    k_after_a = list(g.pending)
    g.pending = [(br, "else")]
    g.do("PlaySoundAtLocation", GPS, {"Sound": g.get("SfxFootB"), "Location": feet, "VolumeMultiplier": g.get("FootVolume"),
                                      "PitchMultiplier": g.f("RandomFloatInRange", Min=0.92, Max=1.06)})
    g.pending = k_after_a  # the staff only after the A step (every second step)
    staff_at = g.f("Add_VectorVector", A=feet, B=g.f("Multiply_VectorFloat", A=g.ret("GetActorForwardVector", ACTOR, target=g.me()), B=40.0))
    four = g.f("EqualEqual_IntInt", A=g.f("Percent_IntInt", A=g.get("StepCount"), B=4), B=0)
    br4 = g.branch(four)
    g.do("PlaySoundAtLocation", GPS, {"Sound": g.get("SfxStaffA"), "Location": staff_at, "VolumeMultiplier": g.get("StaffVolume"),
                                      "PitchMultiplier": g.f("RandomFloatInRange", Min=0.95, Max=1.05)})
    g.pending = [(br4, "else")]
    g.do("PlaySoundAtLocation", GPS, {"Sound": g.get("SfxStaffB"), "Location": staff_at, "VolumeMultiplier": g.get("StaffVolume"),
                                      "PitchMultiplier": g.f("RandomFloatInRange", Min=0.95, Max=1.05)})
    graphs.append(g.spec())

    # Move (IA_Move from the inherited EventGraph): relative to the camera's yaw, like any third-person walk;
    # orient-to-movement turns the body (the class defaults already have it on, controller yaw off).
    g = G("Move")
    cr = g.call("BreakRotator", KML, {"InRot": g.ret("GetControlRotation", PAWN, target=g.me())})
    flat = g.f("MakeRotator", Roll=0.0, Pitch=0.0, Yaw=f"{cr}.Yaw")
    g.do("AddMovementInput", PAWN, {"WorldDirection": g.f("GetForwardVector", InRot=flat), "ScaleValue": "entry.Forward / Backward"}, target=g.me())
    g.do("AddMovementInput", PAWN, {"WorldDirection": g.f("GetRightVector", InRot=flat), "ScaleValue": "entry.Left / Right"}, target=g.me())
    graphs.append(g.spec())

    return {"asset": TRAV, "description": "The Keeper as a playable pawn for the ending (task ENDING; README_Ending.md). "
            "Built with --reset-graphs: every function graph here is rebuilt; the inherited EventGraph (IA_Move, IA_Look, "
            "BeginPlay -> StartAnimDriver) is not in the spec and stays.",
            "variables": variables, "functions": functions, "graphs": graphs,
            "cdo_defaults": {"AutoPossessAI": "Disabled", "AutoPossessPlayer": "Disabled",
                             "ArmLength": 280.0, "ArmLagSpeed": 6.0,
                             "EyeForward": 0.0, "EyeHeight": 64.0}}


# ============================================================================ BP_Saskarta_Carrier (scoped)

def carrier():
    graphs = []
    variables = [var("Traveller", f"object:{TRAV_C}"), var("CapsuleSocket", "name", "capsule_root"),
                 var("KeeperSideCm", "float", "110.0"), var("InCapsuleLift", "float", "50.0"),
                 var("StandLift", "float", "32.0"), var("SlamDelay", "float", "2.6"),
                 var("SfxHatchHiss", "object:/Script/Engine.SoundBase", asset(f"{CAR_SFX}/SFX_Carrier_Hatch_Open")),
                 var("SfxHatchLatch", "object:/Script/Engine.SoundBase", asset(f"{CAR_SFX}/SFX_Carrier_Hatch_LockRelease")),
                 var("SfxHatchSlam", "object:/Script/Engine.SoundBase", asset(f"{CAR_SFX}/SFX_Carrier_Suspension_Clunk_05")),
                 var("SfxHatchDust", "object:/Script/Engine.SoundBase", asset("/Game/SaskartaGaea/Audio/Environment/SFX_Gravel_Trickle_01"))]
    functions = [fn("SnapToRoad"), fn("FreezeCarrier"), fn("SpawnTravellerInCapsule"), fn("TravellerGripRim"),
                 fn("TravellerStandBeside"), fn("GetTraveller", outputs=[("Result", f"object:{TRAV_C}")], pure=True),
                 fn("PlayCloseHatch"), fn("CloseHatchSlam")]

    # SnapToRoad: in the breach black, onto the spline centre, facing up-road, by the RUNNER's own rule for the
    # sequence origin (USaskartaEventRunner::StartSequence: GetLocationAtSplineInputKey at the closest key, yaw of
    # -GetTangentAtSplineInputKey). CIN_18/19 key the capsule cameras in that origin's frame, so the carrier must face
    # exactly that yaw. The old +-3 m chord straddled spline point 4 (B18 fires 1.96 m past it): 88 deg behind the
    # point, 137 deg after it, so a carrier stopping within 3 m of it turned up to ~25 deg off the origin and the
    # capsule (2.6 m behind the pivot) swung up to ~1 m sideways out of the interior camera (task ENDING-PREP).
    # Z: never below where it stands, +2 cm so the teleport is clear. Over B18's stop window (4,790-4,796) the landscape
    # is 3-19 cm under the spline, so spline + 62 lifts the carrier at most ~20 cm and it settles in the black. The
    # rule is for B18 only: elsewhere the landscape is 11.6 m under to 7.4 m over the spline. The runner's sequence
    # origin takes its Z from the pawn at the stop (RoadCineOrigin), not from the spline.
    g = G("SnapToRoad")
    g.branch(g.ret("IsValid", KSL, {"Object": g.get("RoadSpline")}))
    here = g.ret("K2_GetActorLocation", ACTOR, target=g.me())
    key = g.ret("FindInputKeyClosestToWorldLocation", SPL, {"WorldLocation": here}, target=g.get("RoadSpline"))
    at = g.ret("GetLocationAtSplineInputKey", SPL, {"InKey": key, "CoordinateSpace": "World"}, target=g.get("RoadSpline"))
    tan = g.ret("GetTangentAtSplineInputKey", SPL, {"InKey": key, "CoordinateSpace": "World"}, target=g.get("RoadSpline"))
    br = g.call("BreakRotator", KML, {"InRot": g.f("Conv_VectorToRotator", InVec=g.f("Multiply_VectorFloat", A=tan, B=-1.0))})
    rot = g.f("MakeRotator", Roll=0.0, Pitch=0.0, Yaw=f"{br}.Yaw")
    hv = g.call("BreakVector", KML, {"InVec": here})
    av = g.call("BreakVector", KML, {"InVec": at})
    z = g.f("FMax", A=f"{hv}.Z", B=g.f("Add_DoubleDouble", A=f"{av}.Z", B=62.0))
    dest = g.vec(f"{av}.X", f"{av}.Y", g.f("Add_DoubleDouble", A=z, B=2.0))
    g.do("K2_TeleportTo", ACTOR, {"DestLocation": dest, "DestRotation": rot}, target=g.me())
    graphs.append(g.spec())

    # FreezeCarrier: the runner unlocks input after CIN_18; the dead carrier must not drive in the black
    g = G("FreezeCarrier")
    cm = comp(g, CMC, "Character Movement Component")
    g.do("StopMovementImmediately", MOVC, target=cm)
    g.do("SetMovementMode", CMC, {"NewMovementMode": "MOVE_None"}, target=cm)
    graphs.append(g.spec())

    def socket(g):
        m = comp(g, SKM, "Skeletal Mesh Component")
        return g.ret("GetSocketLocation", SCENE, {"InSocketName": g.get("CapsuleSocket")}, target=m)

    # SpawnTravellerInCapsule: the placed traveller (hidden since BeginPlay) goes into the lining
    g = G("SpawnTravellerInCapsule")
    t = g.cast(TRAV_C, g.xret("GetActorOfClass", GPS, {"ActorClass": TRAV_C}), "BP Saskarta Traveller")
    g.set("Traveller", t)
    sock = socket(g)
    loc = g.f("Add_VectorVector", A=sock, B=g.vec(0.0, 0.0, g.get("InCapsuleLift")))
    g.do("EnterCapsule", TRAV_C, {"Location": loc, "Rotation": g.ret("K2_GetActorRotation", ACTOR, target=g.me())}, target=g.get("Traveller"))
    graphs.append(g.spec())

    g = G("TravellerGripRim")
    g.branch(g.ret("IsValid", KSL, {"Object": g.get("Traveller")}))
    g.do("GripRim", TRAV_C, target=g.get("Traveller"))
    graphs.append(g.spec())

    # TravellerStandBeside: on the capsule's LEFT (the valley side is left at 4,790), facing up-road
    g = G("TravellerStandBeside")
    g.branch(g.ret("IsValid", KSL, {"Object": g.get("Traveller")}))
    sock = socket(g)
    left = g.f("Multiply_VectorFloat", A=g.ret("GetActorRightVector", ACTOR, target=g.me()),
               B=g.f("Multiply_DoubleDouble", A=g.get("KeeperSideCm"), B=-1.0))
    base = g.f("Add_VectorVector", A=sock, B=left)
    here = g.call("BreakVector", KML, {"InVec": g.ret("K2_GetActorLocation", ACTOR, target=g.me())})
    zfix = g.f("Add_DoubleDouble", A=f"{here}.Z", B=g.get("StandLift"))   # carrier centre (~60 up) + 32 = the Keeper's half-height
    bv = g.call("BreakVector", KML, {"InVec": base})
    loc = g.vec(f"{bv}.X", f"{bv}.Y", zfix)
    g.do("StandAt", TRAV_C, {"Location": loc, "Rotation": g.ret("K2_GetActorRotation", ACTOR, target=g.me())}, target=g.get("Traveller"))
    graphs.append(g.spec())

    # PlayCloseHatch (CIN_19 cue, once Samyor is down): the lid shuts by itself, a hiss, and the slam SlamDelay later
    g = G("PlayCloseHatch")
    g.do("PlayClip", args={"Anim": asset(f"{CARRIER_FULL}/A_CarrierFull_CloseHatch"), "Mode": "Shutdown", "bLoop": False})
    g.do("PlaySoundAtLocation", GPS, {"Sound": g.get("SfxHatchHiss"), "Location": socket(g), "VolumeMultiplier": 0.8})
    g.timer("CloseHatchSlam", g.get("SlamDelay"), False)
    graphs.append(g.spec())

    # CloseHatchSlam: the latch clunk, the heavy lid, the dust settling (sound only)
    g = G("CloseHatchSlam")
    for sfx, vol in (("SfxHatchSlam", 1.0), ("SfxHatchLatch", 0.9), ("SfxHatchDust", 0.6)):
        g.do("PlaySoundAtLocation", GPS, {"Sound": g.get(sfx), "Location": socket(g), "VolumeMultiplier": vol})
    graphs.append(g.spec())

    g = G("GetTraveller")
    g.nodes["result"] = {"result": True}
    g.links.append([g.get("Traveller"), "result.Result"])
    g.links.append(["entry.then", "result.execute"])
    graphs.append(g.spec())

    return {"asset": CARRIER, "description": "Scoped ending additions (task ENDING). Build with --reset-graphs together with "
            "BP_Saskarta_Traveller.json (EnterCapsule / GripRim / StandAt are called here). The carrier's other graphs are untouched. "
            "Uses the existing RoadSpline variable and the existing PlayShutdown / PlayOpenHatch.",
            "variables": variables, "functions": functions, "graphs": graphs}


# ============================================================================ BPC_CarrierVision (scoped)

def carrier_vision():
    graphs = []
    functions = [fn("ShowLogLine", [("Line", "text"), ("Result", "name")]), fn("ShowBlack"), fn("HideBlack")]
    g = G("ShowLogLine")
    g.do("TypeLine", BOOTLOG_C, {"Line": "entry.Line", "Result": "entry.Result"}, target=g.get("BootLogWidget"))
    graphs.append(g.spec())
    g = G("ShowBlack")
    b = g.get("BootLogWidget")
    g.do("ClearTerminal", BOOTLOG_C, target=b)
    g.do("SetBlackOpacity", BOOTLOG_C, {"Opacity": 1.0}, target=g.get("BootLogWidget"))
    g.do("SetRenderOpacity", WIDGET, {"InOpacity": 1.0}, target=g.get("BootLogWidget"))
    g.do("SetVisibility", WIDGET, {"InVisibility": "HitTestInvisible"}, target=g.get("BootLogWidget"))
    graphs.append(g.spec())
    g = G("HideBlack")
    g.do("SetVisibility", WIDGET, {"InVisibility": "Collapsed"}, target=g.get("BootLogWidget"))
    g.do("SetVisionWeight", args={"Weight": 0.0})
    graphs.append(g.spec())
    return {"asset": CV, "description": "Scoped ending additions (task ENDING): the collapse and transmission log lines "
            "(RETRO_BOOT.md: ShowLogLine(Line, Result) wraps BootLog.TypeLine) and the black the ending cinematics show and hide.",
            "variables": [], "functions": functions, "graphs": graphs}


# ============================================================================ PC_Saskarta (scoped)

LOG_LINES = {  # hook: (text, result)  RETRO_BOOT.md: OK stamps [ OK ], FAIL stamps [FAIL], NONE stamps nothing
    "Cine_LogCriticalFailure": ("CARRIER 07 - CRITICAL FAILURE", "FAIL"),
    "Cine_LogHandoverSearching": ("HANDOVER - SEARCHING", "NONE"),
    "Cine_LogNoCarrier": ("NO CARRIER AVAILABLE", "FAIL"),
    "Cine_LogLockReleased": ("CAPSULE LOCK - RELEASED", "OK"),
    "Cine_LogTransmissionComplete": ("TRANSMISSION COMPLETE", "OK"),
}


def pc():
    graphs = []
    functions = [fn("Cine_Breach"), fn("Cine_ClearBlack"), fn("Cine_ShowBlack")] + [fn(k) for k in LOG_LINES] + \
                [fn("PossessTraveller"), fn("StartHumanWalk"), fn("StopHumanWalk")]

    for name, cv_fn in (("Cine_Breach", "PlayBreach"), ("Cine_ClearBlack", "HideBlack"), ("Cine_ShowBlack", "ShowBlack")):
        g = G(name)
        g.do(cv_fn, CV_C, target=g.get("CarrierVision"))
        graphs.append(g.spec())
    for name, (text, result) in LOG_LINES.items():
        g = G(name)
        g.do("ShowLogLine", CV_C, {"Line": text, "Result": result}, target=g.get("CarrierVision"))
        graphs.append(g.spec())

    # PossessTraveller: make sure the Keeper stands (a skip jumps past the 15.8 s cue), possess, face up-road
    g = G("PossessTraveller")
    car = g.cast(CARRIER_C, g.ret("K2_GetPawn", CTRL, target=g.me()), "BP Saskarta Carrier")
    g.do("TravellerStandBeside", CARRIER_C, target=car)
    trav = g.ret("GetTraveller", CARRIER_C, target=car, out="Result")
    g.branch(g.ret("IsValid", KSL, {"Object": trav}))
    g.do("Possess", CTRL, {"InPawn": trav}, target=g.me())
    yaw = g.call("BreakRotator", KML, {"InRot": g.ret("K2_GetActorRotation", ACTOR, target=trav)})
    g.do("SetControlRotation", CTRL, {"NewRotation": g.f("MakeRotator", Roll=0.0, Pitch=-8.0, Yaw=f"{yaw}.Yaw")}, target=g.me())
    g.do("ApplyPlayerFOV")
    graphs.append(g.spec())

    # StartHumanWalk: the carrier tether (breach -> reboot) must not act on the Keeper; the traveller tethers itself
    g = G("StartHumanWalk")
    g.do("StopTether", TETHER_C, target=g.get("RoadTether"))
    t = g.cast(TRAV_C, g.ret("K2_GetPawn", CTRL, target=g.me()), "BP Saskarta Traveller")
    g.do("StartWalk", TRAV_C, target=t)
    graphs.append(g.spec())

    g = G("StopHumanWalk")
    t = g.cast(TRAV_C, g.ret("K2_GetPawn", CTRL, target=g.me()), "BP Saskarta Traveller")
    g.do("StopWalk", TRAV_C, target=t)
    graphs.append(g.spec())

    return {"asset": PC, "description": "Scoped ending additions (task ENDING): the no-parameter hooks story-events.json "
            "calls (CallHook passes no text, so each log line is its own wrapper). Build with --reset-graphs together with "
            "BPC_CarrierVision.ending.json, BP_Saskarta_Carrier.ending.json and BP_Saskarta_Traveller.json. The other PC graphs "
            "are untouched; the pause fix (Human/Transmit) is a separate step in task-ENDING-brief.md.",
            "variables": [], "functions": functions, "graphs": graphs}


# ============================================================================ BP_Saskarta_HighVoice

def high_voice():
    graphs = []
    components = [{"name": "MastBase", "class": SCENE}, {"name": "StandPoint", "class": SCENE},
                  {"name": "SeatPoint", "class": SCENE}, {"name": "Plate", "class": "/Script/Engine.StaticMeshComponent"},
                  {"name": "Crown", "class": "/Script/Engine.StaticMeshComponent"},
                  {"name": "Column", "class": "/Script/Engine.StaticMeshComponent"}]
    variables = [var("CrownMID", f"object:{MID}"), var("GlowTimer", "struct:/Script/Engine.TimerHandle"),
                 var("GlowStart", "float", "0.0"), var("GlowDuration", "float", "8.0"), var("GlowInterval", "float", "0.05"),
                 var("ColRest", "struct:/Script/CoreUObject.LinearColor", "(R=4.0,G=1.8,B=0.6,A=1.0)"),
                 var("ColPeak", "struct:/Script/CoreUObject.LinearColor", "(R=40.0,G=18.0,B=6.0,A=1.0)"),
                 var("ColumnMaxZ", "float", "60.0")]
    functions = [fn("SnapKeeperToPlate"), fn("HideKeeper"), fn("StartGlowAndColumn"), fn("GlowStep"), fn("ResetGlowAndColumn"),
                 fn("EnsureMID")]

    g = G("SnapKeeperToPlate")
    pawn = g.ret("GetPlayerPawn", GPS, {"PlayerIndex": 0})
    sp = g.get("StandPoint")
    g.do("K2_TeleportTo", ACTOR, {"DestLocation": g.ret("K2_GetComponentLocation", SCENE, target=sp),
                                  "DestRotation": g.ret("K2_GetComponentRotation", SCENE, target=g.get("StandPoint"))}, target=pawn)
    graphs.append(g.spec())

    g = G("HideKeeper")
    g.do("SetActorHiddenInGame", ACTOR, {"bNewHidden": True}, target=g.ret("GetPlayerPawn", GPS, {"PlayerIndex": 0}))
    graphs.append(g.spec())

    g = G("EnsureMID")
    br = g.branch(g.f("Not_PreBool", A=g.ret("IsValid", KSL, {"Object": g.get("CrownMID")})))
    g.set("CrownMID", g.xret("CreateDynamicMaterialInstance", PRIM, {"ElementIndex": 0}, target=g.get("Crown")))
    graphs.append(g.spec())

    g = G("StartGlowAndColumn")
    g.do("EnsureMID")
    # The relay answers through its equipment and crown; the sky column was
    # removed from the ending art direction. Keep legacy component hidden.
    g.do("SetVisibility", SCENE, {"bNewVisibility": False}, target=g.get("Column"))
    g.set("GlowStart", g.ret("GetTimeSeconds", GPS))
    g.timer("GlowStep", g.get("GlowInterval"), True, store="GlowTimer")
    graphs.append(g.spec())

    # GlowStep (0.05 s): a practical crown glow, with no sky column.
    g = G("GlowStep")
    a = g.f("FClamp", Value=g.f("Divide_DoubleDouble", A=g.f("Subtract_DoubleDouble", A=g.ret("GetTimeSeconds", GPS), B=g.get("GlowStart")),
                                  B=g.get("GlowDuration")), Min=0.0, Max=1.0)
    s = g.f("FInterpEaseInOut", A=0.0, B=1.0, Alpha=a, Exponent=2.0)
    g.do("SetVectorParameterValue", MID, {"ParameterName": "Col", "Value": g.f("LinearColorLerp", A=g.get("ColRest"), B=g.get("ColPeak"), Alpha=s)},
         target=g.get("CrownMID"))
    g.branch(g.f("GreaterEqual_DoubleDouble", A=a, B=1.0))
    g.do("K2_ClearAndInvalidateTimerHandle", KSL, {"Handle": g.get("GlowTimer")})
    graphs.append(g.spec())

    g = G("ResetGlowAndColumn")
    g.do("K2_ClearAndInvalidateTimerHandle", KSL, {"Handle": g.get("GlowTimer")})
    g.do("SetVisibility", SCENE, {"bNewVisibility": False}, target=g.get("Column"))
    g.do("SetRelativeScale3D", SCENE, {"NewScale3D": g.vec(1.0, 1.0, 0.01)}, target=g.get("Column"))
    g.do("EnsureMID")
    g.do("SetVectorParameterValue", MID, {"ParameterName": "Col", "Value": g.get("ColRest")}, target=g.get("CrownMID"))
    graphs.append(g.spec())

    g = G("EventGraph", entry=False)
    bp = g.node({"event": "ReceiveBeginPlay"}, "bp")
    g.pending = [(bp, "then")]
    g.do("ResetGlowAndColumn")
    graphs.append(g.spec())

    return {"asset": HV, "create": {"parent": ACTOR},
            "description": "The High Voice relay set's logic (V10; task ENDING). Meshes, component transforms and the tag "
            "Saskarta.HighVoice are placed by the V10 step (task-ENDING-brief.md step 6); this spec only adds the components and "
            "the functions CIN_24 calls. Crown material: MI_HighVoice_Glow (parent M_Glow, vector Col).",
            "components": components, "variables": variables, "functions": functions, "graphs": graphs}


def main():
    out = {
        "BP_Saskarta_Traveller.json": traveller(),
        "BP_Saskarta_Carrier.ending.json": carrier(),
        "BPC_CarrierVision.ending.json": carrier_vision(),
        "PC_Saskarta.ending.json": pc(),
        "BP_Saskarta_HighVoice.json": high_voice(),
    }
    for name, spec in out.items():
        (SPECS / name).write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        n = sum(len(g["nodes"]) for g in spec["graphs"])
        print(f"{name}: {len(spec['functions'])} functions, {len(spec['graphs'])} graphs, {n} nodes")


if __name__ == "__main__":
    main()
