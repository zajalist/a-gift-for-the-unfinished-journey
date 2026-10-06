"""Apply the scoped Saskarta memory hooks to the pinned official source once."""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "Plugins/CesiumForUnreal"
EVIDENCE = ROOT / "Saved/Verification/gaussian_memory_20261001/renderer_integration"

def patch(rel, old, new):
    path = PLUGIN / rel
    text = path.read_text()
    if old not in text:
        raise RuntimeError("Pinned source hunk missing: " + rel + " / " + old[:70])
    backup = EVIDENCE / "upstream_before" / rel
    backup.parent.mkdir(parents=True, exist_ok=True)
    if not backup.exists():
        backup.write_bytes(path.read_bytes())
    path.write_text(text.replace(old, new, 1))

di_h = "Source/CesiumRuntime/Private/CesiumGaussianSplatDataInterface.h"
di_cpp = "Source/CesiumRuntime/Private/CesiumGaussianSplatDataInterface.cpp"
sub_h = "Source/CesiumRuntime/Private/CesiumGaussianSplatSubsystem.h"
sub_cpp = "Source/CesiumRuntime/Private/CesiumGaussianSplatSubsystem.cpp"

patch(di_h, "  FReadBuffer TileIndicesBuffer;", "  // Saskarta modification: small copied render-thread uniforms, no Gaussian reupload.\n  FVector4f MemoryControl = FVector4f(0, 0, 1, 0);\n  FVector4f MemoryFeetGround = FVector4f(0, 0, 0, 0);\n  uint32 MemorySeed = 0;\n\n  FReadBuffer TileIndicesBuffer;")
patch(di_h, "SHADER_PARAMETER_SRV(Buffer<uint>, TileIndices)", "SHADER_PARAMETER(FVector4f, MemoryControl)\nSHADER_PARAMETER(FVector4f, MemoryFeetGround)\nSHADER_PARAMETER(uint32, MemorySeed)\nSHADER_PARAMETER_SRV(Buffer<uint>, TileIndices)")
patch(di_h, "  void MarkDirty();", "  void MarkDirty();\n  void SetMemoryUniforms(FVector4f Control, FVector4f FeetGround, uint32 Seed);")
patch(di_cpp, '#include "CesiumRuntime.h"', '#include "CesiumRuntime.h"\n// Saskarta modification: identify only explicit memory tilesets.\n#include "CesiumGaussianMemoryTileset.h"')
patch(di_cpp, "  // Each tile corresponds to ten vectors:", "  // Saskarta modification: each tile has eleven vectors; row10 identifies memories.\n  // Original ten vectors:")
patch(di_cpp, "  const int32 vectorsPerComponent = 10;", "  const int32 vectorsPerComponent = 11;")
patch(di_cpp, "        static_cast<float>(tileRotation.W));", "        static_cast<float>(tileRotation.W));\n    pBufferData[Offset + 10] = FVector4f(\n        Cast<ACesiumGaussianMemoryTileset>(pComponent->GetOwner()) ? 1.f : 0.f, 0.f, 0.f, 0.f);")
patch(di_cpp, "  UNiagaraDataInterface::GetParameterDefinitionHLSL(ParamInfo, OutHLSL);", "  UNiagaraDataInterface::GetParameterDefinitionHLSL(ParamInfo, OutHLSL);\n  OutHLSL.Appendf(TEXT(\"float4 %s_MemoryControl;\\nfloat4 %s_MemoryFeetGround;\\nuint %s_MemorySeed;\\n\"),\n      *ParamInfo.DataInterfaceHLSLSymbol, *ParamInfo.DataInterfaceHLSLSymbol, *ParamInfo.DataInterfaceHLSLSymbol);")
patch(di_cpp, "        {TEXT(\"FunctionName\"), FStringFormatArg(FunctionInfo.InstanceName)},", "        {TEXT(\"FunctionName\"), FStringFormatArg(FunctionInfo.InstanceName)},\n        {TEXT(\"MemoryControl\"), FStringFormatArg(ParamInfo.DataInterfaceHLSLSymbol + TEXT(\"_MemoryControl\"))},\n        {TEXT(\"MemoryFeetGround\"), FStringFormatArg(ParamInfo.DataInterfaceHLSLSymbol + TEXT(\"_MemoryFeetGround\"))},\n        {TEXT(\"MemorySeed\"), FStringFormatArg(ParamInfo.DataInterfaceHLSLSymbol + TEXT(\"_MemorySeed\"))},")
patch(di_cpp, "  bSuccess &= InVisitor->UpdateShaderParameters<FGaussianSplatShaderParams>();", "  bSuccess &= InVisitor->UpdateShaderParameters<FGaussianSplatShaderParams>();\n  // Include source modifications in Niagara's shader cache key.\n  bSuccess &= InVisitor->UpdateShaderFile(TEXT(\"/Plugin/CesiumForUnreal/Private/CesiumGaussianSplatCompute.usf\"));\n  bSuccess &= InVisitor->UpdateShaderFile(TEXT(\"/Plugin/CesiumForUnreal/Private/SaskartaMemoryGaussianDream.ush\"));")
patch(di_cpp, "  Params->TileIndices =", "  Params->MemoryControl = DIProxy.MemoryControl;\n  Params->MemoryFeetGround = DIProxy.MemoryFeetGround;\n  Params->MemorySeed = DIProxy.MemorySeed;\n  Params->TileIndices =")
patch(di_cpp, "    if (pSplatComponent->GetWorld() != pWorld) {", "    if (pSplatComponent->GetWorld() != pWorld || !pSplatSystem->ShouldRenderMemoryComponent(pSplatComponent)) {")
patch(di_cpp, "void UCesiumGaussianSplatDataInterface::MarkTilesDirty() {", "// Saskarta modification: update three tiny uniforms without pausing Niagara or reallocating trained buffers.\nvoid UCesiumGaussianSplatDataInterface::SetMemoryUniforms(FVector4f Control, FVector4f FeetGround, uint32 Seed) {\n  auto* RTProxy = GetProxyAs<FNiagaraDataInterfaceProxyCesiumGaussianSplats>();\n  ENQUEUE_RENDER_COMMAND(FSaskartaGaussianMemoryUniforms)\n  ([RTProxy, Control, FeetGround, Seed](FRHICommandListImmediate&) {\n    RTProxy->MemoryControl = Control;\n    RTProxy->MemoryFeetGround = FeetGround;\n    RTProxy->MemorySeed = Seed;\n  });\n}\n\nvoid UCesiumGaussianSplatDataInterface::MarkTilesDirty() {")

