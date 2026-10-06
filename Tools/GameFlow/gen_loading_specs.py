"""Generate the loading-screen graph specs (Task TITLE, addendum 4: first-start loading cycle).

    python Tools/GameFlow/gen_loading_specs.py          # writes the three spec files below
    python Tools/GameFlow/gen_loading_specs.py --widget-only   # only WBP_Saskarta_Loading.graph.json

Flow after this change: black -> fire intro (the calligraphy card burns in) -> the card burns away
onto the LOADING screen -> the title. The loading screen is a real preload, not a timer:

  phase 1 (road)   the view target is the carrier pawn at the PlayerStart, so World Partition
                   streams the road start and its materials render (PSOs compile) behind the
                   opaque intro card and loading screen. Done when USaskartaReadiness reports every
                   condition met at the pawn (streaming, PCG idle, shader/PSO work 0, textures,
                   grass stable) and RoadMinTime has passed, or at RoadMaxTime.
  phase 2 (title)  the view target is the title camera. Done when every condition is met there,
                   TitleMinTime has passed and the loading screen has been visible LoadMinShown s
                   since the card started to burn away; or at LoadMaxTime after BeginIntro
                   (about 10 s of intro plus 45 s of loading), then it continues anyway and logs
                   what was still pending (DescribeUnmet).
  then             BeginTitle (the title sequence and widget start under the loading screen) and
                   LoadingWidget.FadeOut(LoadFadeTime).

The progress line is 0.5 x the road phase's readiness fraction, then 0.5 + 0.5 x the title's.

Writes:
  Tools/GameFlow/specs/PC_Saskarta.json            (full spec, patched in place)
  Tools/GameFlow/specs/PC_Saskarta.loading.json    (scoped: only the graphs this adds or changes)
  Tools/GameFlow/specs/WBP_Saskarta_Loading.graph.json
Build (editor gate held, never during PIE):
  node Tools/GameFlow/bpgraph.mjs build --port 52342 --reset-graphs \\
      Tools/GameFlow/specs/WBP_Saskarta_Loading.graph.json Tools/GameFlow/specs/PC_Saskarta.loading.json
"""
import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
SPECS = HERE / "specs"
PC = "/Game/SaskartaGaea/GameFlow/PC_Saskarta"
LOADING = "/Game/SaskartaGaea/GameFlow/UI/WBP_Saskarta_Loading"
LOADING_C = LOADING + ".WBP_Saskarta_Loading_C"
INTRO_C = "/Game/SaskartaGaea/GameFlow/UI/WBP_Saskarta_Intro.WBP_Saskarta_Intro_C"
KML = "/Script/Engine.KismetMathLibrary"
KSL = "/Script/Engine.KismetSystemLibrary"
GPS = "/Script/Engine.GameplayStatics"
READY = "/Script/SaskartaCore.SaskartaReadiness"


def call(fn, cls=None):
    return {"call": fn, "class": cls} if cls else {"call": fn}


# ----------------------------------------------------------------------------- loading widget
def loading_widget_spec():
    variables = [
        {"name": "Target", "type": "float", "default": "0.0"},
        {"name": "Shown", "type": "float", "default": "0.0"},
        {"name": "StepTimer", "type": "struct:/Script/Engine.TimerHandle"},
        {"name": "StepInterval", "type": "float", "default": "0.033"},
        {"name": "FillRate", "type": "float", "default": "2.5"},
        {"name": "PulseRate", "type": "float", "default": "1.3"},
        {"name": "bFading", "type": "bool", "default": "false"},
        {"name": "FadeStart", "type": "float", "default": "0.0"},
        {"name": "FadeDur", "type": "float", "default": "1.0"},
    ]
    functions = [
        {"name": "SetProgress", "pure": False, "inputs": [{"name": "Progress", "type": "float"}], "outputs": []},
        {"name": "FadeOut", "pure": False, "inputs": [{"name": "Time", "type": "float"}], "outputs": []},
        {"name": "Step", "pure": False, "inputs": [], "outputs": []},
    ]
    event_graph = {
        "graph": "EventGraph",
        "nodes": {
            "construct": {"event": "Construct"},
            "me": {"self": True},
            "interval": {"get": "StepInterval"},
            "timer": {"timer": True},
            "setTimer": {"set": "StepTimer"},
        },
        "links": [
            ["construct.then", "timer.execute"],
            ["me.self", "timer.Object"],
            ["interval.StepInterval", "timer.Time"],
            ["timer.then", "setTimer.execute"],
            ["timer.ReturnValue", "setTimer.StepTimer"],
        ],
        "defaults": {"timer.FunctionName": "Step", "timer.bLooping": "true"},
    }
    # No KeeperPointCloud_Capture hook here: the C++ USaskartaCaptureGuard (42ee1c1a) turns that capture on
    # while the loading screen is up and off 1.5 s after it goes.
    # Target only ever grows, so the line never runs backwards when a condition flips.
    set_progress = {
        "graph": "SetProgress",
        "nodes": {
            "entry": {"entry": True},
            "clamp": call("FClamp", KML),
            "target": {"get": "Target"},
            "grow": call("FMax", KML),
            "setTarget": {"set": "Target"},
        },
        "links": [
            ["entry.then", "setTarget.execute"],
            ["entry.Progress", "clamp.Value"],
            ["target.Target", "grow.A"],
            ["clamp.ReturnValue", "grow.B"],
            ["grow.ReturnValue", "setTarget.Target"],
        ],
        "defaults": {"clamp.Min": "0.0", "clamp.Max": "1.0"},
    }
    fade_out = {
        "graph": "FadeOut",
        "nodes": {
            "entry": {"entry": True},
            "now": call("GetTimeSeconds", GPS),
            "setFading": {"set": "bFading"},
            "setStart": {"set": "FadeStart"},
            "setDur": {"set": "FadeDur"},
            "setTarget": {"set": "Target"},
        },
        "links": [
            ["entry.then", "setTarget.execute"],
            ["setTarget.then", "setFading.execute"],
            ["setFading.then", "setStart.execute"],
            ["now.ReturnValue", "setStart.FadeStart"],
            ["setStart.then", "setDur.execute"],
            ["entry.Time", "setDur.FadeDur"],
        ],
        "defaults": {"setTarget.Target": "1.0", "setFading.bFading": "true"},
    }
    step = {
        "graph": "Step",
        "nodes": {
            "entry": {"entry": True},
            "me": {"self": True},
            "now": call("GetTimeSeconds", GPS),
            # the line eases toward Target
            "shown": {"get": "Shown"},
            "target": {"get": "Target"},
            "dt": {"get": "StepInterval"},
            "rate": {"get": "FillRate"},
            "ease": call("FInterpTo", KML),
            "setShown": {"set": "Shown"},
            "scale": call("MakeVector2D", KML),
            "fill": {"get": "ProgressFill"},
            "setScale": call("SetRenderScale", "/Script/UMG.Widget"),
            # the ember glow breathes: 0.8 +- 0.2
            "pulseRate": {"get": "PulseRate"},
            "phase": call("Multiply_DoubleDouble", KML),
            "sin": call("Sin", KML),
            "amp": call("Multiply_DoubleDouble", KML),
            "glowOpacity": call("Add_DoubleDouble", KML),
            "glow": {"get": "EmberGlow"},
            "setGlow": call("SetRenderOpacity", "/Script/UMG.Widget"),
            # fade-out and removal
            "fading": {"get": "bFading"},
            "ifFading": {"branch": True},
            "fadeStart": {"get": "FadeStart"},
            "fadeDur": {"get": "FadeDur"},
            "elapsed": call("Subtract_DoubleDouble", KML),
            "safeDur": call("FMax", KML),
            "ratio": call("Divide_DoubleDouble", KML),
            "alpha": call("FClamp", KML),
            "opacity": call("Lerp", KML),
            "setOpacity": call("SetRenderOpacity", "/Script/UMG.Widget"),
            "gone": call("LessEqual_DoubleDouble", KML),
            "ifGone": {"branch": True},
            "stepGet": {"get": "StepTimer"},
            "clearStep": call("K2_ClearAndInvalidateTimerHandle", KSL),
            "remove": call("RemoveFromParent", "/Script/UMG.Widget"),
        },
        "links": [
            ["entry.then", "setShown.execute"],
            ["shown.Shown", "ease.Current"],
            ["target.Target", "ease.Target"],
            ["dt.StepInterval", "ease.DeltaTime"],
            ["rate.FillRate", "ease.InterpSpeed"],
            ["ease.ReturnValue", "setShown.Shown"],
            ["setShown.then", "setScale.execute"],
            ["ease.ReturnValue", "scale.X"],
            ["scale.ReturnValue", "setScale.Scale"],
            ["fill.ProgressFill", "setScale.self"],
            ["setScale.then", "setGlow.execute"],
            ["now.ReturnValue", "phase.A"],
            ["pulseRate.PulseRate", "phase.B"],
            ["phase.ReturnValue", "sin.A"],
            ["sin.ReturnValue", "amp.A"],
            ["amp.ReturnValue", "glowOpacity.A"],
            ["glowOpacity.ReturnValue", "setGlow.InOpacity"],
            ["glow.EmberGlow", "setGlow.self"],
            ["setGlow.then", "ifFading.execute"],
            ["fading.bFading", "ifFading.Condition"],
            ["ifFading.then", "setOpacity.execute"],
            ["now.ReturnValue", "elapsed.A"],
            ["fadeStart.FadeStart", "elapsed.B"],
            ["fadeDur.FadeDur", "safeDur.A"],
            ["elapsed.ReturnValue", "ratio.A"],
            ["safeDur.ReturnValue", "ratio.B"],
            ["ratio.ReturnValue", "alpha.Value"],
            ["alpha.ReturnValue", "opacity.Alpha"],
            ["opacity.ReturnValue", "setOpacity.InOpacity"],
            ["me.self", "setOpacity.self"],
            ["setOpacity.then", "ifGone.execute"],
            ["opacity.ReturnValue", "gone.A"],
            ["gone.ReturnValue", "ifGone.Condition"],
            ["ifGone.then", "clearStep.execute"],
            ["stepGet.StepTimer", "clearStep.Handle"],
            ["clearStep.then", "remove.execute"],
            ["me.self", "remove.self"],
        ],
        "defaults": {
            "scale.Y": "1.0",
            "amp.B": "0.2",
            "glowOpacity.B": "0.8",
            "safeDur.B": "0.001",
            "alpha.Min": "0.0",
            "alpha.Max": "1.0",
            "opacity.A": "1.0",
            "opacity.B": "0.0",
            "gone.B": "0.001",
        },
    }
    from gen_loading_presentation import enhance_widget
    return enhance_widget({
        "asset": LOADING,
        "description": ("First-start loading screen (Task TITLE, addendum 4). PC_Saskarta creates it under the "
                        "intro card in BeginIntro, feeds SetProgress from USaskartaReadiness while it warms the "
                        "road and title views, then calls FadeOut. Widget-owned 30 Hz timer, no Tick. "
                        "Generated by Tools/GameFlow/gen_loading_specs.py."),
        "variables": variables,
        "functions": functions,
        "graphs": [event_graph, set_progress, fade_out, step],
    })


