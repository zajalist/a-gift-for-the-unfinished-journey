// USaskartaAmbienceImport. See the header.

#include "SaskartaAmbienceImport.h"
#include "SaskartaAmbienceAsset.h"

#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Sound/SoundBase.h"
#include "Sound/SoundClass.h"
#include "Sound/SoundSubmix.h"
#include "UObject/Package.h"

DEFINE_LOG_CATEGORY_STATIC(LogSaskartaAmbienceImport, Log, All);

const TCHAR* USaskartaAmbienceImport::AmbienceAssetPath = TEXT("/Game/SaskartaGaea/Audio/Ambience2/DA_Ambience.DA_Ambience");
const TCHAR* USaskartaAmbienceImport::AmbienceFolder = TEXT("/Game/SaskartaGaea/Audio/Ambience2");

namespace SaskartaAmbienceImportPrivate
{
    struct FFileInfo
    {
        FString Asset;
        FString Folder;
        FString Zone;
        FString Type;
        FString Pool;
        float VolumeDb = 0.f;
        float RateCps = 0.f;
    };

    static FString Str(const TSharedPtr<FJsonObject>& O, const TCHAR* Key)
    {
        FString S;
        if (O.IsValid())
        {
            O->TryGetStringField(Key, S);
        }
        return S;
    }

    static float Num(const TSharedPtr<FJsonObject>& O, const TCHAR* Key, float Default)
    {
        double D = Default;
        if (O.IsValid() && O->TryGetNumberField(Key, D))
        {
            return static_cast<float>(D);
        }
        return Default;
    }

    static bool Interval(const TSharedPtr<FJsonObject>& O, float& OutMin, float& OutMax)
    {
        OutMin = OutMax = 0.f;
        const TArray<TSharedPtr<FJsonValue>>* Arr = nullptr;
        if (O.IsValid() && O->TryGetArrayField(TEXT("interval_s"), Arr) && Arr && Arr->Num() >= 2)
        {
            OutMin = static_cast<float>((*Arr)[0]->AsNumber());
            OutMax = static_cast<float>((*Arr)[1]->AsNumber());
            return true;
        }
        return false;
    }

    static TSoftObjectPtr<USoundBase> Sound(const TMap<FString, FFileInfo>& Files, const FString& AssetName, TArray<FString>& Missing)
    {
        const FFileInfo* F = Files.Find(AssetName);
        if (!F)
        {
            Missing.AddUnique(AssetName);
            return TSoftObjectPtr<USoundBase>(USaskartaAmbienceImport::SoundPath(USaskartaAmbienceImport::AmbienceFolder, AssetName));
        }
        return TSoftObjectPtr<USoundBase>(USaskartaAmbienceImport::SoundPath(F->Folder, F->Asset));
    }

    static FSaskartaAmbienceBed MakeBed(const TMap<FString, FFileInfo>& Files, const FString& AssetName, TArray<FString>& Missing)
    {
        FSaskartaAmbienceBed Bed;
        Bed.Name = FName(*AssetName);
        Bed.Sound = Sound(Files, AssetName, Missing);
        if (const FFileInfo* F = Files.Find(AssetName))
        {
            Bed.VolumeDb = F->VolumeDb;
        }
        return Bed;
    }
}

FSoftObjectPath USaskartaAmbienceImport::SoundPath(const FString& Folder, const FString& AssetName)
{
    const FString Dir = Folder.IsEmpty() ? FString(AmbienceFolder) : Folder;
    return FSoftObjectPath(FString::Printf(TEXT("%s/%s.%s"), *Dir, *AssetName, *AssetName));
}

bool USaskartaAmbienceImport::ImportAmbienceFromManifest(USaskartaAmbienceAsset* Asset, const FString& ManifestPath, FString& OutReport)
{
    if (!Asset)
    {
        OutReport = TEXT("No asset.");
        return false;
    }
    const FString Path = ManifestPath.IsEmpty()
        ? FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("GameAudio/Ambience2/manifest.json"))
        : ManifestPath;
    FString Json;
    if (!FFileHelper::LoadFileToString(Json, *Path))
    {
        OutReport = FString::Printf(TEXT("Cannot read %s"), *Path);
        return false;
    }
    const bool bOk = ParseManifestJson(Json, Asset, OutReport);
    if (bOk)
    {
        Asset->MarkPackageDirty();
    }
    return bOk;
}

