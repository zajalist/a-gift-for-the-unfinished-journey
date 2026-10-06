# Actual Gaussian memory renderer integration

Staged source release: Cesium for Unrealv2.29.1, UE5.8 SourceOnly archive,
commit `29ea626a7a5c76f12e49fd22e9628c870740598d`. The official archive hash is
`19d103edb08cd6abe0d729386ec4d085d07d415e1b8922133807de7c3240ab0e`.
The correct58 archive comes from official GitHub release metadata; the web
release page currently has a5.8 row linked to the57 archive.

The source-only release includes Cesium native static libraries, shaders and
Gaussian content assets. It installs no UnrealEditor DLL. Local engine5.8.2
uses BuildId55116800. Source must be compiled against that engine; no binary
ABI compatibility or rendered correctness is claimed. The plugin descriptor
is explicitly disabled by default. No uproject/Config/native project/Content
files were edited, and the live PIE session was untouched.

## Installed path

`ACesiumGaussianMemoryTileset` is a public Blueprint/C++ API. Its local loader
requires a reviewed trained sidecar manifest and a single embedded-buffer GLB
under the plugin's Resources/GaussianMemories folder. It rejects remote child
tiles, unknown representation, untrained data and scene counts above65000.
At most two prepared actors are reserved; at most one is active. Inactive
memory Gaussian arrays are omitted from the GPU roster and sort count.

Call `PrepareLocalMemory(id)` before the section, wait for
`IsMemoryDataReady()`, then call `BeginMemory(actualFeetCm, groundZCm,
reducedMotion, holdSeconds)`. The2.5s fade begins after native GPU upload fences
complete. It holds8–14s and fades3s, with maximum envelope0.24. Update
`UpdateMemoryFooting` from the human controller using the actual feet and
support trace. `EndMemory` starts a gentle release; `SuspendMemory` immediately
clears presentation for unsafe footing, mandatory prompts, cinematics, title
reset and checkpoint handoff. Actor EndPlay cleans up ownership/reservation.
Root wiring into those gameplay events remains required after the source freeze.

The data interface carries three small render uniforms(time/envelope/motion,
feet/ground, stable seed). Each tile gets an explicit memory flag. The native
Gaussian compute shader invokes `SaskartaDreamGaussian` after trained buffers
are read and before output center, covariance projection and Niagara's native
ViewDepth sorting. Centers are transformed to world centimeters, deformed,
then transformed back to the original system frame. Native anisotropic sigma
and quaternion are preserved, with a positive4% sigma breathing scalar.
The original spherical harmonics are evaluated and slightly desaturated.

This is actual3D Gaussian splatting. Cesium uses Niagara to carry the final
covariance-projected quads and perform depth sorting. It is not a replacement
particle or point-cloud effect. The native Gaussian exponential alpha kernel
remains intact. Memory claim requires its material to be translucent with
depth testing enabled; additive or depth-disabled variants fail closed.

The independent2–8cm drift plus coherent mirage ripple stays under12cm.
Bounds use all transformed box corners and add12cm. The1.5m corridor mask
also accounts for3 sigma kernel radius,4% breathing and12cm motion; foot/ground
opacity is zero. Reduced motion stops translations, mirage, scale breathing
and opacity pulses and retains the envelope fade only.

## Root acceptance after playtest

1. Compile the staged source against local UE5.8.2. Enable the plugin only in
   a controlled source reload. Do not use an arbitrary5.7 binary ZIP.
2. Load/cook `/CesiumForUnreal/GaussianSplatting/GaussianSplatSystem` and
   `M_CesiumSplatMaterial` with a fresh Niagara shader compile; compile hashes
   include both patched shader files. Native asset bytes were not modified.
3. Supply approved trained data from the DataPipeline lane. Verify four source
   fiducials, glTF Y-up/right-handed meters, Cesium's internal1024 precision
   scale and component transform, and world cm masking in the actual map.
4. Inspect center motion before covariance, anisotropic shape and view-dependent
   SH, real mesh depth occlusion(terrain, Samyor, staff, station), reverse views,
   pitch, foot corridor, fading, reduced motion and all interruption cleanup.
5. Verify Standalone and a packaged offline run. Measure maximum65000 active,
   two resident scenes,128MiB combined memory and1.5msGPU1080p targets. These
   are acceptance targets, not measured results. Lower the true Gaussian tier
   to32000/12000 if necessary; do not substitute fake particle primitives.

## Evidence and provenance

Saved/Verification/gaussian_memory_20261001/renderer_integration contains the
official release metadata/source pin, verified archive, original patched-file
backups, source diffs and installed file hashes. Plugin Apache2.0 LICENSE and
all bundled third-party notices are preserved. Modified files carry notices.

Primary sources:

- https://github.com/CesiumGS/cesium-unreal/releases/tag/v2.29.1
- https://cesium.com/learn/cesium-unreal/ref-doc/changes.html
- https://github.com/CesiumGS/cesium-unreal/blob/29ea626a7a5c76f12e49fd22e9628c870740598d/Shaders/Private/CesiumGaussianSplatCompute.usf
- https://github.com/CesiumGS/cesium-unreal/blob/v2.29.1/LICENSE
- https://github.com/nerfstudio-project/gsplat/blob/v1.5.3/LICENSE
- https://docs.gsplat.studio/main/examples/colmap.html
- https://colmap.github.io/format.html
- https://colmap.github.io/license.html

Blocker: real approved scene captures/trained Gaussian assets do not exist yet.
No capture, training, build, test, editor/Hayba mutation or GPU/runtime inspection
was performed during live PIE. Renderer integration is source staged only.
