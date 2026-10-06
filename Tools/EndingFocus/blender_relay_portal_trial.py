"""Reversible boolean trial of a human-scale passage through the relay base.

This is an offline geometry probe, not a production import: cut faces need
masonry cleanup, UVs, and real collision before gameplay use.
"""
import bpy
import pathlib
import sys
import time

src = pathlib.Path(sys.argv[sys.argv.index('--') + 1])
dst = pathlib.Path(sys.argv[sys.argv.index('--') + 2])
dst.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.open_mainfile(filepath=str(src))
obj = next(o for o in bpy.context.scene.objects if o.type == 'MESH')
before = len(obj.data.polygons)
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, -0.16, -0.410))
cutter = bpy.context.object
cutter.name = 'Trial doorway cutter 1.4m x 2.4m at 20m scale'
cutter.dimensions = (0.070, 0.78, 0.120)
bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
bpy.context.view_layer.objects.active = obj
mod = obj.modifiers.new('Trial clear through doorway', 'BOOLEAN')
mod.operation = 'DIFFERENCE'
mod.solver = 'EXACT'
mod.object = cutter
print('PORTAL_BOOLEAN_START=' + str(time.time()), flush=True)
bpy.ops.object.modifier_apply(modifier=mod.name)
print('PORTAL_BOOLEAN_DONE=' + str(time.time()) + ' faces=' + str(len(obj.data.polygons)) + ' source_faces=' + str(before), flush=True)
bpy.data.objects.remove(cutter, do_unlink=True)
bpy.context.preferences.filepaths.save_version = 0
bpy.ops.wm.save_as_mainfile(filepath=str(dst))
print('PORTAL_TRIAL=' + str(dst), flush=True)
