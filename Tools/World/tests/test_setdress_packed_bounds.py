"""Packed-BP component bounds math (CPU-only mocks; no Unreal editor calls)."""
from types import SimpleNamespace
import os
import sys
import math

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import place_setdress as ps


def vec(x, y, z):
    return SimpleNamespace(x=x, y=y, z=z)


def transform(translation, yaw_degrees, scale):
    return SimpleNamespace(translation=translation, yaw=yaw_degrees, scale=scale)


def transform_point(t, p):
    import math
    angle = math.radians(t.yaw)
    x, y, z = (v * t.scale for v in p)
    return (t.translation[0] + x * math.cos(angle) - y * math.sin(angle),
            t.translation[1] + x * math.sin(angle) + y * math.cos(angle),
            t.translation[2] + z)


def inverse_actor_point(t, p):
    import math
    angle = math.radians(-t.yaw)
    x, y, z = (p[i] - t.translation[i] for i in range(3))
    return ((x * math.cos(angle) - y * math.sin(angle)) / t.scale,
            (x * math.sin(angle) + y * math.cos(angle)) / t.scale,
            z / t.scale)


class MockMesh:
    def get_bounds(self):
        return SimpleNamespace(origin=vec(10.0, -5.0, 3.0), box_extent=vec(2.0, 1.0, 4.0))


class MockStaticComponent:
    def __init__(self, mesh, world_transform):
        self.static_mesh = mesh
        self.world_transform = world_transform

    def get_world_transform(self):
        return self.world_transform


class MockInstancedComponent:
    def __init__(self, mesh, world_transforms):
        self.static_mesh = mesh
        self.world_transforms = world_transforms

    def get_instance_count(self):
        return len(self.world_transforms)

    def get_instance_transform(self, index, world_space):
        assert world_space is True
        return self.world_transforms[index]


def compose_world(actor, local_instance):
    """Compose uniform yaw/scale transforms for mock get_instance_transform(world_space=True)."""
    translation = transform_point(actor, local_instance.translation)
    return transform(translation, actor.yaw + local_instance.yaw, actor.scale * local_instance.scale)


def test_aggregate_uses_real_component_and_every_transformed_instance_corner():
    actor = transform((1000.0, -50.0, 25.0), 90.0, 2.0)
    mesh = MockMesh()
    ordinary = MockStaticComponent(mesh, actor)
    instances = MockInstancedComponent(mesh, [
        compose_world(actor, transform((20.0, 0.0, 0.0), 90.0, 2.0)),
        compose_world(actor, transform((-30.0, 5.0, 10.0), -90.0, 0.5)),
    ])

    center, extent = ps.aggregate_mesh_component_bounds(
        actor, [ordinary, instances], transform_point, inverse_actor_point,
        lambda component: isinstance(component, MockInstancedComponent))

    # Independent expected actor-local boxes: regular mesh plus both transformed instances.
    assert all(math.isclose(a, b, abs_tol=1e-8) for a, b in zip(center, (-0.5, 9.0, 6.0)))
    assert all(math.isclose(a, b, abs_tol=1e-8) for a, b in zip(extent, (32.5, 15.0, 8.0)))


def test_missing_mesh_geometry_is_not_replaced_by_actor_placeholder_bounds():
    actor = transform((100.0, 200.0, 300.0), 35.0, 1.0)
    assert ps.aggregate_mesh_component_bounds(actor, [], transform_point, inverse_actor_point,
                                              lambda component: False) is None
    no_mesh = MockStaticComponent(None, actor)
    assert ps.aggregate_mesh_component_bounds(actor, [no_mesh], transform_point, inverse_actor_point,
                                              lambda component: False) is None


def test_check2_script_uses_the_same_component_bounds_helper_as_settle():
    script = ps.build_script(ps.CHECK2_BODY, SITE='S', ITEMS=[])
    ps.validate(script)
    assert 'def actor_mesh_bounds(a):' in script
    assert 'bounds = actor_mesh_bounds(a)' in ps.CHECK2_BODY
    assert 'bounds = actor_mesh_bounds(a)' in ps.EDITOR_HEAD
