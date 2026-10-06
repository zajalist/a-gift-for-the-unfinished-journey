// Body of a User Interface material Custom node, output float3.
// Inputs: Atlas(TextureObject), Still(TextureObject), UV(float2), ClockS(float),
// ReducedMotion(float), FrameSize(float2 = 512,288).
// Import atlas/still with sRGB, no mipmaps, clamp addressing. UI opaque black
// backdrop supplies the full screen; this one small image contains no map.
float frame = floor(frac(max(ClockS, 0.0) / 4.0) * 64.0);
float2 cell = float2(fmod(frame, 8.0), floor(frame / 8.0));
float2 margin = 0.5 / FrameSize;
float2 safeUV = clamp(UV, margin, 1.0 - margin);
float2 atlasUV = (cell + safeUV) / 8.0;
float3 animated = Texture2DSample(Atlas, AtlasSampler, atlasUV).rgb;
float3 still = Texture2DSample(Still, StillSampler, safeUV).rgb;
return lerp(animated, still, step(0.5, ReducedMotion));
