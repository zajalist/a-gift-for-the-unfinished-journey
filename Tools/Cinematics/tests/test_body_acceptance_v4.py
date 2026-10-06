from pathlib import Path
import struct
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import prepare_body_acceptance_v4 as prepare


def test_observable_float32_value_is_exact_not_broadened_world_tolerance():
    namespace={'struct':struct}
    exec(prepare.HELPER,namespace)
    near=namespace['key_near']
    assert near(297430.6875,297430.7)
    assert near(482888.8125,482888.8)
    assert not near(297430.71875,297430.7)
    assert not near(297430.6875+.002,297430.7)
    assert not near(18.856+.001,18.856)
