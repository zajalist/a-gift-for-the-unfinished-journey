# Loading / charging crank proposal, revision 17

This lane prepares a single visual revision of `SaskartaMotorDiagram.cpp`. Native source, assets, the editor, builds and Git were not changed.

## Screenshot diagnosis

- The stationary top marker ends at radius 73 while the outer rim is radius 67: a visible 6-unit gap makes it appear detached.
- Each spoke starts at radius 25 and stops at 54. The hub is radius 24 and the inner rim is radius 61, leaving small inner gaps and large outer gaps.
- The bright pin sits on the inner rim at radius 61 without an arm or handle. It reads as a loose bead. Six equally bright rotating spokes make the identity of the active crank difficult to follow.
- Loading currently makes 1.75 turns, so complete readiness leaves the pin away from the top mark.

## Proposed native drawing

Keep the 67/61-unit rings and six-spoke silhouette. Join each spoke from the 24-unit hub to the 61-unit rim. Attach the fixed top marker directly to the outer ring, from radius 74 to 67. Add a brighter radial arm from the hub to a spindle at radius 51, with a closed 24-by-8-unit tangential grip. The handle stays inside the rim and rotates around the same hub with the spokes. The existing input glyph remains clear in the center during charging; loading shows a small axle instead.

Both states call the same drawing helper. Charging retains the exact gameplay phase, top target angle, accepted-window arc and input glyph behavior. Its hub retains its existing readiness brightness through the helper argument.

Loading maps clamped readiness directly onto two revolutions and completes at the top mark. The external arc and 512-unit line remain exact readiness indicators; both stop or reverse when readiness does. The line is reduced from 4 to 3 units and remains vertically centered on the axle. No elapsed-time animation, smoothing, fabricated progress, input logic, charge calculation or layout changes are introduced.

## Deliverables

- `Proposed/SaskartaMotorDiagram.cpp`: full proposed native file derived from the actual source.
- `loading_crank_refinement.patch`: exact unified diff against that source.
- `prepare_proposal.py`: standard-library proposal generation.
- `render_preview.ps1`: a small System.Drawing CPU geometry sketch with no new dependencies.
- `Saved/Verification/ui_refinement_v13/loading_crank_refinement_v17/receipt.json`: baseline and proposal SHA-256 digests, scope and limitations.
- `Saved/Verification/ui_refinement_v13/loading_crank_refinement_v17/crank_preview.png`: one image comparing charging at the top window and loading at 65%.

The preview is a geometry sketch, not an Unreal render. No gameplay testing or native compilation was performed. The root agent must check the source baseline before later integration because other proposal lanes may target the same native file. Integration must wait until the user has closed the active editor session.
