"""Prepare an offline 96-view camera plan after root supplies surveyed bounds."""
import argparse
import math
from pathlib import Path

from common import OUTPUT, SCENES, WORLD_FRAME, cross, finite_vector, normalized, read_json, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bounds", type=Path, required=True)
    parser.add_argument("--id", choices=SCENES, required=True)
    args = parser.parse_args()
    spec = read_json(args.bounds)[args.id]
    if spec.get("bounds_approved_by_root") is not True:
        raise ValueError("Root must approve actual source bounds before generating camera positions")
    origin = finite_vector(spec["origin_ue_cm"])
    target = finite_vector(spec["target_ue_cm"])
    radius = float(spec["orbit_radius_cm"])
    heights = finite_vector(spec["height_offsets_cm"], 2)
    fov = float(spec["horizontal_fov_degrees"])
    if not math.isfinite(radius) or radius <= 0 or not 10 < fov < 120 or heights[0] == heights[1]:
        raise ValueError("Need a positive orbit radius, two heights and a bounded FOV")
    if not spec.get("source_actor_paths") or len(spec.get("fiducials", [])) != 4:
        raise ValueError("Root must supply source actors and four surveyed fiducials")
    frames = []
    for band, height in enumerate(heights):
        for index in range(48):
            angle = 2 * math.pi * (index + 0.5 * band) / 48
            p = [target[0]+radius*math.cos(angle), target[1]+radius*math.sin(angle), target[2]+height]
            forward = normalized([a-b for a, b in zip(target, p)])
            right = normalized(cross([0, 0, 1], forward))
            up = cross(forward, right)
            frames.append({"name": f"view_{band*48+index:03}.png", "height_band": band,
                           "planned_position_ue_cm": p, "planned_forward_ue": forward,
                           "planned_right_ue": right, "planned_up_ue": up})
    focal = 960 / (2 * math.tan(math.radians(fov) / 2))
    plan = {"id": args.id, "status": "planned_not_captured", "captured": False,
            "world_frame": WORLD_FRAME, "origin_ue_cm": origin, "resolution": [960, 540],
            "height_bands": 2, "intrinsics": [focal, focal, 480, 270],
            "source_actor_paths": spec["source_actor_paths"], "bounds": spec,
            "frames": frames, "exposure": spec["locked_exposure"],
            "capture_contract": "CAPTURE_CONTRACT.md; actual measured camera bases required"}
    write_json(OUTPUT / args.id / "capture_plan.json", plan)
    print(f"Prepared 96 planned cameras for {args.id}; no capture executed")


if __name__ == "__main__":
    main()
