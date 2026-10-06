# After the radio tree rebuild, resize its existing key prompt call in place.
# Preserve the live station delegate bindings instead of rebuilding the graphs.
import unreal

bp = unreal.load_asset('/Game/SaskartaGaea/GameFlow/UI/WBP_Saskarta_Radio')
bel = unreal.BlueprintEditorLibrary
graph = unreal.BlueprintGraphEditor.get_graph_editor(bel.find_event_graph(bp))
nodes = graph.list_all_nodes()
pins = [bel.find_input_pin(n, 'InIconSize') for n in nodes if str(bel.get_node_title(n)).startswith('Configure')]
if len(pins) != 1 or pins[0] is None:
    raise RuntimeError('expected exactly one radio key Configure call')
print('RADIO_KEY sized=' + str(pins[0].set_pin_value('20.0')))
bindings = [str(bel.get_node_title(n)) for n in nodes if str(bel.get_node_title(n)).startswith('Assign On Radio')]
print('RADIO_BINDINGS ' + str(bindings))
if len(bindings) != 3:
    raise RuntimeError('radio station delegate bindings are incomplete')
radio_class = unreal.load_object(None, '/Game/SaskartaGaea/GameFlow/UI/WBP_Saskarta_Radio.WBP_Saskarta_Radio_C')
defaults = unreal.get_default_object(radio_class)
# Older asset defaults include '(R)' text even though the prompt has its own glyph.
for name, value in [('TextOn', 'ON'), ('TextOff', 'OFF')]:
    defaults.set_editor_property(name, unreal.Text(value))
bel.compile_blueprint(bp)
status = str(bp.get_editor_property('status'))
print('RADIO_WIDGET status=' + status)
if 'ERROR' in status.upper():
    raise RuntimeError('radio widget compile failed')
defaults = unreal.get_default_object(bp.generated_class())
print('RADIO_POWER ' + str(defaults.get_editor_property('TextOn')) + '/' + str(defaults.get_editor_property('TextOff')))
print('RADIO_WIDGET saved=' + str(unreal.EditorAssetLibrary.save_loaded_asset(bp, False)))
