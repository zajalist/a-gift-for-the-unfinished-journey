#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS
#include "SaskartaSaveGame.h"
#include "Kismet/GameplayStatics.h"

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaHumanCheckpointClassification, "Saskarta.Ending.HumanCheckpointClassification",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaHumanCheckpointClassification::RunTest(const FString&)
{
    USaskartaSaveGame* Save = NewObject<USaskartaSaveGame>();
    TestFalse(TEXT("legacy defaults have no invented elder pose"), Save->bHasHumanPose);
    TestFalse(TEXT("legacy defaults have no invented stranded carrier pose"), Save->bHasHumanCarrierPose);
    TestFalse(TEXT("empty checkpoint is not Human"), Save->IsHumanCheckpoint());
    Save->CheckpointId = TEXT("CP4_HUMAN");
    TestTrue(TEXT("old CP4 without flow name is Human"), Save->IsHumanCheckpoint());
    Save->CheckpointId = TEXT("CP2_WAYSTATION");
    Save->bHasExactCarrierPose = true;
    TestFalse(TEXT("exact carrier snapshot does not imply Human"), Save->IsHumanCheckpoint());
    Save->FlowState = TEXT("Human");
    TestTrue(TEXT("explicit Human flow is recognized"), Save->IsHumanCheckpoint());
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaHumanCheckpointRoundTrip, "Saskarta.Ending.HumanCheckpointRoundTrip",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaHumanCheckpointRoundTrip::RunTest(const FString&)
{
    USaskartaSaveGame* Save = NewObject<USaskartaSaveGame>();
    Save->CheckpointId = TEXT("CP4_HUMAN");
    Save->FlowState = TEXT("Human");
    Save->bHasHumanPose = true;
    Save->HumanPose = FTransform(FRotator(0.f, 79.f, 0.f), FVector(1800.f, -2200.f, 1392.f));
    Save->HumanViewRotation = FRotator(-8.f, 83.f, 0.f);
    Save->bHasHumanCarrierPose = true;
    Save->HumanCarrierPose = FTransform(FRotator(0.f, 71.f, 0.f), FVector(1600.f, -2000.f, 1350.f));
    Save->FiredBeats.Add(TEXT("B19_HATCH"));
    Save->HighWaterUeM = 77.f;
    Save->ShowState.bValid = true;
    Save->ShowState.PlayedBackbone.Add(TEXT("OPEN_01"));
    FSaskartaDustWreckSave OldWreck;
    OldWreck.CarrierPose = FTransform(FRotator(0.f, 40.f, 0.f), FVector(200.f, 300.f, 400.f));
    OldWreck.RoadM = 785.f;
    Save->DustWrecks.Add(OldWreck);

    TArray<uint8> Bytes;
    if (!TestTrue(TEXT("Human snapshot serializes"), UGameplayStatics::SaveGameToMemory(Save, Bytes))) return false;
    USaskartaSaveGame* Back = Cast<USaskartaSaveGame>(UGameplayStatics::LoadGameFromMemory(Bytes));
    if (!TestNotNull(TEXT("Human snapshot loads"), Back)) return false;
    TestTrue(TEXT("Human classification persists"), Back->IsHumanCheckpoint());
    TestTrue(TEXT("elder pose persists"), Back->bHasHumanPose && Back->HumanPose.Equals(Save->HumanPose));
    TestTrue(TEXT("elder view persists"), Back->HumanViewRotation.Equals(Save->HumanViewRotation));
    TestTrue(TEXT("stranded carrier pose persists"), Back->bHasHumanCarrierPose && Back->HumanCarrierPose.Equals(Save->HumanCarrierPose));
    TestFalse(TEXT("Human pose never becomes an exact dust carrier pose"), Back->bHasExactCarrierPose);
    TestTrue(TEXT("hatch progression persists"), Back->FiredBeats.Contains(TEXT("B19_HATCH")));
    TestTrue(TEXT("radio state persists"), Back->ShowState.PlayedBackbone.Contains(TEXT("OPEN_01")));
    TestEqual(TEXT("earlier dust wreck count persists"), Back->DustWrecks.Num(), 1);
    if (Back->DustWrecks.Num() == 1)
    {
        TestTrue(TEXT("earlier dust wreck pose untouched"), Back->DustWrecks[0].CarrierPose.Equals(OldWreck.CarrierPose));
        TestEqual(TEXT("earlier dust wreck road position untouched"), Back->DustWrecks[0].RoadM, OldWreck.RoadM);
    }
    return true;
}
#endif
