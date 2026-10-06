"""Cheap Workbench review images for the separate S26 dressed-door derivative."""
import bpy
from mathutils import Vector
from pathlib import Path

root=Path(__file__).resolve().parents[2]
folder=root/'Saved/Ending/RelayTower'
bpy.ops.wm.open_mainfile(filepath=str(folder/'S26_RelayTower_TrueDoorDressed_ReviewOnly.blend'))
scene=bpy.context.scene
scene.render.engine='BLENDER_WORKBENCH'
scene.display.shading.light='STUDIO'
scene.display.shading.color_type='MATERIAL'
scene.display.shading.show_cavity=True
scene.display.shading.cavity_type='BOTH'
scene.render.resolution_percentage=100
scene.render.image_settings.file_format='PNG'
for obj in bpy.data.objects:
    if obj.type=='EMPTY':obj.hide_render=True
camera_data=bpy.data.cameras.new('Dressed-door review camera')
camera=bpy.data.objects.new('Dressed-door review camera',camera_data)
scene.collection.objects.link(camera);scene.camera=camera

camera.location=(1.4,-2.0,.8)
camera.rotation_euler=(Vector((0,0,0))-camera.location).to_track_quat('-Z','Y').to_euler()
camera_data.type='ORTHO';camera_data.ortho_scale=1.25
scene.render.resolution_x=800;scene.render.resolution_y=1000
scene.render.filepath=str(folder/'S26_RelayTower_TrueDoorDressed_Exterior.png')
bpy.ops.render.render(write_still=True)

camera.location=(.71,-.78,-.17)
camera.rotation_euler=(Vector((.119,-.127,-.413))-camera.location).to_track_quat('-Z','Y').to_euler()
camera_data.ortho_scale=.31
scene.render.resolution_x=900;scene.render.resolution_y=900
scene.render.filepath=str(folder/'S26_RelayTower_TrueDoorDressed_Portal.png')
bpy.ops.render.render(write_still=True)
print('DRESSED_DOOR_PREVIEWS',flush=True)
