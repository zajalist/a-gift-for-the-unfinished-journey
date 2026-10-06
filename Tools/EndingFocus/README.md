# Focused ending packet

The human is Samyor, the passenger carried inside the capsule. He carries no
package. This packet develops the user's approved continuous footing/staff
mechanic and requested **actual 3D Gaussian splat** memories, alongside the
existing summit station and ending. It is prepared offline; nothing here has
been installed in Unreal or visually accepted. The new isolated native
`SaskartaElderWalk.h/.cpp` implementation is now written for the next root serial
build; it is guarded until its actual contact animations/profile are installed.

Run `python Tools/EndingFocus/prepare_packet.py` to emit the bounded read-only
Hayba survey, source/asset evidence and composition data. Root executes editor
work after the current human playtest. This packet writes only its own scoped
verification directory. The later staff authoring packet and the two explicitly
granted new native files are separate from that original read-only packet.

## Implementation handoff (2026-10-01)

- `USaskartaElderWalk` activates only for the possessed, walking Traveller in
  Human flow. Pause, prompts, cinematics, detours, disabled movement and endings
  release its own speed/facing/animation leases and hide its row. E must be
  released before it rearms; story prompts retain priority.
- One cached audio component plays quiet existing wind, gravel and staff cues.
  Assets preload asynchronously at the human handoff. Support polls at 10 Hz
  with at most three short collision traces. Missing terrain creates no hazard.
- Real nearby walls provide shelter. Loose ground must be visibly authored and
  tagged `Saskarta.Elder.Loose`; the subsystem never guesses that a missing
  collision sample is dangerous. Gusts vary through the three climb sections.
- Planting stays stationary, with real boot/staff contacts. A/D shifts the
  skeleton via the authored Blend Space rather than moving a planted staff
  through the ground. This refines the earlier 20–35 cm/s brace draft: the
  existing single-node animation driver would override a moving contact clip.
- The temporary transparent native UMG row uses the existing E texture and
  caption font, and counts at least five actually displayed seconds. The
  authored Hayba UMG row remains an editor handoff, not claimed as installed.
  The profile's HintWidgetClass loads that authored subclass; named
  ElderHintRow/ElderStaffGlyph/ElderStaffCaption preserve its designer layout.
- Hold/toggle staff and reduced gust functions are exposed for accessibility.
  No stamina countdown, camera replacement, radio reset or story/audio edit.

`python -B Tools/EndingFocus/author_staff_contacts.py` produced 58 scoped files
at `Saved/Verification/ending_focus_20261001/staff_contact_authoring/`. Five real
bone animation clips retain measured boots, right-hand grip, recorder and staff
surface. In the sampled source poses the body minimum is 0.393–0.402 cm and the
staff minimum is 0.424 cm. These are source measurements, not Unreal acceptance.
`INSTALL.md` specifies the actual Blend Space editor setup, imported pose and
rendered review, profile/cook handoff and locomotion transition risk. The profile
is created uncertified: unsupported slopes/contact misses keep ordinary walking
available and disable the penalty. A proper terrain-aware AnimBP/Control Rig
extension is still required before increasing its current four-degree guard.

`place_station_clusters.py` is the concrete post-PIE Hayba script for two varied
crates, one lid and one latch using verified installed PolyHaven meshes beside
the exact saved radio station. It fits the real support normal and probes all
rotated corners before its first write, rejects more than 2.5 cm residual
corner gaps, more than 12 degree slopes and missing collision, owns only
`SD_S26_EndFocus_*` actors, and leaves results unsaved for the root's existing
save/readback protocol. It has not run in Unreal.

## The climb the player actually performs

Continue normal WASD movement and mouse look through the real escort drone.
The player chooses the firmer line and holds **E** to plant his staff when wind
or loose ground disturbs his balance. While planted he can slowly shift his
weight with A/D in the skeleton, with feet and staff fixed; release E to continue. This happens throughout the 200 m climb,
with three distinct spaces, rather than three compulsory stops:

1. **4790–4845 m, exposed shelf.** Dust, cloth and an increasing gust sound warn
   before a gust. The inside line is more sheltered. The first mild gust teaches
   E with a small transparent gameplay prompt that stays visible five seconds.
2. **4845–4925 m, retaining ruins.** Short firm paving sections and visibly loose
   gravel make route selection matter. The stele/lookback remains optional.
   Staff contact stabilizes a loose step; the player can choose shelter without
   collecting anything or leaving the forward route.
3. **4925–4990 m, station approach.** Wind progressively calms as the station
   encloses the path. Staff use remains available, but challenges thin out. The
   lamp, audible relay machinery and continuous title music reward arrival.

There is no stamina timer, step-by-step button rhythm, score, health meter or
new death/retry state. Poor footing creates a short stumble and recovery in
place. Never pull him over a cliff or take away his walking controls indefinitely.
The fixed front route, station door and final transmission stay where authored.

### Concrete implementation contract

