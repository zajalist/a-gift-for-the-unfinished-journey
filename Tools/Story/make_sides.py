"""Split docs/story/recording-script.md into one recording sheet per speaker.

Writes docs/story/sides/<SPEAKER>.md. Each sheet holds the voice description, the
recording setup, and only that speaker's story and idle lines, so a remote
performer can record without the rest of the script. Rerun after editing the script.

    python Tools/Story/make_sides.py
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "docs" / "story" / "recording-script.md"
OUT = ROOT / "docs" / "story" / "sides"
SPEAKERS = ("KEEPER", "VISITOR", "ELDER")  # the Neighbour was merged into the Keeper (2026-09-27)


def sections(text):
    """Map each '## ' heading to its body, keeping '### ' subsections inside it."""
    found = {}
    for part in re.split(r"(?m)^## ", text)[1:]:
        title, _, body = part.partition("\n")
        found[title.strip()] = body
    return found


def rows_for(body, speaker, speaker_col):
    """Table rows whose speaker cell starts with the speaker, grouped under their ### heading."""
    out, heading, header = [], None, None
    for line in body.splitlines():
        if line.startswith("### "):
            heading = line[4:].strip()
            continue
        if line.startswith("| ID "):
            header = line
            continue
        if not line.startswith("| ") or line.startswith("|---"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) > speaker_col and cells[speaker_col].replace("*", "").startswith(speaker):
            out.append((heading, header, line))
    return out


def table(rows):
    lines, last = [], object()
    for heading, header, row in rows:
        if heading != last:
            if heading:
                lines += ["", f"### {heading}", ""]
            divider = "|" + "|".join("---" for _ in header.strip().strip("|").split("|")) + "|"
            lines += [header, divider]
            last = heading
        lines.append(row)
    return "\n".join(lines)


def main():
    text = SCRIPT.read_text(encoding="utf-8")
    parts = sections(text)
    voices = parts.get("Voices", "")
    setup = parts.get("Recording setup", "").strip()
    story = parts.get("Story radio lines", "")
    idle = parts.get("Idle radio lines", "")
    idle_rules = idle.split("### ")[0].strip()
    station = parts.get("Station lines (casual broadcast)", "")
    OUT.mkdir(exist_ok=True)
    for speaker in SPEAKERS:
        who = next((l for l in voices.splitlines() if l.startswith(f"| **{speaker}**")), "")
        story_rows = rows_for(story, speaker, 2)
        idle_rows = rows_for(idle, speaker, 1)
        station_rows = rows_for(station, speaker, 1)
        seconds = round(sum(float(m) for _, _, r in story_rows + idle_rows + station_rows
                            for m in re.findall(r"\|\s*~?(\d+(?:\.\d+)?) s\s*\|\s*$", r)))
        sheet = [
            f"# {speaker.title()}: recording sheet",
            "",
            f"Generated from [`recording-script.md`](../recording-script.md) by `Tools/Story/make_sides.py`; edit the script, not this file.",
            "",
            "## Who this is",
            "",
            "| Speaker | Who | Performed by | Treatment in post |",
            "|---|---|---|---|",
            who,
            "",
            "This voice exists only on old archive tapes played by a radio. Record it clean and dry; the tape sound is added afterwards.",
            "",
            "## Recording setup",
            "",
            setup,
            "",
            f"## Story lines ({len(story_rows)})",
            "",
            table(story_rows) if story_rows else "None.",
            "",
            f"## Idle lines ({len(idle_rows)})",
            "",
            idle_rules,
            "",
            table(idle_rows) if idle_rows else "None.",
            "",
            f"## Station lines ({len(station_rows)})",
            "",
            "Ilaawb, recorded in its own session; the rules are in the script's *Station lines* section.",
            "",
            table(station_rows) if station_rows else "None.",
            "",
            f"**Target total for this voice: about {seconds} s of final audio.**",
            "",
        ]
        path = OUT / f"{speaker}.md"
        path.write_text("\n".join(sheet), encoding="utf-8", newline="\n")
        print(f"{path.relative_to(ROOT)}: {len(story_rows)} story, {len(idle_rows)} idle, {len(station_rows)} station, ~{seconds} s")


if __name__ == "__main__":
    main()
