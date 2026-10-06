// USaskartaSaveGame: the run checkpoint and the profile (EVENTS.md section 7).
//
// One class, two slots:
//   Saskarta_Run      CheckpointId, HighWaterUeM, FiredBeats, FlowState, ActiveModes, reapplied state
//   Saskarta_Profile  SeenCinematics (drives HoldAfterSeen skip) and bCompletedOnce
// The runner writes and reads them; nothing else needs to.

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/SaveGame.h"
#include "SaskartaSaveGame.generated.h"

class USaskartaSaveGame;
class UWorld;

/** Optional Cistern receiver encounter. Absent in old saves; ordinary story progression is independent. */
USTRUCT()
struct FSaskartaRadioRepairSave
{
    GENERATED_BODY()
    UPROPERTY() bool bValid = false;
    UPROPERTY() bool bCompleted = false;
    UPROPERTY() bool bWasOpen = false;
    UPROPERTY() int32 Stage = 0;
    UPROPERTY() float AerialDeg = -55.f;
    UPROPERTY() float Frequency = -0.45f;
    UPROPERTY() float StableS = 0.f;
};

USTRUCT()
struct FSaskartaDustWreckSave
{
    GENERATED_BODY()
    UPROPERTY() FTransform CarrierPose;
    UPROPERTY() float RoadM = 0.f;
};

/**
 * RADIOSHOW: the Low Voice show's state in the run checkpoint (RADIO_SHOW.md section 7). Times are
 * stored as ages (seconds before the save), so they survive a new session's clock. Written by
 * USaskartaRadioStation through USaskartaSaveGame::OnWritingRun, read back on Continue through
 * USaskartaSaveGame::OnRestoredRun. bValid is false in a save written before the show existed.
 */
USTRUCT(BlueprintType)
struct SASKARTACORE_API FSaskartaShowSaveState
{
    GENERATED_BODY()

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Save|Show")
    bool bValid = false;

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Save|Show")
    int32 Act = 0;

    /** Backbone ids (and song-slot ids) played, and those dropped. */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Save|Show")
    TArray<FName> PlayedBackbone;

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Save|Show")
    TArray<FName> DroppedBackbone;

    /** Pushed back by an interruption, the closing items of the act left behind, and the carried items (Nuri's letter). */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Save|Show")
    TArray<FName> BackboneFront;

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Save|Show")
    TArray<FName> ClosingQueue;

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Save|Show")
    TArray<FName> CarryQueue;

    /** The song bag: songs played in a slot, and the last play of each song (parallel arrays). */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Save|Show")
    TArray<FName> SongsPlayed;

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Save|Show")
    TArray<FName> SongLastIds;

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Save|Show")
    TArray<float> SongLastAgeS;

    /** Every FILL / LINGER / ROOM / REACT / link id used, and how long before the save (parallel arrays). */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Save|Show")
    TArray<FName> UsedIds;

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Save|Show")
    TArray<float> UsedAgeS;

    /** Reaction cooldown clocks per event (parallel arrays), the global one and the per-act counts (index act - 1). */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Save|Show")
    TArray<FName> EventIds;

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Save|Show")
    TArray<float> EventAgeS;

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Save|Show")
    float LastReactAgeS = -1.f;

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Save|Show")
    TArray<int32> ReactsPerAct;

    /** -1 = no time check yet. */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Save|Show")
    float LastTimeCheckAgeS = -1.f;

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Save|Show")
    TArray<FName> PoisPassed;

    /** Story beats whose line has ended (after_beat items). */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Save|Show")
    TArray<FName> EndedBeats;

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Save|Show")
    bool bSignoffStarted = false;

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Save|Show")
    bool bSignoffDone = false;

    /** A song playing at the save resumes here after the opening fill (None = none), with its outro. */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Save|Show")
    FName SongId;

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Save|Show")
    float SongPositionS = 0.f;

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Save|Show")
    FName SongOutroId;
};

