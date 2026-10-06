"""Small Workbench geometry previews of the reversible tower review .blend.

These show aperture and chamber form only; they are not a PBR art acceptance.
"""
import bpy
from mathutils import Vector
from pathlib import Path

root = Path(__file__).resolve().parents[2]
source = root / 'Saved/Ending/RelayTower/S26_RelayTower_ChamberWindow_v3_ReviewOnly.blend'
out = root / 'Saved/Ending/RelayTower'
bpy.ops.wm.open_mainfile(filepath=str(source))
scene = bpy.context.scene
scene.render.engine = 'BLENDER_WORKBENCH'
scene.render.resolution_x = 560
scene.render.resolution_y = 560
scene.render.resolution_percentage = 100
scene.display.shading.light = 'STUDIO'
scene.display.shading.color_type = 'MATERIAL'
scene.display.shading.show_cavity = True
scene.display.shading.cavity_type = 'BOTH'
scene.render.image_settings.file_format = 'PNG'
for obj in bpy.data.objects:
    if obj.type == 'EMPTY':
        obj.hide_render = True
for mat in bpy.data.materials:
    name = mat.name.lower()
    if 'stone' in name: mat.diffuse_color = (0.55, 0.51, 0.43, 1)
    elif 'oak' in name: mat.diffuse_color = (0.16, 0.10, 0.065, 1)
    elif 'copper' in name: mat.diffuse_color = (0.12, 0.28, 0.23, 1)

camera_data = bpy.data.cameras.new('Review camera')
camera = bpy.data.objects.new('Review camera', camera_data)
scene.collection.objects.link(camera)
scene.camera = camera

def render(name, position, target, lens):
    camera.location = position
    direction = Vector(target) - camera.location
    camera.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
    camera_data.lens = lens
    scene.render.filepath = str(out / name)
    bpy.ops.render.render(write_still=True)
    print('RELAY_GEOMETRY_PREVIEW', scene.render.filepath, flush=True)

render('S26_RelayTower_Geometry_Exterior_v3.png', (1.15, -1.45, 1.08),
       (0, 0, 0.30), 35)
render('S26_RelayTower_Geometry_Portal_v3.png', (0.0, -0.90, -0.28),
       (0, -0.10, -0.38), 35)
render('S26_RelayTower_Geometry_Interior_v3.png', (0.0, -0.54, -0.39),
       (0, 0.10, -0.38), 25)
