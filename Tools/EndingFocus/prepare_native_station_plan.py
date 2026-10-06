"""Prepare one read-only terrain fit, then native spawn/material instructions."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'Saved/Verification/ending_focus_20261001/capsule_exit_compact_review_v4'
source=(ROOT/'Tools/EndingFocus/place_station_clusters.py').read_text()
script=source[:source.index('# All support probes completed')]
script+='''
rows=[]
for plan in plans:
    p=plan['position']; r=plan['rotation']
    slots=plan['mesh'].get_editor_property('static_materials')
    rows.append(dict(label=plan['label'],mesh=plan['mesh'].get_path_name(),
        location=[p.x,p.y,p.z],rotation=[r.roll,r.pitch,r.yaw],scale=[plan['scale']]*3,
        existing=plan['existing'].get_path_name() if plan['existing'] else None,
        clearance_cm=plan['corner_clearance_cm'],
        materials=[m.material_interface.get_path_name() if m.material_interface else None for m in slots]))
print('ENDING_STATION_NATIVE_PLANS '+json.dumps(dict(plans=rows,read_only=True,saved=False),separators=(',',':')))
'''
(OUT/'00_station_contact_plan.py').write_text(script)
print(OUT/'00_station_contact_plan.py')
