"""Prove the authored eye ray through the selected source window, offline."""
import json
import sys
from pathlib import Path
import numpy as np
from measure_station_shell_fit import ROOT,OUT,Surface,SOURCE
sys.path.insert(0,str(ROOT/'Tools/Cinematics'))
import samyor_notice as notice
import samyor_reveal as rig
import traveller_gaze as gaze
import ending_staging as staging


def measure():
    fit=json.loads((OUT/'source_fit.json').read_text())
    choice=min((x for x in fit['candidates'] if x['intersections']==0),key=lambda x:x['scale'][2])
    surface=Surface();post=fit['protected_anchors']
    rot=np.array([rig.qrot(rig.qaxis((0,0,1),choice['yaw']),axis) for axis in np.eye(3)]).T
    scale=np.array(choice['scale']);origin=np.array(choice['origin_cm'])
    actor=rig.qaxis((0,0,1),notice.BODY_YAW)
    def local(point):return ((np.array(point)-origin)@rot)/scale
    rows=[]
    for seconds in (2.5,4.5,19.8):
        world=rig.fk(notice.pose_at(seconds))
        eye=rig.vadd(world['Head'][0],rig.qrot(world['Head'][1],gaze.EYE_LOCAL))
        eye=np.array(post['inside'])+rig.qrot(actor,eye)
        forward=np.array(rig.qrot(actor,rig.qrot(world['Head'][1],gaze.HEAD_FORWARD)))
        hits=surface.segment(local(eye),local(eye+forward*600))
        rows.append(dict(sequence_seconds=seconds+59.5,eye_world_cm=eye.tolist(),eye_source_cm=local(eye).tolist(),
                         direction_world=forward.tolist(),surface_hits=[p.tolist() for p in hits]))
    report=dict(source=str(SOURCE.relative_to(ROOT)),scale=scale.tolist(),origin_cm=origin.tolist(),yaw=choice['yaw'],
        visible_sun_bearing=staging.SUN_BEARING,peak_sun_elevation=.62,rows=rows,
        limitations=['Source triangle evidence; not rendered Unreal evidence',
                    'Eye offset uses the measured reference head and existing authored eye point',
                    'Actual horizon and clouds require rendered inspection',
                    'Old hut must be reversibly replaced: overlapping original wall can block the new window'])
    (OUT/'window_line_of_sight.json').write_text(json.dumps(report,indent=2)+'\n')
    print('WINDOW_SOURCE_RAYS',[(r['sequence_seconds'],len(r['surface_hits'])) for r in rows])
    return report


if __name__=='__main__':measure()
