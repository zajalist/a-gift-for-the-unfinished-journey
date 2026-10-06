# Building `M_PP_CarrierVision`

`build_vision_material.py` builds the robot-vision post-process material in the
live editor through Hayba `python_run`. The shader code itself lives in
`Shaders/CarrierVision.hlsl` (the source of truth). The script embeds it as the
Custom node's code.

| | |
|---|---|
| Asset | `/Game/SaskartaGaea/GameFlow/Materials/M_PP_CarrierVision` |
| Domain / location | Post Process, Scene Color After Tonemapping |
| Graph | Emissive Color ← Custom `CarrierVision` (Float3) with 13 inputs, in order: `UV` ← ScreenPosition.ViewportUV, `ViewSize` ← ViewSize, `Time` ← Time, `SceneColorDummy` ← SceneTexture(PostProcessInput0).Color, 8 scalar parameters, `OpticsTint` ← VectorParameter.RGB |
| Parameters (group `CarrierVision`) | `VisionStart` 0, `VisionMode` 0, `GlitchSeed` 0, `RampTime` 0.8, `OffTime` 0.3, `BootBlack` 0.3, `OnTime` 0.3, `Residual` 1.0, `OpticsTint` (0.78, 0.93, 1.0, 1) |
| Side effects | Creates the asset if it is missing. On a re-run it deletes every expression in it and rebuilds the graph. Saves **only** this package. Starts nothing: no PIE, and no level load. |

## Run it

The editor must be running with Hayba listening on `127.0.0.1:52342`.

### 1. Substitute the HLSL into the script

The script contains exactly one placeholder: the body of
`HLSL_SOURCE = r'''__HLSL__'''`. Replace that literal marker with the full
text of `Shaders/CarrierVision.hlsl`. Use a literal replacement, not a regex.
The script's first statement refuses to run if the substitution is missing.

```bash
node -e "
const fs = require('fs');
const py = fs.readFileSync('Tools/GameFlow/build_vision_material.py', 'utf8');
const hlsl = fs.readFileSync('Shaders/CarrierVision.hlsl', 'utf8');
const parts = py.split('__HLSL__');
if (parts.length !== 2) throw new Error('expected exactly one marker, found ' + (parts.length - 1));
if (hlsl.includes(\"'''\") || hlsl.includes('\\\\')) throw new Error('HLSL must not contain triple quotes or backslashes');
fs.writeFileSync('Saved/GameFlow_build_vision_material.py', parts.join(hlsl));
"
```

The HLSL is written to survive the round trip. It is ASCII only, with no
backslashes, no quote characters and no preprocessor defines. Hayba's policy
scanner also reads the contents of string literals, so the HLSL must not spell
any banned call name either (a file-open call, eval, compile, and so on). Keep
it that way when editing. The substituted script is about 26 KB; the
`python_run` limit is 256 KB.

### 2. Send it through `python_run`

- Via MCP, call Hayba `python_run` with `{ "script": <file contents> }`.
- Via raw TCP, send `{"cmd":"python_run","id":<n>,"params":{"script":<file contents>}}`
  with a 4-byte big-endian length prefix, using the same framing as
  `mcp-tools/hayba-mcp/scripts/probe-blueprint-authoring.mjs` in the Hayba repo.

`python_run` stops the script at 5 s. The script avoids per-node recompiles:
node properties are set with `PropertyAccessChangeNotifyMode.NEVER`, and
`recompile_material` runs once at the end, so the normal run time is well
under the limit. If the deadline does interrupt it after the graph is built,
step 4 still compiles and saves the asset.

### 3. Read the `CV` lines in stdout

Expected output:

