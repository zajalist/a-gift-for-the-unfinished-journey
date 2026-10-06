"""Add ground following and a robust drive unlock to BP_Saskarta_Carrier (user, 2026-09-27).

    python Tools/GameFlow/gen_carrier_ground.py     # patches Tools/GameFlow/specs/BP_Saskarta_Carrier.json

User: "when going through sloped terrain the car doesnt tilt" and "i dont see the wheels turning".

1. UpdateGround (a 30 Hz timer started in StartAnimDriver; no Tick). The Character capsule stays
   upright, so the MESH follows the ground:
   - line traces down at the four wheel contact points (front +/-55 cm across at +55 cm forward,
     rear at -50 cm), in the actor's frame;
   - pitch = atan2(front - rear, 105 cm), roll = -atan2(right - left, 110 cm), clamped to
     +/-25 and +/-20 deg;
   - GroundRot is interpolated toward that at 8/s (RInterpTo), and the mesh's world rotation
     becomes (the mesh's own yaw -90) composed with (roll, pitch, actor yaw);
   - the mesh's relative Z follows the mean wheel height (clamped +/-30 cm), so the wheels sit on
     the ground instead of the capsule's centre point.
   The first-person camera hangs on the capsule, so it does not roll with the body (no nausea).
2. UpdateAnim: the Off / Shutdown hold no longer freezes a MOVING carrier. If the carrier moves
   faster than MoveThreshold while still in the boot hold (a missed handover), the drive blend
   space plays anyway, so the wheels always turn when the carrier moves.
"""
import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
SPEC = HERE / "specs" / "BP_Saskarta_Carrier.json"
KML = "/Script/Engine.KismetMathLibrary"
KSL = "/Script/Engine.KismetSystemLibrary"
GPS = "/Script/Engine.GameplayStatics"
ACTOR = "/Script/Engine.Actor"
SCENE = "/Script/Engine.SceneComponent"


class G:
    def __init__(self, name):
        self.name, self.nodes, self.links, self.defaults, self.n = name, {}, [], {}, 0

    def add(self, spec, prefix="n"):
        self.n += 1
        k = f"{prefix}{self.n}"
        self.nodes[k] = spec
        return k

    def call(self, fn, cls=None, prefix=None, **defs):
        k = self.add({"call": fn, "class": cls} if cls else {"call": fn}, prefix or fn[0].lower() + fn[1:6])
        for p, v in defs.items():
            self.defaults[f"{k}.{p}"] = str(v)
        return k

    def link(self, a, b):
        self.links.append([a, b])

    def json(self):
        return {"graph": self.name, "nodes": self.nodes, "links": self.links, "defaults": self.defaults}


