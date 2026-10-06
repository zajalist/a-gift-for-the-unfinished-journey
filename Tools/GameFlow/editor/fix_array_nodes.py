# python_run (Hayba) after a bpgraph build of CM_Saskarta: Hayba places KismetArrayLibrary calls as plain
# K2Node_CallFunction nodes, whose wildcard pins never take a type ("The type of Target Array is
# undetermined"). This swaps each for the node the editor's own spawner makes (K2Node_CallArrayFunction)
# and relinks it through the schema (TryCreateConnection), which propagates the array type.
import unreal
BEL = unreal.BlueprintEditorLibrary
ASSET = '/Game/SaskartaGaea/GameFlow/Debug/CM_Saskarta'
FUNCS = {'Get': 'Array_Get', 'Length': 'Array_Length', 'Find Item': 'Array_Find'}
bp = unreal.load_asset(ASSET)
swapped = 0
for g in BEL.list_graphs(bp):
    ge = unreal.BlueprintGraphEditor.get_graph_editor(g)
    for node in ge.list_all_nodes():
        if node.get_class().get_name() != 'K2Node_CallFunction':
            continue
        title = str(BEL.get_node_title(node)).strip()
        fn = FUNCS.get(title)
        if fn is None:
            continue
        links = []
        for p in BEL.list_all_pins(node):
            for o in p.list_connected_pins():
                links.append((str(p.get_pin_name()), o))
        new = ge.add_call_function_node('/Script/Engine.KismetArrayLibrary:' + fn)
        BEL.set_node_pos(new, BEL.get_node_pos(node))
        ge.remove_nodes([node])
        links.sort(key=lambda l: 0 if l[0] == 'TargetArray' else 1)
        for name, other in links:
            pin = BEL.find_input_pin(new, name)
            if not pin.is_valid():
                pin = BEL.find_output_pin(new, name)
            if not pin.try_create_connection(other):
                print('FAIL link', str(g.get_name()), fn, name)
        swapped += 1
unreal.BlueprintEditorLibrary.compile_blueprint(bp)
status = str(bp.get_editor_property('status'))
if 'ERROR' not in status.upper():
    unreal.EditorAssetLibrary.save_loaded_asset(bp, False)
print('swapped', swapped, 'status', status)