# ----------------------------------------------------------------------------- PC_Saskarta
PC_VARIABLES = [
    {"name": "LoadingWidget", "type": "object:" + LOADING_C},
    {"name": "LoadPhase", "type": "int", "default": "1"},
    {"name": "PhaseStart", "type": "float", "default": "0.0"},
    {"name": "bIntroRevealed", "type": "bool", "default": "false"},
    {"name": "RevealAt", "type": "float", "default": "0.0"},
    {"name": "RoadMinTime", "type": "float", "default": "1.5"},
    {"name": "RoadMaxTime", "type": "float", "default": "20.0"},
    {"name": "TitleMinTime", "type": "float", "default": "2.0"},
    {"name": "LoadMinShown", "type": "float", "default": "12.0"},
    {"name": "LoadMaxTime", "type": "float", "default": "55.0"},
    {"name": "LoadFadeTime", "type": "float", "default": "1.0"},
]
PC_NEW_FUNCTIONS = ["StepIntroCard", "StepCards", "PollRoad", "PollTitle"]
# User's boot order (2026-09-27, final): black -> the fire card (the calligraphy burns, English
# below) -> Tripothon card -> Hayba card -> loading (only as long as needed, at least 12 s, with the
# point-cloud Keeper) -> title. The preload runs behind the cards with world rendering OFF.
PC_VARIABLES += [
    {"name": "EventCardWidget", "type": "object:/Game/SaskartaGaea/GameFlow/UI/WBP_Saskarta_EventCard.WBP_Saskarta_EventCard_C"},
    {"name": "HaybaCardWidget", "type": "object:/Game/SaskartaGaea/GameFlow/UI/WBP_Saskarta_HaybaCard.WBP_Saskarta_HaybaCard_C"},
    {"name": "CardPhase", "type": "int", "default": "0"},
    {"name": "LoadShownAt", "type": "float", "default": "0.0"},
    {"name": "OpeningSkipTimer", "type": "struct:/Script/Engine.TimerHandle"},
    {"name": "OpeningSkipInterval", "type": "float", "default": "0.05"},
    {"name": "bOpeningSkipRequested", "type": "bool", "default": "false"},
    {"name": "SkipRevealBurnTime", "type": "float", "default": "0.25"},
]
PC_NEW_FUNCTIONS += ["PollOpeningSkip", "RequestOpeningSkip"]
# task-TIMING-brief.md + user: burn-away 8 s (was 12 s; user, 2026-09-28); the loading screen now shows at least 12 s (LoadMinShown) after
# the Hayba card; cold cap about 90 s of loading (LoadMaxTime counts from BeginIntro: 24 s fire +
# 12 s cards + ~90 s). LoadMaxTime 180 s since the C++ loading budget (903cb2f1) slices streaming: slower but smooth.
TIMING_DEFAULTS = {"RevealBurnTime": "8.0", "LoadMinShown": "12.0", "LoadMaxTime": "180.0", "RoadMaxTime": "60.0",
                   "TitleMinTime": "2.0", "RoadMinTime": "1.5"}


