"""Replace only the S17 site object in the merged V2 JSON, preserving every other byte."""

import json
import os
from pathlib import Path
import re
import tempfile


ROOT = Path(__file__).resolve().parents[3]
AGGREGATE = ROOT / "Tools/World/setdress_v2_sites.json"
GROUP = Path(__file__).with_name("water_stone_features.json")
ID = "S17_DryCistern"


def record_span(text: str) -> tuple[int, int]:
    pattern = re.compile(r'(?m)^  \{\r?\n   "id": "' + ID + r'",')
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise ValueError(f"expected one top-level {ID} record, found {len(matches)}")
    start = matches[0].start()
    record, length = json.JSONDecoder().raw_decode(text[start + 2:])
    if record["id"] != ID:
        raise ValueError("wrong record at matched span")
    return start, start + 2 + length


def main() -> None:
    original_bytes = AGGREGATE.read_bytes()
    original = original_bytes.decode("utf-8")
    group = GROUP.read_bytes().decode("utf-8")
    old_start, old_end = record_span(original)
    new_start, new_end = record_span(group)
    replacement = group[new_start:new_end]
    revised = original[:old_start] + replacement + original[old_end:]

    before = json.loads(original)
    after = json.loads(revised)
    old_sites = {site["id"]: site for site in before["sites"]}
    new_sites = {site["id"]: site for site in after["sites"]}
    if before.keys() != after.keys() or old_sites.keys() != new_sites.keys():
        raise ValueError("aggregate structure/site IDs changed")
    if any(old_sites[sid] != new_sites[sid] for sid in old_sites if sid != ID):
        raise ValueError("a site other than S17 changed")
    if revised[:old_start] != original[:old_start] or revised[old_start + len(replacement):] != original[old_end:]:
        raise ValueError("bytes outside S17 changed")
    if new_sites[ID] != json.loads(replacement):
        raise ValueError("S17 aggregate differs from group record")
    if AGGREGATE.read_bytes() != original_bytes:
        raise RuntimeError("aggregate changed concurrently; retry after other writer completes")

    with tempfile.NamedTemporaryFile(dir=AGGREGATE.parent, prefix=".s17-", suffix=".tmp", delete=False) as out:
        temporary = Path(out.name)
        out.write(revised.encode("utf-8"))
    try:
        if AGGREGATE.read_bytes() != original_bytes:
            raise RuntimeError("aggregate changed during patch; no replacement made")
        os.replace(temporary, AGGREGATE)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"patched only {ID}; old record {old_end - old_start} chars, new {len(replacement)} chars; all other bytes preserved")


if __name__ == "__main__":
    main()
