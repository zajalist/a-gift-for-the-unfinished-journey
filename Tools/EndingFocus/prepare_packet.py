"""Offline scoped ending packet. No UE process, GPU, mutation, or tests."""
from pathlib import Path
import hashlib
import json
import datetime

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'Saved/Verification/ending_focus_20261001/packet'

SURVEY = '''import unreal,json
es=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
assert es.get_game_world() is None,'Stop PIE before this read-only survey'
world=es.get_editor_world()
assert world is not None and world.get_name()=='Saskarta_WP'
actors=list(unreal.EditorLevelLibrary.get_all_level_actors())
assert len(actors)<2500,'Load only the exact summit region'
required=('SD_S26_HighVoiceTripo_001','SD_S26_Upgrade_20261001_Transmitter','SD_S26_Upgrade_20261001_Biofuel00','SD_S26_Upgrade_20261001_Biofuel01')
bylabel={}
for actor in actors:
    label=actor.get_actor_label()
    if label.startswith(('SD_S26_HighVoiceTripo_','SD_S26_Upgrade_20261001_')):
        assert label not in bylabel,'Duplicate station actor label'
        bylabel[label]=actor
assert all(label in bylabel for label in required),'Load exact saved station descriptors first'
rows=[]
for label,actor in sorted(bylabel.items()):
    comps=[]
    for comp in actor.get_components_by_class(unreal.StaticMeshComponent):
        mesh=comp.get_editor_property('static_mesh')
        if mesh is None:continue
        box=mesh.get_bounding_box()
        comps.append(dict(name=comp.get_name(),mesh=mesh.get_path_name(),world_pose=comp.get_world_transform().export_text(),local_bounds=[[box.min.x,box.min.y,box.min.z],[box.max.x,box.max.y,box.max.z]],collision=str(comp.get_collision_enabled())))
    rows.append(dict(label=label,actor=actor.get_path_name(),package=actor.get_outermost().get_path_name(),pose=actor.get_actor_transform().export_text(),components=comps))
print('ENDING_FOCUS_STATION_SURVEY '+json.dumps(dict(changed=False,saved=False,actors=rows),separators=(',',':')))
'''


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    if (OUT / 'manifest.json').exists():
        raise SystemExit('Packet already exists; preserve it and use a fresh revision directory')
    post = json.loads((ROOT/'Tools/Cinematics/probe_ending.json').read_text(encoding='utf-8'))['radio_post']
    story = json.loads((ROOT/'docs/story/story-events.json').read_text(encoding='utf-8'))
    beats = {x['id']:x for x in story['beats']}
    route = []
    for name in ('B19_REVEAL','B20_REST_BOULDER','B21_LAST_LOOK_BACK','B22_REST_HANDRAIL','B23_LAST_ENTRY'):
        if name in beats:
            b=beats[name]
            route.append({k:b[k] for k in ('id','distance_m','world','ue_distance_from_p0_m') if k in b})
    sections = dict(status='approved_direction_not_installed',human='Samyor is the capsule passenger',
        locomotion=dict(walk_cm_s=110,braced_cm_s=[20,35],terrain_poll_hz=10,max_traces_per_poll=3,
            brace_hold_s=0.35,stumble_max_s=0.7,recovery_immunity_s=1.5,hitch_pause_threshold_s=0.25),
        sections=[dict(id='exposed_shelf',road_m=[4790,4845],challenge='Readable gusts and sheltered inside line'),
                  dict(id='retaining_ruins',road_m=[4845,4925],challenge='Firm paving versus loose ground'),
                  dict(id='station_approach',road_m=[4925,4990],challenge='Calmer arrival and relay destination')],
        protected_beats=route,protected_station_anchors=post,
        continuous_music='same title-track component and cursor',
        renderer_required='actual trained anisotropic 3D Gaussian data; no fake particle substitute')
    (OUT/'walk_and_station_contract.json').write_text(json.dumps(sections,indent=2)+'\n',encoding='utf-8')
    (OUT/'survey_station.py').write_text(SURVEY,encoding='utf-8')
    sources=[Path(__file__),ROOT/'Tools/EndingFocus/README.md',ROOT/'Tools/EndingFocus/MemoryGaussianDream.ush',
             ROOT/'Tools/GameFlow/gen_ending_specs.py',ROOT/'Tools/GameFlow/gen_first_light_ending.py',
             ROOT/'Tools/Cinematics/probe_ending.json',ROOT/'Tools/Cinematics/ending_staging.py',
             ROOT/'docs/story/story-events.json',ROOT/'docs/story/station.json',
             ROOT/'Plugins/SaskartaCore/Source/SaskartaCore/Private/SaskartaDroneSequence.cpp']
    candidates={
        'station_shell':'Content/SaskartaGaea/Environment/Tripo02/SM_T2_s26_radio_station.uasset',
        'fence':'Content/SaskartaGaea/Environment/Tripo02/SM_T2_s26_fence_panel.uasset',
        'gate':'Content/SaskartaGaea/Environment/Tripo02/SM_T2_s26_gate_open.uasset',
        'transmitter':'Content/SaskartaGaea/Environment/Tripo02/SM_T2_s26_transmitter_cabinet.uasset',
        'biofuel':'Content/SaskartaGaea/Characters/Carrier/Biofuel/Assemblies/BP_Biofuel01_Assembly.uasset',
        'crate_body':'Content/Pallbearer/PolyHaven/wooden_crate_01/wooden_crate_01_2k/StaticMeshes/wooden_crate_01.uasset',
        'crate_lid':'Content/Pallbearer/PolyHaven/wooden_crate_01/wooden_crate_01_2k/StaticMeshes/wooden_crate_01_lid.uasset',
        'crate_latch':'Content/Pallbearer/PolyHaven/wooden_crate_01/wooden_crate_01_2k/StaticMeshes/wooden_crate_01_latch.uasset'}
    inventory={k:dict(path=v,exists=(ROOT/v).is_file()) for k,v in candidates.items()}
    (OUT/'asset_inventory.json').write_text(json.dumps(inventory,indent=2)+'\n',encoding='utf-8')
    manifest=dict(status='offline_prepared_not_installed',utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        no_editor_calls=True,no_gpu_jobs=True,no_build=True,no_tests=True,
        source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        output_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.iterdir() if p.is_file()},
        review='README one refinement review; no visual/gameplay acceptance claimed')
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    print('ENDING_FOCUS_PACKET_READY',OUT)


if __name__=='__main__':
    main()
