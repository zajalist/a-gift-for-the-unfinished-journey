"""Add only the Caption widget's OnEndCard binding after the scoped end-card spec build.

Run through Hayba python_run with the editor gate held. Existing caption bindings
and function graphs are left in place. Re-running is idempotent.
"""
import unreal

BEL = unreal.BlueprintEditorLibrary
path = '/Game/SaskartaGaea/GameFlow/UI/WBP_Saskarta_Caption'
bp = unreal.load_asset(path)
if not bp:
    raise RuntimeError('Caption widget missing: ' + path)
ge = unreal.BlueprintGraphEditor.get_graph_editor(BEL.find_event_graph(bp))


def title(node):
    return str(BEL.get_node_title(node))


def link(a, b):
    if not a.try_create_connection(b):
        raise RuntimeError('Cannot link ' + str(a.get_pin_name()) + ' -> ' + str(b.get_pin_name()))


nodes = ge.list_all_nodes()
assigns = [n for n in nodes if title(n) == 'Assign On End Card']
previous = [n for n in nodes if title(n) == 'Assign On Skip Progress']
if len(previous) != 1:
    raise RuntimeError('Expected the existing OnSkipProgress tail binding')
tail = BEL.find_output_pin(previous[0], 'then')
if not assigns:
    if tail.list_connected_pins():
        raise RuntimeError('OnSkipProgress tail already continues; inspect before appending')
    runner = ge.add_call_function_node('/Script/SaskartaCore.SaskartaEventRunner:GetEventRunner')
    runner_pin = BEL.find_output_pin(runner, 'ReturnValue')
    ge.create_node_from_name('Saskarta|Events|AssignOnEndCard', unreal.Vector2D(600, 2550), [runner_pin])
    assigns = [n for n in ge.list_all_nodes() if title(n) == 'Assign On End Card']
if len(assigns) != 1:
    raise RuntimeError('Expected one OnEndCard assignment')
incoming = BEL.find_input_pin(assigns[0], 'execute')
if not incoming.list_connected_pins():
    if tail.list_connected_pins():
        raise RuntimeError('OnSkipProgress tail is occupied; inspect before repairing OnEndCard')
    link(tail, incoming)

events = [n for n in ge.list_all_nodes() if n.get_class().get_name() == 'K2Node_CustomEvent'
          and title(n) == 'OnEndCard_Event']
if len(events) != 1:
    raise RuntimeError('Expected one generated OnEndCard_Event')
event = events[0]
exec_pin = BEL.find_output_pin(event, 'then')
if not exec_pin.list_connected_pins():
    call = ge.add_call_function_node('ShowEndCard')
    link(exec_pin, BEL.find_input_pin(call, 'execute'))
    link(BEL.find_output_pin(event, 'Id'), BEL.find_input_pin(call, 'Id'))
elif not BEL.find_output_pin(event, 'Id').list_connected_pins():
    raise RuntimeError('OnEndCard event executes without forwarding Id; inspect the existing handler')

BEL.compile_blueprint(bp)
status = str(bp.get_editor_property('status'))
if 'ERROR' in status.upper():
    raise RuntimeError('Caption compile failed: ' + status)
if not unreal.EditorAssetLibrary.save_loaded_asset(bp, False):
    raise RuntimeError('Caption save failed')
print('OnEndCard bound; caption status', status)
