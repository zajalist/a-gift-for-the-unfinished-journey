"""Offline selection guards; never contact Unreal."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
import prepare_ground_contact_loading as loading


def row(label, cls, bounds):
    return dict(label=label, guid=label, native_class=cls, bounds=bounds,
                actor_path='/Game/World.' + label, package='/Game/P_' + label)


def test_load_includes_current_collision_proxy_under_selected_prop():
    cart = row('Cart', 'StaticMeshActor', [[0, 0, 50], [100, 100, 100]])
    proxy = row('Terrain', 'LandscapeStreamingProxy', [[-5000, -5000, -100], [5000, 5000, 500]])
    far = row('FarTerrain', 'LandscapeStreamingProxy', [[10000, 10000, 0], [20000, 20000, 100]])
    result = dict(rows=[cart, proxy, far], truncated=False)
    assert loading.selection_from(result, ['Cart']) == [proxy, cart]


def test_missing_proxy_and_ambiguous_selection_refused():
    cart = row('Cart', 'StaticMeshActor', [[0, 0, 50], [100, 100, 100]])
    with pytest.raises(ValueError, match='No current LandscapeStreamingProxy'):
        loading.selection_from(dict(rows=[cart], truncated=False), ['Cart'])
    with pytest.raises(ValueError, match='exact labels'):
        loading.selection_from(dict(rows=[cart], truncated=False), ['Cart', 'Cart'])


def test_loading_is_explicit_and_small():
    cart = row('Cart', 'StaticMeshActor', [[0, 0, 50], [100, 100, 100]])
    proxies = [row(str(i), 'LandscapeStreamingProxy', [[-100, -100, 0], [200, 200, 100]]) for i in range(4)]
    with pytest.raises(ValueError, match='four actors'):
        loading.selection_from(dict(rows=[cart] + proxies, truncated=False), ['Cart'])
    assert 'load_actors(' not in loading.QUERY
    assert "item['guid'] not in resident" in loading.LOAD
    assert 'get_dirty_map_packages' in loading.RELEASE
    assert 'existing_residents_preserved' in loading.RELEASE


def test_contact_query_excludes_decal_noise_without_losing_source_props():
    script = loading.QUERY.replace('__CENTRE__', '[0, 0, 0]').replace('__RADIUS__', '5000').replace('__CONTACT_ONLY__', 'True')
    loading.checked(script)
    assert "'DecalActor'" in script
    assert "'omitted_classes': omitted_classes" in script
    assert "'included_count': len(rows)" in script
    assert "'LandscapeStreamingProxy'" not in script
    assert "'StaticMeshActor'" not in script
