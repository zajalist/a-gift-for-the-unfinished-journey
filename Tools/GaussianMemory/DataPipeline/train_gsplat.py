"""Run the pinned official gsplat trainer later, one scene per process."""
import argparse
import importlib
import importlib.metadata
import os
import subprocess
import sys
from pathlib import Path

from common import GSPLAT_COMMIT, TIERS, WORLD_FRAME, read_json, require_capture_receipt, scoped, sha256, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--gsplat-checkout", type=Path, required=True)
    parser.add_argument("--tier", type=int, choices=TIERS, default=65000)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    dataset = scoped(args.dataset)
    receipt, capture_path = require_capture_receipt(dataset)
    reconstruction = read_json(dataset/"colmap_receipt.json")
    if reconstruction.get("completed") is not True or reconstruction.get("world_frame") != WORLD_FRAME:
        raise ValueError("Completed metric known-pose COLMAP receipt required")
    if reconstruction["capture_receipt_sha256"] != sha256(capture_path):
        raise ValueError("Capture provenance changed after reconstruction")
    if not 4 <= reconstruction["triangulated_point_count"] <= args.tier:
        raise ValueError("Real initialization points must fit the requested tier; never initialize random points")
    for name, digest in reconstruction["model_sha256"].items():
        if Path(name).name != name or sha256(dataset/"sparse/0"/name) != digest:
            raise ValueError("Reconstructed model changed")
    for name, digest in reconstruction["training_images_sha256"].items():
        if Path(name).name != name or sha256(dataset/"images"/name) != digest:
            raise ValueError("Training image changed")
    config = {"data_dir": str(dataset), "data_factor": 1, "result_dir": str(dataset/f"trained_{args.tier}"),
              "normalize_world_space": False, "init_type": "sfm", "sh_degree": 3, "max_steps": 30000,
              "save_ply": True, "ply_steps": [30000], "save_steps": [30000], "eval_steps": [30000],
              "disable_viewer": True, "pose_opt": False, "pose_noise": 0.0, "app_opt": False,
              "init_opa": 0.5, "init_scale": 0.1, "opacity_reg": 0.01, "scale_reg": 0.01}
    if not args.execute:
        print({"trainer": "official examples/simple_trainer.py", "commit": GSPLAT_COMMIT,
               "config": config, "strategy": {"MCMCStrategy.cap_max": args.tier}})
        print("Dry run; no trainer imports or GPU work executed")
        return
    checkout = args.gsplat_checkout.resolve()
    commit = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
    dirty = subprocess.check_output(["git", "-C", str(checkout), "status", "--porcelain"], text=True).strip()
    if commit != GSPLAT_COMMIT or dirty:
        raise ValueError("Trainer must be a clean checkout of the exact official pinned commit")
    result = Path(config["result_dir"])
    if result.exists():
        raise ValueError("Refusing to overwrite or mix training results")
    os.environ["TORCH_HOME"] = str(result/"torch_cache")
    sys.path.insert(0, str(checkout))
    sys.path.insert(0, str(checkout/"examples"))
    trainer = importlib.import_module("simple_trainer")
    gsplat = importlib.import_module("gsplat")
    if not Path(gsplat.__file__).resolve().is_relative_to(checkout):
        raise ValueError("Imported gsplat did not come from the pinned checkout")
    strategy = importlib.import_module("gsplat.strategy").MCMCStrategy(cap_max=args.tier, verbose=True)
    cfg = trainer.Config(**config, strategy=strategy)
    # Run the official Runner training path directly, with its normal offline
    # evaluation behavior and no live viewer.
    runner = trainer.Runner(local_rank=0, world_rank=0, world_size=1, cfg=cfg)
    runner.train()
    ply = result/"ply/point_cloud_29999.ply"
    checkpoint = result/"ckpts/ckpt_29999_rank0.pt"
    if not ply.is_file() or not checkpoint.is_file():
        raise ValueError("Official trainer did not produce the final full PLY/checkpoint")
    torch = importlib.import_module("torch")
    packages = sorted({f"{dist.metadata['Name']}=={dist.version}" for dist in importlib.metadata.distributions()})
    write_json(result/"training_receipt.json", {"id": receipt["id"], "trained": True,
               "trainer": "nerfstudio-project/gsplat/examples/simple_trainer.py", "trainer_commit": commit,
               "trainer_license": "Apache-2.0", "world_frame": WORLD_FRAME, "config": config,
               "strategy": {"type": "MCMCStrategy", "cap_max": args.tier}, "seed": 42,
               "capture_receipt_path": str(capture_path.relative_to(dataset)),
               "capture_receipt_sha256": sha256(capture_path), "colmap_receipt_sha256": sha256(dataset/"colmap_receipt.json"),
               "source_ply_path": str(ply.relative_to(result)), "source_ply_sha256": sha256(ply),
               "checkpoint_sha256": sha256(checkpoint), "asset_license": receipt["asset_license"],
               "environment": {"python": sys.version, "torch": torch.__version__,
                               "gsplat": getattr(gsplat, "__version__", "unknown"),
                               "cuda_build": torch.version.cuda, "gpu": torch.cuda.get_device_name(0),
                               "installed_packages": packages}})


if __name__ == "__main__":
    main()