bool USaskartaAmbienceImport::ParseManifestJson(const FString& Json, USaskartaAmbienceAsset* Asset, FString& OutReport)
{
    using namespace SaskartaAmbienceImportPrivate;
    OutReport.Reset();
    if (!Asset)
    {
        OutReport = TEXT("No asset.");
        return false;
    }
    TSharedPtr<FJsonObject> Root;
    const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Json);
    if (!FJsonSerializer::Deserialize(Reader, Root) || !Root.IsValid())
    {
        OutReport = TEXT("The manifest is not a JSON object.");
        return false;
    }

    // --- files
    TMap<FString, FFileInfo> Files;
    TArray<FString> Missing;
    const TArray<TSharedPtr<FJsonValue>>* FileArr = nullptr;
    if (Root->TryGetArrayField(TEXT("files"), FileArr) && FileArr)
    {
        for (const TSharedPtr<FJsonValue>& V : *FileArr)
        {
            const TSharedPtr<FJsonObject> O = V->AsObject();
            FFileInfo F;
            F.Asset = Str(O, TEXT("asset"));
            if (F.Asset.IsEmpty())
            {
                continue;
            }
            F.Folder = Str(O, TEXT("ue_folder"));
            F.Zone = Str(O, TEXT("zone"));
            F.Type = Str(O, TEXT("type"));
            F.Pool = Str(O, TEXT("pool"));
            F.VolumeDb = Num(O, TEXT("volume_db"), 0.f);
            F.RateCps = Num(O, TEXT("rate_cps"), 0.f);
            Files.Add(F.Asset, F);
        }
    }

    // Reset every imported field (the mix defaults are kept unless unset).
    Asset->Zones.Reset();
    Asset->Pools.Reset();
    Asset->Spots.Reset();
    Asset->StormBeds.Reset();
    Asset->DoseByRoadM.Reset();
    Asset->GeigerClicks.Reset();
    Asset->GeigerRateLoops.Reset();
    Asset->GeigerChirps.Reset();

    // --- zones
    const TArray<TSharedPtr<FJsonValue>>* ZoneArr = nullptr;
    if (Root->TryGetArrayField(TEXT("zones"), ZoneArr) && ZoneArr)
    {
        for (const TSharedPtr<FJsonValue>& V : *ZoneArr)
        {
            const TSharedPtr<FJsonObject> O = V->AsObject();
            FSaskartaAmbienceZone Z;
            Z.Name = FName(*Str(O, TEXT("zone")));
            Z.FromM = Num(O, TEXT("from_m"), 0.f);
            Z.ToM = Num(O, TEXT("to_m"), 0.f);
            Z.XfadeM = Num(O, TEXT("xfade_m"), 150.f);
            const TArray<TSharedPtr<FJsonValue>>* Beds = nullptr;
            if (O->TryGetArrayField(TEXT("beds"), Beds) && Beds)
            {
                for (const TSharedPtr<FJsonValue>& B : *Beds)
                {
                    Z.Beds.Add(MakeBed(Files, B->AsString(), Missing));
                }
            }
            const TArray<TSharedPtr<FJsonValue>>* Pools = nullptr;
            if (O->TryGetArrayField(TEXT("pools"), Pools) && Pools)
            {
                for (const TSharedPtr<FJsonValue>& P : *Pools)
                {
                    Z.Pools.Add(FName(*P->AsString()));
                }
            }
            Asset->Zones.Add(Z);
        }
        Asset->Zones.Sort([](const FSaskartaAmbienceZone& A, const FSaskartaAmbienceZone& B) { return A.FromM < B.FromM; });
    }

    // --- pools (the Geiger's are its own fields)
    const TSharedPtr<FJsonObject>* PoolObj = nullptr;
    if (Root->TryGetObjectField(TEXT("pools"), PoolObj) && PoolObj && PoolObj->IsValid())
    {
        for (const TPair<FString, TSharedPtr<FJsonValue>>& KV : (*PoolObj)->Values)
        {
            const TSharedPtr<FJsonObject> O = KV.Value->AsObject();
            TArray<TSoftObjectPtr<USoundBase>> Sounds;
            const TArray<TSharedPtr<FJsonValue>>* FilesOfPool = nullptr;
            if (O.IsValid() && O->TryGetArrayField(TEXT("files"), FilesOfPool) && FilesOfPool)
            {
                for (const TSharedPtr<FJsonValue>& F : *FilesOfPool)
                {
                    Sounds.Add(Sound(Files, F->AsString(), Missing));
                }
            }
            if (KV.Key == TEXT("Geiger_Click"))
            {
                Asset->GeigerClicks = Sounds;
                continue;
            }
            if (KV.Key == TEXT("Geiger_Device"))
            {
                continue; // switch/chirps come from the file list below
            }
            FSaskartaAmbiencePool P;
            P.Name = FName(*KV.Key);
            P.Sounds = MoveTemp(Sounds);
            Interval(O, P.IntervalMinS, P.IntervalMaxS);
            P.VolumeDb = Num(O, TEXT("volume_db"), -10.f);
            Asset->Pools.Add(P);
        }
    }

    // --- spots
    const TArray<TSharedPtr<FJsonValue>>* PlaceArr = nullptr;
    if (Root->TryGetArrayField(TEXT("placement"), PlaceArr) && PlaceArr)
    {
        for (const TSharedPtr<FJsonValue>& V : *PlaceArr)
        {
            const TSharedPtr<FJsonObject> O = V->AsObject();
            FSaskartaAmbienceSpot S;
            S.Label = FName(*Str(O, TEXT("label")));
            const FString AssetName = Str(O, TEXT("asset"));
            if (!AssetName.IsEmpty() && !AssetName.Contains(TEXT("*")))
            {
                S.Sound = Sound(Files, AssetName, Missing);
            }
            S.Location = FVector(Num(O, TEXT("x"), 0.f), Num(O, TEXT("y"), 0.f), Num(O, TEXT("z"), 0.f));
            S.RoadM = Num(O, TEXT("road_m"), 0.f);
            S.InnerRadiusM = Num(O, TEXT("inner_radius_m"), 5.f);
            S.FalloffM = Num(O, TEXT("falloff_m"), 40.f);
            S.VolumeDb = Num(O, TEXT("volume_db"), -8.f);
            S.Note = Str(O, TEXT("note"));
            S.bWaterOption = S.Note.StartsWith(TEXT("WATER OPTION"));
            Asset->Spots.Add(S);
        }
    }

    // --- dose table
    const TArray<TSharedPtr<FJsonValue>>* DoseArr = nullptr;
    if (Root->TryGetArrayField(TEXT("dose_cps"), DoseArr) && DoseArr)
    {
        for (const TSharedPtr<FJsonValue>& V : *DoseArr)
        {
            const TArray<TSharedPtr<FJsonValue>>& Pair = V->AsArray();
            if (Pair.Num() >= 2)
            {
                Asset->DoseByRoadM.Add(FVector2D(Pair[0]->AsNumber(), Pair[1]->AsNumber()));
            }
        }
        Asset->DoseByRoadM.Sort([](const FVector2D& A, const FVector2D& B) { return A.X < B.X; });
    }

    // --- storm layer and Geiger device sounds (by name)
    auto Has = [&Files](const TCHAR* Name) { return Files.Contains(Name); };
    Asset->WindBreeze = Sound(Files, TEXT("AMB_Storm_WindBreeze_Loop"), Missing);
    Asset->WindStrong = Sound(Files, TEXT("AMB_Storm_WindStrong_Loop"), Missing);
    Asset->WindGale = Sound(Files, TEXT("AMB_Storm_WindGale_Loop"), Missing);
    if (Has(TEXT("AMB_Storm_SandHiss_Loop")))
    {
        Asset->StormBeds.Add(MakeBed(Files, TEXT("AMB_Storm_SandHiss_Loop"), Missing));
    }
    if (Has(TEXT("AMB_Storm_SandOnMetal_Loop")))
    {
        Asset->StormBeds.Add(MakeBed(Files, TEXT("AMB_Storm_SandOnMetal_Loop"), Missing));
    }
    Asset->GeigerSwitchOn = Sound(Files, TEXT("SFX_Geiger_SwitchOn"), Missing);
    Asset->GeigerSwitchOff = Sound(Files, TEXT("SFX_Geiger_SwitchOff"), Missing);
    TArray<FString> Names;
    Files.GetKeys(Names);
    Names.Sort();
    for (const FString& N : Names)
    {
        const FFileInfo& F = Files[N];
        if (N.StartsWith(TEXT("SFX_Geiger_AlarmChirp_")))
        {
            Asset->GeigerChirps.Add(Sound(Files, N, Missing));
        }
        else if (F.Zone == TEXT("Geiger") && F.RateCps > 0.f)
        {
            FSaskartaGeigerLoop L;
            L.RateCps = F.RateCps;
            L.Sound = Sound(Files, N, Missing);
            Asset->GeigerRateLoops.Add(L);
        }
        else if (Asset->GeigerClicks.Num() == 0 && N.StartsWith(TEXT("SFX_Geiger_Click_")))
        {
            // No Geiger_Click pool in the manifest: take the clicks by name.
            Asset->GeigerClicks.Add(Sound(Files, N, Missing));
        }
    }
    Asset->GeigerRateLoops.Sort([](const FSaskartaGeigerLoop& A, const FSaskartaGeigerLoop& B) { return A.RateCps < B.RateCps; });

    // --- mix defaults (the editor lane creates these; a missing one is simply not used)
    if (Asset->AmbienceSubmix.IsNull())
    {
        Asset->AmbienceSubmix = TSoftObjectPtr<USoundSubmix>(FSoftObjectPath(FString::Printf(TEXT("%s/SMX_Ambience.SMX_Ambience"), AmbienceFolder)));
    }
    if (Asset->AmbienceClass.IsNull())
    {
        Asset->AmbienceClass = TSoftObjectPtr<USoundClass>(FSoftObjectPath(FString::Printf(TEXT("%s/SC_Ambience.SC_Ambience"), AmbienceFolder)));
    }
    if (Asset->GeigerClass.IsNull())
    {
        Asset->GeigerClass = TSoftObjectPtr<USoundClass>(FSoftObjectPath(FString::Printf(TEXT("%s/SC_Geiger.SC_Geiger"), AmbienceFolder)));
    }

    ApplyBriefRules(Asset);

    int32 PoolSounds = 0;
    for (const FSaskartaAmbiencePool& P : Asset->Pools)
    {
        PoolSounds += P.Sounds.Num();
    }
    OutReport = FString::Printf(
        TEXT("files %d, zones %d, pools %d (%d sounds), spots %d, dose points %d, geiger clicks %d, rate loops %d, chirps %d, storm beds %d"),
        Files.Num(), Asset->Zones.Num(), Asset->Pools.Num(), PoolSounds, Asset->Spots.Num(), Asset->DoseByRoadM.Num(),
        Asset->GeigerClicks.Num(), Asset->GeigerRateLoops.Num(), Asset->GeigerChirps.Num(), Asset->StormBeds.Num());
    if (Missing.Num() > 0)
    {
        OutReport += FString::Printf(TEXT("; not in the file list (default folder used): %s"), *FString::Join(Missing, TEXT(", ")));
    }
    return Asset->Zones.Num() > 0;
}

