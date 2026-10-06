"""Generated read-only probes must contain executable builtin data literals."""
import ast
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import prepare_dawn_terrain as probe


def test_probe_points_are_builtin_literals_and_bounded(tmp_path):
    target=tmp_path/'terrain'
    probe.prepare(target)
    scripts=list(target.glob('*.py'))
    assert len(scripts)==6
    for script in scripts:
        code=script.read_text()
        tree=ast.parse(code)
        loop=next(n for n in tree.body if isinstance(n,ast.For))
        points=ast.literal_eval(loop.iter)  # rejects np.float64(...) source leakage
        assert len(points)==8
        assert all(len(p['body_surface'])==3 and all(type(v) is float for v in p['body_surface']) for p in points)
        assert 'calls<48' in code and 'total_seconds()<3.5' in code
        assert not any(word in code for word in ('save_asset','set_actor','spawn_actor'))
