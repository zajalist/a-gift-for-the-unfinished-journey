from pathlib import Path
import json
import math
import sys

HERE=Path(__file__).resolve().parents[1]/'story_sets'
sys.path.insert(0,str(HERE))
import prepare_fence_coping as coping


def prepared():
    return json.loads((coping.OUT/'design.json').read_text(encoding='utf-8'))


def test_every_actual_foot_is_inside_flat_cap_with_measured_margin():
    rows=prepared()
    assert len(rows)==14
    for d in rows:
        for p in d['row']['contacts']:
            assert all(d['rect']['min'][i]+.29<=p[i]<=d['rect']['max'][i]-.29 for i in range(2))
            assert abs(d['body_z']+p[2]-d['cap_top'])<.5
        assert d['cap_thickness']==2.


def test_foreign_cap_can_only_touch_the_height_matched_corner_pair():
    rows=prepared()
    for d in rows:
        r=d['row']
        for p in r['contacts']:
            point=coping.xy(r,p)
            for other in rows:
                if d is other:continue
                q=other['row'];rad=math.radians(q['yaw']);c,s=math.cos(rad),math.sin(rad)
                dx,dy=[point[i]-q['world_xy_cm'][i] for i in range(2)]
                local=[dx*c+dy*s,-dx*s+dy*c]
                if all(other['rect']['min'][i]<=local[i]<=other['rect']['max'][i] for i in range(2)):
                    assert d['corner_mate_label']==q['label']+'_Coping'
                    assert abs(other['cap_top']-(d['body_z']+p[2]))<.2


def test_apply_guards_and_material_are_explicit():
    code=(coping.OUT/'apply/FenceRear00.py').read_text(encoding='utf-8')
    assert "a.get_actor_transform().export_text()==p['transform']" in code
    assert "a.static_mesh_component.set_material(0,metal)" in code
    assert "old[i] if old[i] else" in code
    assert coping.METAL in code
    assert 'save_packages' not in code and 'destroy_actor' not in code
