"""Match the approved tower review camera for cut-geometry comparison."""
import bpy
from pathlib import Path
from mathutils import Vector

root = Path(__file__).resolve().parents[2]
source = root / 'Saved/Ending/RelayTower/S26_RelayTower_ChamberWindow_v3_ReviewOnly.blend'
out = root / 'Saved/Ending/RelayTower/S26_RelayTower_MatchedGeometry_v3.png'
bpy.ops.wm.open_mainfile(filepath=str(source))
scene = bpy.context.scene
scene.render.engine = 'BLENDER_WORKBENCH'
scene.render.resolution_x = 800
scene.render.resolution_y = 1000
scene.render.resolution_percentage = 100
scene.display.shading.light = 'STUDIO'
scene.display.shading.color_type = 'MATERIAL'
scene.display.shading.show_cavity = True
scene.display.shading.cavity_type = 'BOTH'
scene.render.image_settings.file_format = 'PNG'
for obj in bpy.data.objects:
    if obj.type == 'EMPTY': obj.hide_render = True
camera_data = bpy.data.cameras.new('Matched approved review camera')
camera = bpy.data.objects.new('Matched approved review camera', camera_data)
scene.collection.objects.link(camera)
camera.location = (1.4, -2.0, 0.8)
camera.rotation_euler = (Vector((0, 0, 0)) - camera.location).to_track_quat('-Z', 'Y').to_euler()
camera_data.type = 'ORTHO'
camera_data.ortho_scale = 1.25
scene.camera = camera
scene.render.filepath = str(out)
bpy.ops.render.render(write_still=True)
print('RELAY_MATCHED_GEOMETRY', out, flush=True)
