# python_run (Hayba), after ui_build of WBP_Saskarta_Caption.tree.json and the bpgraph build of
# WBP_Saskarta_Caption.graph.json. Builds the EventGraph bindings bpgraph cannot place:
#   Event Construct -> GetEventRunner -> Assign On<Delegate> x8 (chained) -> each generated custom event
#   calls the widget function with the delegate's parameters (OnSubtitleShow breaks FSaskartaSubtitle).
# Set STEP: -1 = remove every function graph and EventGraph node (before a full rebuild),
# 0 = clear and place the assign chain, 1 = wire the handlers, 2 = compile + save.
import re
import unreal
STEP = 0
BEL = unreal.BlueprintEditorLibrary
bp = unreal.load_asset('/Game/SaskartaGaea/GameFlow/UI/WBP_Saskarta_Caption')
ge = unreal.BlueprintGraphEditor.get_graph_editor(BEL.find_event_graph(bp))
DELEGATES = ['OnSubtitleShow', 'OnSubtitleHide', 'OnCaptionShow', 'OnCaptionHide', 'OnPromptShow', 'OnPromptHide', 'OnLetterbox', 'OnSkipProgress']
# handler event -> (widget function, [(event pin, function pin)])
WIRING = {
    'OnSubtitleHide_Event': ('HideSubtitle', []),
    'OnCaptionShow_Event': ('ShowCaption', [('Text', 'Text'), ('Target', 'Target')]),
    'OnCaptionHide_Event': ('HideCaption', [('Target', 'Target')]),
    'OnPromptShow_Event': ('ShowPrompt', [('Text', 'Text')]),
    'OnPromptHide_Event': ('HidePrompt', []),
    'OnLetterbox_Event': ('SetLetterbox', [('bOn', 'bOn'), ('BlendS', 'BlendS')]),
    'OnSkipProgress_Event': ('SetSkipProgress', [('Fraction', 'Fraction')]),
}


def title(n):
    return str(BEL.get_node_title(n))


def link(a, b):
    if not a.try_create_connection(b):
        print('FAIL link', str(a.get_pin_name()), '->', str(b.get_pin_name()))


nodes = ge.list_all_nodes()
if STEP == -1:
    for gname in [str(x.get_name()) for x in BEL.list_graphs(bp)]:
        if gname not in ('EventGraph',):
            BEL.remove_function_graph(bp, gname)
    ge.remove_nodes([n for n in nodes if title(n) not in ('Event PreConstruct', 'Event Construct', 'Event Tick')])
    print('graphs left', str([str(x.get_name()) for x in BEL.list_graphs(bp)]))
elif STEP == 0:
    keep = ('Event PreConstruct', 'Event Construct', 'Event Tick')
    ge.remove_nodes([n for n in nodes if title(n) not in keep])
    construct = [n for n in ge.list_all_nodes() if title(n) == 'Event Construct'][0]
    r = ge.add_call_function_node('/Script/SaskartaCore.SaskartaEventRunner:GetEventRunner')
    rpin = BEL.find_output_pin(r, 'ReturnValue')
    prev = BEL.find_output_pin(construct, 'then')
    y = 0
    for d in DELEGATES:
        a = ge.create_node_from_name('Saskarta|Events|Assign' + d, unreal.Vector2D(600, y), [rpin])
        y += 300
        assign = [n for n in ge.list_all_nodes() if title(n) == 'Assign ' + ' '.join(re.findall('[A-Z][a-z]*', d))]
        print(d, len(assign))
        if assign:
            link(prev, BEL.find_input_pin(assign[0], 'execute'))
            prev = BEL.find_output_pin(assign[0], 'then')
elif STEP == 1:
    events = {re.sub(r'_[0-9]+$', '', title(n)): n for n in nodes if n.get_class().get_name() == 'K2Node_CustomEvent'}
    print('events', str(sorted(events)))
    cls = '/Game/SaskartaGaea/GameFlow/UI/WBP_Saskarta_Caption.WBP_Saskarta_Caption_C:'
    for ev, (fn, pins) in WIRING.items():
        e = events[ev]
        c = ge.add_call_function_node(fn)
        link(BEL.find_output_pin(e, 'then'), BEL.find_input_pin(c, 'execute'))
        for ep, fp in pins:
            link(BEL.find_output_pin(e, ep), BEL.find_input_pin(c, fp))
    e = events['OnSubtitleShow_Event']
    sp = BEL.find_output_pin(e, 'Subtitle')
    names = [x for x in ge.list_available_nodes([sp]) if 'Break' in x and 'Subtitle' in x]
    print('break', str(names))
    brk = ge.create_node_from_name(names[0], unreal.Vector2D(1300, 0), [sp])
    brk = [n for n in ge.list_all_nodes() if n.get_class().get_name() == 'K2Node_BreakStruct'][0]
    c = ge.add_call_function_node('ShowSubtitle')
    link(BEL.find_output_pin(e, 'then'), BEL.find_input_pin(c, 'execute'))
    for f in ('English', 'Saskartan', 'Header', 'Speaker', 'DurationS'):
        link(BEL.find_output_pin(brk, f), BEL.find_input_pin(c, f))
    if not BEL.find_input_pin(brk, 'SaskartaSubtitle').list_connected_pins():
        for p in BEL.list_input_pins(brk):
            link(sp, p)
else:
    BEL.compile_blueprint(bp)
    status = str(bp.get_editor_property('status'))
    if 'ERROR' not in status.upper():
        unreal.EditorAssetLibrary.save_loaded_asset(bp, False)
    print('status', status)
