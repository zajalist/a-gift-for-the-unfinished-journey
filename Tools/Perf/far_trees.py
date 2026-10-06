"""Distant tree groves (user, 2026-10-06): ~1000 static stand-in trees >= 450 m from the road, on the
always-loaded holder Saskarta_FarTrees (one ISM per mesh; no shadow, no WPO, no collision).
    python Tools/Perf/far_trees.py 1 2 3 ...   # add the ISM for those mesh indices (0..8)
Same seed each call, so every call regenerates identical positions and keeps its own mesh's share."""
import sys
sys.path.insert(0, 'Tools/Perf')
from uncull_far_meshes import send

TEMPLATE = open(__file__.replace('far_trees.py', 'far_trees_editor.txt'), encoding='utf-8').read()

for k in sys.argv[1:]:
    print(send(TEMPLATE.replace('K = 0', 'K = ' + k)).strip(), flush=True)