def patch_begin_intro(g):
    """BeginIntro: the loading widget goes in under the card (Z 450 < 500), the first view is the
    carrier at the road start (phase 1), and the phase clock starts with the intro."""
    n, links, d = g["nodes"], g["links"], g["defaults"]
    n["ignoreMove"] = call("SetIgnoreMoveInput", "/Script/Engine.Controller")
    n["ignoreLook"] = call("SetIgnoreLookInput", "/Script/Engine.Controller")
    links.remove(["freeze.then", "findCamera.execute"])
    links.remove(["castMove.CastFailed", "findCamera.execute"])
    links += [
        ["freeze.then", "ignoreMove.execute"],
        ["castMove.CastFailed", "ignoreMove.execute"],
        ["ignoreMove.then", "ignoreLook.execute"],
        ["ignoreLook.then", "findCamera.execute"],
    ]
    links.append(["me.self", "ignoreMove.self"])
    links.append(["me.self", "ignoreLook.self"])
    d["ignoreMove.bNewMoveInput"] = "true"
    d["ignoreLook.bNewLookInput"] = "true"
    n["makeLoading"] = {"create_widget": LOADING_C}
    n["setLoading"] = {"set": "LoadingWidget"}
    n["addLoading"] = call("AddToViewport", "/Script/UMG.UserWidget")
    n["setPhase"] = {"set": "LoadPhase"}
    n["setPhaseStart"] = {"set": "PhaseStart"}
    links.remove(["findCamera.ReturnValue", "viewCamera.NewViewTarget"])
    links.append(["pawn.ReturnValue", "viewCamera.NewViewTarget"])
    links.remove(["addIntro.then", "uiOnly.execute"])
    links += [
        ["addIntro.then", "makeLoading.execute"],
        ["me.self", "makeLoading.OwningPlayer"],
        ["makeLoading.then", "setLoading.execute"],
        ["makeLoading.ReturnValue", "setLoading.LoadingWidget"],
        ["setLoading.then", "addLoading.execute"],
        ["makeLoading.ReturnValue", "addLoading.self"],
        ["addLoading.then", "uiOnly.execute"],
    ]
    links.remove(["setIntroStart.then", "pollTimer.execute"])
    links += [
        ["setIntroStart.then", "setPhase.execute"],
        ["setPhase.then", "setPhaseStart.execute"],
        ["now.ReturnValue", "setPhaseStart.PhaseStart"],
        ["setPhaseStart.then", "pollTimer.execute"],
    ]
    d["addLoading.ZOrder"] = "450"
    d["setPhase.LoadPhase"] = "1"
    return g


def patch_begin_intro_a7(g):
    """Addendum 7 (the ember-phase lag): the 3D world does not render while the cards play. Addendum 4
    had made the pawn the view target under the opaque fire card, so the road start streamed and
    rendered under it and draws waiting on PSOs stalled the render thread (the ember animation
    stuttered). Now BeginIntro turns world rendering off (UGameplayStatics::SetEnableWorldRendering,
    GameViewportClient->bDisableWorldRendering), keeps the view on the title camera, and starts in
    LoadPhase 0 (the fire card). StepCards (below) starts the credit cards and the road preload
    once the card has burned away onto the static loading screen."""
    n, links, d = g["nodes"], g["links"], g["defaults"]
    if "noWorld" in n:
        return g
    n["noWorld"] = call("SetEnableWorldRendering", GPS)
    d["noWorld.bEnable"] = "false"
    links.remove(["pawn.ReturnValue", "viewCamera.NewViewTarget"])
    links.append(["findCamera.ReturnValue", "viewCamera.NewViewTarget"])
    links.remove(["findCamera.then", "viewCamera.execute"])
    links += [["findCamera.then", "noWorld.execute"], ["noWorld.then", "viewCamera.execute"]]
    d["setPhase.LoadPhase"] = "0"
    return g


def patch_begin_intro_input_guard(g):
    """GameAndUI is needed for the PC key poll; movement and look stay frozen."""
    n, links, d = g["nodes"], g["links"], g["defaults"]
    n.setdefault("ignoreMove", call("SetIgnoreMoveInput", "/Script/Engine.Controller"))
    n.setdefault("ignoreLook", call("SetIgnoreLookInput", "/Script/Engine.Controller"))
    for edge in (["freeze.then", "findCamera.execute"], ["castMove.CastFailed", "findCamera.execute"]):
        if edge in links:
            links.remove(edge)
    wanted = [
        ["freeze.then", "ignoreMove.execute"], ["castMove.CastFailed", "ignoreMove.execute"],
        ["ignoreMove.then", "ignoreLook.execute"], ["ignoreLook.then", "findCamera.execute"],
        ["me.self", "ignoreMove.self"], ["me.self", "ignoreLook.self"],
    ]
    for edge in wanted:
        if edge not in links:
            links.append(edge)
    d["ignoreMove.bNewMoveInput"] = "true"
    d["ignoreLook.bNewLookInput"] = "true"
    return g


EVENT_C = "/Game/SaskartaGaea/GameFlow/UI/WBP_Saskarta_EventCard.WBP_Saskarta_EventCard_C"
HAYBA_C = "/Game/SaskartaGaea/GameFlow/UI/WBP_Saskarta_HaybaCard.WBP_Saskarta_HaybaCard_C"
WIDGET = "/Script/UMG.Widget"
USERW = "/Script/UMG.UserWidget"


def patch_begin_intro_cards(g):
    """BeginIntro adds the two credit cards under the fire card (Z 490 / 480, opaque backdrops,
    their content transparent until PlayCard) and over the loading screen (Z 450)."""
    n, links, d = g["nodes"], g["links"], g["defaults"]
    n["uiOnly"] = call("SetInputMode_GameAndUIEx", "/Script/UMG.WidgetBlueprintLibrary")
    if "makeEvent" in n:
        return g
    n["makeEvent"] = {"create_widget": EVENT_C}
    n["setEvent"] = {"set": "EventCardWidget"}
    n["addEvent"] = call("AddToViewport", USERW)
    n["makeHayba"] = {"create_widget": HAYBA_C}
    n["setHayba"] = {"set": "HaybaCardWidget"}
    n["addHayba"] = call("AddToViewport", USERW)
    n["setCardPhase"] = {"set": "CardPhase"}
    n["openingSkipInterval"] = {"get": "OpeningSkipInterval"}
    n["openingSkipTimer"] = {"timer": True}
    n["setOpeningSkipTimer"] = {"set": "OpeningSkipTimer"}
    links.remove(["addLoading.then", "uiOnly.execute"])
    links += [
        ["addLoading.then", "makeEvent.execute"], ["me.self", "makeEvent.OwningPlayer"],
        ["makeEvent.then", "setEvent.execute"], ["makeEvent.ReturnValue", "setEvent.EventCardWidget"],
        ["setEvent.then", "addEvent.execute"], ["makeEvent.ReturnValue", "addEvent.self"],
        ["addEvent.then", "makeHayba.execute"], ["me.self", "makeHayba.OwningPlayer"],
        ["makeHayba.then", "setHayba.execute"], ["makeHayba.ReturnValue", "setHayba.HaybaCardWidget"],
        ["setHayba.then", "addHayba.execute"], ["makeHayba.ReturnValue", "addHayba.self"],
        ["addHayba.then", "setCardPhase.execute"], ["setCardPhase.then", "uiOnly.execute"],
        ["uiOnly.then", "openingSkipTimer.execute"], ["me.self", "openingSkipTimer.Object"],
        ["openingSkipInterval.OpeningSkipInterval", "openingSkipTimer.Time"],
        ["openingSkipTimer.then", "setOpeningSkipTimer.execute"],
        ["openingSkipTimer.ReturnValue", "setOpeningSkipTimer.OpeningSkipTimer"],
    ]
    d.update({"addEvent.ZOrder": "490", "addHayba.ZOrder": "480", "setCardPhase.CardPhase": "0",
              "openingSkipTimer.FunctionName": "PollOpeningSkip", "openingSkipTimer.bLooping": "true"})
    return g


