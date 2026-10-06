"""Guard the glass runner against painting an absent droplet across the side bands."""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import make_sensor_glass as glass


@pytest.mark.parametrize("amount", [0.6, 0.85])
def test_empty_runner_cannot_create_half_coverage(amount):
    # T=26 falls in the quiet part of the baked drop life cycle, when an
    # absent runner's q=(9,9) can otherwise beat the stale sheet distance.
    maps = glass.load_maps(glass.OUT, suffix="_1024")
    scene = np.full((90, 160, 3), 0.4)
    debug = {}
    glass.shade(scene, maps, T=26.0, amount=amount, dbg=debug)

    side = np.abs(debug["UV"][..., 0] - 0.5) > 0.3
    phantom = side & (debug["rpx"] == 0) & (debug["alive"] > 0.5) & (debug["cov"] > 0)
    real = side & (debug["rpx"] > 0) & (debug["alive"] > 0.5) & (debug["cov"] > 0)

    assert not phantom.any(), "an absent runner must not create a 0.5-coverage side band"
    assert real.any(), "the fix must preserve actual runner droplets"
