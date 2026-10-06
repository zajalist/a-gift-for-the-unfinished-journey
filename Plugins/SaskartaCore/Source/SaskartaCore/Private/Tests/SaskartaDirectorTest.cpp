// Automation tests for USaskartaLightingDirector and USaskartaReadiness (Task L7).
//
// Ruling R33: written offline with the implementation (fail-first waived); the morning
// session builds the module and runs them:
//   Automation RunTests Saskarta.Director
//   Automation RunTests Saskarta.Readiness
// Saskarta.Director.LookKeysAsset needs DA_Saskarta_LookKeys, so run
// Tools/Look/build_look_keys_asset.py build first.
//
// Key comparisons walk FSaskartaLookKey by reflection, so every blended field is checked
// and a field added later is covered without editing the test.

#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "Engine/World.h"
#include "SaskartaLightingDirector.h"
#include "SaskartaLookKeys.h"
#include "SaskartaReadiness.h"
#include "UObject/UnrealType.h"

namespace SaskartaDirectorTest
{
    static constexpr int32 FloatFieldCount = 20; // every float UPROPERTY of FSaskartaLookKey

    /** A key whose every float field is Base + its field index, and FogColor (Base, Base+1, Base+2). */
    static FSaskartaLookKey MakeKey(FName Name, float RoadM, float Base)
    {
        FSaskartaLookKey K;
        int32 Index = 0;
        for (TFieldIterator<FProperty> It(FSaskartaLookKey::StaticStruct()); It; ++It)
        {
            if (const FFloatProperty* F = CastField<FFloatProperty>(*It))
            {
                F->SetPropertyValue_InContainer(&K, Base + static_cast<float>(Index++));
            }
        }
        K.Name = Name;
        K.RoadM = RoadM;
        K.FogColor = FLinearColor(Base, Base + 1.f, Base + 2.f, 1.f);
        return K;
    }

    /** Field-wise linear interpolation, the reference the blend must match (yaw kept small). */
    static FSaskartaLookKey LerpByReflection(const FSaskartaLookKey& A, const FSaskartaLookKey& B, float T)
    {
        FSaskartaLookKey R = A;
        for (TFieldIterator<FProperty> It(FSaskartaLookKey::StaticStruct()); It; ++It)
        {
            if (const FFloatProperty* F = CastField<FFloatProperty>(*It))
            {
                const float VA = F->GetPropertyValue_InContainer(&A);
                const float VB = F->GetPropertyValue_InContainer(&B);
                F->SetPropertyValue_InContainer(&R, VA + (VB - VA) * T);
            }
        }
        R.FogColor = A.FogColor + (B.FogColor - A.FogColor) * T;
        return R;
    }

    /** Tolerance 0 means bit-exact. Returns the number of float fields compared. */
    static int32 ExpectKeysMatch(FAutomationTestBase& Test, const FString& What,
        const FSaskartaLookKey& Actual, const FSaskartaLookKey& Expected, float Tolerance)
    {
        auto Same = [Tolerance](float A, float E)
        {
            return Tolerance == 0.f ? A == E : FMath::IsNearlyEqual(A, E, Tolerance);
        };
        int32 Compared = 0;
        for (TFieldIterator<FProperty> It(FSaskartaLookKey::StaticStruct()); It; ++It)
        {
            if (const FFloatProperty* F = CastField<FFloatProperty>(*It))
            {
                ++Compared;
                const float A = F->GetPropertyValue_InContainer(&Actual);
                const float E = F->GetPropertyValue_InContainer(&Expected);
                if (!Same(A, E))
                {
                    Test.AddError(FString::Printf(TEXT("%s: %s = %.7f, expected %.7f"), *What, *F->GetName(), A, E));
                }
            }
        }
        const FLinearColor& CA = Actual.FogColor;
        const FLinearColor& CE = Expected.FogColor;
        if (!Same(CA.R, CE.R) || !Same(CA.G, CE.G) || !Same(CA.B, CE.B) || !Same(CA.A, CE.A))
        {
            Test.AddError(FString::Printf(TEXT("%s: FogColor = %s, expected %s"), *What, *CA.ToString(), *CE.ToString()));
        }
        return Compared;
    }
}

