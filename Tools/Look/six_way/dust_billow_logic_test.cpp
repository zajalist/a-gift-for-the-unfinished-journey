#include "SaskartaDustBillowLogic.h"

#include <cassert>
#include <iostream>
#include <limits>
#include <set>

using Logic = FSaskartaDustBillowLogic;

static void CheckSample(const Logic::FSample& Value)
{
    for (float Number : {Value.X, Value.Y, Value.Z, Value.Width, Value.Height, Value.SpinDegrees, Value.Opacity})
        assert(std::isfinite(Number));
    assert(Value.Width >= 3600.f && Value.Width <= 5880.01f);
    assert(Value.Height * 2.f == Value.Width);
    assert(Value.Opacity >= 0.f && Value.Opacity <= .390001f);
    assert(Value.Variant >= 0 && Value.Variant < 8);
    // Even a fully rotated quad's bounding sphere stays behind the front.
    const float Radius = .5f * std::hypot(Value.Width, Value.Height);
    assert(Value.X + Radius < -800.f);
    assert(Value.Z >= 1300.f && Value.Z <= 7900.01f);
}

int main()
{
    static_assert(Logic::Count == 10, "Billow draw/component budget changed");
    std::set<int> Variants;
    float MinimumSeparation = std::numeric_limits<float>::max();
    for (int Frame = 0; Frame <= 30000; ++Frame)
    {
        const float Time = static_cast<float>(Frame) * .1f;
        for (int Index = 0; Index < Logic::Count; ++Index)
        {
            const auto Sample = Logic::Sample(Index, Time, static_cast<float>(Frame % 101) * .01f);
            CheckSample(Sample);
            Variants.insert(Sample.Variant);
            const auto Again = Logic::Sample(Index, Time, static_cast<float>(Frame % 101) * .01f);
            assert(Sample.X == Again.X && Sample.Y == Again.Y && Sample.Z == Again.Z);
            assert(Sample.SpinDegrees == Again.SpinDegrees && Sample.Opacity == Again.Opacity);
            if (Frame == 0) assert(Sample.Opacity == 0.f);
            for (int Other = Index + 1; Other < Logic::Count; ++Other)
            {
                const auto B = Logic::Sample(Other, Time, 1.f);
                const float Separation = std::sqrt((Sample.X-B.X)*(Sample.X-B.X)
                    + (Sample.Y-B.Y)*(Sample.Y-B.Y) + (Sample.Z-B.Z)*(Sample.Z-B.Z));
                MinimumSeparation = std::min(MinimumSeparation, Separation);
                assert(Separation > 2500.f); // Distinct world centres, never one stacked screen sheet.
            }
        }
    }
    assert(Variants.size() == 8);
    for (int Index = 0; Index < Logic::Count; ++Index)
    {
        const float Cycle = 13.f + static_cast<float>(Index % 4) * 1.9f;
        const float Wrap = Cycle * (2.f - Logic::Shapes[Index].Phase);
        for (float Offset : {-.001f, 0.f, .001f})
            assert(Logic::Sample(Index, Wrap + Offset, 1.f).Opacity < .00001f);
        assert(Logic::Sample(Index, -100.f, 1.f).Opacity == 0.f);
        CheckSample(Logic::Sample(Index, std::numeric_limits<float>::max(), -100.f));
        CheckSample(Logic::Sample(Index, 1e20f, 100.f));
        assert(Logic::Sample(Index, 100.f, -100.f).Opacity == Logic::Sample(Index, 100.f, 0.f).Opacity);
        assert(Logic::Sample(Index, 100.f, 100.f).Opacity == Logic::Sample(Index, 100.f, 1.f).Opacity);
    }
    const float NaN = std::numeric_limits<float>::quiet_NaN();
    const float Infinity = std::numeric_limits<float>::infinity();
    for (float Invalid : {NaN, Infinity, -Infinity})
    {
        assert(Logic::Sample(0, Invalid, 1.f).Opacity == 0.f);
        assert(Logic::Sample(0, 1.f, Invalid).Opacity == 0.f);
        assert(Logic::DistanceOpacity(Invalid) == 0.f);
    }
    assert(Logic::Sample(-1, 1.f, 1.f).Opacity == 0.f);
    assert(Logic::Sample(Logic::Count, 1.f, 1.f).Opacity == 0.f);
    for (float Distance : {-1.f, 0.f, 800.f, 40000.f, 1000000.f})
        assert(Logic::DistanceOpacity(Distance) == 0.f);
    for (float Distance : {1800.f, 10000.f, 32000.f})
        assert(Logic::DistanceOpacity(Distance) == 1.f);
    for (int Distance = 0; Distance <= 41000; ++Distance)
    {
        const float Opacity = Logic::DistanceOpacity(static_cast<float>(Distance));
        assert(Opacity >= 0.f && Opacity <= 1.f);
    }
    std::cout << "DUST_BILLOW_LOGIC_OK samples=300010 variants=8 min_centres_cm=" << MinimumSeparation << '\n';
}
