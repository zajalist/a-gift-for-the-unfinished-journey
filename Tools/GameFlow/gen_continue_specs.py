"""Generate only the PC/vision Continue additions; never contacts the editor.

Build BPC_CarrierVision.continue.json and PC_Saskarta.continue.json together,
then the title tree/graphs from gen_settings_specs.mjs --title-only.
The existing native RestoreFromSave owns pawn, view, flow and checkpoint state.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

SPECS = Path(__file__).resolve().parent / "specs"
GF = "/Game/SaskartaGaea/GameFlow"
KSL = "/Script/Engine.KismetSystemLibrary"
KML = "/Script/Engine.KismetMathLibrary"
GS = "/Script/Engine.GameplayStatics"
WIDGET = "/Script/UMG.Widget"
USERW = "/Script/UMG.UserWidget"
SEQ = "/Script/LevelSequence.LevelSequencePlayer"
VISION = GF + "/BPC_CarrierVision.BPC_CarrierVision_C"


class Graph:
    def __init__(self, name):
        self.data = {"graph": name, "nodes": {"entry": {"entry": True}}, "links": [], "defaults": {}}
        self.tail = ["entry.then"]

    def node(self, name, spec):
        self.data["nodes"][name] = spec
        return name

    def call(self, name, function, cls=None):
        return self.node(name, {"call": function, **({"class": cls} if cls else {})})

    def link(self, source, target):
        self.data["links"].append([source, target])

    def default(self, pin, value):
        self.data["defaults"][pin] = str(value).lower() if isinstance(value, bool) else str(value)

    def step(self, node):
        for source in self.tail:
            self.link(source, node + ".execute")
        self.tail = [node + ".then"]

    def get(self, name):
        node = self.node("get" + name, {"get": name})
        return node + "." + name

    def valid(self, source, prefix):
        self.call(prefix + "Valid", "IsValid", KSL)
        self.node(prefix + "Branch", {"branch": True})
        self.link(source, prefix + "Valid.Object")
        self.link(prefix + "Valid.ReturnValue", prefix + "Branch.Condition")
        self.step(prefix + "Branch")
        return prefix + "Branch.else"

    def finish_valid(self, skipped):
        self.tail.append(skipped)

    def timer_clear(self, field):
        self.call("clear" + field, "K2_ClearAndInvalidateTimerHandle", KSL)
        self.link(self.get(field), "clear" + field + ".Handle")
        self.step("clear" + field)

    def widget_remove(self, field):
        value = self.get(field)
        skip = self.valid(value, field)
        self.call("stop" + field, "StopAllAnimations", USERW)
        self.link(value, "stop" + field + ".self")
        self.step("stop" + field)
        self.call("remove" + field, "RemoveFromParent", WIDGET)
        self.link(value, "remove" + field + ".self")
        self.step("remove" + field)
        self.finish_valid(skip)


def function(name, output=False):
    return {"name": name, "pure": False, "inputs": [],
            "outputs": [{"name": "bRestored", "type": "bool"}] if output else []}


def vision_cleanup():
    g = Graph("RestoreAfterContinue")
    for field in ("LineTimer", "StepTimer", "FadeTimer"):
        g.timer_clear(field)
    for field in ("TitleWidget", "BootLogWidget", "SubtitleWidget"):
        g.widget_remove(field)
    g.call("stopHum", "StopHum")
    g.step("stopHum")
    g.call("cleanVision", "CleanUp")
    g.step("cleanVision")
    return g.data


def continue_game():
    g = Graph("ContinueGame")
    g.node("me", {"self": True})
    g.node("resetRestored", {"set": "bContinueRestored"})
    g.default("resetRestored.bContinueRestored", False)
    g.step("resetRestored")
    g.node("ifTitle", {"branch": True})
    g.call("isTitle", "EqualEqual_NameName", KML)
    g.link(g.get("FlowState"), "isTitle.A")
    g.default("isTitle.B", "Title")
    g.link("isTitle.ReturnValue", "ifTitle.Condition")
    g.step("ifTitle")
    g.node("result", {"result": True})
    g.link(g.get("bContinueRestored"), "result.bRestored")
    g.link("ifTitle.else", "result.execute")

    # Stop the exact title player before native restore sets its final view.
    # No widgets/audio are dismissed until restoration returns true.
    player = g.get("TitleSequencePlayer")
    skip = g.valid(player, "titlePlayer")
    g.call("stopTitle", "Stop", SEQ)
    g.link(player, "stopTitle.self")
    g.step("stopTitle")
    g.finish_valid(skip)
    g.call("restore", "RestoreFromSave", "/Script/SaskartaCore.SaskartaEventLibrary")
    g.link("me.self", "restore.WorldContext")
    g.step("restore")
    g.node("restored", {"branch": True})
    g.link("restore.ReturnValue", "restored.Condition")
    g.step("restored")
    success_tail = list(g.tail)

    g.tail = ["restored.else"]
    skip = g.valid(player, "replayTitle")
    g.call("replay", "PlayLooping", SEQ)
    g.link(player, "replay.self")
    g.default("replay.NumLoops", -1)
    g.step("replay")
    g.finish_valid(skip)
    g.step("result")

    g.tail = success_tail
    for field in ("IntroTimer", "OpeningSkipTimer"):
        g.timer_clear(field)
    music = g.get("TitleMusic")
    skip = g.valid(music, "music")
    g.call("stopMusic", "Stop", "/Script/Engine.AudioComponent")
    g.link(music, "stopMusic.self")
    g.step("stopMusic")
    g.finish_valid(skip)
    vision = g.get("CarrierVision")
    skip = g.valid(vision, "vision")
    g.call("cleanupVision", "RestoreAfterContinue", VISION)
    g.link(vision, "cleanupVision.self")
    g.step("cleanupVision")
    g.finish_valid(skip)
    for field in ("IntroWidget", "LoadingWidget", "EventCardWidget", "HaybaCardWidget"):
        g.widget_remove(field)
    g.call("worldVisible", "SetEnableWorldRendering", GS)
    g.default("worldVisible.bEnable", True)
    g.step("worldVisible")
    g.call("gameInput", "SetInputMode_GameOnly", "/Script/UMG.WidgetBlueprintLibrary")
    g.link("me.self", "gameInput.PlayerController")
    g.default("gameInput.bFlushInput", True)
    g.step("gameInput")
    g.node("cursorOff", {"set": "bShowMouseCursor"})
    g.default("cursorOff.bShowMouseCursor", False)
    g.step("cursorOff")
    # A fresh controller has not run TryGround. Resume the carrier's tether
    # explicitly, while Human restoration keeps it stopped.
    g.call("isHuman", "EqualEqual_NameName", KML)
    g.link("getFlowState.FlowState", "isHuman.A")
    g.default("isHuman.B", "Human")
    g.node("humanFlow", {"branch": True})
    g.link("isHuman.ReturnValue", "humanFlow.Condition")
    g.step("humanFlow")
    human_skip = "humanFlow.then"
    g.tail = ["humanFlow.else"]
    tether = g.get("RoadTether")
    skip = g.valid(tether, "tether")
    g.call("startTether", "StartTether", GF + "/BPC_RoadTether.BPC_RoadTether_C")
    g.link(tether, "startTether.self")
    g.step("startTether")
    g.finish_valid(skip)
    g.tail.append(human_skip)
    g.call("enterPlaying", "EnterPlaying")
    g.step("enterPlaying")
    g.node("success", {"set": "bContinueRestored"})
    g.default("success.bContinueRestored", True)
    g.step("success")
    g.step("result")
    return g.data


def merge_named(items, value, key):
    items[:] = [item for item in items if item[key] != value[key]]
    items.append(value)


def inline(value):
    if isinstance(value, dict):
        return "{ " + ", ".join(json.dumps(key) + ": " + inline(item) for key, item in value.items()) + " }" if value else "{}"
    if isinstance(value, list):
        return "[" + ", ".join(inline(item) for item in value) + "]"
    return json.dumps(value, ensure_ascii=False)


def compact_format(value, indent=""):
    one = inline(value)
    if len(indent) + len(one) <= 150 or not isinstance(value, (dict, list)):
        return one
    child = indent + "  "
    if isinstance(value, list):
        return "[\n" + ",\n".join(child + compact_format(item, child) for item in value) + "\n" + indent + "]"
    return "{\n" + ",\n".join(child + json.dumps(key) + ": " + compact_format(item, child) for key, item in value.items()) + "\n" + indent + "}"


def write(name, data):
    text = compact_format(data) if name == "PC_Saskarta.json" else json.dumps(data, ensure_ascii=False, indent=1 if name == "BPC_CarrierVision.json" else 2)
    (SPECS / name).write_text(text + "\n", encoding="utf-8")


def main():
    pc = json.loads((SPECS / "PC_Saskarta.json").read_text(encoding="utf-8"))
    vision = json.loads((SPECS / "BPC_CarrierVision.json").read_text(encoding="utf-8"))
    title = next(graph for graph in pc["graphs"] if graph["graph"] == "BeginTitle")
    title["nodes"]["cacheTitlePlayer"] = {"set": "TitleSequencePlayer"}
    title["links"] = [edge for edge in title["links"] if edge not in (
        ["castSeqActor.then", "playLoop.execute"],
        ["castSeqActor.then", "cacheTitlePlayer.execute"],
        ["cacheTitlePlayer.then", "playLoop.execute"],
        ["getPlayer.ReturnValue", "cacheTitlePlayer.TitleSequencePlayer"],
    )]
    title["links"] += [
        ["castSeqActor.then", "cacheTitlePlayer.execute"],
        ["getPlayer.ReturnValue", "cacheTitlePlayer.TitleSequencePlayer"],
        ["cacheTitlePlayer.then", "playLoop.execute"],
    ]
    player_var = {"name": "TitleSequencePlayer", "type": "object:/Script/LevelSequence.LevelSequencePlayer"}
    restored_var = {"name": "bContinueRestored", "type": "bool", "default": "false"}
    merge_named(pc.setdefault("variables", []), player_var, "name")
    merge_named(pc["variables"], restored_var, "name")
    merge_named(pc.setdefault("functions", []), function("ContinueGame", True), "name")
    merge_named(pc["graphs"], continue_game(), "graph")
    merge_named(vision.setdefault("functions", []), function("RestoreAfterContinue"), "name")
    merge_named(vision["graphs"], vision_cleanup(), "graph")
    write("PC_Saskarta.json", pc)
    write("BPC_CarrierVision.json", vision)
    write("PC_Saskarta.continue.json", {
        "asset": pc["asset"],
        "description": "Scoped Continue integration: retain title on failure; native restore owns flow, pawn and view. No first-boot or TryGround path.",
        "variables": [player_var, restored_var],
        "functions": [function("BeginTitle"), function("ContinueGame", True)],
        "graphs": [copy.deepcopy(title), continue_game()],
    })
    write("BPC_CarrierVision.continue.json", {
        "asset": vision["asset"],
        "description": "Scoped post-Continue startup overlay cleanup, called only after successful native restoration.",
        "functions": [function("RestoreAfterContinue")],
        "graphs": [vision_cleanup()],
    })
    print("Generated Continue graphs and updated their full PC/vision source specs; no editor calls.")


if __name__ == "__main__":
    main()
