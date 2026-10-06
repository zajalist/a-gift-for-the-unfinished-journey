"""Low resolution, review-only preview for the offline S26 annex asset."""
import bpy
from mathutils import Vector
from pathlib import Path

out=Path(__file__).resolve().parents[2]/'SourceArt/Tripo/20261003/S26_VictorianRadioStation'
bpy.ops.wm.open_mainfile(filepath=str(out/'S26_PlayableRadioAnnex_v1.blend'))

world=bpy.data.worlds.new('Overcast_Studio')
world.use_nodes=True
world.node_tree.nodes['Background'].inputs['Color'].default_value=(.57,.62,.65,1)
world.node_tree.nodes['Background'].inputs['Strength'].default_value=.7
bpy.context.scene.world=world

def area(name,loc,power,size):
    data=bpy.data.lights.new(name,'AREA'); data.energy=power; data.shape='DISK'; data.size=size
    obj=bpy.data.objects.new(name,data); bpy.context.collection.objects.link(obj)
    obj.location=loc; obj.rotation_euler=(Vector((-1.2,.75,2.2))-obj.location).to_track_quat('-Z','Y').to_euler()

area('Soft sun',(-5,-3,9),1500,9)
area('Sky fill',(5,3,7),850,11)

cam_data=bpy.data.cameras.new('Review camera'); cam=bpy.data.objects.new('Review camera',cam_data)
bpy.context.collection.objects.link(cam); bpy.context.scene.camera=cam
cam.location=(-9,-10,6.8)
target=Vector((1.05,.8,2.05))
cam.rotation_euler=(target-cam.location).to_track_quat('-Z','Y').to_euler()
cam_data.type='ORTHO'; cam_data.ortho_scale=10.5

scene=bpy.context.scene
scene.render.engine='BLENDER_EEVEE'
scene.render.resolution_x=768; scene.render.resolution_y=576
scene.render.resolution_percentage=100
scene.render.image_settings.file_format='PNG'
scene.render.filepath=str(out/'S26_PlayableRadioAnnex_v1_exterior_preview.png')
scene.render.film_transparent=False
scene.render.image_settings.color_mode='RGBA'
scene.view_settings.view_transform='AgX'
bpy.ops.render.render(write_still=True)

# Interior: see continuous walls, protected unobstructed window and wide equipment side.
cam.location=(.55,-.25,1.64)
target=Vector((1.3,2.0,1.52))
cam.rotation_euler=(target-cam.location).to_track_quat('-Z','Y').to_euler()
cam_data.type='PERSP'; cam_data.lens=22
scene.render.filepath=str(out/'S26_PlayableRadioAnnex_v1_interior_preview.png')
bpy.ops.render.render(write_still=True)
