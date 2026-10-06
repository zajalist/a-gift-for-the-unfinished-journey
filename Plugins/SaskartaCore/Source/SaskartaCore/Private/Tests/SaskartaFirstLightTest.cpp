// Automation tests for the First Light ending's pure rules (SaskartaFirstLightLogic.h): the dawn mix clears the
// horizon at ClearAtS, recapture steps, the dawn key keeps the cloud sea and fog, the live-channel caption speakers,
// the PlayDawn / StopSfx action names, and the real story data's CIN_24 cue chain.
// Written offline while the standalone playtest held the binaries. Run after the build:
//   Automation RunTests Saskarta.FirstLight

#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "SaskartaFirstLightLogic.h"
#include "SaskartaStoryImport.h"

#define SASKARTA_FL_TEST_FLAGS (EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaFirstLightDawnTest, "Saskarta.FirstLight.DawnMix", SASKARTA_FL_TEST_FLAGS)
bool FSaskartaFirstLightDawnTest::RunTest(const FString&)
{
    // PreDawn +3 -> Dawn -4, horizon -0.5: the disc clears at half the pitch span.
    const float C = FSaskartaFirstLight::ClearMix(3.f, -4.f, -0.5f);
    TestEqual(TEXT("clear mix"), C, 0.5f, 1e-4f);
    TestEqual(TEXT("flat span falls back to 0.5"), FSaskartaFirstLight::ClearMix(2.f, 2.f, 0.f), 0.5f);
    TestEqual(TEXT("start"), FSaskartaFirstLight::DawnMix(0.f, 120.f, 62.f, C), 0.f);
    TestEqual(TEXT("clears exactly at ClearAtS"), FSaskartaFirstLight::DawnMix(62.f, 120.f, 62.f, C), C, 1e-4f);
    TestEqual(TEXT("end"), FSaskartaFirstLight::DawnMix(120.f, 120.f, 62.f, C), 1.f);
    TestEqual(TEXT("past the end holds"), FSaskartaFirstLight::DawnMix(500.f, 120.f, 62.f, C), 1.f);
    TestEqual(TEXT("no duration jumps"), FSaskartaFirstLight::DawnMix(0.f, 0.f, 62.f, C), 1.f);
    TestEqual(TEXT("bad ClearAtS -> one ramp"), FSaskartaFirstLight::DawnMix(60.f, 120.f, 200.f, C), 0.5f, 1e-4f);
    float Prev = -1.f;
    bool bMonotonic = true;
    for (float T = 0.f; T <= 121.f; T += 0.25f)
    {
        const float M = FSaskartaFirstLight::DawnMix(T, 120.f, 62.f, C);
        bMonotonic &= M >= Prev;
        Prev = M;
    }
    TestTrue(TEXT("monotonic"), bMonotonic);
    // The sun's pitch through the ramp: above the horizon only after ClearAtS.
    const float PitchAt61 = FMath::Lerp(3.f, -4.f, FSaskartaFirstLight::DawnMix(61.f, 120.f, 62.f, C));
    const float PitchAt63 = FMath::Lerp(3.f, -4.f, FSaskartaFirstLight::DawnMix(63.f, 120.f, 62.f, C));
    TestTrue(TEXT("below the horizon before"), PitchAt61 > -0.5f);
    TestTrue(TEXT("above the horizon after"), PitchAt63 < -0.5f);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaFirstLightRecaptureTest, "Saskarta.FirstLight.Recapture", SASKARTA_FL_TEST_FLAGS)
bool FSaskartaFirstLightRecaptureTest::RunTest(const FString&)
{
    TestTrue(TEXT("first tick"), FSaskartaFirstLight::RecaptureDue(-1.f, 0.f));
    TestFalse(TEXT("inside a step"), FSaskartaFirstLight::RecaptureDue(0.f, 9.9f));
    TestTrue(TEXT("crosses 10"), FSaskartaFirstLight::RecaptureDue(9.9f, 10.1f));
    TestFalse(TEXT("same time"), FSaskartaFirstLight::RecaptureDue(10.1f, 10.1f));
    int32 Count = 0;
    float Prev = -1.f;
    for (float T = 0.f; T <= 120.f; T += FSaskartaFirstLight::ApplyIntervalS)
    {
        Count += FSaskartaFirstLight::RecaptureDue(Prev, T) ? 1 : 0;
        Prev = T;
    }
    TestEqual(TEXT("13 recaptures over 120 s (start + every 10 s)"), Count, 13);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaFirstLightKeysTest, "Saskarta.FirstLight.Keys", SASKARTA_FL_TEST_FLAGS)