def patch_loading_hidden_during_cards(g):
    """Keep the loading overlay hidden until the last credit card finishes."""
    n, links, d = g["nodes"], g["links"], g["defaults"]
    n["loadingHidden"] = call("SetVisibility", WIDGET)
    old = ["addLoading.then", "makeEvent.execute"]
    if old in links:
        links.remove(old)
    for edge in (["addLoading.then", "loadingHidden.execute"],
                 ["makeLoading.ReturnValue", "loadingHidden.self"],
                 ["loadingHidden.then", "makeEvent.execute"]):
        if edge not in links:
            links.append(edge)
    d["loadingHidden.InVisibility"] = "Collapsed"
    return g


def patch_opening_skip_timer(g):
    """Keep polling throughout startup, including after the title handoff begins."""
    n, links, d = g["nodes"], g["links"], g["defaults"]
    n["uiOnly"] = call("SetInputMode_GameAndUIEx", "/Script/UMG.WidgetBlueprintLibrary")
    n.setdefault("afterInputMode", {"sequence": 2})
    n.setdefault("openingSkipInterval", {"get": "OpeningSkipInterval"})
    n.setdefault("openingSkipTimer", {"timer": True})
    n.setdefault("setOpeningSkipTimer", {"set": "OpeningSkipTimer"})
    for edge in (["uiOnly.then", "play.execute"], ["uiOnly.then", "openingSkipTimer.execute"]):
        if edge in links:
            links.remove(edge)
    for edge in (["uiOnly.then", "afterInputMode.execute"], ["afterInputMode.then_0", "play.execute"],
                 ["afterInputMode.then_1", "openingSkipTimer.execute"], ["me.self", "openingSkipTimer.Object"],
                 ["openingSkipInterval.OpeningSkipInterval", "openingSkipTimer.Time"],
                 ["openingSkipTimer.then", "setOpeningSkipTimer.execute"],
                 ["openingSkipTimer.ReturnValue", "setOpeningSkipTimer.OpeningSkipTimer"]):
        if edge not in links:
            links.append(edge)
    d.update({"openingSkipTimer.FunctionName": "PollOpeningSkip", "openingSkipTimer.bLooping": "true"})
    return g


def step_cards():
    """StepCards: the card hand-overs, one guarded step per CardPhase (a Sequence of three)."""
    n = {"entry": {"entry": True}, "steps": {"sequence": 3}, "phase": {"get": "CardPhase"},
         "now": call("GetTimeSeconds", GPS), "me": {"self": True}}
    links = [["entry.then", "steps.execute"]]
    d = {}
    # 0 -> 1: the fire card has burned away: the Tripothon card and the road preload
    # (world rendering stays off; streaming and PSO precache run without drawing).
    n.update({
        "is0": call("EqualEqual_IntInt", KML), "revealed": {"get": "bIntroRevealed"},
        "revealAt": {"get": "RevealAt"}, "burnTime": {"get": "RevealBurnTime"}, "burnEnd": call("Add_DoubleDouble", KML),
        "burnt": call("GreaterEqual_DoubleDouble", KML), "go0a": call("BooleanAND", KML), "go0": call("BooleanAND", KML),
        "if0": {"branch": True}, "ev0": {"get": "EventCardWidget"}, "playEvent": call("PlayCard", EVENT_C),
        "pawn": call("K2_GetPawn", "/Script/Engine.Controller"),
        "viewPawn": call("SetViewTargetWithBlend", "/Script/Engine.PlayerController"),
        "setLoad": {"set": "LoadPhase"}, "setPhaseStart": {"set": "PhaseStart"}, "setCard1": {"set": "CardPhase"},
    })
    links += [
        ["phase.CardPhase", "is0.A"], ["revealAt.RevealAt", "burnEnd.A"], ["burnTime.RevealBurnTime", "burnEnd.B"],
        ["now.ReturnValue", "burnt.A"], ["burnEnd.ReturnValue", "burnt.B"], ["is0.ReturnValue", "go0a.A"],
        ["revealed.bIntroRevealed", "go0a.B"], ["go0a.ReturnValue", "go0.A"], ["burnt.ReturnValue", "go0.B"],
        ["steps.then_0", "if0.execute"], ["go0.ReturnValue", "if0.Condition"],
        ["if0.then", "playEvent.execute"], ["ev0.EventCardWidget", "playEvent.self"],
        ["playEvent.then", "viewPawn.execute"], ["me.self", "viewPawn.self"], ["me.self", "pawn.self"],
        ["pawn.ReturnValue", "viewPawn.NewViewTarget"], ["viewPawn.then", "setLoad.execute"],
        ["setLoad.then", "setPhaseStart.execute"], ["now.ReturnValue", "setPhaseStart.PhaseStart"],
        ["setPhaseStart.then", "setCard1.execute"],
    ]
    d.update({"is0.B": "0", "viewPawn.BlendTime": "0.0", "setLoad.LoadPhase": "1", "setCard1.CardPhase": "1"})
    # 1 -> 2: the Tripothon card is done: the Hayba card
    n.update({
        "is1": call("EqualEqual_IntInt", KML), "ev1": {"get": "EventCardWidget"}, "done1": call("IsDone", EVENT_C),
        "go1": call("BooleanAND", KML), "if1": {"branch": True}, "removeEvent": call("RemoveFromParent", WIDGET),
        "hb1": {"get": "HaybaCardWidget"}, "playHayba": call("PlayCard", HAYBA_C), "setCard2": {"set": "CardPhase"},
    })
    links += [
        ["phase.CardPhase", "is1.A"], ["ev1.EventCardWidget", "done1.self"], ["is1.ReturnValue", "go1.A"],
        ["done1.bIsDone", "go1.B"], ["steps.then_1", "if1.execute"], ["go1.ReturnValue", "if1.Condition"],
        ["if1.then", "removeEvent.execute"], ["ev1.EventCardWidget", "removeEvent.self"],
        ["removeEvent.then", "playHayba.execute"], ["hb1.HaybaCardWidget", "playHayba.self"],
        ["playHayba.then", "setCard2.execute"],
    ]
    d.update({"is1.B": "1", "setCard2.CardPhase": "2"})
    # 2 -> 3: the Hayba card is done. Restore the future handoff baseline, then
    # hold main-world rendering behind the opaque car/loading UI in this same call.
    n.update({
        "is2": call("EqualEqual_IntInt", KML), "hb2": {"get": "HaybaCardWidget"}, "done2": call("IsDone", HAYBA_C),
        "go2": call("BooleanAND", KML), "if2": {"branch": True}, "removeHayba": call("RemoveFromParent", WIDGET),
        "world": call("SetEnableWorldRendering", GPS), "setShown": {"set": "LoadShownAt"}, "setCard3": {"set": "CardPhase"},
        "loading": {"get": "LoadingWidget"}, "loadingShown": call("SetVisibility", WIDGET),
        "beginPresentation": call("BeginPresentation", LOADING_C),
        "loadBudget": call("GetLoadingBudget", "/Script/SaskartaCore.SaskartaLoadingBudget"),
        "startupRenderHold": call("SetStartupLoadingScreenVisible", "/Script/SaskartaCore.SaskartaLoadingBudget"),
    })
    links += [
        ["phase.CardPhase", "is2.A"], ["hb2.HaybaCardWidget", "done2.self"], ["is2.ReturnValue", "go2.A"],
        ["done2.bIsDone", "go2.B"], ["steps.then_2", "if2.execute"], ["go2.ReturnValue", "if2.Condition"],
        ["if2.then", "removeHayba.execute"], ["hb2.HaybaCardWidget", "removeHayba.self"],
        ["removeHayba.then", "loadingShown.execute"], ["loading.LoadingWidget", "loadingShown.self"],
        ["loadingShown.then", "beginPresentation.execute"],
        ["loading.LoadingWidget", "beginPresentation.self"],
        ["beginPresentation.then", "world.execute"], ["world.then", "startupRenderHold.execute"],
        ["loadBudget.ReturnValue", "startupRenderHold.self"], ["loading.LoadingWidget", "startupRenderHold.LoadingScreen"],
        ["startupRenderHold.then", "setShown.execute"],
        ["now.ReturnValue", "setShown.LoadShownAt"], ["setShown.then", "setCard3.execute"],
    ]
    d.update({"is2.B": "2", "world.bEnable": "true", "setCard3.CardPhase": "3",
              "loadingShown.InVisibility": "HitTestInvisible", "startupRenderHold.bVisible": "true"})
    missing_nodes = sorted({pin.split('.', 1)[0] for edge in links for pin in edge} - set(n))
    assert not missing_nodes, f'StepCards links reference missing nodes: {missing_nodes}'
    for edge in (["removeHayba.then", "loadingShown.execute"],
                 ["loadingShown.then", "beginPresentation.execute"],
                 ["beginPresentation.then", "world.execute"]):
        assert links.count(edge) == 1, f'StepCards loading reveal edge missing/duplicated: {edge}'
    assert not any(a == "loadingShown.then" and b != "beginPresentation.execute" for a, b in links), \
        'StepCards loading reveal has a bypass around BeginPresentation'
    return {"graph": "StepCards", "nodes": n, "links": links, "defaults": d}


