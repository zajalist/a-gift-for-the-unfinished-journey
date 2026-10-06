// Automation tests for USaskartaGameUserSettings, per task-P2-brief.md Step 1.
//
// Run 1 (offline): ComputeCVars() returns an empty map, so
// Saskarta.Settings.CVarMapping is expected to FAIL once these tests can be
// built and run (Run 2, after the user rebuilds and restarts the editor).
// Saskarta.Settings.SaveLoadRoundTrip does not depend on ComputeCVars and is
// expected to pass once the module builds.

#include "Misc/AutomationTest.h"
#include "SaskartaGameUserSettings.h"

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaCVarMappingTest, "Saskarta.Settings.CVarMapping",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaCVarMappingTest::RunTest(const FString&)
{
    USaskartaGameUserSettings* S = NewObject<USaskartaGameUserSettings>();
    S->FoliageDensity = 0.5f; S->FoliageDistance = 1.25f; S->CloudMode = 0; S->bReduceFlashing = true;
    S->UpscalerMethod = 0; S->UpscalerMode = 1;
    const TMap<FString, FString> C = USaskartaGameUserSettings::ComputeCVars(S);
    TestEqual("grass density", C.FindRef(TEXT("grass.DensityScale")), FString(TEXT("0.500")));
    TestEqual("grass cull", C.FindRef(TEXT("grass.CullDistanceScale")), FString(TEXT("1.250")));
    TestEqual("clouds", C.FindRef(TEXT("r.VolumetricCloud")), FString(TEXT("0")));
    TestEqual("flashing", C.FindRef(TEXT("r.Saskarta.ReduceFlashing")), FString(TEXT("1")));
    TestEqual("tsr", C.FindRef(TEXT("r.AntiAliasingMethod")), FString(TEXT("4")));
    TestEqual("balanced", C.FindRef(TEXT("r.ScreenPercentage")), FString(TEXT("58.000")));
    // Task P3 mirrors (the settings menu's read path).
    S->MasterVolume = 0.4f; S->bSubtitles = false; S->SubtitleSize = 2; S->CameraShake = 1.7f;
    const TMap<FString, FString> M = USaskartaGameUserSettings::ComputeCVars(S);
    TestEqual("mirror density", M.FindRef(TEXT("saskarta.foliage.density")), FString(TEXT("0.500")));
    TestEqual("mirror mode", M.FindRef(TEXT("saskarta.upscaler.mode")), FString(TEXT("1")));
    TestEqual("mirror master", M.FindRef(TEXT("saskarta.volume.master")), FString(TEXT("0.400")));
    TestEqual("mirror subtitles", M.FindRef(TEXT("saskarta.subtitles")), FString(TEXT("0")));
    TestEqual("mirror subtitle size", M.FindRef(TEXT("saskarta.subtitles.size")), FString(TEXT("2")));
    TestEqual("mirror shake clamped", M.FindRef(TEXT("saskarta.camerashake")), FString(TEXT("1.000")));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaRoundTripTest, "Saskarta.Settings.SaveLoadRoundTrip",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaRoundTripTest::RunTest(const FString&)
{
    const FString Ini = FPaths::ProjectSavedDir() / TEXT("Tests/SaskartaSettingsRoundTrip.ini");
    USaskartaGameUserSettings* A = NewObject<USaskartaGameUserSettings>();
    A->FoliageDensity = 0.75f; A->bSubtitles = false; A->UpscalerMode = 2; A->FieldOfView = 100.f;
    A->SaveConfig(CPF_Config, *Ini);
    USaskartaGameUserSettings* B = NewObject<USaskartaGameUserSettings>();
    B->LoadConfig(nullptr, *Ini);
    TestEqual("density", B->FoliageDensity, 0.75f);
    TestFalse("subtitles", B->bSubtitles);
    TestEqual("mode", B->UpscalerMode, 2);
    TestEqual("fov", B->FieldOfView, 100.f);
    return true;
}