bool FSaskartaFirstLightKeysTest::RunTest(const FString&)
{
    FSaskartaLookKey Pre;
    Pre.SunPitch = 3.f;
    Pre.SunYaw = 28.f;
    Pre.CloudBaseKm = 0.15f;
    Pre.FogDensity = 0.0104f;
    FSaskartaDawnParams P;
    const FSaskartaLookKey Start = FSaskartaFirstLight::MakeStartKey(Pre, P);
    const FSaskartaLookKey Dawn = FSaskartaFirstLight::MakeDawnKey(Pre, P);
    TestEqual(TEXT("start keeps its pitch"), Start.SunPitch, 3.f);
    TestEqual(TEXT("start takes the dawn yaw (no swing)"), Start.SunYaw, P.SunYaw);
    TestEqual(TEXT("dawn pitch"), Dawn.SunPitch, P.EndPitch);
    TestEqual(TEXT("dawn keeps the cloud sea"), Dawn.CloudBaseKm, 0.15f);
    TestEqual(TEXT("dawn keeps the fog"), Dawn.FogDensity, 0.0104f);
    TestEqual(TEXT("dawn grade clear"), Dawn.GradeClearWeight, 1.f);
    TestEqual(TEXT("dawn no storm"), Dawn.StormIntensity, 0.f);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaFirstLightCaptionTest, "Saskarta.FirstLight.CaptionSpeaker", SASKARTA_FL_TEST_FLAGS)
bool FSaskartaFirstLightCaptionTest::RunTest(const FString&)
{
    TestEqual(TEXT("replies name nobody"), FSaskartaFirstLight::CaptionSpeaker(TEXT("BELOW_R03"), TEXT("EHB")).ToString(),
        FString(TEXT("ILAAWB · LIVE")));
    TestTrue(TEXT("Samyor has no label"), FSaskartaFirstLight::CaptionSpeaker(TEXT("SAMYOR_B24_01"), TEXT("SAMYOR")).IsNone());
    TestTrue(TEXT("others unchanged"), FSaskartaFirstLight::CaptionSpeaker(TEXT("SHOW_A5_TAIL_02"), TEXT("HOST")) == FName(TEXT("HOST")));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaFirstLightDataTest, "Saskarta.FirstLight.Data", SASKARTA_FL_TEST_FLAGS)
bool FSaskartaFirstLightDataTest::RunTest(const FString&)
{
    TestTrue(TEXT("PlayDawn parses"), USaskartaStoryImport::ParseActionType(TEXT("PlayDawn")) == ESaskartaActionType::PlayDawn);
    TestTrue(TEXT("StopSfx parses"), USaskartaStoryImport::ParseActionType(TEXT("StopSfx")) == ESaskartaActionType::StopSfx);
    FString Json;
    const FString Path = FPaths::Combine(FPaths::ProjectDir(), TEXT("docs/story/story-events.json"));
    if (!FFileHelper::LoadFileToString(Json, *Path))
    {
        AddWarning(TEXT("story-events.json not found; data checks skipped"));
        return true;
    }
    // The chain the editor pass installs: lamp prompt -> hand prompt -> CIN_24 (dawn, live lines, replies, tail).
    for (const TCHAR* Needle : { TEXT("\"B23L_LAMP\""), TEXT("\"Leave a light on.\""), TEXT("\"PlayDawn\""), TEXT("\"StopSfx\""),
             TEXT("\"SAMYOR_B24_10\""), TEXT("\"BELOW_R21\""), TEXT("\"SHOW_A5_TAIL_02\""), TEXT("\"eyetae_title\"") })
    {
        TestTrue(FString::Printf(TEXT("story data has %s"), Needle), Json.Contains(Needle));
    }
    return true;
}

#endif
