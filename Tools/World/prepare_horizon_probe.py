"""Emit a bounded editor readback of horizon lighting and visible geometry; never send."""
from pathlib import Path
import argparse
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'Tools/Look'))
from apply_look import READ
from prepare_ground_contact_loading import HEAD, checked

MESH_PAGE = HEAD + '''
acts = unreal.EditorLevelLibrary.get_all_level_actors()
offset = __OFFSET__
mesh_rows = []
components = []
for a in acts:
    cname = a.get_class().get_name()
    if isinstance(a, unreal.LandscapeProxy) or 'HLOD' in cname or 'HLOD' in a.get_actor_label():
        continue
    for c in a.get_components_by_class(unreal.StaticMeshComponent):
        if c.static_mesh is not None:
            components.append(c)
components.sort(key=lambda c: c.get_path_name())
for c in components[offset:offset+20]:
        a = c.get_owner()
        m = c.static_mesh
        bb = m.get_bounding_box()
        mesh_rows.append({'actor': a.get_path_name(), 'label': a.get_actor_label(),
            'class': a.get_class().get_name(), 'component': c.get_path_name(),
            'component_class': c.get_class().get_name(), 'mesh': m.get_path_name(),
            'pose': c.get_world_transform().export_text(), 'bounds_local': [xyz(bb.min), xyz(bb.max)],
            'visible': c.is_visible(), 'hidden_in_game': c.get_editor_property('hidden_in_game'),
            'materials': [c.get_material(i).get_path_name() if c.get_material(i) else None for i in range(min(4,c.get_num_materials()))],
            'material_count': c.get_num_materials(), 'tags': [str(t) for t in a.tags][:8]})
print('HORIZON_MESH_PAGE ' + json.dumps({'offset': offset, 'rows': mesh_rows,
      'total_non_hlod_meshes': len(components), 'next_offset': offset+20 if offset+20<len(components) else None,
      'loaded_actor_count': len(acts)}, separators=(',', ':')))
'''

LARGE_HLOD = HEAD + '''
rows = []
for a in unreal.EditorLevelLibrary.get_all_level_actors():
    if 'HLOD' not in a.get_class().get_name():
        continue
    origin, extent = a.get_actor_bounds(False)
    if extent.z < 100000 and max(extent.x, extent.y) < 500000:
        continue
    components = []
    for c in a.get_components_by_class(unreal.StaticMeshComponent):
        if c.static_mesh is not None:
            components.append({'path': c.get_path_name(), 'mesh': c.static_mesh.get_path_name(),
                'visible': c.is_visible(), 'hidden_in_game': c.get_editor_property('hidden_in_game'),
                'materials': [c.get_material(i).get_path_name() if c.get_material(i) else None for i in range(min(4,c.get_num_materials()))],
                'material_count': c.get_num_materials()})
    rows.append({'actor': a.get_path_name(), 'label': a.get_actor_label(), 'class': a.get_class().get_name(),
                 'origin': xyz(origin), 'extent': xyz(extent), 'components': components[:2],
                 'component_count': len(components)})
rows.sort(key=lambda r: max(r['extent']), reverse=True)
print('HORIZON_LARGE_HLOD ' + json.dumps({'rows': rows[:20], 'candidate_count': len(rows),
      'truncated': len(rows)>20, 'scope': 'HLOD bounds taller than2km or wider than10km'}, separators=(',', ':')))
'''


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--offset', type=int, default=0)
    ap.add_argument('--pages', type=int, default=4)
    args = ap.parse_args()
    if args.offset < 0 or not 1 <= args.pages <= 10:
        raise ValueError('Use a nonnegative offset and 1..10 small pages')
    out = ROOT / 'Saved/HorizonRepair'
    out.mkdir(parents=True, exist_ok=True)
    lighting = HEAD + READ.rsplit('print(json.dumps(out))', 1)[0] + '''
out['editor_camera'] = str(es.get_level_viewport_camera_info())
out['world_bounds'] = str(lib.get_editor_world_bounds())
print('HORIZON_LIGHTING ' + json.dumps(out, separators=(',', ':')))
'''
    files = [('lighting_only_probe.py', lighting), ('large_hlod_probe.py', LARGE_HLOD)]
    files.extend((f'mesh_page_{i:03d}.py', MESH_PAGE.replace('__OFFSET__', str(i)))
                 for i in range(args.offset, args.offset+args.pages*20, 20))
    for name, script in files:
        target = out / name
        target.write_text(checked(script), encoding='utf-8')
        print(target)


if __name__ == '__main__':
    main()