The isolated native subsystem is now written under the root's explicit two-file
grant, ready for its next serial build. `StartHumanWalk` enables it through Human
flow and the pawn's existing bWalking state; `StopHumanWalk`, any cinematic, pause,
checkpoint handoff and title reset suspend/clean it. Poll terrain/support at
10 Hz with at most three short traces per poll, cached physical surface/zone
classification, and no level-wide actor scan or synchronous asset load. A
contact miss means ordinary safe walking until streamed terrain is available;
it never means a stumble. The road tether's current ±9 m limit remains intact.

Suggested states: `Walk`, `Unsteady`, `StaffPlant`, `Recover`. Gust notice lasts
1.8–2.6 s; a safe staff plant reaches stability in 0.35 s. Hold E is continuous,
not an on-beat tap. Braced speed is 20–35 cm/s; ordinary speed preserves the
existing 110 cm/s. A failed loose step stops forward displacement for no more
than 0.7 s, then auto-recovers and gives 1.5 s immunity. No displacement penalty
is applied on a frame over 0.25 s. A recovery cannot queue another recovery.

E already accepts road prompts. Resolve priority as: mandatory station prompt,
explicit optional interaction when standing in its volume, then staff plant.
Do not let an optional rest steal E while the player is walking or unsteady.
Release-to-rearm prevents holding the staff from accepting a station prompt.
Offer a hold/toggle staff option and reduced gust strength under accessibility.

The currently installed rig only has Rest, SlowWalk, SupportedIdle and Transmit
plus the newer final-rise/notice/turn/collapse clips. **A planted staff requires
a proper contact-preserving brace pose and a stumble recovery blend.** Do not
scale the whole mesh, lean the whole actor through the floor, or replay
SupportedIdle as a new physical plant without checking hand/shaft/tip contact.
The low back repair and full head remain intact. Additive upper body sway stays
within about 3°, planted staff tip stays fixed on the traced surface, and feet
use the real contact positions. The drone's flight remains the camera source.

## Actual Gaussian memories

Memories form softly in the spaces alongside Samyor, then break apart into
individual anisotropic Gaussians as he moves through the climb. They never cut
the camera, stop his feet, replace the landscape, play a second broadcast or
cover the current ground. They recall places he has just seen on this trip;
they do not invent a childhood in a surface city he never inhabited.

Three compact source tableaux are suitable: the lower gate/road he passed,
the numbered stop/old wall, and the cistern/relay fittings. Use the actual prior
authored scenes and their approved materials. Do not include floating cart or
broken-wall defects in a memory capture. More distant incomplete edges make
the fragments feel like remembered places rather than duplicated full levels.

### Renderer choice and exact evidence

