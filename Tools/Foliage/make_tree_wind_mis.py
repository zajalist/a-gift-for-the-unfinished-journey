# Give the static tree stand-ins SaskartaWind WPO (world sprint, Task V5 redo, ruling R39).
#
#   node Tools/Foliage/run_foliage.mjs py Tools/Foliage/make_tree_wind_mis.py
#
# MUST NOT run while the ProceduralVegetationEditor engine plugin is unmounted. Both
# MA_Foliage_Trees (the Megaplant master) and M_Saskarta_PlantFoliage depend on its content;
# with it unmounted every Megaplant MI falls back to WorldGridMaterial and anything saved in
# that state loses its references. The script refuses to run in that state.
#
# Why not edit MA_Foliage_Trees itself: it lives in the engine install
# (/ProceduralVegetationEditor/SampleAssets/..., C:/Program Files/Epic Games/UE_5.8), which the
# project never edits (docs/pcg-foliage-pipeline.md). M_Saskarta_PlantFoliage is the project's
# copy of that master, and it already carries the SaskartaWind node (Tools/Foliage/build_wind_nodes.py,
# reading MPC_Saskarta_Wind) beside the player trample. Its collections are MPC_Saskarta_Player and
# MPC_Saskarta_Wind: exactly 2, the limit (task-V4-report.md), and this script adds none.
#
# For each Megaplant MI on a SM_Saskarta_TreeFar_* slot it:
#   1. duplicates the MI to /Game/SaskartaGaea/Foliage/Static/Materials/MI_TreeFar_<name> (the native
#      Megaplant MIs are never changed);
#   2. reparents the copy onto M_Saskarta_PlantFoliage (the copy's master; every MA_Foliage_Trees
#      parameter exists there, checked on 2026-09-27);
#   3. turns the trample off (bend 0, push 0, max offset 0, radius 1 cm) and sets the wind height
#      (TramplePlantHeight doubles as the wind's Height01 scale) and SaskartaWindAmount;
#   4. assigns the copies to the stand-in meshes' slots.
# It does not save: save the MIs and the 9 meshes with Tools/Foliage/save_packages.py.
import unreal

DEST = '/Game/SaskartaGaea/Foliage/Static/Materials'
MASTER = '/Game/SaskartaGaea/Materials/M_Saskarta_PlantFoliage'
SPECIES = ['DeadPine_A', 'DeadPine_B', 'DeadPine_C', 'DeadPine_D', 'DeadPine_E', 'Ginkgo_A', 'Ginkgo_B', 'Ginkgo_C', 'Ginkgo_D']
HEIGHT = {'Dead_Pine': 2000.0, 'Ginkgo': 1200.0}   # cm: sway grows with (z / height)^2
WIND_AMOUNT = 2.0

mel = unreal.MaterialEditingLibrary
eal = unreal.EditorAssetLibrary
if unreal.load_asset('/ProceduralVegetationEditor/SampleAssets/Materials/MasterMaterials/MA_Foliage_Trees') is None:
    raise RuntimeError('ProceduralVegetationEditor is not mounted: enable the plugin and restart the editor first')
master = unreal.load_asset(MASTER)
made = {}
for sp in SPECIES:
    sm = unreal.load_asset('/Game/SaskartaGaea/Foliage/Static/SM_Saskarta_TreeFar_' + sp)
    slots = sm.get_editor_property('static_materials')
    for i in range(len(slots)):
        src = slots[i].get_editor_property('material_interface')
        name = src.get_name()
        if name.startswith('MI_TreeFar_'):
            continue
        if name not in made:
            path = DEST + '/MI_TreeFar_' + name[3:]
            mi = unreal.load_asset(path)
            if mi is None:
                mi = eal.duplicate_asset(src.get_path_name().split('.')[0], path)
            mel.set_material_instance_parent(mi, master)
            h = HEIGHT['Ginkgo'] if 'Ginkgo' in name else HEIGHT['Dead_Pine']
            mel.set_material_instance_scalar_parameter_value(mi, 'TrampleBendStrength', 0.0)
            mel.set_material_instance_scalar_parameter_value(mi, 'TramplePushDown', 0.0)
            mel.set_material_instance_scalar_parameter_value(mi, 'TrampleMaxOffset', 0.0)
            mel.set_material_instance_scalar_parameter_value(mi, 'TrampleRadius', 1.0)
            mel.set_material_instance_scalar_parameter_value(mi, 'TramplePlantHeight', h)
            mel.set_material_instance_scalar_parameter_value(mi, 'SaskartaWindAmount', WIND_AMOUNT)
            mel.update_material_instance(mi)
            made[name] = mi
        sm.set_material(i, made[name])
    print('MESH ' + sp + ' -> ' + str([s.get_editor_property('material_interface').get_name() for s in sm.get_editor_property('static_materials')]))
print('MIS ' + str(sorted([m.get_path_name().split('.')[0] for m in made.values()])))