POLL_INTRO = {
    "graph": "PollIntro",
    "nodes": {
        "entry": {"entry": True},
        "card": call("StepIntroCard"),
        "cards": call("StepCards"),
        "cardPhase": {"get": "CardPhase"},
        "loadPhase": {"get": "LoadPhase"},
        "started": call("GreaterEqual_IntInt", KML),
        "ifStarted": {"branch": True},
        "isRoad": call("EqualEqual_IntInt", KML),
        "ifRoad": {"branch": True},
        "road": call("PollRoad"),
        "shown": call("EqualEqual_IntInt", KML),
        "ifShown": {"branch": True},
        "title": call("PollTitle"),
    },
    "links": [
        ["entry.then", "card.execute"],
        ["card.then", "cards.execute"],
        ["cards.then", "ifStarted.execute"],
        ["cardPhase.CardPhase", "started.A"],
        ["started.ReturnValue", "ifStarted.Condition"],
        ["ifStarted.then", "ifRoad.execute"],
        ["loadPhase.LoadPhase", "isRoad.A"],
        ["isRoad.ReturnValue", "ifRoad.Condition"],
        ["ifRoad.then", "road.execute"],
        ["ifRoad.else", "ifShown.execute"],
        ["cardPhase.CardPhase", "shown.A"],
        ["shown.ReturnValue", "ifShown.Condition"],
        ["ifShown.then", "title.execute"],
    ],
    "defaults": {"started.B": "1", "isRoad.B": "1", "shown.B": "3"},
}

# Once the card has burned in (IsHolding: 8 s, or at a skip) it burns away onto the loading screen.
STEP_INTRO_CARD = {
    "graph": "StepIntroCard",
    "nodes": {
        "entry": {"entry": True},
        "revealed": {"get": "bIntroRevealed"},
        "notRevealed": call("Not_PreBool", KML),
        "intro": {"get": "IntroWidget"},
        "holding": call("IsHolding", INTRO_C),
        "due": call("BooleanAND", KML),
        "ifDue": {"branch": True},
        "setRevealed": {"set": "bIntroRevealed"},
        "now": call("GetTimeSeconds", GPS),
        "setRevealAt": {"set": "RevealAt"},
        "reveal": call("RevealIntro"),
    },
    "links": [
        ["entry.then", "ifDue.execute"],
        ["revealed.bIntroRevealed", "notRevealed.A"],
        ["intro.IntroWidget", "holding.self"],
        ["notRevealed.ReturnValue", "due.A"],
        ["holding.bHold", "due.B"],
        ["due.ReturnValue", "ifDue.Condition"],
        ["ifDue.then", "setRevealed.execute"],
        ["setRevealed.then", "setRevealAt.execute"],
        ["now.ReturnValue", "setRevealAt.RevealAt"],
        ["setRevealAt.then", "reveal.execute"],
    ],
    "defaults": {"setRevealed.bIntroRevealed": "true"},
}


