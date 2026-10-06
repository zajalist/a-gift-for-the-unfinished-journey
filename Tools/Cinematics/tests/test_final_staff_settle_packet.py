from pathlib import Path
import ast
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import install_final_staff_settle as packet
import samyor_final as final
import samyor_reveal as rig


def test_incremental_packet_writes_only_staff_in_two_existing_clips(tmp_path):
    out=tmp_path/'packet';plan=packet.prepare(out)
    assert len(plan['groups'])==2 and len(plan['script_sha256'])==9
    assert {g['package'] for g in plan['groups']}=={rig.ANIM_DIR+'/'+n for n in final.CLIPS}
    writes=[]
    for script in (out/packet.FOLDER).glob('*.py'):
        text=script.read_text();compile(text,str(script),'exec')
        assert not any(x in text for x in ('remove_all_bone_tracks','add_bone_curve','set_frame_rate','set_number_of_frames','create_asset','LevelSequence'))
        for node in ast.walk(ast.parse(text)):
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='set_bone_track_keys':
                writes.append(ast.literal_eval(node.args[0]))
    assert writes==['staff011','staff011']
    assert packet.check(out)==plan
    first=next((out/packet.FOLDER).glob('*_keys_*.py'))
    first.write_text(first.read_text()+'\n# changed\n')
    with pytest.raises(AssertionError,match='Packet changed'):packet.check(out)


def test_installed_baseline_diff_is_exactly_staff_translation():
    old=packet.baseline_tracks()
    for name,(_,new) in final.baked().items():
        assert [bone for bone in new if old[name][bone]!=new[bone]]==['staff011']
        assert all(a[1:]==b[1:] for a,b in zip(old[name]['staff011'],new['staff011']))
