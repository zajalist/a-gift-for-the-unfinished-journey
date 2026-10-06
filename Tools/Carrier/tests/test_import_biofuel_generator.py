import importlib.util
from pathlib import Path

from Tools.Look.apply_look import check_banned


MODULE_PATH = Path(__file__).resolve().parents[1] / 'import_biofuel_generator.py'
SPEC = importlib.util.spec_from_file_location('import_biofuel_generator', MODULE_PATH)
biofuel = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(biofuel)


def test_intact_fbx_has_expected_parts_scale_and_shared_material_contract():
    result = biofuel.inspect_archive(biofuel.INTACT_ZIP, biofuel.INTACT_FILES, biofuel.INTACT_PARTS)

    assert result['fbx_version'] == 7400
    assert result['unit_scale'] == 1.0
    assert result['parts'] == 13
    assert result['triangles'] == 9189
    assert result['bounds_cm'] == [44.978, 28.235, 26.697]
    assert {'biofuel_body', 'biofuel_liquid', 'biofuel_glass', 'biofuel_charge07'} <= set(result['materials'])


def test_broken_fbx_includes_separate_ground_spill_and_damaged_material_slots():
    result = biofuel.inspect_archive(biofuel.BROKEN_ZIP, biofuel.BROKEN_FILES, biofuel.BROKEN_PARTS)

    assert result['parts'] == 25
    assert result['triangles'] == 11949
    assert result['bounds_cm'] == [44.978, 45.678, 28.181]
    assert {'spill', 'leak', 'leak_small', 'drop01', 'drop05', 'body_broken'} <= set(biofuel.BROKEN_PARTS)
    assert {'biofuel_spill', 'biofuel_low_fuel', 'biofuel_torn_metal'} <= set(result['materials'])


def test_editor_scripts_compile_and_require_explicit_broken_road_anchor():
    scripts = [
        biofuel.make_editor_script('import-intact'),
        biofuel.make_editor_script('import-broken'),
        biofuel.make_editor_script('build-intact'),
        biofuel.make_editor_script('build-broken'),
        biofuel.make_editor_script('mount'),
    ]
    for index, script in enumerate(scripts):
        compile(script, f'biofuel-editor-{index}', 'exec')
        assert '__' not in script
        check_banned(script)

    import_script = scripts[0]
    assert 'combine_meshes' in import_script and 'False' in import_script
    assert 'convert_scene_unit' in import_script and 'import_uniform_scale' in import_script
    assert 'transform_vertex_to_absolute' in import_script
    assert 'BP_Saskarta_Carrier' in scripts[-1]
    assert 'child_actor_class' in scripts[-1]
    assert 'capsule_root' in scripts[-1]
    assert 'unreal.Vector(*(0.0, 1.312, 1.35))' in scripts[-1]
    assert 'unreal.Vector(0.0075, 0.0075, 0.0075)' in scripts[-1]
    assert 'body_roof_anchor' not in scripts[-1]
    try:
        biofuel.make_editor_script('place-broken')
    except KeyError as error:
        assert error.args == ('origin',)
    else:
        raise AssertionError('road prop script must not choose a world location implicitly')

    place = biofuel.make_editor_script('place-broken', origin=(100.0, 200.0, -300.0, 45.0))
    compile(place, 'biofuel-broken-place', 'exec')
    check_banned(place)
    assert 'No Landscape ground' in place
    assert 'isinstance(pair, unreal.HitResult)' in place
    assert 'WRECK_03' not in place


def test_mount_export_parsers_resolve_exact_scs_node_and_socket():
    assert biofuel.exported_object_references(
        "(USCS_Node'/Game/Carrier:Node_A',USCS_Node'/Game/Carrier:Node_B')") == [
            '/Game/Carrier:Node_A', '/Game/Carrier:Node_B']
    assert biofuel.exported_name("'Biofuel01Assembly'") == 'Biofuel01Assembly'
    assert biofuel.exported_name('Biofuel01Assembly') == 'Biofuel01Assembly'
    assert biofuel.scs_reference_from_export(
        "SimpleConstructionScript'/Game/Carrier.BP_C:SimpleConstructionScript_0'",
        '/Game/Carrier.BP_C') == '/Game/Carrier.BP_C:SimpleConstructionScript_0'
    assert biofuel.MOUNT_SOCKET == 'capsule_root'
    assert biofuel.MOUNT_RELATIVE_LOCATION == (0.0, 1.312, 1.35)
    assert biofuel.MOUNT_RELATIVE_SCALE == 0.0075


def test_road_anchor_reproduces_profiled_first_light_mark_frame_without_selecting_it():
    pose = biofuel.road_anchor(3550.0, -4.0)

    assert pose == (361204.69, 382682.42, -29100.0, 156.0)
    # This is a coordinate conversion check only. The spawn script has no implicit
    # mark/site selection and remains gated on an explicit caller-supplied anchor.