patch(sub_h, "class UCesiumGaussianSplatSubsystem :", "class UCesiumGaussianSplatSubsystem :")
patch(sub_h, "  void RecomputeBounds();", "  void RecomputeBounds();\n\n  // Saskarta modification: one explicit trained memory, capped at65k Gaussians.\n  bool ClaimMemory(class ACesiumGaussianMemoryTileset* Owner);\n  void ReleaseMemory(class ACesiumGaussianMemoryTileset* Owner);\n  void UpdateMemoryUniforms(class ACesiumGaussianMemoryTileset* Owner);\n  int32 GetMemoryGaussianCount(const AActor* Owner) const;\n  bool ShouldRenderMemoryComponent(const UCesiumGltfGaussianSplatComponent* Component) const;\n  int32 GetRenderableSplatCount(UWorld* World) const;")
patch(sub_h, "  int32 _splatCount = 0;", "  TWeakObjectPtr<class ACesiumGaussianMemoryTileset> _memoryOwner;\n  int32 _splatCount = 0;")
patch(sub_cpp, '#include "CesiumRuntime.h"', '#include "CesiumRuntime.h"\n// Saskarta modification: source Gaussian memory controls.\n#include "CesiumGaussianMemoryTileset.h"')
patch(sub_cpp, "    FBox TransformedBounds{\n        ComponentTransform.TransformPosition(ActorBounds.Min),\n        ComponentTransform.TransformPosition(ActorBounds.Max)};", "    // Transform all box corners and include the bounded dream displacement.\n    FBox TransformedBounds = ActorBounds.TransformBy(ComponentTransform).ExpandBy(12.0);")
patch(sub_cpp, "  this->SplatComponents.Add(Component);", "  if (SplatComponents.Contains(Component)) return;\n  if (Cast<ACesiumGaussianMemoryTileset>(Component->GetOwner())\n      && GetMemoryGaussianCount(Component->GetOwner()) + Component->Data.NumSplats > 65000) {\n    UE_LOG(LogCesium, Error, TEXT(\"Gaussian memory rejected:65k trained Gaussian cap exceeded\"));\n    return;\n  }\n  this->SplatComponents.Add(Component);")
patch(sub_cpp, "  this->SplatComponents.Remove(Component);", "  if (!this->SplatComponents.Contains(Component)) return;\n  this->SplatComponents.Remove(Component);")
patch(sub_cpp, "        this->_splatCount);", "        this->GetRenderableSplatCount(pWorld));")
patch(sub_cpp, "  this->SplatComponents.Empty();", "  this->_memoryOwner.Reset();\n  this->SplatComponents.Empty();")
path = PLUGIN / sub_cpp
with path.open('a') as f:
 f.write('''
// Saskarta modification: one memory owner; hidden resident data is not sorted/rendered.
int32 UCesiumGaussianSplatSubsystem::GetMemoryGaussianCount(const AActor* Owner) const {
  int32 Count = 0;
  for (const auto* C : SplatComponents) if (C && C->GetOwner() == Owner) Count += C->Data.NumSplats;
  return Count;
}

bool UCesiumGaussianSplatSubsystem::ShouldRenderMemoryComponent(const UCesiumGltfGaussianSplatComponent* C) const {
  const auto* Memory = Cast<ACesiumGaussianMemoryTileset>(C->GetOwner());
  return !Memory || Memory == _memoryOwner.Get();
}

int32 UCesiumGaussianSplatSubsystem::GetRenderableSplatCount(UWorld* World) const {
  int32 Count = 0;
  for (const auto* C : SplatComponents)
    if (C && C->GetWorld() == World && ShouldRenderMemoryComponent(C)) Count += C->Data.NumSplats;
  return Count;
}

bool UCesiumGaussianSplatSubsystem::ClaimMemory(ACesiumGaussianMemoryTileset* Owner) {
  if (!IsValid(Owner) || Owner->GetWorld() != GetPrimaryWorld()
      || (_memoryOwner.IsValid() && _memoryOwner.Get() != Owner)
      || GetMemoryGaussianCount(Owner) < 1 || GetMemoryGaussianCount(Owner) > 65000) return false;
  if (_memoryOwner.Get() != Owner) {
    _memoryOwner = Owner;
    makeInterfaceDirty();
    RecomputeBounds();
  }
  UpdateMemoryUniforms(Owner);
  return true;
}

void UCesiumGaussianSplatSubsystem::ReleaseMemory(ACesiumGaussianMemoryTileset* Owner) {
  if (_memoryOwner.Get() != Owner) return;
  if (auto* DI = getDataInterface()) DI->SetMemoryUniforms(FVector4f(0,0,1,0), FVector4f(0,0,0,0), 0);
  _memoryOwner.Reset();
  makeInterfaceDirty();
}

void UCesiumGaussianSplatSubsystem::UpdateMemoryUniforms(ACesiumGaussianMemoryTileset* Owner) {
  if (!IsValid(Owner) || _memoryOwner.Get() != Owner || Owner->GetWorld() != _pLastCreatedWorld) return;
  if (auto* DI = getDataInterface()) DI->SetMemoryUniforms(
      FVector4f(Owner->MemoryClockS, Owner->MemoryEnvelope, Owner->bMemoryReducedMotion ? 1.f : 0.f, 1.f),
      FVector4f(float(Owner->MemoryFeetCm.X),float(Owner->MemoryFeetCm.Y),float(Owner->MemoryFeetCm.Z),Owner->MemoryGroundZCm),
      Owner->MemorySeed);
}
''')