// ---------------------------------------------------------------------------- key blend

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaDirectorKeyBlendTest, "Saskarta.Director.KeyBlend",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaDirectorKeyBlendTest::RunTest(const FString&)
{
    using namespace SaskartaDirectorTest;
    const FSaskartaLookKey A = MakeKey(TEXT("A"), 0.f, 1.f);
    const FSaskartaLookKey B = MakeKey(TEXT("B"), 100.f, 5.f);
    const FSaskartaLookKey C = MakeKey(TEXT("C"), 300.f, 11.f);
    const TArray<FSaskartaLookKey> Keys = { A, B, C };

    // Exact at every key's road metre.
    const int32 Compared = ExpectKeysMatch(*this, TEXT("at A"), USaskartaLightingDirector::BlendKeys(Keys, 0.f), A, 0.f);
    TestEqual(TEXT("every float field compared"), Compared, FloatFieldCount);
    ExpectKeysMatch(*this, TEXT("at B"), USaskartaLightingDirector::BlendKeys(Keys, 100.f), B, 0.f);
    ExpectKeysMatch(*this, TEXT("at C"), USaskartaLightingDirector::BlendKeys(Keys, 300.f), C, 0.f);
    TestEqual(TEXT("name at B"), USaskartaLightingDirector::BlendKeys(Keys, 100.f).Name.ToString(), FString(TEXT("B")));

    // Linear between neighbours.
    ExpectKeysMatch(*this, TEXT("A..B 25%"), USaskartaLightingDirector::BlendKeys(Keys, 25.f), LerpByReflection(A, B, 0.25f), 1e-4f);
    ExpectKeysMatch(*this, TEXT("A..B 50%"), USaskartaLightingDirector::BlendKeys(Keys, 50.f), LerpByReflection(A, B, 0.5f), 1e-4f);
    ExpectKeysMatch(*this, TEXT("B..C 50%"), USaskartaLightingDirector::BlendKeys(Keys, 200.f), LerpByReflection(B, C, 0.5f), 1e-4f);
    ExpectKeysMatch(*this, TEXT("B..C 90%"), USaskartaLightingDirector::BlendKeys(Keys, 280.f), LerpByReflection(B, C, 0.9f), 1e-4f);

    // Clamped outside the keys.
    ExpectKeysMatch(*this, TEXT("before A"), USaskartaLightingDirector::BlendKeys(Keys, -50.f), A, 0.f);
    ExpectKeysMatch(*this, TEXT("after C"), USaskartaLightingDirector::BlendKeys(Keys, 5000.f), C, 0.f);

    // Yaw takes the shortest arc: 350 -> 10 passes through 0, not 180.
    FSaskartaLookKey Y0 = A; Y0.SunYaw = 350.f;
    FSaskartaLookKey Y1 = B; Y1.SunYaw = 10.f;
    const float MidYaw = USaskartaLightingDirector::BlendKeys({ Y0, Y1 }, 50.f).SunYaw;
    TestTrue(TEXT("yaw shortest arc"), FMath::IsNearlyEqual(FRotator::NormalizeAxis(MidYaw), 0.f, 1e-3f));

    // Empty and single-key inputs.
    TestEqual(TEXT("single key"), USaskartaLightingDirector::BlendKeys({ B }, 999.f).RoadM, 100.f);
    USaskartaLightingDirector::BlendKeys(TArray<FSaskartaLookKey>(), 10.f); // must not crash
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaDirectorSmoothingTest, "Saskarta.Director.Smoothing",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaDirectorSmoothingTest::RunTest(const FString&)
{
    // 25 s of 0.5 s steps toward a 1000 m jump covers 1 - 1/e of it (the time constant).
    float M = 0.f;
    const int32 Steps = FMath::RoundToInt(USaskartaLightingDirector::SmoothingTauS / USaskartaLightingDirector::BlendIntervalS);
    TestEqual(TEXT("50 steps in 25 s"), Steps, 50);
    for (int32 i = 0; i < Steps; ++i)
    {
        M = USaskartaLightingDirector::SmoothTowards(M, 1000.f, USaskartaLightingDirector::BlendIntervalS, USaskartaLightingDirector::SmoothingTauS);
    }
    TestNearlyEqual(TEXT("one time constant"), M, 1000.f * (1.f - FMath::Exp(-1.f)), 0.5f);
    // A 20 m respawn move shifts the look by well under a metre in one tick.
    const float Step = USaskartaLightingDirector::SmoothTowards(0.f, 20.f, 0.5f, 25.f);
    TestTrue(TEXT("respawn step small"), Step > 0.f && Step < 0.5f);
    TestEqual(TEXT("tau 0 snaps"), USaskartaLightingDirector::SmoothTowards(3.f, 7.f, 0.5f, 0.f), 7.f);
    return true;
}

// ---------------------------------------------------------------------------- lightning

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaDirectorThunderTest, "Saskarta.Director.Thunder",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaDirectorThunderTest::RunTest(const FString&)
{
    TestNearlyEqual(TEXT("343 m -> 1 s"), USaskartaLightingDirector::ThunderDelaySeconds(343.f), 1.f, 1e-6f);
    for (const float D : { 1000.f, 2500.f, 4321.f, 8000.f })
    {
        TestNearlyEqual(*FString::Printf(TEXT("delay at %.0f m"), D),
            USaskartaLightingDirector::ThunderDelaySeconds(D), D / 343.f, 1e-5f);
    }
    TestNearlyEqual(TEXT("8 km -> 23.32 s"), USaskartaLightingDirector::ThunderDelaySeconds(8000.f), 23.3236f, 1e-3f);
    TestTrue(TEXT("1 km close"), USaskartaLightingDirector::IsCloseStrike(1000.f));
    TestTrue(TEXT("2499 m close"), USaskartaLightingDirector::IsCloseStrike(2499.f));
    TestFalse(TEXT("2500 m rolling"), USaskartaLightingDirector::IsCloseStrike(2500.f));
    TestFalse(TEXT("8 km rolling"), USaskartaLightingDirector::IsCloseStrike(8000.f));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaDirectorLightningTest, "Saskarta.Director.Lightning",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaDirectorLightningTest::RunTest(const FString&)
{
    // Flash: 0.08 s up, 0.4 s down.
    TestEqual(TEXT("flash t0"), USaskartaLightingDirector::FlashEnvelope(0.f), 0.f);
    TestNearlyEqual(TEXT("flash rising"), USaskartaLightingDirector::FlashEnvelope(0.04f), 0.5f, 1e-4f);
    TestNearlyEqual(TEXT("flash peak"), USaskartaLightingDirector::FlashEnvelope(0.08f), 1.f, 1e-4f);
    TestNearlyEqual(TEXT("flash falling"), USaskartaLightingDirector::FlashEnvelope(0.28f), 0.5f, 1e-4f);
    TestNearlyEqual(TEXT("flash end"), USaskartaLightingDirector::FlashEnvelope(0.48f), 0.f, 1e-4f);
    TestEqual(TEXT("flash after"), USaskartaLightingDirector::FlashEnvelope(1.f), 0.f);

    // Interval: 8-35 s at the reference intensity, shorter when stormier, clamped.
    TestNearlyEqual(TEXT("min at 0.45"), USaskartaLightingDirector::NextLightningIntervalS(0.f, 0.45f), 8.f, 1e-3f);
    TestNearlyEqual(TEXT("max at 0.45"), USaskartaLightingDirector::NextLightningIntervalS(1.f, 0.45f), 35.f, 1e-3f);
    TestNearlyEqual(TEXT("stormy halves"), USaskartaLightingDirector::NextLightningIntervalS(0.f, 0.9f), 4.f, 1e-3f);
    TestNearlyEqual(TEXT("calm x1.5"), USaskartaLightingDirector::NextLightningIntervalS(1.f, 0.3f), 52.5f, 1e-3f);
    TestTrue(TEXT("threshold 0.3"), USaskartaLightingDirector::LightningMinIntensity == 0.3f);
    return true;
}

// ---------------------------------------------------------------------------- the real keys

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaDirectorLookKeysAssetTest, "Saskarta.Director.LookKeysAsset",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaDirectorLookKeysAssetTest::RunTest(const FString&)
{
    const USaskartaLookKeys* Asset = LoadObject<USaskartaLookKeys>(nullptr,
        TEXT("/Game/SaskartaGaea/Look/DA_Saskarta_LookKeys.DA_Saskarta_LookKeys"));
    if (!TestNotNull(TEXT("DA_Saskarta_LookKeys (run Tools/Look/build_look_keys_asset.py build)"), Asset))
    {
        return false;
    }
    const TArray<FSaskartaLookKey>& Keys = Asset->Keys;
    const TArray<FName> Names = { TEXT("Valley"), TEXT("ValleyHold"), TEXT("Ridge"), TEXT("BasinPeak"),
        TEXT("BasinHold"), TEXT("Cistern"), TEXT("CisternHold"), TEXT("Stair"), TEXT("InCloud"), TEXT("PreDawn") };
    const TArray<float> Metres = { 0.f, 900.f, 1500.f, 2150.f, 2700.f, 2950.f, 3250.f, 3650.f, 4350.f, 4550.f };
    TestEqual(TEXT("ten authored keys"), Keys.Num(), Names.Num());
    for (int32 i = 0; i < FMath::Min(Keys.Num(), Names.Num()); ++i)
    {
        TestEqual(*FString::Printf(TEXT("name %d"), i), Keys[i].Name.ToString(), Names[i].ToString());
        TestEqual(*FString::Printf(TEXT("road m %d"), i), Keys[i].RoadM, Metres[i]);
        SaskartaDirectorTest::ExpectKeysMatch(*this, Names[i].ToString(),
            USaskartaLightingDirector::BlendKeys(Keys, Keys[i].RoadM), Keys[i], 0.f);
    }
    if (Keys.Num() == Names.Num())
    {
        TestNearlyEqual(TEXT("Valley storm"), Keys[0].StormIntensity, 0.28f, 1e-5f);
        TestNearlyEqual(TEXT("Basin peak storm"), Keys[3].StormIntensity, 1.f, 1e-5f);
        TestNearlyEqual(TEXT("Above clear grade"), Keys[9].GradeClearWeight, 1.f, 1e-5f);
        // Stair (3650 m) to InCloud (4350 m): the midpoint must blend both authored values.
        const FSaskartaLookKey Mid = USaskartaLightingDirector::BlendKeys(Keys, 4000.f);
        TestNearlyEqual(TEXT("mid fog density"), Mid.FogDensity, (Keys[7].FogDensity + Keys[8].FogDensity) * 0.5f, 1e-5f);
    }
    return true;
}

// ---------------------------------------------------------------------------- readiness

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaReadinessFieldsTest, "Saskarta.Readiness.Fields",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaReadinessFieldsTest::RunTest(const FString&)
{
    // The struct carries exactly the spec's six fields, with these types.
    const UScriptStruct* S = FSaskartaReadinessState::StaticStruct();
    TestNotNull(TEXT("bStreamingComplete"), CastField<FBoolProperty>(S->FindPropertyByName(TEXT("bStreamingComplete"))));
    TestNotNull(TEXT("bPCGIdle"), CastField<FBoolProperty>(S->FindPropertyByName(TEXT("bPCGIdle"))));
    TestNotNull(TEXT("PendingPSOs"), CastField<FIntProperty>(S->FindPropertyByName(TEXT("PendingPSOs"))));
    TestNotNull(TEXT("bTexturesSettled"), CastField<FBoolProperty>(S->FindPropertyByName(TEXT("bTexturesSettled"))));
    TestNotNull(TEXT("bGrassSettled"), CastField<FBoolProperty>(S->FindPropertyByName(TEXT("bGrassSettled"))));
    TestNotNull(TEXT("Fraction"), CastField<FFloatProperty>(S->FindPropertyByName(TEXT("Fraction"))));
    int32 Count = 0;
    for (TFieldIterator<FProperty> It(S); It; ++It) { ++Count; }
    TestEqual(TEXT("six fields"), Count, 6);

    // No world: every field is filled (sentinels replaced), nothing world-bound is ready.
    const FSaskartaReadinessState None = USaskartaReadiness::GetReadiness(nullptr, FVector::ZeroVector);
    TestTrue(TEXT("no world: PendingPSOs filled"), None.PendingPSOs >= 0);
    TestTrue(TEXT("no world: Fraction filled"), None.Fraction >= 0.f && None.Fraction <= 1.f);
    TestFalse(TEXT("no world: streaming"), None.bStreamingComplete);
    TestFalse(TEXT("no world: pcg"), None.bPCGIdle);
    TestFalse(TEXT("no world: grass"), None.bGrassSettled);
    TestEqual(TEXT("no world: fraction"), None.Fraction, USaskartaReadiness::ComputeFraction(None));

    // An empty game world: no World Partition and no PCG, so those are ready; grass needs 1 s of history.
    UWorld* World = UWorld::CreateWorld(EWorldType::Game, /*bInformEngineOfWorld*/ false);
    if (!TestNotNull(TEXT("test world"), World))
    {
        return false;
    }
    const FSaskartaReadinessState R = USaskartaReadiness::GetReadiness(World, FVector::ZeroVector);
    TestTrue(TEXT("streaming complete (no WP)"), R.bStreamingComplete);
    TestTrue(TEXT("pcg idle"), R.bPCGIdle);
    TestTrue(TEXT("PendingPSOs filled"), R.PendingPSOs >= 0);
    TestFalse(TEXT("grass not yet settled (first sample)"), R.bGrassSettled);
    TestTrue(TEXT("Fraction in 0..1"), R.Fraction >= 0.f && R.Fraction <= 1.f);
    TestEqual(TEXT("Fraction matches fields"), R.Fraction, USaskartaReadiness::ComputeFraction(R));
    TestTrue(TEXT("no instances in an empty world"), USaskartaReadiness::CountInstancesNear(World, FVector::ZeroVector, 20000.f) == 0);
    World->DestroyWorld(false);

    // Fraction and the timeout description.
    FSaskartaReadinessState All;
    All.bStreamingComplete = All.bPCGIdle = All.bTexturesSettled = All.bGrassSettled = true;
    All.PendingPSOs = 0;
    TestEqual(TEXT("all met"), USaskartaReadiness::ComputeFraction(All), 1.f);
    TestEqual(TEXT("nothing unmet"), USaskartaReadiness::DescribeUnmet(All), FString());
    FSaskartaReadinessState Two = All;
    Two.bPCGIdle = false;
    Two.PendingPSOs = 12;
    Two.bTexturesSettled = false;
    TestNearlyEqual(TEXT("two of five"), USaskartaReadiness::ComputeFraction(Two), 0.4f, 1e-6f);
    TestEqual(TEXT("unmet listed"), USaskartaReadiness::DescribeUnmet(Two), FString(TEXT("pcg, psos(12), textures")));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaReadinessGrassStabilityTest, "Saskarta.Readiness.GrassStability",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaReadinessGrassStabilityTest::RunTest(const FString&)
{
    int64 Last = -1;
    double Changed = 0.0;
    const double Stable = USaskartaReadiness::GrassStableS;
    TestFalse(TEXT("first sample"), USaskartaReadiness::UpdateStability(500, 10.0, Last, Changed, Stable));
    TestFalse(TEXT("same count, 0.5 s"), USaskartaReadiness::UpdateStability(500, 10.5, Last, Changed, Stable));
    TestTrue(TEXT("same count, 1.0 s"), USaskartaReadiness::UpdateStability(500, 11.0, Last, Changed, Stable));
    TestFalse(TEXT("count changed"), USaskartaReadiness::UpdateStability(620, 11.25, Last, Changed, Stable));
    TestFalse(TEXT("0.75 s after change"), USaskartaReadiness::UpdateStability(620, 12.0, Last, Changed, Stable));
    TestTrue(TEXT("1.25 s after change"), USaskartaReadiness::UpdateStability(620, 12.5, Last, Changed, Stable));
    TestTrue(TEXT("history keeps the count"), Last == 620);
    return true;
}

// ---------------------------------------------------------------------------- CPPBATCH: overrides

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaDirectorOverrideTest, "Saskarta.Director.Overrides", EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaDirectorOverrideTest::RunTest(const FString&)
{
    using namespace SaskartaDirectorTest;
    const FSaskartaLookKey Road = MakeKey(TEXT("Valley"), 0.f, 1.f);
    const FSaskartaLookKey Cine = MakeKey(TEXT("CineDawnHold"), 900.f, 5.f);

    // Alpha 0: the road look untouched (fog x1, no storm pin).
    const FSaskartaLookKey R0 = USaskartaLightingDirector::ComposeLook(Road, Cine, 0.f, 1.f, -1.f);
    TestEqual("alpha 0 keeps the road name", R0.Name, Road.Name);
    TestEqual("alpha 0 keeps the road fog", R0.FogDensity, Road.FogDensity);
    TestEqual("alpha 0 keeps the storm", R0.StormIntensity, Road.StormIntensity);

    // Alpha 1: the override (name too), road m stays the road's.
    const FSaskartaLookKey R1 = USaskartaLightingDirector::ComposeLook(Road, Cine, 1.f, 1.f, -1.f);
    TestEqual("alpha 1 name", R1.Name, Cine.Name);
    TestEqual("alpha 1 sun", R1.SunIntensityLux, Cine.SunIntensityLux, 1e-4f);
    TestEqual("road m is the road's", R1.RoadM, Road.RoadM);

    // Halfway: the midpoint, name switches at 0.5.
    const FSaskartaLookKey RH = USaskartaLightingDirector::ComposeLook(Road, Cine, 0.5f, 1.f, -1.f);
    TestEqual("half sun", RH.SunIntensityLux, (Road.SunIntensityLux + Cine.SunIntensityLux) * 0.5f, 1e-4f);
    TestEqual("half name", RH.Name, Cine.Name);

    // Fog multiplier: both layers; storm pin clamps.
    const FSaskartaLookKey RF = USaskartaLightingDirector::ComposeLook(Road, Cine, 0.f, 2.5f, 1.7f);
    TestEqual("fog x2.5", RF.FogDensity, Road.FogDensity * 2.5f, 1e-5f);
    TestEqual("second fog x2.5", RF.FogSecondDensity, Road.FogSecondDensity * 2.5f, 1e-6f);
    TestEqual("storm pinned, clamped", RF.StormIntensity, 1.f);
    TestEqual("storm pin 0", USaskartaLightingDirector::ComposeLook(Road, Cine, 0.f, 1.f, 0.f).StormIntensity, 0.f);
    TestEqual("fog never negative", USaskartaLightingDirector::ComposeLook(Road, Cine, 0.f, -1.f, -1.f).FogDensity, 0.f);

    const TArray<FSaskartaLookKey> Keys = { Road, Cine };
    TestTrue("find by name", USaskartaLightingDirector::FindKeyByName(Keys, TEXT("CineDawnHold")) == &Keys[1]);
    TestTrue("unknown name", USaskartaLightingDirector::FindKeyByName(Keys, TEXT("Nope")) == nullptr);

    TestEqual("blend start", USaskartaLightingDirector::BlendValue(0.f, 1.f, 0.f, 2.f), 0.f);
    TestEqual("blend middle (smoothstep)", USaskartaLightingDirector::BlendValue(0.f, 1.f, 1.f, 2.f), 0.5f, 1e-5f);
    TestEqual("blend end", USaskartaLightingDirector::BlendValue(0.f, 1.f, 2.f, 2.f), 1.f);
    TestEqual("zero blend jumps", USaskartaLightingDirector::BlendValue(3.f, 7.f, 0.f, 0.f), 7.f);
    TestTrue("blend is monotonic", USaskartaLightingDirector::BlendValue(1.f, 0.f, 0.5f, 2.f) > USaskartaLightingDirector::BlendValue(1.f, 0.f, 1.5f, 2.f));
    return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
