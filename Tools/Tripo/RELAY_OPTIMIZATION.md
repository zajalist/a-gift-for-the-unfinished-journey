# S26 relay tower runtime mesh candidate

The approved `S26_RelayTower_8K_PBR_Review.blend` and its three 8K maps stay
untouched. The chamber-and-window cut is now saved as
`Saved/Ending/RelayTower/S26_RelayTower_ChamberWindow_ReviewOnly.blend`.
The builder accepts **only that exact cut derivative** and rejects the
approved master, portal trial and chamber-only review file. The cut still
needs geometric and rendered review before runtime promotion.
`build_relay_tower_candidate.py` duplicates the cut
tower mesh in memory,
applies a restrained collapse reduction, shifts the duplicate to a bottom
pivot, and exports a **mesh-only** GLB. It writes a separate audit report and
refuses to overwrite either file. The source still has 1,861,164 triangles;
the candidate has **not** been generated or visually approved while 4K
capture status is unknown.

After capture is clear, use the portable Blender 5.2.2 executable:

```powershell
& 'D:\CodexTools\blender-5.2.2-windows-x64\blender.exe' -b -P Tools/Tripo/build_relay_tower_candidate.py -- --source Saved/Ending/RelayTower/S26_RelayTower_ChamberWindow_ReviewOnly.blend --ratio 0.80 --output Saved/Ending/RelayTower/SM_S26_RelayTower_Candidate80.glb
python Tools/Tripo/audit_relay_tower_candidate.py Saved/Ending/RelayTower/SM_S26_RelayTower_Candidate80.glb --report Saved/Ending/RelayTower/SM_S26_RelayTower_Candidate80.audit.json --max-triangles 1250000
```

The 1.25M ceiling is a provisional *test target* (roughly 80% of the current
1.53M-triangle chamber cut), not an art-approved budget.
If the actual output exceeds it, inspect the triangle count and choose a
different candidate name/ratio. A passing metadata audit only checks
triangles, one mesh/section, UV0 and normals, bottom pivot, bounds and the
three external 8K map headers. It cannot prove that slender aerial members,
counterweights, arched door, buttresses or PBR seam alignment survived.
Compare all four sides with the approved review preview before promoting it.
The separate PBR chamber shell is not decimated or exported by this mesh-only
candidate builder; it needs its own import after the portal+window cut passes.

`stage_relay_tower.py packet` remains blocked until a distinct candidate
passes the declared ceiling **and** an Unreal support receipt records
landscape, foundation, yard and CIN24 framing gates. The rejected rear-yard
coordinate must not be reused. Only then generate and inspect the packet;
import is a later explicit editor step. For final performance, evaluate Nanite,
simple collision and texture streaming in Unreal rather than assuming triangle
reduction alone makes this 20 m landmark cheap.
