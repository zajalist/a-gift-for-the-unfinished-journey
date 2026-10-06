#pragma once

#include <algorithm>
#include <array>
#include <cmath>

/** Fixed spatial/lifetime budget. No world, camera, random stream or allocation. */
struct FSaskartaDustBillowLogic
{
    static constexpr int Count = 10;
    static constexpr float MaxDistanceCm = 40000.f;
    struct FShape { float BehindM, SideM, HeightM, WidthM, Phase; int Variant; };
    struct FSample { float X, Y, Z, Width, Height, SpinDegrees, Opacity; int Variant; };
    inline static constexpr std::array<FShape, Count> Shapes{{
        {38.f,-104.f,13.f,40.f,.07f,0}, {34.f,-62.f,17.f,44.f,.42f,3},
        {44.f,-21.f,15.f,42.f,.78f,6}, {36.f, 23.f,21.f,46.f,.24f,1},
        {48.f, 68.f,16.f,40.f,.61f,4}, {40.f,110.f,20.f,44.f,.91f,7},
        {82.f,-77.f,46.f,50.f,.36f,2}, {96.f,-15.f,63.f,56.f,.69f,5},
        {88.f, 52.f,53.f,52.f,.13f,0}, {112.f,112.f,72.f,48.f,.53f,4}
    }};

    static float Smooth(float Value)
    {
        const float T = std::clamp(Value, 0.f, 1.f);
        return T * T * (3.f - 2.f * T);
    }

    static float DistanceOpacity(float DistanceCm)
    {
        if (!std::isfinite(DistanceCm) || DistanceCm <= 0.f) return 0.f;
        // Never fill the lens on approach; fade before the hard render cutoff.
        return Smooth((DistanceCm - 800.f) / 1000.f) * (1.f - Smooth((DistanceCm - 32000.f) / 8000.f));
    }

    static FSample Sample(int Index, float ActiveTimeS, float Near)
    {
        if (Index < 0 || Index >= Count || !std::isfinite(ActiveTimeS) || !std::isfinite(Near)) return {};
        const FShape& Shape = Shapes[Index];
        const float Time = std::max(0.f, ActiveTimeS);
        const float Cycle = 13.f + static_cast<float>(Index % 4) * 1.9f;
        const float U = std::fmod(Time / Cycle + Shape.Phase, 1.f);
        const float Angle = U * 6.28318530718f;
        const float Envelope = Smooth(U / .16f) * Smooth((1.f - U) / .2f) * Smooth(Time / 1.8f);
        const float Width = Shape.WidthM * (0.9f + 0.15f * std::sin(U * 3.14159265359f)) * 100.f;
        return {-(Shape.BehindM + 6.f * U) * 100.f,
                (Shape.SideM + 3.f * std::sin(Angle + Shape.Phase)) * 100.f,
                (Shape.HeightM + 7.f * U) * 100.f,
                Width, Width * .5f, (Shape.Phase - .5f) * 20.f + 8.f * std::sin(Angle),
                (.24f + .15f * std::clamp(Near, 0.f, 1.f)) * Envelope, Shape.Variant};
    }
};