shader = "Shaders/Private/CesiumGaussianSplatCompute.usf"
patch(shader, "void {FunctionName}(", '// Saskarta modification: drift trained3D centers before covariance projection/sorting.\n#include "/Plugin/CesiumForUnreal/Private/SaskartaMemoryGaussianDream.ush"\n\nvoid {FunctionName}(')
patch(shader, "  const int TileTransformsStride = 10;", "  const int TileTransformsStride = 11;")
patch(shader, "  float4 InColor = {ColorsBuffer}[Index];", "  float4 InColor = {ColorsBuffer}[Index];\n  bool IsMemory = {TileTransformsBuffer}[TileIndex * TileTransformsStride + 10].x > 0.5;\n  if (IsMemory) {\n    float3 OriginalWorldCm = mul(float4(InPosition, 1.0), M_SystemLocalToWorld).xyz;\n    float3 DreamWorldCm, DreamSigmaCm;\n    float DreamOpacity;\n    uint StableId = uint(Index) - {SHDegrees}[TileIndex * 3 + 2];\n    SaskartaDreamGaussian(StableId ^ {MemorySeed}, {MemoryControl}.x,\n        {MemoryControl}.y * {MemoryControl}.w, {MemoryControl}.z,\n        OriginalWorldCm, InScale, InColor.a, {MemoryFeetGround}.xyz, {MemoryFeetGround}.w,\n        DreamWorldCm, DreamSigmaCm, DreamOpacity);\n    InPosition = mul(float4(DreamWorldCm, 1.0), M_SystemWorldToLocal).xyz;\n    InScale = DreamSigmaCm;\n    InColor.a = DreamOpacity;\n  }")
patch(shader, "    OutColor = InColor + float4(SHColor, 0.0);", "    OutColor = InColor + float4(SHColor, 0.0);\n    if (IsMemory) {\n      float Grey = dot(OutColor.rgb, float3(.2126, .7152, .0722));\n      OutColor.rgb = lerp(Grey.xxx, OutColor.rgb, .65);\n    }")

