"""Shared spatial/timing contract for the measured station ending."""
import math

SUN_BEARING = 198.66  # visible disc; the directional light travels at18.66
TURN_AT = 97.2
TURN_SECONDS = 2.3
COLLAPSE_AT = TURN_AT + TURN_SECONDS
COLLAPSE_END = COLLAPSE_AT + 3.8


def turn_fraction(seconds):
    alpha = min(1.0, max(0.0, seconds / 2.0))
    return alpha * alpha * (3.0 - 2.0 * alpha)


def arrival_yaw(post):
    a, b = post['exit_mid'], post['collapse']
    return math.degrees(math.atan2(b[1]-a[1], b[0]-a[0])) - 90.0


def turn_delta(post):
    return (SUN_BEARING - 90.0 - arrival_yaw(post) + 180.0) % 360.0 - 180.0
