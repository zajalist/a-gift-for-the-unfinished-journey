# Subtitle refinement v17

Prepared offline, not installed. Root is the only editor operator.

The user screenshot is `C:/Users/Admin/AppData/Local/Temp/codex-clipboard-a801aeb3-542a-487a-a6da-4f54d7203a5b.png`. It shows a floating RADIO HOST label and a broad dark band behind two dialogue lines.

`native_packet.json` contains the exact Hayba query, property, slot, compile and save commands. First confirm the actual loaded owner: the supplied target `WBP_Saskarta_Subtitle` is the carrier warning in checked-in graph source. The named speaker/dialogue tree and EventRunner delegate bindings belong to `WBP_Saskarta_Caption`. Do not apply this packet to Subtitle or rebuild a widget tree to make it fit.

The revision keeps the centered scene overlay and existing typography. It reduces padding between speaker and dialogue from 33 to 4 design pixels, removes the isolated speaker backdrop, reduces main-plate alpha from .62 to .36, and reduces main padding from 66/22/66/26 to 40/4/40/10. The existing soft texture and nine-slice margins remain. Width, text, font sizes, timing, root anchors and cinematic lift remain controlled by existing runtime behavior.

Readback is explicit in the packet. Capture mutation property acceptance, exact named widget relationships/GUIDs, compile status and save success. A collapsed designer layout cannot certify visible PIE geometry. Capture actual dialogue over bright ground, including single/two-line and carrier cues; observe the Small/Medium/Large setting if present. The current authored Caption generator has no SubtitleSize/cvar/SetFont linkage even though settings writes `saskarta.subtitles.size`; do not claim that setting works from the layout patch.

`source_sync_proposal.patch` proposes the generator synchronization for root after native acceptance. It does not change graph logic and has not been applied. Root can then regenerate `WBP_Saskarta_Caption.tree.json` through the existing generator. `prepare_packet.py` only reads source and writes this lane's files.

Native relationship evidence: `SaskartaEventRunner.cpp` ShowLineSubtitle/ShowStationSubtitle feed timed pages through UpdateSubtitlePages and OnSubtitleShow; `Tools/GameFlow/editor/caption_graph.py` binds the Caption widget handler to ShowSubtitle. ShowSubtitle/NextChunk own speaker mapping, branch visibility, adaptive wrap, chunk timing, replacement and fades.

The requested browser-harness skill was absent at `D:/Scripts/mcp-tools/browser-harness/SKILL.md`; this offline packet did not use browser automation. No Unreal tool, build, tests, source/spec edit, Content edit or git operation was performed by this lane.