POLL_OPENING_SKIP = {
    "graph": "PollOpeningSkip",
    "nodes": {
        "entry": {"entry": True},
        "space": call("IsInputKeyDown", "/Script/Engine.PlayerController"),
        "right": call("IsInputKeyDown", "/Script/Engine.PlayerController"),
        "physicalHeld": call("BooleanOR", KML),
        "requested": {"get": "bOpeningSkipRequested"},
        "active": call("BooleanOR", KML),
        "ifHeld": {"branch": True},
        "flow": {"get": "FlowState"},
        "isNone": call("EqualEqual_NameName", KML),
        "isBooting": call("EqualEqual_NameName", KML),
        "flowSteps": {"sequence": 2},
        "flowBranch": {"branch": True},
        "setRequested": {"set": "bOpeningSkipRequested"},
        "phase": {"get": "CardPhase"},
        "isFire": call("EqualEqual_IntInt", KML),
        "fireBranch": {"branch": True},
        "intro": {"get": "IntroWidget"},
        "skipFire": call("EnterHold", INTRO_C),
        "isEvent": call("EqualEqual_IntInt", KML),
        "eventBranch": {"branch": True},
        "eventCard": {"get": "EventCardWidget"},
        "skipEvent": call("Skip", EVENT_C),
        "isHayba": call("EqualEqual_IntInt", KML),
        "haybaBranch": {"branch": True},
        "hayba": {"get": "HaybaCardWidget"},
        "skipHayba": call("Skip", HAYBA_C),
        "vision": {"get": "CarrierVision"},
        "bootHeld": call("BooleanAND", KML),
        "bootBranch": {"branch": True},
        "skipBoot": call("SkipBoot", "/Game/SaskartaGaea/GameFlow/BPC_CarrierVision.BPC_CarrierVision_C"),
    },
    "links": [
        ["entry.then", "ifHeld.execute"],
        ["physicalHeld.ReturnValue", "active.A"], ["requested.bOpeningSkipRequested", "active.B"],
        ["active.ReturnValue", "ifHeld.Condition"],
        ["space.ReturnValue", "physicalHeld.A"], ["right.ReturnValue", "physicalHeld.B"],
        ["ifHeld.then", "flowSteps.execute"],
        ["flowSteps.then_0", "flowBranch.execute"],
        ["flow.FlowState", "isNone.A"], ["flow.FlowState", "isBooting.A"],
        ["isNone.ReturnValue", "flowBranch.Condition"],
        ["flowBranch.then", "setRequested.execute"],
        ["setRequested.then", "fireBranch.execute"],
        ["phase.CardPhase", "isFire.A"], ["isFire.ReturnValue", "fireBranch.Condition"],
        ["fireBranch.then", "skipFire.execute"], ["intro.IntroWidget", "skipFire.self"],
        ["fireBranch.else", "eventBranch.execute"],
        ["phase.CardPhase", "isEvent.A"], ["isEvent.ReturnValue", "eventBranch.Condition"],
        ["eventBranch.then", "skipEvent.execute"], ["eventCard.EventCardWidget", "skipEvent.self"],
        ["eventBranch.else", "haybaBranch.execute"], ["phase.CardPhase", "isHayba.A"],
        ["isHayba.ReturnValue", "haybaBranch.Condition"],
        ["haybaBranch.then", "skipHayba.execute"], ["hayba.HaybaCardWidget", "skipHayba.self"],
        ["flowSteps.then_1", "bootBranch.execute"],
        ["physicalHeld.ReturnValue", "bootHeld.A"], ["isBooting.ReturnValue", "bootHeld.B"],
        ["bootHeld.ReturnValue", "bootBranch.Condition"],
        ["bootBranch.then", "skipBoot.execute"], ["vision.CarrierVision", "skipBoot.self"],
    ],
    "defaults": {
        "space.Key": "SpaceBar", "right.Key": "Gamepad_FaceButton_Right",
        "isNone.B": "None", "isBooting.B": "Booting", "isFire.B": "0", "isEvent.B": "1", "isHayba.B": "2",
        "setRequested.bOpeningSkipRequested": "true",
    },
}

REQUEST_OPENING_SKIP = {
    "graph": "RequestOpeningSkip",
    "nodes": {"entry": {"entry": True}, "requested": {"set": "bOpeningSkipRequested"}},
    "links": [["entry.then", "requested.execute"]],
    "defaults": {"requested.bOpeningSkipRequested": "true"},
}


def patch_reveal_intro(graph):
    """Shorten only the visual burn-away after an explicit skip request."""
    n, links, d = graph["nodes"], graph["links"], graph["defaults"]
    if "skipBurn" in n:
        return graph
    n.update({
        "skipRequested": {"get": "bOpeningSkipRequested"},
        "skipBurn": {"get": "SkipRevealBurnTime"},
        "duration": call("SelectFloat", KML),
    })
    links.remove(["burnTime.RevealBurnTime", "reveal.BurnTime"])
    links += [
        ["skipRequested.bOpeningSkipRequested", "duration.bPickA"],
        ["skipBurn.SkipRevealBurnTime", "duration.A"],
        ["burnTime.RevealBurnTime", "duration.B"],
        ["duration.ReturnValue", "reveal.BurnTime"],
    ]
    return graph


def patch_poll_road(graph):
    """A skip removes the minimum presentation wait, never the readiness requirement."""
    n, links = graph["nodes"], graph["links"]
    if "skipOrMin" in n:
        return graph
    n["skipRequested"] = {"get": "bOpeningSkipRequested"}
    n["skipOrMin"] = call("BooleanOR", KML)
    links.remove(["pastMin.ReturnValue", "ready.B"])
    links += [["pastMin.ReturnValue", "skipOrMin.A"], ["skipRequested.bOpeningSkipRequested", "skipOrMin.B"],
              ["skipOrMin.ReturnValue", "ready.B"]]
    return graph


def patch_poll_title(graph):
    """Skip time-only waits while preserving all title-camera readiness checks."""
    n, links = graph["nodes"], graph["links"]
    if "skipOrMin" in n:
        return graph
    n["skipRequested"] = {"get": "bOpeningSkipRequested"}
    n["skipOrMin"] = call("BooleanOR", KML)
    n["skipOrShown"] = call("BooleanOR", KML)
    links.remove(["pastMin.ReturnValue", "metAndMin.B"])
    links.remove(["shownLong.ReturnValue", "shown.B"])
    links += [
        ["pastMin.ReturnValue", "skipOrMin.A"], ["skipRequested.bOpeningSkipRequested", "skipOrMin.B"],
        ["skipOrMin.ReturnValue", "metAndMin.B"],
        ["shownLong.ReturnValue", "skipOrShown.A"], ["skipRequested.bOpeningSkipRequested", "skipOrShown.B"],
        ["skipOrShown.ReturnValue", "shown.B"],
    ]
    return graph