def update_ground():
    g = G("UpdateGround")
    g.nodes["entry"] = {"entry": True}
    loc = g.call("K2_GetActorLocation", ACTOR, "loc")
    fwd = g.call("GetActorForwardVector", ACTOR, "fwd")
    right = g.call("GetActorRightVector", ACTOR, "right")
    heights = {}
    prev = "entry.then"
    for name, x, y in (("FL", 55.0, -55.0), ("FR", 55.0, 55.0), ("RL", -50.0, -55.0), ("RR", -50.0, 55.0)):
        fx = g.call("Multiply_VectorFloat", KML, "fx", B=x)
        g.link(f"{fwd}.ReturnValue", f"{fx}.A")
        ry = g.call("Multiply_VectorFloat", KML, "ry", B=y)
        g.link(f"{right}.ReturnValue", f"{ry}.A")
        p1 = g.call("Add_VectorVector", KML, "p")
        g.link(f"{loc}.ReturnValue", f"{p1}.A")
        g.link(f"{fx}.ReturnValue", f"{p1}.B")
        p2 = g.call("Add_VectorVector", KML, "p")
        g.link(f"{p1}.ReturnValue", f"{p2}.A")
        g.link(f"{ry}.ReturnValue", f"{p2}.B")
        top = g.call("Add_VectorVector", KML, "top", B="(X=0,Y=0,Z=120)")
        g.link(f"{p2}.ReturnValue", f"{top}.A")
        bot = g.call("Add_VectorVector", KML, "bot", B="(X=0,Y=0,Z=-300)")
        g.link(f"{p2}.ReturnValue", f"{bot}.A")
        tr = g.call("LineTraceSingle", KSL, "trace", TraceChannel="TraceTypeQuery1", bTraceComplex="false",
                    DrawDebugType="None", bIgnoreSelf="true")
        g.link(f"{top}.ReturnValue", f"{tr}.Start")
        g.link(f"{bot}.ReturnValue", f"{tr}.End")
        g.link(prev, f"{tr}.execute")
        prev = f"{tr}.then"
        hit = g.call("BreakHitResult", GPS, "hit")
        g.link(f"{tr}.OutHit", f"{hit}.Hit")
        # a miss (off the landscape) falls back to the probe point's own height minus 60 cm
        fallback = g.call("Subtract_DoubleDouble", KML, "fb", B=60.0)
        pz = g.call("BreakVector", KML, "pz")
        g.link(f"{p2}.ReturnValue", f"{pz}.InVec")
        g.link(f"{pz}.Z", f"{fallback}.A")
        iz = g.call("BreakVector", KML, "iz")
        g.link(f"{hit}.ImpactPoint", f"{iz}.InVec")
        h = g.call("SelectFloat", KML, "h")
        g.link(f"{iz}.Z", f"{h}.A")
        g.link(f"{fallback}.ReturnValue", f"{h}.B")
        g.link(f"{tr}.ReturnValue", f"{h}.bPickA")
        heights[name] = f"{h}.ReturnValue"

    def avg(a, b):
        s = g.call("Add_DoubleDouble", KML, "sum")
        g.link(heights[a], f"{s}.A")
        g.link(heights[b], f"{s}.B")
        m = g.call("Multiply_DoubleDouble", KML, "avg", B=0.5)
        g.link(f"{s}.ReturnValue", f"{m}.A")
        return f"{m}.ReturnValue"

    front, rear, left, rightH = avg("FL", "FR"), avg("RL", "RR"), avg("FL", "RL"), avg("FR", "RR")
    dp = g.call("Subtract_DoubleDouble", KML, "dp")
    g.link(front, f"{dp}.A")
    g.link(rear, f"{dp}.B")
    pitch = g.call("DegAtan2", KML, "pitch", X=105.0)
    g.link(f"{dp}.ReturnValue", f"{pitch}.Y")
    pc = g.call("FClamp", KML, "pclamp", Min=-25.0, Max=25.0)
    g.link(f"{pitch}.ReturnValue", f"{pc}.Value")
    dr = g.call("Subtract_DoubleDouble", KML, "dr")
    g.link(left, f"{dr}.A")          # left - right = -(right - left)
    g.link(rightH, f"{dr}.B")
    roll = g.call("DegAtan2", KML, "roll", X=110.0)
    g.link(f"{dr}.ReturnValue", f"{roll}.Y")
    rc = g.call("FClamp", KML, "rclamp", Min=-20.0, Max=20.0)
    g.link(f"{roll}.ReturnValue", f"{rc}.Value")
    target = g.call("MakeRotator", KML, "target", Yaw=0.0)
    g.link(f"{rc}.ReturnValue", f"{target}.Roll")
    g.link(f"{pc}.ReturnValue", f"{target}.Pitch")
    cur = g.add({"get": "GroundRot"}, "cur")
    interp = g.call("RInterpTo", KML, "interp", DeltaTime=0.033, InterpSpeed=8.0)
    g.link(f"{cur}.GroundRot", f"{interp}.Current")
    g.link(f"{target}.ReturnValue", f"{interp}.Target")
    setRot = g.add({"set": "GroundRot"}, "setRot")
    g.link(f"{interp}.ReturnValue", f"{setRot}.GroundRot")
    g.link(prev, f"{setRot}.execute")
    # world rotation = mesh yaw offset (-90) composed with (roll, pitch, actor yaw)
    ar = g.call("K2_GetActorRotation", ACTOR, "ar")
    arb = g.call("BreakRotator", KML, "arb")
    g.link(f"{ar}.ReturnValue", f"{arb}.InRot")
    grb = g.call("BreakRotator", KML, "grb")
    g.link(f"{setRot}.Output_Get", f"{grb}.InRot")
    tilt = g.call("MakeRotator", KML, "tilt")
    g.link(f"{grb}.Roll", f"{tilt}.Roll")
    g.link(f"{grb}.Pitch", f"{tilt}.Pitch")
    g.link(f"{arb}.Yaw", f"{tilt}.Yaw")
    off = g.call("MakeRotator", KML, "meshYaw", Roll=0.0, Pitch=0.0, Yaw=-90.0)
    comp = g.call("ComposeRotators", KML, "comp")
    g.link(f"{off}.ReturnValue", f"{comp}.A")
    g.link(f"{tilt}.ReturnValue", f"{comp}.B")
    meshAny = g.call("GetComponentByClass", ACTOR, "meshAny", ComponentClass="/Script/Engine.SkeletalMeshComponent")
    mesh = g.add({"cast": "/Script/Engine.SkeletalMeshComponent"}, "mesh")
    g.link(f"{meshAny}.ReturnValue", f"{mesh}.Object")
    g.link(f"{setRot}.then", f"{mesh}.execute")
    setW = g.call("K2_SetWorldRotation", SCENE, "setWorld", bSweep="false", bTeleport="true")
    g.link(f"{mesh}.AsSkeletal Mesh Component", f"{setW}.self")
    g.link(f"{comp}.ReturnValue", f"{setW}.NewRotation")
    g.link(f"{mesh}.then", f"{setW}.execute")
    # mesh height: the mean wheel height relative to the capsule bottom (actor Z - 60), clamped
    s1 = g.call("Add_DoubleDouble", KML, "sum")
    g.link(front, f"{s1}.A")
    g.link(rear, f"{s1}.B")
    mean = g.call("Multiply_DoubleDouble", KML, "mean", B=0.5)
    g.link(f"{s1}.ReturnValue", f"{mean}.A")
    lz = g.call("BreakVector", KML, "lz")
    g.link(f"{loc}.ReturnValue", f"{lz}.InVec")
    bottom = g.call("Subtract_DoubleDouble", KML, "bottom", B=60.0)
    g.link(f"{lz}.Z", f"{bottom}.A")
    dz = g.call("Subtract_DoubleDouble", KML, "dz")
    g.link(f"{mean}.ReturnValue", f"{dz}.A")
    g.link(f"{bottom}.ReturnValue", f"{dz}.B")
    dzc = g.call("FClamp", KML, "dzc", Min=-30.0, Max=30.0)
    g.link(f"{dz}.ReturnValue", f"{dzc}.Value")
    rz = g.call("Add_DoubleDouble", KML, "rz", B=-60.0)
    g.link(f"{dzc}.ReturnValue", f"{rz}.A")
    rel = g.call("MakeVector", KML, "rel", X=0.0, Y=0.0)
    g.link(f"{rz}.ReturnValue", f"{rel}.Z")
    setL = g.call("K2_SetRelativeLocation", SCENE, "setRel", bSweep="false", bTeleport="true")
    g.link(f"{mesh}.AsSkeletal Mesh Component", f"{setL}.self")
    g.link(f"{rel}.ReturnValue", f"{setL}.NewLocation")
    g.link(f"{setW}.then", f"{setL}.execute")
    return g.json()


