#include "Misc/AutomationTest.h"
#include "SaskartaSaveGame.h"
#include "Kismet/GameplayStatics.h"

#if WITH_DEV_AUTOMATION_TESTS
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaPursuitSaveRoundTrip, "Saskarta.Pursuit.RescueSaveRoundTrip",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)

bool FSaskartaPursuitSaveRoundTrip::RunTest(const FString&)
{
    USaskartaSaveGame* Snapshot = NewObject<USaskartaSaveGame>();
    Snapshot->CheckpointId = TEXT("CP_EARLY_DUST");
    Snapshot->bHasExactCarrierPose = true;
    Snapshot->CarrierPose = FTransform(FRotator(0.f, 73.f, 0.f), FVector(100.f, 200.f, 300.f));
    Snapshot->CarrierViewRotation = FRotator(3.f, 81.f, 0.f);
    Snapshot->CheckpointRoadM = 710.f;
    Snapshot->HighWaterUeM = 4410.f;
    Snapshot->FiredBeats.Add(TEXT("B04A_DUST_FRONT"));
    Snapshot->FlowState = TEXT("Playing");
    Snapshot->bHasPowerState = true;
    Snapshot->PowerCharge = 43.25f;
    Snapshot->bPowerFirstRechargeComplete = true;
    Snapshot->ShowState.bValid = true;
    Snapshot->ShowState.PlayedBackbone.Add(TEXT("OPEN_01"));
    FSaskartaDustWreckSave Lost;
    Lost.CarrierPose = FTransform(FRotator(0.f, 80.f, 0.f), FVector(1200.f, 2200.f, 300.f));
    Lost.RoadM = 786.f;
    Snapshot->DustWrecks.Add(Lost);
    TArray<uint8> Bytes;
    TestTrue(TEXT("full rescue snapshot serializes"), UGameplayStatics::SaveGameToMemory(Snapshot, Bytes));
    USaskartaSaveGame* Restored = Cast<USaskartaSaveGame>(UGameplayStatics::LoadGameFromMemory(Bytes));
    if (!TestNotNull(TEXT("snapshot loads"), Restored)) return false;
    TestTrue(TEXT("exact carrier pose retained"), Restored->bHasExactCarrierPose && Restored->CarrierPose.Equals(Snapshot->CarrierPose));
    TestTrue(TEXT("view orientation retained"), Restored->CarrierViewRotation.Equals(Snapshot->CarrierViewRotation));
    TestEqual(TEXT("recovery is before the lost carrier"), Restored->CheckpointRoadM, 710.f);
    TestEqual(TEXT("charge restored from earlier state"), Restored->PowerCharge, 43.25f);
    TestTrue(TEXT("prior story progression retained"), Restored->FiredBeats.Contains(TEXT("B04A_DUST_FRONT")));
    TestTrue(TEXT("radio state retained"), Restored->ShowState.PlayedBackbone.Contains(TEXT("OPEN_01")));
    TestEqual(TEXT("wreck retained"), Restored->DustWrecks.Num(), 1);
    if (Restored->DustWrecks.Num() == 1)
    {
        TestTrue(TEXT("wreck remains at exact loss pose"), Restored->DustWrecks[0].CarrierPose.Equals(Lost.CarrierPose));
        TestEqual(TEXT("wreck remains at loss road distance"), Restored->DustWrecks[0].RoadM, 786.f);
    }
    USaskartaSaveGame* Legacy = NewObject<USaskartaSaveGame>();
    TestFalse(TEXT("legacy landmark checkpoints remain compatible"), Legacy->bHasExactCarrierPose);
    TestEqual(TEXT("old saves have no invented wrecks"), Legacy->DustWrecks.Num(), 0);
    return true;
}
#endif