POLL_ROAD = {
    "graph": "PollRoad",
    "nodes": {
        "entry": {"entry": True},
        "me": {"self": True},
        "pawn": call("K2_GetPawn", "/Script/Engine.Controller"),
        "pawnLoc": call("K2_GetActorLocation", "/Script/Engine.Actor"),
        "readiness": call("GetReadiness", READY),
        "fraction": call("ComputeFraction", READY),
        "half": call("Multiply_DoubleDouble", KML),
        "loading": {"get": "LoadingWidget"},
        "progress": call("SetProgress", LOADING_C),
        "now": call("GetTimeSeconds", GPS),
        "phaseStart": {"get": "PhaseStart"},
        "elapsed": call("Subtract_DoubleDouble", KML),
        "minTime": {"get": "RoadMinTime"},
        "maxTime": {"get": "RoadMaxTime"},
        "met": call("GreaterEqual_DoubleDouble", KML),
        "pastMin": call("GreaterEqual_DoubleDouble", KML),
        "timedOut": call("GreaterEqual_DoubleDouble", KML),
        "ready": call("BooleanAND", KML),
        "done": call("BooleanOR", KML),
        "ifDone": {"branch": True},
        "ifMet": {"branch": True},
        "unmet": call("DescribeUnmet", READY),
        "warnText": call("Concat_StrStr", "/Script/Engine.KismetStringLibrary"),
        "warn": call("PrintString", KSL),
        "setPhase": {"set": "LoadPhase"},
        "setPhaseStart": {"set": "PhaseStart"},
        "findCam": call("GetActorOfClass", GPS),
        "viewCam": call("SetViewTargetWithBlend", "/Script/Engine.PlayerController"),
    },
    "links": [
        ["entry.then", "readiness.execute"],
        ["me.self", "pawn.self"],
        ["pawn.ReturnValue", "pawnLoc.self"],
        ["pawnLoc.ReturnValue", "readiness.ViewLocation"],
        ["readiness.ReturnValue", "fraction.Readiness"],
        ["fraction.ReturnValue", "half.A"],
        ["readiness.then", "progress.execute"],
        ["loading.LoadingWidget", "progress.self"],
        ["half.ReturnValue", "progress.Progress"],
        ["now.ReturnValue", "elapsed.A"],
        ["phaseStart.PhaseStart", "elapsed.B"],
        ["fraction.ReturnValue", "met.A"],
        ["elapsed.ReturnValue", "pastMin.A"],
        ["minTime.RoadMinTime", "pastMin.B"],
        ["elapsed.ReturnValue", "timedOut.A"],
        ["maxTime.RoadMaxTime", "timedOut.B"],
        ["met.ReturnValue", "ready.A"],
        ["pastMin.ReturnValue", "ready.B"],
        ["ready.ReturnValue", "done.A"],
        ["timedOut.ReturnValue", "done.B"],
        ["progress.then", "ifDone.execute"],
        ["done.ReturnValue", "ifDone.Condition"],
        ["ifDone.then", "ifMet.execute"],
        ["met.ReturnValue", "ifMet.Condition"],
        ["ifMet.then", "setPhase.execute"],
        ["ifMet.else", "warn.execute"],
        ["readiness.ReturnValue", "unmet.Readiness"],
        ["unmet.ReturnValue", "warnText.B"],
        ["warnText.ReturnValue", "warn.InString"],
        ["warn.then", "setPhase.execute"],
        ["setPhase.then", "setPhaseStart.execute"],
        ["now.ReturnValue", "setPhaseStart.PhaseStart"],
        ["setPhaseStart.then", "findCam.execute"],
        ["findCam.then", "viewCam.execute"],
        ["me.self", "viewCam.self"],
        ["findCam.ReturnValue", "viewCam.NewViewTarget"],
    ],
    "defaults": {
        "half.B": "0.5",
        "met.B": "0.999",
        "warnText.A": "Saskarta loading: the road view timed out; still pending: ",
        "warn.bPrintToScreen": "false",
        "warn.bPrintToLog": "true",
        "setPhase.LoadPhase": "2",
        "findCam.ActorClass": "/Script/CinematicCamera.CineCameraActor",
        "viewCam.BlendTime": "0.0",
    },
}

POLL_TITLE = {
    "graph": "PollTitle",
    "nodes": {
        "entry": {"entry": True},
        "me": {"self": True},
        "findCam": call("GetActorOfClass", GPS),
        "camLoc": call("K2_GetActorLocation", "/Script/Engine.Actor"),
        "readiness": call("GetReadiness", READY),
        "fraction": call("ComputeFraction", READY),
        "half": call("Multiply_DoubleDouble", KML),
        "plusHalf": call("Add_DoubleDouble", KML),
        "loading": {"get": "LoadingWidget"},
        "progress": call("SetProgress", LOADING_C),
        "now": call("GetTimeSeconds", GPS),
        "phaseStart": {"get": "PhaseStart"},
        "phaseElapsed": call("Subtract_DoubleDouble", KML),
        "titleMin": {"get": "TitleMinTime"},
        "pastMin": call("GreaterEqual_DoubleDouble", KML),
        "revealAt": {"get": "LoadShownAt"},
        "sinceReveal": call("Subtract_DoubleDouble", KML),
        "minShown": {"get": "LoadMinShown"},
        "shownLong": call("GreaterEqual_DoubleDouble", KML),
        "revealed": {"get": "bIntroRevealed"},
        "shown": call("BooleanAND", KML),
        "met": call("GreaterEqual_DoubleDouble", KML),
        "metAndMin": call("BooleanAND", KML),
        "ready": call("BooleanAND", KML),
        "introStart": {"get": "IntroStart"},
        "total": call("Subtract_DoubleDouble", KML),
        "maxTime": {"get": "LoadMaxTime"},
        "pastMax": call("GreaterEqual_DoubleDouble", KML),
        "timedOut": call("BooleanAND", KML),
        "go": call("BooleanOR", KML),
        "ifGo": {"branch": True},
        "pollGet": {"get": "IntroTimer"},
        "stopPoll": call("K2_ClearAndInvalidateTimerHandle", KSL),
        "ifReady": {"branch": True},
        "unmet": call("DescribeUnmet", READY),
        "warnText": call("Concat_StrStr", "/Script/Engine.KismetStringLibrary"),
        "warn": call("PrintString", KSL),
        "beginTitle": call("BeginTitle"),
        "fadeTime": {"get": "LoadFadeTime"},
        "fade": call("FadeOut", LOADING_C),
    },
    "links": [
        ["entry.then", "findCam.execute"],
        ["findCam.then", "readiness.execute"],
        ["findCam.ReturnValue", "camLoc.self"],
        ["camLoc.ReturnValue", "readiness.ViewLocation"],
        ["readiness.ReturnValue", "fraction.Readiness"],
        ["fraction.ReturnValue", "half.A"],
        ["half.ReturnValue", "plusHalf.A"],
        ["readiness.then", "progress.execute"],
        ["loading.LoadingWidget", "progress.self"],
        ["plusHalf.ReturnValue", "progress.Progress"],
        ["now.ReturnValue", "phaseElapsed.A"],
        ["phaseStart.PhaseStart", "phaseElapsed.B"],
        ["phaseElapsed.ReturnValue", "pastMin.A"],
        ["titleMin.TitleMinTime", "pastMin.B"],
        ["now.ReturnValue", "sinceReveal.A"],
        ["revealAt.LoadShownAt", "sinceReveal.B"],
        ["sinceReveal.ReturnValue", "shownLong.A"],
        ["minShown.LoadMinShown", "shownLong.B"],
        ["revealed.bIntroRevealed", "shown.A"],
        ["shownLong.ReturnValue", "shown.B"],
        ["fraction.ReturnValue", "met.A"],
        ["met.ReturnValue", "metAndMin.A"],
        ["pastMin.ReturnValue", "metAndMin.B"],
        ["metAndMin.ReturnValue", "ready.A"],
        ["shown.ReturnValue", "ready.B"],
        ["now.ReturnValue", "total.A"],
        ["introStart.IntroStart", "total.B"],
        ["total.ReturnValue", "pastMax.A"],
        ["maxTime.LoadMaxTime", "pastMax.B"],
        ["pastMax.ReturnValue", "timedOut.A"],
        ["revealed.bIntroRevealed", "timedOut.B"],
        ["ready.ReturnValue", "go.A"],
        ["timedOut.ReturnValue", "go.B"],
        ["progress.then", "ifGo.execute"],
        ["go.ReturnValue", "ifGo.Condition"],
        ["ifGo.then", "stopPoll.execute"],
        ["pollGet.IntroTimer", "stopPoll.Handle"],
        ["stopPoll.then", "ifReady.execute"],
        ["ready.ReturnValue", "ifReady.Condition"],
        ["ifReady.then", "beginTitle.execute"],
        ["ifReady.else", "warn.execute"],
        ["readiness.ReturnValue", "unmet.Readiness"],
        ["unmet.ReturnValue", "warnText.B"],
        ["warnText.ReturnValue", "warn.InString"],
        ["warn.then", "beginTitle.execute"],
        ["beginTitle.then", "fade.execute"],
        ["loading.LoadingWidget", "fade.self"],
        ["fadeTime.LoadFadeTime", "fade.Time"],
    ],
    "defaults": {
        "findCam.ActorClass": "/Script/CinematicCamera.CineCameraActor",
        "half.B": "0.5",
        "plusHalf.B": "0.5",
        "met.B": "0.999",
        "warnText.A": "Saskarta loading: timed out at the title camera; still pending: ",
        "warn.bPrintToScreen": "false",
        "warn.bPrintToLog": "true",
    },
}


