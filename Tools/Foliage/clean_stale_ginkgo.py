"""Clear the stale ginkgo stand-in instances left in the tree partition actors (LANE4, 2026-09-28).

    python Tools/Foliage/clean_stale_ginkgo.py [ix,iy ...]

The pine swap (5714f73) regenerated every tree region, but generate_local left the old
SM_Saskarta_TreeFar_Ginkgo_* ISM components in the saved PCG partition actors (stale managed
resources), so the leaf-quad trees still drew next to the new pines. Per region, as separate calls:
load the region's proxies and partition actors -> clear every ISM whose mesh is
SM_Saskarta_TreeFar_Ginkgo_* -> save the touched partition actors (chunks of 20) -> unload.
Hold a wp-region lease over the regions first (editor_gate.py).
"""
import sys
import time
import generate_tree_regions as g

CLEAR = g.HEAD + """
n = 0
touched = 0
for a in eas.get_all_level_actors():
    if a.get_class().get_name().startswith('PCGPartition'):
        l = a.get_actor_location()
        if l.x < x0 - 25600.0 or l.x > x0 + 2 * P + 25600.0 or l.y < y0 - 25600.0 or l.y > y0 + 2 * P + 25600.0:
            continue
        hit = False
        for c in a.get_components_by_class(unreal.InstancedStaticMeshComponent):
            m = c.get_editor_property('static_mesh')
            if m is not None and m.get_name().startswith('SM_Saskarta_TreeFar_Ginkgo_'):
                n += c.get_instance_count()
                c.clear_instances()
                hit = True
        if hit:
            a.modify()
            touched += 1
print('RESULT clear ' + str(n) + ' ' + str(touched))
"""

SAVE_DIRTY = g.HEAD + """
CHUNK = 0
pk = []
for a in eas.get_all_level_actors():
    if a.get_class().get_name().startswith('PCGPartition'):
        l = a.get_actor_location()
        if l.x < x0 - 25600.0 or l.x > x0 + 2 * P + 25600.0 or l.y < y0 - 25600.0 or l.y > y0 + 2 * P + 25600.0:
            continue
        for c in a.get_components_by_class(unreal.InstancedStaticMeshComponent):
            m = c.get_editor_property('static_mesh')
            if m is not None and m.get_name().startswith('SM_Saskarta_TreeFar_Ginkgo_'):
                pk.append(a.get_package())
                break
part = pk[CHUNK * 20:(CHUNK + 1) * 20]
ok = True
if len(part) > 0:
    ok = unreal.EditorLoadingAndSavingUtils.save_packages(part, True)
print('RESULT save ' + str(len(part)) + ' ' + str(len(pk)) + ' ' + str(ok))
"""


def main(argv):
    regions = [tuple(int(v) for v in s.split(",")) for s in argv] or [
        tuple(int(v) for v in k.split(",")) for k in g.load_done().get("regions_pines", {})]
    total = 0
    for r in regions:
        base = g.run(g.LOADED, r)
        g.run(g.LOAD, r, MODE="load")
        time.sleep(2)
        res = g.run(CLEAR, r)
        total += int(res[1])
        chunk = 0
        while True:
            s = g.run(SAVE_DIRTY, r, CHUNK=chunk)
            if s[3] != "True":
                raise RuntimeError(f"{r}: save failed")
            if (chunk + 1) * 20 >= int(s[2]):
                break
            chunk += 1
        g.run(g.LOAD, r, MODE="unload")
        time.sleep(3)
        print(time.strftime("%H:%M:%S"), r, "cleared", res[1], "instances in", res[2], "partition actors; saved", s[2], flush=True)
    print("TOTAL cleared", total)


if __name__ == "__main__":
    main(sys.argv[1:])