def patch_update_anim(g):
    """locked = (Off or Shutdown) and not moving."""
    n, links, d = g["nodes"], g["links"], g["defaults"]
    if "moving" in n:
        return
    n["moving"] = {"call": "Greater_DoubleDouble", "class": KML}
    n["thresh"] = {"get": "MoveThreshold"}
    n["still"] = {"call": "Not_PreBool", "class": KML}
    n["lockedStill"] = {"call": "BooleanAND", "class": KML}
    links.remove(["locked.ReturnValue", "ifLocked.Condition"])
    links += [["speed.ReturnValue", "moving.A"], ["thresh.MoveThreshold", "moving.B"], ["moving.ReturnValue", "still.A"],
              ["locked.ReturnValue", "lockedStill.A"], ["still.ReturnValue", "lockedStill.B"],
              ["lockedStill.ReturnValue", "ifLocked.Condition"]]


def patch_start(g):
    n, links, d = g["nodes"], g["links"], g["defaults"]
    if "groundTimer" in n:
        return
    n["groundTimer"] = {"timer": True}
    n["keepGround"] = {"set": "GroundTimer"}
    links.remove(["timer.then", "keep.execute"]) if ["timer.then", "keep.execute"] in links else None
    links += [["timer.then", "keep.execute"]] if ["timer.then", "keep.execute"] not in links else []
    links += [["keep.then", "groundTimer.execute"], ["me.self", "groundTimer.Object"],
              ["groundTimer.then", "keepGround.execute"], ["groundTimer.ReturnValue", "keepGround.GroundTimer"]]
    d.update({"groundTimer.FunctionName": "UpdateGround", "groundTimer.Time": "0.033", "groundTimer.bLooping": "true"})


def main():
    s = json.loads(SPEC.read_text(encoding="utf-8"))
    names = {v["name"] for v in s["variables"]}
    if "GroundRot" not in names:
        s["variables"].append({"name": "GroundRot", "type": "struct:/Script/CoreUObject.Rotator"})
    if "GroundTimer" not in names:
        s["variables"].append({"name": "GroundTimer", "type": "struct:/Script/Engine.TimerHandle"})
    if not any(f["name"] == "UpdateGround" for f in s["functions"]):
        s["functions"].append({"name": "UpdateGround", "inputs": [], "outputs": [], "pure": False})
    graphs = {g["graph"]: g for g in s["graphs"]}
    patch_update_anim(graphs["UpdateAnim"])
    patch_start(graphs["StartAnimDriver"])
    s["graphs"] = [g for g in s["graphs"] if g["graph"] != "UpdateGround"] + [update_ground()]
    SPEC.write_text(json.dumps(s, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print("patched", SPEC.name)


if __name__ == "__main__":
    main()