```
CV asset=/Game/SaskartaGaea/GameFlow/Materials/M_PP_CarrierVision created=True removed_nodes=0
CV domain=MaterialDomain.MD_POST_PROCESS blendable=BlendableLocation.BL_SCENE_COLOR_AFTER_TONEMAPPING
CV nodes=14 (expect 14)
CV custom output=CustomMaterialOutputType.CMOT_FLOAT3 code_chars=N/N
CV pins=UV<-MaterialExpressionScreenPosition,ViewSize<-MaterialExpressionViewSize,Time<-MaterialExpressionTime,SceneColorDummy<-MaterialExpressionSceneTexture,VisionStart<-MaterialExpressionScalarParameter,...,OpticsTint<-MaterialExpressionVectorParameter
CV failed_links=[] emissive_connect=True emissive_is_custom=True
CV scalars=VisionStart=0.0,VisionMode=0.0,GlitchSeed=0.0,RampTime=0.8,OffTime=0.3,BootBlack=0.3,OnTime=0.3,Residual=1.0
CV tint=0.78,0.93,1.0,1.0
CV recompile_errors=0
CV saved=True
```

A re-run prints `created=False removed_nodes=14`. Any `NONE` in `pins`, or a
non-empty `failed_links`, means a wire did not connect. The material will then
fail with *"Custom material CarrierVision missing input"*.

`recompile_errors` only covers what is known when the call returns
(translation). The HLSL itself is compiled asynchronously, which is why step 4
is required.

### 4. Compile and read the real result: Hayba `material_compile`

```json
{ "material_path": "/Game/SaskartaGaea/GameFlow/Materials/M_PP_CarrierVision" }
```

It returns `{material_path, errors[], has_errors, saved, stats}`. The step is
done when `has_errors` is false and `saved` is true. Record the instruction
count from `stats` for the verification report (spec §Verification 1). For
scale, the offline FXC build of the node inside a mock post-process wrapper
reports about 341 instruction slots and 3 texture samples. UE's own count will
differ.

### 5. Confirm it on disk

`Content/SaskartaGaea/GameFlow/Materials/M_PP_CarrierVision.uasset` exists,
and its modification time is from this run.

## After editing `CarrierVision.hlsl`

Either re-run steps 1–5 (the script is idempotent), or paste the file into the
Custom node's `Code` with Hayba `material_set_node` and then run step 4. In
both cases the `.hlsl` file stays the source of truth: never edit the code
only inside the editor.

## Fallback: `SceneTextureLookup` rejected by the compiler

If `material_compile` reports `SceneTextureLookup` or
`ViewportUVToSceneTextureUV` as undeclared, or as not allowed, move the three
scene fetches into SceneTexture nodes. The look is unchanged, because both
halves run the same deterministic code (same hashes, same seed).

```
                        +-- Custom A --------------+   UVs +----------------+ Color
 same 13 inputs ------> | return (float2) = G UV   |------>| SceneTexture   |-------+
                        | UVR   (Float2 output)    |------>| PostProcess-   |---+   |
                        | UVB   (Float2 output)    |------>| Input0  x3     |-+ |   |
                        +--------------------------+       +----------------+ | |   |
                                                                              v v   v
                        +-- Custom B (Float3) -----------------------------------------+
 same 13 inputs ------> | SceneR, SceneG, SceneB (float4 inputs) + the same 13 inputs  |--> Emissive
                        +---------------------------------------------------------------+
```

1. **Custom A** gets a copy of `CarrierVision.hlsl` with three changes:
   - Delete the `Scene()` method from `FCarrier`.
   - Replace the Black early-out (`return float3(0.0, 0.0, 0.0);`) with
     `UVR = 0.5; UVB = 0.5; return float2(0.5, 0.5);`.
   - Replace everything from the three `c.r / c.g / c.b = F.Scene(...)` lines
     to the end of the file with:
     `UVR = PicUV + OffR; UVB = PicUV + OffB; return PicUV;`

   Set output type Float2, and `AdditionalOutputs` = `UVR` (Float2) and
   `UVB` (Float2). Set `additional_outputs` **with** notification (the default
   mode, not `NEVER`), because `PostEditChangeProperty` is what runs
   `RebuildOutputs()` and creates the named output pins. After that, A's
   outputs are named `return`, `UVR` and `UVB`.
