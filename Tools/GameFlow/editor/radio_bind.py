# python_run (Hayba), LANE5: after the bpgraph build of WBP_Saskarta_Radio.graph.json, bind the station's
# OnRadioForcedOn / OnRadioForcedOff / OnRadioGlitch to the panel's HandleForcedOn / HandleForcedOff / HandleGlitch.
#   Construct chain ... -> RadioKey.Show -> GetRadioStation -> Assign x3 (chained) -> each custom event calls its handler.
# Set STEP: 0 = place the assign chain, 1 = wire the handlers, 2 = compile + save.
import re
import unreal
STEP = 0
BEL = unreal.BlueprintEditorLibrary
bp = unreal.load_asset('/Game/SaskartaGaea/GameFlow/UI/WBP_Saskarta_Radio')
ge = unreal.BlueprintGraphEditor.get_graph_editor(BEL.find_event_graph(bp))
DELEGATES = ['OnRadioForcedOn', 'OnRadioForcedOff', 'OnRadioGlitch']
WIRING = {
    'OnRadioForcedOn_Event': ('HandleForcedOn', [('BeatId', 'BeatId')]),
    'OnRadioForcedOff_Event': ('HandleForcedOff', [('bRadioOnAfter', 'bRadioOnAfter')]),
    'OnRadioGlitch_Event': ('HandleGlitch', [('Type', 'Type'), ('DurationS', 'DurationS'), ('Intensity', 'Intensity')]),
}


def title(n):
    return str(BEL.get_node_title(n))


def link(a, b):
    if not a.try_create_connection(b):
        print('FAIL link', str(a.get_pin_name()), '->', str(b.get_pin_name()))


nodes = ge.list_all_nodes()
if STEP == 0:
    # the end of the Construct chain: the exec output with no link
    ends = [n for n in nodes if title(n).startswith('Show') and BEL.find_output_pin(n, 'then') is not None
            and not BEL.find_output_pin(n, 'then').list_connected_pins()]
    print('chain end', str([title(n) for n in ends]))
    prev = BEL.find_output_pin(ends[0], 'then')
    r = ge.add_call_function_node('/Script/SaskartaCore.SaskartaRadioStation:GetRadioStation')
    rpin = BEL.find_output_pin(r, 'ReturnValue')
    names = [x for x in ge.list_available_nodes([rpin]) if 'Assign' in x]
    print('assign names', str(names))
    y = 600
    for d in DELEGATES:
        full = [x for x in names if x.endswith('Assign' + d)]
        before = set(str(n.get_name()) for n in ge.list_all_nodes())
        ge.create_node_from_name(full[0], unreal.Vector2D(1400, y), [rpin])
        y += 300
        new = [n for n in ge.list_all_nodes() if str(n.get_name()) not in before and title(n).startswith('Assign')]
        print(d, str(len(new)))
        if new:
            link(prev, BEL.find_input_pin(new[0], 'execute'))
            prev = BEL.find_output_pin(new[0], 'then')
elif STEP == 1:
    events = {title(n): n for n in nodes if n.get_class().get_name() == 'K2Node_CustomEvent'}
    print('events', str(sorted(events)))
    for ev, (fn, pins) in WIRING.items():
        e = events[ev]
        c = ge.add_call_function_node(fn)
        link(BEL.find_output_pin(e, 'then'), BEL.find_input_pin(c, 'execute'))
        for ep, fp in pins:
            link(BEL.find_output_pin(e, ep), BEL.find_input_pin(c, fp))
else:
    BEL.compile_blueprint(bp)
    status = str(bp.get_editor_property('status'))
    if 'ERROR' not in status.upper():
        unreal.EditorAssetLibrary.save_loaded_asset(bp, False)
    print('status', status)
