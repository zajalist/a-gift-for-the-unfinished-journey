"""Render a CPU-only material review without changing the master asset."""
import bpy
import math
import pathlib
import sys
from mathutils import Vector

src = pathlib.Path(sys.argv[sys.argv.index('--') + 1])
dst = src.with_name(src.stem + '_preview.png')
bpy.ops.wm.open_mainfile(filepath=str(src))
scene = bpy.context.scene
scene.render.engine = 'CYCLES'
scene.cycles.device = 'CPU'
scene.cycles.samples = 12
scene.cycles.use_denoising = True
scene.render.resolution_x = 800
scene.render.resolution_y = 1000
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = 'PNG'
scene.render.film_transparent = False
scene.world.color = (0.55, 0.48, 0.39)
scene.world.use_nodes = True
background = scene.world.node_tree.nodes.get('Background')
background.inputs['Color'].default_value = (0.65, 0.56, 0.44, 1)
background.inputs['Strength'].default_value = 0.75

def aim(obj, point):
    direction = Vector(point) - obj.location
    obj.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()

bpy.ops.object.camera_add(location=(1.4, -2.0, 0.8))
camera = bpy.context.object
aim(camera, (0, 0, 0))
camera.data.type = 'ORTHO'
camera.data.ortho_scale = 1.25
scene.camera = camera
for loc, power, size in [((1.6, -1.8, 2.3), 450, 2.0), ((-1.6, 0.5, 1.0), 250, 1.5)]:
    bpy.ops.object.light_add(type='AREA', location=loc)
    lamp = bpy.context.object
    lamp.data.energy = power
    lamp.data.shape = 'DISK'
    lamp.data.size = size
    aim(lamp, (0, 0, 0))
bpy.ops.mesh.primitive_plane_add(size=200, location=(0, 0, -0.5))
ground = bpy.context.object
ground.name = 'Preview Ground'
ground_mat = bpy.data.materials.new('Preview sand')
ground_mat.diffuse_color = (0.28, 0.22, 0.16, 1)
ground.data.materials.append(ground_mat)
scene.view_settings.view_transform = 'AgX'
scene.render.filepath = str(dst)
print('PREVIEW_START=' + str(dst), flush=True)
bpy.ops.render.render(write_still=True)
print('PREVIEW_DONE=' + str(dst), flush=True)
