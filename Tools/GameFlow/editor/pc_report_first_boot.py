# python_run (Hayba), LANE5: PC_Saskarta.TryGround, after its EnterPlaying, reports the flow event
# FirstBootVisionOnline to the story runner (README_Events.md section 3), so B01 plays CIN_01_DIRECTIVE.
# On a reboot the same report is harmless: B01 is one-shot. Idempotent: skips if the node is there.
import unreal
BEL = unreal.BlueprintEditorLibrary
bp = unreal.load_asset('/Game/SaskartaGaea/GameFlow/PC_Saskarta')
ge = unreal.BlueprintGraphEditor.get_graph_editor(BEL.find_graph(bp, 'TryGround'))
nodes = ge.list_all_nodes()
titles = [str(BEL.get_node_title(n)) for n in nodes]
if any('Report Flow' in t or 'ReportFlow' in t for t in titles):
    print('already there')
else:
    ep = [n for n in nodes if str(BEL.get_node_title(n)) == 'Enter Playing' or str(BEL.get_node_title(n)) == 'EnterPlaying']
    print('enter playing nodes', len(ep))
    rf = ge.add_call_function_node('/Script/SaskartaCore.SaskartaEventLibrary:ReportFlow')
    then = BEL.find_output_pin(ep[0], 'then')
    downstream = then.list_connected_pins()
    print('after EnterPlaying was linked to', len(downstream))
    print('link', then.try_create_connection(BEL.find_input_pin(rf, 'execute')))
    for d in downstream:
        BEL.find_output_pin(rf, 'then').try_create_connection(d)
    print('value', BEL.find_input_pin(rf, 'FlowEvent').set_pin_value('FirstBootVisionOnline'))
BEL.compile_blueprint(bp)
status = str(bp.get_editor_property('status'))
if 'ERROR' not in status.upper():
    unreal.EditorAssetLibrary.save_loaded_asset(bp, False)
print('status', status)
