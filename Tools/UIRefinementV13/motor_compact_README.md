# Compact motor UMG packet

Status: prepared; not installed or visually accepted.

Apply `motor_compact_transparent.json` serially through native Hayba UI tools, using its preflight and guards. This edits the existing four-widget Designer tree, preserving the native mechanism and its timed crank/valve input feedback. No source change or rebuild is required for the asset edit.

## What the source proves

- `SaskartaMotorDiagram.cpp` binds `MotorMechanism` and `MotorPhosphor` from the authored tree; it does not replace that tree. The custom mechanism draws the accepted timing window, valve side, phase, earned charge and torque/dust status.
- Native initialization disables retained rendering. The direct drawing now has its own dark text edge, so glass can use alpha zero. No material/CRT effect is needed.
- Existing keyboard and gamepad textures are loaded asynchronously from `/Game/SaskartaGaea/UI/Prompts/Light/T_Prompt_...` for Key_E, Key_A, Key_D, Pad_A and DPad directions. Keep them visible.
- `SaskartaPower.cpp:287` moves power instruments to the opposite upper corner while motor mode is active.
- The authored motor source scale is0.82 and bottom offset−156. At720p this predicts y249.12–564, overlapping the installed ReceptionPrompt y504–588. Compact0.66 and bottom offset−232 predict y234.56–488, leaving16px above ReceptionPrompt and116px above HintFit y604–688.

## Required root reads

Native `ui_query` first, including properties/slots/GUIDs. Require exact parent and all four class/name pairs. Source JSON proves intended names, not the current loaded asset. The packet deliberately does not call editor tools from this offline lane.

Query actual layout at720p,1080p and540p. Layout snapshot may report allocation bounds rather than rendered transform bounds; preserve both actual slot and RenderTransform readbacks and use their combined geometry. The custom Slate mechanism has no UMG caption nodes, so a layout snapshot alone cannot prove text readability. View actual tuning and pursuit frames before marking visual acceptance.

## Remaining UI limitation

This is a focused transparency/geometry edit, not completion of overall UI consistency. The mechanism's amber color and words are still native draw code. A full UMG label/color redesign requires a separately granted source lane and build. Shrinking farther would make20px help text less than13.2logicalpx; keep this round at0.66 and check it against the bright road and inside-storm image.

## Persistence

After root accepts the actual edited asset, update the Motor entry in `Tools/UIRuntime/generate_hayba_packets.py` and its generated tree JSON to scale0.66 and position[28,-232]. This agent is forbidden those files, so it supplies the exact semantic change instead of writing outside its lane.