/** RADIOSHOW: native hooks around the run checkpoint (the station adds and reads its show state). */
DECLARE_MULTICAST_DELEGATE_TwoParams(FSaskartaRunSaveHook, UWorld* /*World*/, USaskartaSaveGame* /*Save*/);

UCLASS(BlueprintType)
class SASKARTACORE_API USaskartaSaveGame : public USaveGame
{
    GENERATED_BODY()

public:
    static const TCHAR* RunSlot;
    static const TCHAR* ProfileSlot;

    // --- Saskarta_Run
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Save")
    FName CheckpointId;

    /** Encounter checkpoints retain the actual carrier pose, rather than a named road landmark. */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Save")
    bool bHasExactCarrierPose = false;

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Save")
    FTransform CarrierPose;

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Save")
    FRotator CarrierViewRotation = FRotator::ZeroRotator;

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Save")
    float CheckpointRoadM = -1.f;

    /** CP4 is an on-foot checkpoint. These fields are independent of dust-rescue carrier snapshots. */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Save|Human")
    bool bHasHumanPose = false;

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Save|Human")
    FTransform HumanPose;

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Save|Human")
    FRotator HumanViewRotation = FRotator::ZeroRotator;

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Save|Human")
    bool bHasHumanCarrierPose = false;

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Save|Human")
    FTransform HumanCarrierPose;

    /** Older CP4 files may lack the flow name and the new exact-pose fields. */
    bool IsHumanCheckpoint() const
    {
        return FlowState == FName(TEXT("Human")) || CheckpointId == FName(TEXT("CP4_HUMAN"));
    }

    /** Previous carriers remain where this run lost them to the early dust front. */
    UPROPERTY()
    TArray<FSaskartaDustWreckSave> DustWrecks;

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Save")
    float HighWaterUeM = TNumericLimits<float>::Max();

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Save")
    TArray<FName> FiredBeats;

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Save")
    FName FlowState;

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Save")
    TArray<FName> ActiveModes;

    /** The last SetLook id, or None. */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Save")
    FName LastLook;

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Save")
    float LastFogMultiplier = 1.f;

    /** SpawnOrReveal ids already applied (DL:... entries are data layers). */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Save")
    TArray<FName> Revealed;

    /** ROUTE MAP: the stele ids scanned this run, in scan order (USaskartaRouteMap, through OnWritingRun). */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Save")
    TArray<FName> RouteLogSteles;

    /** ROUTE LOG: the board's carry-over (hits, sites passed, pins, locks), FSaskartaRouteBoardCore::Save text (USaskartaRouteLog). */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Save")
    FString RouteLogBoard;

    /** The first stationary CRT survey's archive/surface association was filed. */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Save")
    bool bFirstSurveyComplete = false;

    /** RADIOSHOW: the Low Voice show's state (the act, the played backbone, the used pools, the song position). */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Save")
    FSaskartaShowSaveState ShowState;

    UPROPERTY()
    FSaskartaRadioRepairSave RadioRepair;

    /** The carrier's current charge. Older checkpoints have bHasPowerState=false and use the depleted handover cell. */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Save|Power")
    bool bHasPowerState = false;

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Save|Power")
    float PowerCharge = 35.f;

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Save|Power")
    float PowerStoppedForS = 0.f;

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Save|Power")
    bool bPowerLimp = false;

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Save|Power")
    bool bPowerFirstRechargeComplete = false;

    /** Broadcast by the runner's SaveCheckpoint before it writes the Saskarta_Run slot (the station fills ShowState). */
    static FSaskartaRunSaveHook OnWritingRun;

    /** Broadcast by the runner's RestoreFromSave after it restored the Saskarta_Run slot (Continue: the station applies ShowState). */
    static FSaskartaRunSaveHook OnRestoredRun;

    // --- Saskarta_Profile
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Save")
    TArray<FName> SeenCinematics;

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Save")
    bool bCompletedOnce = false;
};
