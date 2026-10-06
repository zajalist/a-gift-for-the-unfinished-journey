# Credits: UI input prompts

## Kenney, "Input Prompts" 1.5 (1.5A, created 11-07-2026)

- Author: Kenney (www.kenney.nl)
- Source: https://kenney.nl/assets/input-prompts (`kenney_input-prompts_1.5.zip`)
- Licence: Creative Commons Zero (CC0 1.0), http://creativecommons.org/publicdomain/zero/1.0/
- The original `License.txt` is kept verbatim at
  `Tools/UI/ThirdParty/Kenney_InputPrompts_1.5/License.txt`.

CC0 needs no attribution. We credit Kenney anyway, as the pack asks
("Support by crediting 'Kenney' or 'www.kenney.nl'"). Add "Input prompts based on
Kenney's Input Prompts (kenney.nl, CC0)" to the game's end credits.

Only the SVGs the game uses are vendored (36 from the pack, plus keyboard_e.svg drawn by LANE5 in the same 64 px key style: the pack zip was not on this machine), in `Keyboard_Mouse/` and `Xbox_Series/`.

## What we changed

`Tools/UI/make_input_prompts.py` keeps each Kenney silhouette unchanged and re-grades
it into a Saskarta keycap. It adds a skirt, a top-face gradient, a bevel, a gold rim, an
engraved label, a contrast outline and a baked drop shadow, then recolours the result in
two themes: ivory `#ECE2CE` with umber `#2A1E16`, and dark with ivory. Kenney's red
accents become stele gold. The output goes to `Saved/UI/InputPrompts/`. These derived
PNGs are also CC0, so we may treat them as our own.
