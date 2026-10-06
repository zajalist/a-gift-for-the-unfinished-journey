import csv
import json

import transcribe_author


def test_prompt_uses_only_supplied_canonical_names_and_keywords(tmp_path, monkeypatch):
    story = tmp_path / "docs" / "story"
    story.mkdir(parents=True)
    (story / "names.json").write_text(json.dumps({
        "names": [{"display_in_english_text": "Âlaawb"}],
        "pending": {"places": [
            {"english_placeholder": "the Waiting Water", "saskartan_author_spelling": "ndasef ibubremat"},
            {"english_placeholder": "Untranslated place"},
        ]},
    }, ensure_ascii=False), encoding="utf-8")
    with (story / "saskartan-keywords.tsv").open("w", encoding="utf-8-sig", newline="") as source:
        writer = csv.DictWriter(source, fieldnames=["english", "saskartan"], delimiter="\t")
        writer.writeheader()
        writer.writerows([
            {"english": "the relay", "saskartan": "âlaawb"},
            {"english": "another name", "saskartan": "  ta'handedya  "},
            {"english": "Untranslated keyword", "saskartan": "   "},
        ])
    monkeypatch.setattr(transcribe_author, "ROOT", tmp_path)

    prompt = transcribe_author.initial_prompt()

    assert not (story / "route-board.json").exists()
    assert "Names: Âlaawb, ndasef ibubremat, ta'handedya," in prompt
    assert prompt.casefold().count("âlaawb") == 1
    assert "Untranslated" not in prompt
    assert "the Waiting Water" not in prompt


def test_project_prompt_retains_author_spelling_without_board_labels():
    prompt = transcribe_author.initial_prompt()
    terms = prompt.split("Names: ", 1)[1][:-1].split(", ")

    assert {"Ilaawb", "Âlaawb", "Iy-la'har-dzehiy", "Samyor", "ndasef ibubremat",
            "ta'handedya", "zdawet", "zenwiy", "tarsan", "yeggar tababghē"} <= set(terms)
    assert "GATE" not in terms
    assert "ALAAWB" not in terms
    assert len(terms) == len({term.casefold() for term in terms})
