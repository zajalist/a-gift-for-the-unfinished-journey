"""Prepare NE service view and paired basin/sun captures of the existing haze."""
from pathlib import Path
import ast
import json
import hashlib
import prepare_ground_capture as capture

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'Saved/Tripo/20261001/visual_capture'
DIRECTORY=(ROOT/'Saved/Verification/playtest_feedback_20261001').as_posix()
SERVICE='''targets=[a for a in actors if a.get_actor_label()=='SD_S26_Upgrade_20261001_Transmitter']
assert len(targets)==1,'Exact current service cabinet required'
centre,extent=targets[0].get_actor_bounds(False)
location=centre+unreal.Vector(400,350,120)
rotation=unreal.MathLibrary.find_look_at_rotation(location,centre)
'''
PAIRED=capture.OWNED+'''
haze=[a for a in eas.get_all_level_actors() if a.get_actor_label()=='Saskarta_HorizonHaze_Backdrop']
assert len(haze)==1 and 'Saskarta_HorizonHaze_v1' in [str(t) for t in haze[0].tags],'Exact owned trial required'
h=haze[0];comp=h.get_component_by_class(unreal.StaticMeshComponent)
mat=comp.get_material(0)
assert mat.get_path_name()=='/Game/SaskartaGaea/Look/M_Saskarta_HorizonHaze.M_Saskarta_HorizonHaze'
assert not mat.get_editor_property('is_sky') and mat.get_editor_property('blend_mode')==unreal.BlendMode.BLEND_MASKED
assert mat.get_editor_property('dither_opacity_mask') and abs(mat.get_editor_property('opacity_mask_clip_value')-.5)<.0001
masks=[e for e in unreal.ObjectIterator(unreal.MaterialExpressionCustom) if e.get_outer()==mat and e.get_editor_property('description')=='Only below geometric horizon; native upper sky and sun remain visible']
assert len(masks)==1 and masks[0].get_editor_property('code')=='return smoothstep(0.0, 0.05, normalize(CV).z);','Expected the live root-corrected dawn-safe mask'
assert not h.get_actor_enable_collision() and comp.get_collision_enabled()==unreal.CollisionEnabled.NO_COLLISION,'Resolve the confirmed backdrop collision first'
prior_hidden=h.get_editor_property('hidden');prior_editor=h.is_temporarily_hidden_in_editor()
times=[]
for hidden,suffix in ((True,'off'),(False,'on')):
 h.set_actor_hidden_in_game(hidden);h.set_is_temporarily_hidden_in_editor(hidden)
 times.append(unreal.GameplayStatics.get_time_seconds(world))
 c.capture_scene()
 unreal.RenderingLibrary.export_render_target(world,c.get_editor_property('texture_target'),'__DIRECTORY__','__NAME___'+suffix+'.png')
h.set_actor_hidden_in_game(prior_hidden);h.set_is_temporarily_hidden_in_editor(prior_editor)
print('HORIZON_SOFT_PAIRED_CAPTURE '+json.dumps({'times':times,'same_world_time':times[0]==times[1],'camera':cap.get_actor_transform().export_text(),'fov':c.get_editor_property('fov_angle'),'mask':'smoothstep(0,.05,CV.z)','prior_visibility_restored':True,'paths':['__DIRECTORY__/__NAME___off.png','__DIRECTORY__/__NAME___on.png']},separators=(',',':')))
'''

def finish(text,name,fov):
    for key,value in [('__LABEL__',capture.LABEL),('__TAG__',capture.TAG),('__DIRECTORY__',DIRECTORY),('__NAME__',name),('__FOV__',str(fov))]:text=text.replace(key,value)
    return capture.checked(text)

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    manifest=[]
    for name,frame,fov,pair in [('service_ne_preview',SERVICE,60.,False),
                              ('summit_basin_soft',*capture.summit_frame('summit_basin'),True),
                              ('summit_sun_soft',*capture.summit_frame('summit_sun'),True)]:
        reframe=capture.OWNED+'\nactors=eas.get_all_level_actors()\n'+frame+'''cap.set_actor_location(location,False,False)
cap.set_actor_rotation(rotation,False)
c.set_editor_property('fov_angle',__FOV__)
c.capture_scene()
print('SUMMIT_CAPTURE_REFRAMED '+json.dumps({'camera':cap.get_actor_transform().export_text(),'fov':__FOV__,'saved':False}))
'''
        phases=[('setup',capture.SETUP.replace('__FRAME__',frame)),('reframe',reframe),('pump',capture.PUMP),
                ('paired_ab' if pair else 'export',PAIRED if pair else capture.EXPORT),('cleanup',capture.CLEANUP)]
        for phase,body in phases:
            path=OUT/(name+'_'+phase+'.py');path.write_text(finish(body,name,fov),encoding='utf-8')
            manifest.append({'path':str(path.relative_to(ROOT)),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()});print(path)
    (OUT/'verification_capture_manifest.json').write_text(json.dumps({'scripts':manifest,'execution':'Use reframe if the exact owned helper still exists; otherwise setup. Pump3–5times, export/pairedAB, then cleanup. For paired views the script verifies current dawn-safe material and disabled collision; no material edits. Preserve prior visibility and restore original skylight flags on cleanup.'},indent=2)+'\n',encoding='utf-8')

if __name__=='__main__':main()