void USaskartaAmbienceImport::ApplyBriefRules(USaskartaAmbienceAsset* Asset)
{
    if (!Asset)
    {
        return;
    }

    // --- zones: wind multipliers, dose washout, bed modifiers (brief sections 1-2, 6)
    for (FSaskartaAmbienceZone& Z : Asset->Zones)
    {
        const FString N = Z.Name.ToString();
        Z.WindMultiplier = N == TEXT("Foot") ? 0.9f
            : N == TEXT("Climb") ? 0.8f
            : N == TEXT("Cloud") ? 0.4f
            : N == TEXT("Above") ? 0.15f
            : 1.f;
        Z.DoseMultiplier = N == TEXT("Cloud") ? 0.8f : 1.f;
        for (FSaskartaAmbienceBed& B : Z.Beds)
        {
            const FString BN = B.Name.ToString();
            if (BN == TEXT("AMB_Valley_DryGrass_Loop"))
            {
                // -2 dB, the ridge (1,550-2,020) -6 dB.
                B.ExtraFromM = 1550.f;
                B.ExtraToM = 2020.f;
                B.ExtraDb = -4.f;
            }
            else if (BN == TEXT("AMB_Valley_Insects_Loop"))
            {
                B.StormMode = ESaskartaBedStormMode::InverseToRef;
                B.StormRef = 0.7f;
                B.OffAfterRoadM = 1700.f;
            }
            else if (BN == TEXT("AMB_Storm_WhistleRocks_Loop"))
            {
                B.StormMode = ESaskartaBedStormMode::Linear;
            }
        }
    }
    for (FSaskartaAmbienceBed& B : Asset->StormBeds)
    {
        if (B.Name == TEXT("AMB_Storm_SandHiss_Loop"))
        {
            B.VolumeDb = -6.f;
            B.StormMode = ESaskartaBedStormMode::Squared;
        }
        else if (B.Name == TEXT("AMB_Storm_SandOnMetal_Loop"))
        {
            B.VolumeDb = -8.f;
            B.StormMode = ESaskartaBedStormMode::AboveHalf;
        }
    }

    // --- pools (brief sections 2-3)
    auto Around = [](FSaskartaAmbiencePool& P, float MinM, float MaxM, float Arc, float Height = 0.f)
    {
        P.Placement = ESaskartaPoolPlacement::AroundListener;
        P.MinDistM = MinM;
        P.MaxDistM = MaxM;
        P.ArcDeg = Arc;
        P.HeightOffsetM = Height;
    };
    auto AtEmitters = [](FSaskartaAmbiencePool& P, std::initializer_list<const TCHAR*> Labels, bool bLocal)
    {
        P.Placement = ESaskartaPoolPlacement::AtEmitter;
        P.Emitters.Reset();
        for (const TCHAR* L : Labels)
        {
            P.Emitters.Add(FName(L));
        }
        P.bLocal = bLocal;
    };
    for (FSaskartaAmbiencePool& P : Asset->Pools)
    {
        const FString N = P.Name.ToString();
        if (N == TEXT("Storm_Gust") || N == TEXT("Storm_Sand"))
        {
            // Event-driven by the gust timer.
            P.IntervalMinS = P.IntervalMaxS = 0.f;
            P.Placement = ESaskartaPoolPlacement::TwoD;
            P.Priority = N == TEXT("Storm_Gust") ? 60.f : 40.f;
        }
        else if (N == TEXT("Storm_ThunderClose") || N == TEXT("Storm_ThunderDistant"))
        {
            P.IntervalMinS = P.IntervalMaxS = 0.f;
            P.Placement = ESaskartaPoolPlacement::TwoD;
            P.Priority = 90.f;
        }
        else if (N == TEXT("Storm_StoneSkitter") || N == TEXT("Storm_BranchSnap") || N == TEXT("Storm_TinRattle"))
        {
            Around(P, 15.f, 60.f, 70.f);
            P.Priority = 20.f;
        }
        else if (N == TEXT("Storm_Rockfall"))
        {
            Around(P, 150.f, 400.f, 180.f);
            P.Priority = 25.f;
        }
        else if (N == TEXT("Valley_Birds"))
        {
            Around(P, 150.f, 400.f, 180.f);
            P.MaxStorm = 0.9f;
            P.Priority = 30.f;
        }
        else if (N == TEXT("Valley_Insects"))
        {
            Around(P, 5.f, 20.f, 180.f);
            P.MaxStorm = 0.6f;
            P.bGustLullOnly = true;
            P.Priority = 25.f;
        }
        else if (N == TEXT("WaitingWater_Water"))
        {
            AtEmitters(P, { TEXT("A2_WW_SluiceDrip"), TEXT("A2_WW_Trickle") }, true);
            P.bWaterOption = true;
        }
        else if (N == TEXT("WaitingWater_Dry"))
        {
            AtEmitters(P, { TEXT("A2_WW_GateCreak") }, true);
        }
        else if (N == TEXT("HeronPools_Birds"))
        {
            // 150-300 m off the road around 2,470.
            Around(P, 150.f, 300.f, 180.f);
            P.bLocal = true;
            P.RoadMinM = 2300.f;
            P.RoadMaxM = 2650.f;
        }
        else if (N == TEXT("HeronPools_Water"))
        {
            AtEmitters(P, { TEXT("A2_HP_Lapping") }, true);
            P.bWaterOption = true;
        }
        else if (N == TEXT("Platform_Metal"))
        {
            AtEmitters(P, { TEXT("A2_PF_MetalCreak"), TEXT("A2_PF_StructureWind"), TEXT("A2_PF_Ruins") }, true);
            P.bAlsoOnGust = true;
        }
        else if (N == TEXT("Cistern_Stones") || N == TEXT("Cistern_Drips"))
        {
            AtEmitters(P, { TEXT("A2_CI_DarkDrip") }, true);
        }
        else if (N == TEXT("Waystation_Wood"))
        {
            AtEmitters(P, { TEXT("A2_WS_WindGaps") }, true);
        }
        else if (N == TEXT("Waystation_Cloth"))
        {
            AtEmitters(P, { TEXT("A2_WS_Ruins"), TEXT("A2_WS_WindGaps") }, true);
            P.bAlsoOnGust = true;
        }
        else if (N == TEXT("Climb_Cloth"))
        {
            AtEmitters(P, { TEXT("A2_CL_BannerV7"), TEXT("A2_CL_BannerKnees"), TEXT("A2_CL_Crest") }, true);
            P.bAlsoOnGust = true;
        }
        else if (N == TEXT("Climb_Stones"))
        {
            Around(P, 60.f, 200.f, 180.f, -30.f);
        }
        else if (N == TEXT("Cloud_Drops"))
        {
            Around(P, 2.f, 8.f, 180.f);
            P.Priority = 25.f;
        }
        else if (N == TEXT("Cloud_Wind"))
        {
            P.Placement = ESaskartaPoolPlacement::TwoD;
        }
        else if (N == TEXT("Above_Wind"))
        {
            P.Placement = ESaskartaPoolPlacement::TwoD;
            P.bAllowedInHuman = true;
            P.bStopOnFinalBeat = true;
            P.Priority = 35.f;
        }
    }
}

USaskartaAmbienceAsset* USaskartaAmbienceImport::ImportTransient(UObject* Outer)
{
#if WITH_EDITOR
    USaskartaAmbienceAsset* Transient = NewObject<USaskartaAmbienceAsset>(Outer ? Outer : GetTransientPackage());
    FString Report;
    if (ImportAmbienceFromManifest(Transient, FString(), Report))
    {
        UE_LOG(LogSaskartaAmbienceImport, Warning,
            TEXT("DA_Ambience not found; imported a transient copy from Saved/GameAudio/Ambience2/manifest.json (editor only). %s"), *Report.Left(300));
        return Transient;
    }
    UE_LOG(LogSaskartaAmbienceImport, Warning, TEXT("DA_Ambience not found and the manifest import failed: %s"), *Report);
#endif
    return nullptr;
}
