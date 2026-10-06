"""Vertex transport completeness; no Unreal connection."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
import prepare_mesh_vertex_pages as paging


def pages():
    vertices = [[float(i), 0.0, 0.0] for i in range(905)]
    common = dict(path='/Game/Cart.Cart', source='render_data_geometry_script', lod=0,
                  total=905, bounds=[[0.0, 0.0, 0.0], [904.0, 0.0, 0.0]], page_size=900)
    return [dict(common, offset=0, vertices=vertices[:900], next_offset=900),
            dict(common, offset=900, vertices=vertices[900:], next_offset=None)]


def test_complete_pages_are_ordered_and_keep_all_vertices():
    result = paging.combine(list(reversed(pages())))
    assert len(result['vertices']) == result['counts']['vertices'] == 905
    assert result['truncated'] is False


def test_missing_or_transport_truncated_page_refused():
    with pytest.raises(ValueError, match='incomplete'):
        paging.combine(pages()[:1])
    short = pages()
    short[0]['vertices'] = short[0]['vertices'][:50]
    with pytest.raises(ValueError, match='truncated'):
        paging.combine(short)
    with pytest.raises(ValueError, match='Missing'):
        paging.combine(pages()[1:])


def test_changed_mesh_and_false_bounds_refused():
    changed = pages()
    changed[1]['total'] = 907
    with pytest.raises(ValueError, match='changed'):
        paging.combine(changed)
    wrong = pages()
    wrong[-1]['vertices'][-1] = [903.0, 0.0, 0.0]
    with pytest.raises(ValueError, match='full render bounds'):
        paging.combine(wrong)


def test_script_uses_explicit_current_render_data_and_stdout():
    script = paging.page_script('/Game/Cart.Cart', 900)
    assert 'GeometryScriptLODType.RENDER_DATA' in script
    assert 'lod.lod_index = 0' in script
    assert 'vertices[offset:offset+900]' in script
    assert 'MESH_VERTEX_PAGE ' in script
    assert 'save_asset' not in script
