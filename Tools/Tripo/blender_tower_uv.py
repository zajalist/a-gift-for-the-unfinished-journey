"""Equalize the tower's existing UV islands while preserving the source UV for rebaking."""
import bpy
import pathlib
import sys
import time

src = pathlib.Path(sys.argv[sys.argv.index('--') + 1])
dst = src.with_name('S26_RelayTower_ReUV_Fine.blend')
bpy.ops.wm.open_mainfile(filepath=str(src))
obj = next(o for o in bpy.context.scene.objects if o.type == 'MESH')
mesh = obj.data
mesh.uv_layers[0].name = 'SourceUV'
new_uv = mesh.uv_layers.new(name='GameUV', do_init=True)
mesh.uv_layers.active = new_uv
new_uv.active_render = True
bpy.ops.object.select_all(action='DESELECT')
obj.select_set(True)
bpy.context.view_layer.objects.active = obj
bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.mesh.select_all(action='SELECT')
bpy.ops.object.mode_set(mode='OBJECT')
print('UV_START=' + str(time.time()), flush=True)
bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.uv.select_all(action='SELECT')
bpy.ops.uv.average_islands_scale()
print('UV_EQUALIZED=' + str(time.time()), flush=True)
bpy.ops.uv.pack_islands(margin=0.0005, rotate=True)
print('UV_PACKED=' + str(time.time()), flush=True)
bpy.ops.object.mode_set(mode='OBJECT')
bpy.ops.wm.save_as_mainfile(filepath=str(dst))
print('UV_BLEND=' + str(dst), flush=True)