**Recommended integration candidate: source-pinned Cesium for Unreal v2.28 or
later.** Its [primary change log](https://cesium.com/learn/cesium-unreal/ref-doc/changes.html)
explicitly supports UE5.8 and records a Gaussian Standalone rendering fix.
The inspected source shader reads actual position, orientation, scale and color
buffers and projects the three-dimensional covariance to the screen. It uses
Niagara as its rendering carrier: these are true trained Gaussian primitives,
not replacement dots. No custom sprite/point-cloud approximation is included.

Its [Gaussian shader](https://github.com/CesiumGS/cesium-unreal/blob/ca1d13d264de5ffd7e5e3803de7ce27ce5130ffe/Shaders/Private/CesiumGaussianSplatCompute.usf)
provides a concrete source location for the requested per-Gaussian drift: after
loading the original data, **before** setting output position and projecting
covariance. The packet's `MemoryGaussianDream.ush` is a new helper for that
future scoped renderer patch. It is not installed or compiled. Preserve the
plugin's Gaussian kernel, sorting and depth behavior; ordinary material WPO on
already projected quads would not implement this correctly.

The local project and engine Marketplace inventory contain no installed splat
renderer, and Content/SourceArt contain no `.ply`, `.splat` or `.ksplat` data.
A true Gaussian renderer and real data therefore remain required. Cesium's
existing implementation also needs an explicit per-memory parameter/data path
and packaged local-data inclusion; those do not appear automatically from this
helper. Its true-Gaussian Niagara carrier must be disclosed. If the user means
to prohibit Niagara itself, do not install this candidate or silently substitute.

MLSLabs is a native-renderer alternative, but its current
[Fab listing](https://www.fab.com/listings/f91b57cc-958d-40dd-a455-2535bf00e588)
still lists UE5.5–5.7. Its inspected public Lite API offers cloud transforms,
visibility and PLY sequence frames; individual deformation is inside a DLL.
The [published source](https://github.com/mlslabs/MLSLabsGaussianSplattingRenderer-UE)
does not prove a supported custom per-Gaussian shader hook. Another advertised
UE5.8 page is not enough to claim this project works. XVerse's detailed
[guide](https://github.com/xverse-engine/XScene-UEPlugin/blob/main/UEPlugin/README.md)
also lists only UE5.1–5.5. Neither is being installed by this packet.

### Data preparation after the playtest

Capture each static tableau in isolation with its original approved materials,
fixed lighting and no UI. Take 96 overlapping views at 960×540, two height bands,
locked exposure, plus masks/depth and known camera matrices. Disable animation
and wind during capture. Process one scene at a time. Real multi-view Gaussian
training produces center, log scale, quaternion, opacity and SH color fields;
the [original 3DGS project](https://repo-sam.inria.fr/fungraph/3d-gaussian-splatting/)
describes that representation. A plain XYZ/RGB PLY is not sufficient evidence.
Review trainer and asset licences for the production game before embedding them.

Export an actual `KHR_gaussian_splatting` glTF/3D Tiles representation accepted
by the selected Cesium release, retain full PLY plus metadata for provenance,
and use local packaged data with no network dependency during gameplay.
Verify coordinate units/rotation against four marked source points. Remove
sky/floor shells and capture floaters; keep a 1.5 m clear corridor around the
actual walking line. Set fixed bounds expanded by at least 12 cm for the combined
three-axis dream displacement. Convert renderer-local Gaussian centers to world
centimetres for the corridor mask, then transform modified centers back into
the renderer's original coordinate frame before projection and sorting.

### Presentation and performance targets

One memory active at a time, 12k/32k/65k Gaussian tiers, maximum two resident
memory assets, 128 MiB combined memory target, and 1.5 ms GPU target at 1080p on
the user's machine. These are budgets to measure, not achieved performance.
No capture or training runs beside the live game. Preload the next compact
memory asynchronously, finish upload before the section starts, and release
the prior one after its fade. No runtime PLY parsing or sorting allocation spike.

Fade in 2.5 s, live 8–14 s while walking, fade out 3 s, maximum opacity 0.18–0.28,
soft desaturated colors, no additive glow or red storm tint. Per-Gaussian drift
is slow, stable by Gaussian index, 2–8 cm, with covariance scales breathing at
most 4%. Foot-level memory opacity falls to zero; terrain, Samyor, staff and
station meshes depth-occlude memories. Turn off memory presentation during
unstable footing, mandatory prompts and all cinematics. Reduced motion stops
drift and uses fade only. A frame/GPU budget violation lowers the Gaussian tier;
it never replaces true splats with a fake particle effect.

## Station dressing and cinematic refinement

The copper station with its real opened window, 14 stepped fences, open gateway,
cabinet and two unchanged Carrier biofuel assemblies is already saved. Preserve
the accepted shell, foundations, gate opening and contact fixes. The new work is
purposeful connective dressing and shot composition, not another fence ring.

- **Service cluster:** supported supply/return pipes from the two tanks to the
  transmitter, one pressure/valve fitting, a worn service crate with intact lid
  and latch, and a short spare conduit bundle. All sit beside the cabinet and
  behind the clear entry/exit path. Share the existing brass material system.
- **Operator trace:** a folded cover, one tool or kettle and a cable reel close
  to the service cluster. Avoid domestic clutter suggesting current inhabitants.
- **Path:** three uneven clusters of weathered flat stones guide footsteps;
  exposed loose gravel remains visibly different. Avoid a repeated picket/wall
  rhythm, identical rock spacing or more tall silhouette objects on the horizon.
- **Fences:** retain grounded steps; vary repair details in only three places,
  leaving the open gate as the strongest foreground shape. Do not tilt posts or
  use a global Z offset to hide thick stone supports.

The emitted `survey_station.py` reads the actual installed actor transforms,
support/component bounds and protected anchors. It refuses PIE and missing
required actors; it performs no mutation or save. Use those actual bounds for
the next narrowly generated placement scripts. Every new supported object must
get a current-surface contact check and a strict scoped package save/readback.
The older rough `station_expansion` packet is superseded and must not be replayed.

For CIN19, cut on hand contact and emerge beside the capsule; do not interpolate
the drone through the hull or expose an unsupported climb-out clip. During the
walk the drone shows enough ground ahead to choose footing and keeps the staff
tip and feet in frame. It never switches to a detached invisible camera.

For CIN24, preserve the protected door/inside/exit/collapse locations and current
207 s audio timing. First frame must match the actual settled drone. Let Samyor
notice the brightening sun through the real window, turn toward it, then use
the installed supported rise and exit clips. The final outward walk faces the
sun bearing 198.66°. Keep title music on the same component and cursor. No
radio replay, new speech cadence or hard sound cuts are introduced. The final
collapse, grounded drone, replies after his death and credits transition remain
continuous. A new renderer does not justify touching those story audio rules.

## One refinement review

The review identified and resolved these mistakes before handing this packet off:
Samyor carries no parcel; surface memories are places he saw on this journey;
three rests cannot sustain the walk mechanic; and UE5.8/source shader capability
must be separated from unverified product marketing. Combined drift needs 12 cm
bounds expansion; reduced motion now also stops opacity pulses, and the helper
caps the opacity envelope at 0.28. Remaining execution is
explicit: the native human controller is written but not compiled here;
new real animations, renderer integration, captures/training, scoped station props
and the actual rendered ending are not installed or accepted by this lane.
