# Retired BOARD tooling

The user removed the NAMES/HEARD/MISSED, word/place matching, learning-caption, TUNE and name-dropout mechanics on 2026-09-30. Their native runtime and dedicated tests have been removed. Remaining waveform Python utilities are historical and are not installation or release gates; do not run them to reintroduce gaps or progression metadata.

The current recharge activity is motor rhythm/balance, shared with pursuit. See `docs/sprint/2026-09-30-game-ready-checklist.md` and `docs/handoffs/2026-09-30-board-removal.md`.

`audit_loaded_blueprints.py` is a removal regression probe, not a BOARD installer.
Its small explicit target list reads asset-registry parent tags and the status of
already loaded Blueprint objects. Send its text through a read-only Hayba
`python_run` call with a deadline of at most five seconds after the editor is
ready. It does not load, compile, save, or certify unloaded Blueprints. Do not
replace its explicit list with a project-wide asset-loading loop.
