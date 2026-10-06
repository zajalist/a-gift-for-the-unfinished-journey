# python_run (Hayba): import the RADIOFX set (Saved/GameAudio/Radio, brief task-RADIOFX) to /Game/SaskartaGaea/Audio/Radio.
# Set CHUNK (0, 1, 2, ...) per call: 3 files per call keeps each run under the 5 s deadline.
import unreal
CHUNK = 0
NAMES = ["AMB_Radio_BetweenStations_Loop", "AMB_Radio_DeadChannel_Loop", "AMB_Radio_Relay_Loop", "AMB_Radio_Static_Crackle_Loop", "AMB_Radio_Static_Heavy_Loop", "AMB_Radio_Static_Soft_Loop", "AMB_Radio_StudioRoom_Loop", "AMB_Radio_WeakSignal_Loop", "SFX_Radio_Dropout_01", "SFX_Radio_Dropout_02", "SFX_Radio_Dropout_03", "SFX_Radio_Dropout_04", "SFX_Radio_Dropout_05", "SFX_Radio_Dropout_06", "SFX_Radio_Knob_Off_01", "SFX_Radio_Knob_Off_02", "SFX_Radio_Knob_Off_03", "SFX_Radio_Knob_On_01", "SFX_Radio_Knob_On_02", "SFX_Radio_Knob_On_03", "SFX_Radio_Lightning_01", "SFX_Radio_Lightning_02", "SFX_Radio_Lightning_03", "SFX_Radio_Lightning_04", "SFX_Radio_Power_Off_Collapse", "SFX_Radio_Power_On_Bloom", "SFX_Radio_Tune_BandScan_01", "SFX_Radio_Tune_Click_01", "SFX_Radio_Tune_Click_02", "SFX_Radio_Tune_Click_03", "SFX_Radio_Tune_Click_04", "SFX_Radio_Tune_Sweep_01", "SFX_Radio_Tune_Sweep_02", "SFX_Radio_Tune_Sweep_03", "SFX_Radio_Tune_Sweep_04", "SFX_Radio_Tune_Sweep_05", ]
SRC = unreal.Paths.project_saved_dir() + 'GameAudio/Radio/'
DEST = '/Game/SaskartaGaea/Audio/Radio'
tasks = []
for n in NAMES[CHUNK * 3:(CHUNK + 1) * 3]:
    if unreal.EditorAssetLibrary.does_asset_exist(DEST + '/' + n):
        continue
    t = unreal.AssetImportTask()
    t.set_editor_property('filename', SRC + n + '.wav')
    t.set_editor_property('destination_path', DEST)
    t.set_editor_property('automated', True)
    t.set_editor_property('save', False)
    t.set_editor_property('replace_existing', False)
    tasks.append(t)
unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks(tasks)
done = []
for n in NAMES[CHUNK * 3:(CHUNK + 1) * 3]:
    a = unreal.load_asset(DEST + '/' + n)
    if a is None:
        print('MISSING', n)
        continue
    if n.endswith('_Loop'):
        a.set_editor_property('looping', True)
    unreal.EditorAssetLibrary.save_loaded_asset(a, False)
    done.append(n)
print('chunk', CHUNK, 'of', (len(NAMES) + 2) // 3, 'imported', len(done))