def patch_pc(full):
    from gen_loading_presentation import patch_poll
    names = {v["name"] for v in full["variables"]}
    for v in PC_VARIABLES:
        if v["name"] not in names:
            full["variables"].append(v)
    fnames = {f["name"] for f in full["functions"]}
    for f in PC_NEW_FUNCTIONS:
        if f not in fnames:
            full["functions"].append({"name": f, "pure": False, "inputs": [], "outputs": []})
    graphs = {g["graph"]: g for g in full["graphs"]}
    if "makeLoading" not in graphs["BeginIntro"]["nodes"]:
        patch_begin_intro(graphs["BeginIntro"])
    patch_begin_intro_input_guard(graphs["BeginIntro"])
    patch_begin_intro_a7(graphs["BeginIntro"])
    patch_begin_intro_cards(graphs["BeginIntro"])
    patch_loading_hidden_during_cards(graphs["BeginIntro"])
    patch_opening_skip_timer(graphs["BeginIntro"])
    new = {"PollIntro": POLL_INTRO, "StepIntroCard": STEP_INTRO_CARD, "StepCards": step_cards(),
           "PollRoad": patch_poll_road(POLL_ROAD), "PollTitle": patch_poll_title(POLL_TITLE),
           "PollOpeningSkip": POLL_OPENING_SKIP, "RequestOpeningSkip": REQUEST_OPENING_SKIP}
    patch_reveal_intro(graphs["RevealIntro"])
    for v in full["variables"]:
        if v["name"] in TIMING_DEFAULTS:
            v["default"] = TIMING_DEFAULTS[v["name"]]
    out = []
    for g in full["graphs"]:
        out.append(new.pop(g["graph"], g))
    out += new.values()
    out = [patch_poll(g) if g["graph"] in ("PollRoad", "PollTitle") else g for g in out]
    full["graphs"] = out
    return full


def scoped(full):
    keep = ["BeginIntro", "PollIntro", "StepIntroCard", "StepCards", "PollRoad", "PollTitle",
            "PollOpeningSkip", "RequestOpeningSkip"]
    return {
        "asset": PC,
        "description": ("Scoped rebuild for Task TITLE addendum 4 (generated by gen_loading_specs.py): the loading "
                        "phases between the fire intro and title plus the opening skip poll. Build BPC_CarrierVision.opening_skip.json "
                        "first, then this spec with --reset-graphs and WBP_Saskarta_Loading.graph.json, WBP_Saskarta_Intro.graph.json, "
                        "WBP_Saskarta_EventCard.graph.json and WBP_Saskarta_HaybaCard.graph.json so RequestOpeningSkip is declared. "
                        "PC_Saskarta.json holds the same PC graphs."),
        "variables": full["variables"],
        "functions": [f for f in full["functions"] if f["name"] in keep],
        "graphs": [g for g in full["graphs"] if g["graph"] in keep],
    }


def reveal_scope(full):
    """Only the card-to-Loading handoff; leave every other PC graph untouched."""
    graph = next(g for g in full["graphs"] if g["graph"] == "StepCards")
    needed = {node[key] for node in graph["nodes"].values() for key in ("get", "set") if key in node}
    variables = [v for v in full["variables"] if v["name"] in needed]
    assert {v["name"] for v in variables} == needed, "StepCards references undeclared PC variables"
    functions = [f for f in full["functions"] if f["name"] == "StepCards"]
    assert len(functions) == 1 and graph["nodes"]["beginPresentation"]["call"] == "BeginPresentation"
    return {"asset": PC, "description": "Scoped post-Hayba Loading reveal; one PC graph only.",
            "variables": variables, "functions": functions, "graphs": [graph]}


def fmt(v, indent=""):
    """JSON in the specs' hand style (gen_settings_specs.mjs fmt): a value that fits on one line stays."""
    def inline(x):
        if isinstance(x, list):
            return "[" + ", ".join(inline(y) for y in x) + "]" if x else "[]"
        if isinstance(x, dict):
            if not x:
                return "{}"
            return "{ " + ", ".join(json.dumps(k, ensure_ascii=False) + ": " + inline(y) for k, y in x.items()) + " }"
        return json.dumps(x, ensure_ascii=False)
    one = inline(v)
    if len(indent) + len(one) <= 150 or not isinstance(v, (list, dict)) or not v:
        return one
    nxt = indent + "  "
    if isinstance(v, list):
        return "[\n" + ",\n".join(nxt + fmt(x, nxt) for x in v) + "\n" + indent + "]"
    return ("{\n" + ",\n".join(nxt + json.dumps(k, ensure_ascii=False) + ": " + fmt(x, nxt) for k, x in v.items())
            + "\n" + indent + "}")


def dump(path, obj):
    path.write_text(fmt(obj) + "\n", encoding="utf-8")
    print("wrote", path.relative_to(HERE.parents[1]))


def sync_p3_scope(full):
    """Keep P3's overlapping PC graphs in lockstep with the full controller spec."""
    path = SPECS / "PC_Saskarta.p3.json"
    if not path.exists():
        return
    p3 = json.loads(path.read_text(encoding="utf-8"))
    full_graphs = {graph["graph"]: graph for graph in full["graphs"]}
    for graph in p3["graphs"]:
        source_graph = full_graphs.get(graph["graph"])
        if source_graph is not None:
            graph.clear()
            graph.update(source_graph)
    p3["variables"] = full["variables"]
    dump(path, p3)


def main():
    import sys
    if "--widget-only" in sys.argv:   # leaves PC_Saskarta.json alone (other lanes patch it too)
        dump(SPECS / "WBP_Saskarta_Loading.graph.json", loading_widget_spec())
        return
    full_path = SPECS / "PC_Saskarta.json"
    full = patch_pc(json.loads(full_path.read_text(encoding="utf-8")))
    dump(full_path, full)
    dump(SPECS / "PC_Saskarta.loading.json", scoped(full))
    dump(SPECS / "PC_Saskarta.loading_reveal.json", reveal_scope(full))
    dump(SPECS / "WBP_Saskarta_Loading.graph.json", loading_widget_spec())
    sync_p3_scope(full)


if __name__ == "__main__":
    main()
