"""Audit imported Tripo meshes referenced by saved Saskarta World Partition actors.

This reads actor packages on disk, not the current editor world or generated
placement state. A package reference is evidence that the map saved the mesh;
it is not an instance count or a visual-quality verdict.
"""

import argparse
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[2]
ACTORS = ROOT / "Content" / "__ExternalActors__" / "level" / "Saskarta_WP"
MANIFEST = ROOT / "SourceArt" / "Tripo" / "manifest.json"
MESHES = ROOT / "Content" / "SaskartaGaea" / "Environment" / "Tripo02"
LEVEL = ROOT / "Content" / "level" / "Saskarta_WP.umap"
SITE_TOKEN = re.compile(rb"SD_[A-Za-z0-9_]+\x00")


def site_hint(data):
    tokens = {hit[:-1].decode("ascii") for hit in SITE_TOKEN.findall(data)}
    if not tokens:
        return None, None
    site = min(tokens, key=lambda token: (len(token), token))
    labels = sorted((token for token in tokens if token != site), key=lambda token: (-len(token), token))
    return site[3:], labels[0] if labels else None


def audit():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    approved = sorted({"SM_T2_" + model["t2"] for model in manifest["models"]
                       if model["verdict"] == "use"})
    if len(approved) != 24:
        raise RuntimeError("expected 24 approved Tripo mesh types in the manifest")
    found = {name: [] for name in approved}
    package_count = 0
    referenced_packages = 0
    for package in ACTORS.rglob("*.uasset"):
        package_count += 1
        data = package.read_bytes()
        if b"SM_T2_" not in data:
            continue
        names = [name for name in approved if name.encode("ascii") + b"\x00" in data]
        if not names:
            continue
        referenced_packages += 1
        site, label = site_hint(data)
        path = package.relative_to(ROOT).as_posix()
        for name in names:
            found[name].append({"package": path, "site_hint": site, "actor_label_hint": label})
    types = []
    for name in approved:
        packages = sorted(found[name], key=lambda item: item["package"])
        types.append({"mesh": name,
                      "imported_asset": (MESHES / (name + ".uasset")).relative_to(ROOT).as_posix(),
                      "imported": (MESHES / (name + ".uasset")).is_file(),
                      "package_count": len(packages),
                      "sites": sorted({item["site_hint"] for item in packages if item["site_hint"]}),
                      "unattributed_package_count": sum(item["site_hint"] is None for item in packages),
                      "packages": packages})
    return {"schema_version": 1, "level": LEVEL.relative_to(ROOT).as_posix(),
            "level_exists": LEVEL.is_file(),
            "external_actor_package_count": package_count,
            "approved_mesh_type_count": len(approved),
            "imported_mesh_type_count": sum(row["imported"] for row in types),
            "referenced_mesh_type_count": sum(row["package_count"] > 0 for row in types),
            "referenced_actor_package_count": referenced_packages,
            "missing_mesh_types": [row["mesh"] for row in types if row["package_count"] == 0],
            "types": types}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="write the JSON audit to this path")
    parser.add_argument("--min-types", type=int, default=0,
                        help="exit 2 unless this many approved types are referenced by saved packages")
    args = parser.parse_args()
    report = audit()
    payload = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
        print("%s: %d/%d referenced Tripo mesh types in %d external actor packages" %
              (args.output, report["referenced_mesh_type_count"], report["approved_mesh_type_count"],
               report["external_actor_package_count"]))
    else:
        sys.stdout.write(payload)
    if args.min_types and (report["referenced_mesh_type_count"] < args.min_types
                           or report["imported_mesh_type_count"] != report["approved_mesh_type_count"]
                           or not report["level_exists"]):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