helper = (ROOT / "Tools/EndingFocus/MemoryGaussianDream.ush").read_text()
helper = helper.replace('// Prepared renderer helper, not installed or compiled.', '// Saskarta modification: installed source hook; compilation/rendering not yet verified.')
helper = helper.replace('float pathDistanceCm = length(OriginalCentreCm.xy - SamyorFeetCm.xy);', 'float kernelRadiusCm = 3.0 * max(OriginalSigmaCm.x, max(OriginalSigmaCm.y, OriginalSigmaCm.z)) * 1.04 + 12.0;\n    float pathDistanceCm = length(OriginalCentreCm.xy - SamyorFeetCm.xy) - kernelRadiusCm;')
helper = helper.replace('OriginalCentreCm.z - LocalGroundZCm);', 'OriginalCentreCm.z - LocalGroundZCm - kernelRadiusCm);')
(PLUGIN / "Shaders/Private/SaskartaMemoryGaussianDream.ush").write_text('#ifndef SASKARTA_MEMORY_GAUSSIAN_DREAM\n#define SASKARTA_MEMORY_GAUSSIAN_DREAM\n' + helper + '\n#endif\n')

build = "Source/CesiumRuntime/CesiumRuntime.Build.cs"
patch(build, '        PublicAdditionalLibraries.AddRange(allLibs);', '''        // Saskarta modification: local reviewed true Gaussian datasets are staged loose.
        // Cesium's async file:// accessor can open them in packaged builds without ion/network.
        string memories = Path.Combine(PluginDirectory, "Resources", "GaussianMemories");
        if (Directory.Exists(memories))
            foreach (string memoryFile in Directory.GetFiles(memories, "*", SearchOption.AllDirectories))
                RuntimeDependencies.Add(memoryFile, StagedFileType.NonUFS);

        PublicAdditionalLibraries.AddRange(allLibs);''')
descriptor = PLUGIN / 'CesiumForUnreal.uplugin'
d = json.loads(descriptor.read_text()); d['EnabledByDefault'] = False
descriptor.write_text(json.dumps(d, indent=2) + '\n')
print('Source Gaussian hooks installed; plugin remains disabled by default. No compile/render executed.')