2. Add **three SceneTexture nodes** with `scene_texture_id =
   PPI_POST_PROCESS_INPUT0`. Wire A.`return`, A.`UVR` and A.`UVB` into their
   `Coordinates` pins. When connecting by name through
   `MaterialEditingLibrary`, that pin is called **`UVs`**:
   `GetShortenPinName` maps `Coordinates` → `UVs`. The node treats these
   coordinates as viewport UVs and does the viewport → buffer mapping itself,
   exactly as `ViewportUVToSceneTextureUV` did.
3. **Custom B** is `CarrierVision.hlsl` with `Scene()` deleted and the three
   fetch lines replaced by `c.r = SceneR.r; c.g = SceneG.g; c.b = SceneB.b;`.
   Add inputs `SceneR`, `SceneG` and `SceneB` after the 13 standard inputs, and
   wire in the three nodes' `Color` outputs. Because B now reads those pins by
   name, UE compiles the real fetches for them. `SceneColorDummy` can then be
   dropped from both nodes. B's output goes to Emissive Color.

The cost is the same three fetches plus the timeline ALU run twice, which is
still only a handful of hashes. This recipe was generated mechanically from
the `.hlsl` and compiled offline in a mock of UE's Custom-node wrapper
(A with `inout` UVR/UVB, which is how 5.8 declares additional outputs). It
compiled clean under FXC ps_5_0 and DXC ps_6_6 with warnings as errors:
3 samples, about 412 slots.

## Things verified offline (UE 5.8 sources, 2026-09-26)

- Python names: `MaterialEditingLibrary.{create_material_expression,
  delete_material_expression, get_material_expressions (returns a copy),
  connect_material_expressions, connect_material_property, recompile_material,
  get_inputs_for_material_expression, get_material_expression_input_names,
  get_material_property_input_node, get_num_material_expressions,
  get_material_default_scalar_parameter_value,
  get_material_default_vector_parameter_value}`,
  `EditorAssetLibrary.{does_asset_exist, load_asset, save_loaded_asset}`, and
  `AssetToolsHelpers.get_asset_tools().create_asset(name, path, class,
  factory)`.
- Enum spellings (PyGenUtil `PythonizeName`, where digits stay attached):
  `MaterialDomain.MD_POST_PROCESS`,
  `BlendableLocation.BL_SCENE_COLOR_AFTER_TONEMAPPING`,
  `CustomMaterialOutputType.CMOT_FLOAT3`,
  `SceneTextureId.PPI_POST_PROCESS_INPUT0` (= 14),
  `MaterialProperty.MP_EMISSIVE_COLOR`, `PropertyAccessChangeNotifyMode.NEVER`.
- `unreal.CustomInput` is exported because `UMaterialExpressionCustom::Inputs`
  is an editor property (the type is generated on reference). Its field is
  `input_name`.
- Output names: ScreenPosition `ViewportUV`/`PixelPosition`; SceneTexture
  `Color`/`Size`/`InvSize`; VectorParameter `RGB`/`R`/`G`/`B`/`A`/`RGBA`.
  ViewSize, Time and ScalarParameter have one unnamed output, so pass `''`.
- The unused `SceneColorDummy` pin is compiled with output index 3 (texture
  bound, fetch stripped; `UMaterialExpressionCustom::Compile`). Its name
  appears in the HLSL only inside comments, which the 5.8 identifier scanner
  skips.
- Substrate: `MaterialDomain` stays editable, because hidden legacy-asset
  conversion is always on with Substrate and this material never connects
  `FrontMaterial`.
- The material `Time` node reads `View.GameTime` =
  `ViewFamily.Time.GetWorldTimeSeconds()`. That is the same clock as
  Blueprint `GetTimeSeconds()`, which `BPC_CarrierVision` writes into
  `VisionStart`.
