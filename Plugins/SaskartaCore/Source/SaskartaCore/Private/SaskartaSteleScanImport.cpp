// docs/story/inscriptions.json -> USaskartaSteleScanAsset (task STELESCAN). See SaskartaSteleScanAsset.h.

#include "SaskartaSteleScanAsset.h"

#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Sound/SoundBase.h"
#include "UObject/Package.h"

DEFINE_LOG_CATEGORY_STATIC(LogSaskartaSteleImport, Log, All);

const TCHAR* USaskartaSteleScanImport::AssetPath = TEXT("/Game/SaskartaGaea/Inscriptions/DA_Saskarta_SteleScan.DA_Saskarta_SteleScan");

// ============================================================================================ asset
const FSaskartaInscriptionDef* USaskartaSteleScanAsset::FindInscription(FName Id) const
{
    return Inscriptions.FindByPredicate([Id](const FSaskartaInscriptionDef& D) { return D.Id == Id; });
}

const FSaskartaSteleDef* USaskartaSteleScanAsset::FindStele(FName Id) const
{
    return Steles.FindByPredicate([Id](const FSaskartaSteleDef& D) { return D.Id == Id; });
}

FSaskartaSteleScanTuning USaskartaSteleScanAsset::MakeTuning() const
{
    FSaskartaSteleScanTuning T;
    T.RangeM = RangeM;
    T.MinRangeM = MinRangeM;
    T.MaxViewDeg = MaxViewDeg;
    T.DockViewDeg = DockViewDeg;
    T.MinFaceDot = MinFaceDot;
    T.AheadM = AheadM;
    T.BehindM = BehindM;
    T.SweepS = SweepS;
    T.MatchSweepS = MatchSweepS;
    T.TextAtS = TextAtS;
    T.VoiceAtS = VoiceAtS;
    T.VoiceWaitMaxS = VoiceWaitMaxS;
    T.VoiceMinGapS = VoiceMinGapS;
    T.VoiceLeadS = VoiceLeadS;
    T.HudWaitMaxS = HudWaitMaxS;
    T.HoldAfterVoiceS = HoldAfterVoiceS;
    T.TextOnlyHoldS = TextOnlyHoldS;
    T.MatchHoldS = MatchHoldS;
    T.MaxTextOnlyFullReads = MaxTextOnlyFullReads;
    T.WornWear = WornWear;
    T.bPrompted = bPrompted;
    T.PromptRangeM = PromptRangeM;
    T.PromptViewDeg = PromptViewDeg;
    T.ScanChargeCost = ScanChargeCost;
    if (SilentRoadM.Num() > 0)
    {
        T.SilentRoadM.Reset();
        for (const FVector2D& R : SilentRoadM)
        {
            T.SilentRoadM.Add(FVector2f(static_cast<float>(R.X), static_cast<float>(R.Y)));
        }
    }
    return T;
}

// ============================================================================================ parsing
namespace SaskartaSteleImport
{
    static FString Str(const TSharedPtr<FJsonObject>& Obj, const TCHAR* Field)
    {
        FString Out;
        if (Obj.IsValid() && Obj->HasTypedField<EJson::String>(Field))
        {
            Out = Obj->GetStringField(Field);
        }
        return Out;
    }

    static bool Num(const TSharedPtr<FJsonObject>& Obj, const TCHAR* Field, double& Out)
    {
        if (Obj.IsValid() && Obj->HasTypedField<EJson::Number>(Field))
        {
            Out = Obj->GetNumberField(Field);
            return true;
        }
        return false;
    }

    static void NumInto(const TSharedPtr<FJsonObject>& Obj, const TCHAR* Field, float& Out)
    {
        double V = 0.0;
        if (Num(Obj, Field, V))
        {
            Out = static_cast<float>(V);
        }
    }

    /** "/Game/A/B" -> "/Game/A/B.B" (an object path), or empty for anything that is not a /Game path. */
    static FSoftObjectPath AssetPathOf(const FString& PackagePath)
    {
        if (!PackagePath.StartsWith(TEXT("/Game/")))
        {
            return FSoftObjectPath();
        }
        if (PackagePath.Contains(TEXT(".")))
        {
            return FSoftObjectPath(PackagePath);
        }
        return FSoftObjectPath(PackagePath + TEXT(".") + FPaths::GetBaseFilename(PackagePath));
    }

    static const TArray<TSharedPtr<FJsonValue>>* Arr(const TSharedPtr<FJsonObject>& Obj, const TCHAR* Field)
    {
        if (Obj.IsValid() && Obj->HasTypedField<EJson::Array>(Field))
        {
            return &Obj->GetArrayField(Field);
        }
        return nullptr;
    }
}

bool USaskartaSteleScanImport::ParseInscriptionsJson(const FString& Json, USaskartaSteleScanAsset* Asset, FString& OutReport)
{
    using namespace SaskartaSteleImport;
    OutReport.Reset();
    if (!Asset)
    {
        OutReport = TEXT("no asset");
        return false;
    }
    TSharedPtr<FJsonObject> Root;
    const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Json);
    if (!FJsonSerializer::Deserialize(Reader, Root) || !Root.IsValid())
    {
        OutReport = TEXT("inscriptions.json does not parse");
        return false;
    }
    const TArray<TSharedPtr<FJsonValue>>* InsArr = Arr(Root, TEXT("inscriptions"));
    const TArray<TSharedPtr<FJsonValue>>* SteleArr = Arr(Root, TEXT("steles"));
    if (!InsArr || !SteleArr)
    {
        OutReport = TEXT("inscriptions.json needs inscriptions[] and steles[]");
        return false;
    }

    TArray<FString> Problems;
    Asset->Inscriptions.Reset();
    for (const TSharedPtr<FJsonValue>& V : *InsArr)
    {
        TSharedPtr<FJsonObject> O;
        if (V.IsValid())
        {
            O = V->AsObject();
        }
        const FString Id = Str(O, TEXT("id"));
        if (Id.IsEmpty())
        {
            Problems.Add(TEXT("an inscription without an id"));
            continue;
        }
        FSaskartaInscriptionDef D;
        D.Id = FName(*Id);
        D.Status = Str(O, TEXT("status"));
        D.English = Str(O, TEXT("english"));
        D.Saskartan = Str(O, TEXT("saskartan"));
        D.MachineTranslit = Str(O, TEXT("machine_translit"));
        D.EnglishApprox = Str(O, TEXT("english_approx"));
        const FString Resolves = Str(O, TEXT("resolves_after_beat"));
        D.ResolvesAfterBeat = Resolves.IsEmpty() ? NAME_None : FName(*Resolves);
        D.EnglishApproxResolved = Str(O, TEXT("english_approx_resolved"));
        double Cell = -1.0;
        D.AtlasCell = Num(O, TEXT("atlas_cell"), Cell) ? FMath::RoundToInt(Cell) : INDEX_NONE;
        const FString LineId = Str(O, TEXT("voice_line_id"));
        D.VoiceLineId = LineId.IsEmpty() ? FName(*(TEXT("INSCR_") + Id)) : FName(*LineId);
        D.Voice = TSoftObjectPtr<USoundBase>(AssetPathOf(Str(O, TEXT("voice_asset"))));
        D.VoiceStyle = Str(O, TEXT("voice_style"));
        D.bNeverVoice = Str(O, TEXT("voice_policy")) == TEXT("never");
        NumInto(O, TEXT("duration_s"), D.DurationS);
        if (Asset->FindInscription(D.Id))
        {
            Problems.Add(FString::Printf(TEXT("duplicate inscription %s"), *Id));
            continue;
        }
        Asset->Inscriptions.Add(D);
    }

    Asset->Steles.Reset();
    int32 Unready = 0;
    for (const TSharedPtr<FJsonValue>& V : *SteleArr)
    {
        TSharedPtr<FJsonObject> O;
        if (V.IsValid())
        {
            O = V->AsObject();
        }
        const FString Id = Str(O, TEXT("id"));
        if (Id.IsEmpty())
        {
            Problems.Add(TEXT("a stele without an id"));
            continue;
        }
        FSaskartaSteleDef S;
        S.Id = FName(*Id);
        S.Mesh = FName(*Str(O, TEXT("mesh")));
        S.Inscription = FName(*Str(O, TEXT("inscription")));
        NumInto(O, TEXT("road_m"), S.RoadM);
        NumInto(O, TEXT("wear"), S.Wear);
        S.bDock = S.Mesh.ToString().Contains(TEXT("DockPost"));
        if (const TArray<TSharedPtr<FJsonValue>>* Face = Arr(O, TEXT("face_centre_local_cm")))
        {
            if (Face->Num() == 3)
            {
                S.FaceCentreLocalCm = FVector((*Face)[0]->AsNumber(), (*Face)[1]->AsNumber(), (*Face)[2]->AsNumber());
            }
        }
        const FSaskartaInscriptionDef* Ins = Asset->FindInscription(S.Inscription);
        if (!Ins)
        {
            Problems.Add(FString::Printf(TEXT("%s: unknown inscription %s"), *Id, *S.Inscription.ToString()));
        }
        else if (Ins->AtlasCell < 0 || Ins->Saskartan.IsEmpty() || Ins->Saskartan == TEXT("AUTHOR"))
        {
            ++Unready;
            Problems.Add(FString::Printf(TEXT("%s: %s is not carved into the atlas yet"), *Id, *S.Inscription.ToString()));
        }
        Asset->Steles.Add(S);
    }

    const TSharedPtr<FJsonObject>* TuningPtr = nullptr;
    if (Root->TryGetObjectField(TEXT("tuning"), TuningPtr) && TuningPtr && TuningPtr->IsValid())
    {
        const TSharedPtr<FJsonObject>& T = *TuningPtr;
        NumInto(T, TEXT("scan_range_m"), Asset->RangeM);
        NumInto(T, TEXT("min_range_m"), Asset->MinRangeM);
        NumInto(T, TEXT("max_view_deg"), Asset->MaxViewDeg);
        NumInto(T, TEXT("dock_view_deg"), Asset->DockViewDeg);
        NumInto(T, TEXT("min_face_dot"), Asset->MinFaceDot);
        NumInto(T, TEXT("ahead_m"), Asset->AheadM);
        NumInto(T, TEXT("behind_m"), Asset->BehindM);
        NumInto(T, TEXT("sweep_s"), Asset->SweepS);
        NumInto(T, TEXT("match_sweep_s"), Asset->MatchSweepS);
        NumInto(T, TEXT("text_at_s"), Asset->TextAtS);
        NumInto(T, TEXT("voice_at_s"), Asset->VoiceAtS);
        NumInto(T, TEXT("voice_wait_max_s"), Asset->VoiceWaitMaxS);
        NumInto(T, TEXT("voice_min_gap_s"), Asset->VoiceMinGapS);
        NumInto(T, TEXT("voice_lead_s"), Asset->VoiceLeadS);
        NumInto(T, TEXT("hud_wait_max_s"), Asset->HudWaitMaxS);
        NumInto(T, TEXT("hold_after_voice_s"), Asset->HoldAfterVoiceS);
        NumInto(T, TEXT("text_only_hold_s"), Asset->TextOnlyHoldS);
        NumInto(T, TEXT("match_hold_s"), Asset->MatchHoldS);
        NumInto(T, TEXT("worn_wear"), Asset->WornWear);
        NumInto(T, TEXT("prompt_range_m"), Asset->PromptRangeM);
        NumInto(T, TEXT("prompt_view_deg"), Asset->PromptViewDeg);
        NumInto(T, TEXT("scan_charge_cost"), Asset->ScanChargeCost);
        bool bPromptedJson = true;
        if (T->TryGetBoolField(TEXT("prompted"), bPromptedJson))
        {
            Asset->bPrompted = bPromptedJson;
        }
        const FString PromptTargetJson = Str(T, TEXT("prompt_target"));
        if (!PromptTargetJson.IsEmpty())
        {
            Asset->PromptTarget = FName(*PromptTargetJson);
        }
        Asset->PromptLabel = Str(T, TEXT("prompt_label"));
        double MaxReads = 0.0;
        if (Num(T, TEXT("max_text_only_full_reads"), MaxReads))
        {
            Asset->MaxTextOnlyFullReads = FMath::RoundToInt(MaxReads);
        }
        if (const TArray<TSharedPtr<FJsonValue>>* Silent = Arr(T, TEXT("silent_road_m")))
        {
            Asset->SilentRoadM.Reset();
            for (const TSharedPtr<FJsonValue>& R : *Silent)
            {
                const TArray<TSharedPtr<FJsonValue>>* Pair = nullptr;
                if (R.IsValid() && R->TryGetArray(Pair) && Pair && Pair->Num() == 2)
                {
                    Asset->SilentRoadM.Add(FVector2D((*Pair)[0]->AsNumber(), (*Pair)[1]->AsNumber()));
                }
            }
        }
        const FString Target = Str(T, TEXT("caption_target"));
        if (!Target.IsEmpty())
        {
            Asset->CaptionTarget = FName(*Target);
        }
        const FString Mark = Str(T, TEXT("resolved_mark"));
        Asset->ResolvedMark = Mark;
        Asset->PingSound = TSoftObjectPtr<USoundBase>(AssetPathOf(Str(T, TEXT("ping_sound"))));
        Asset->MatchSound = TSoftObjectPtr<USoundBase>(AssetPathOf(Str(T, TEXT("match_sound"))));
    }

    OutReport = FString::Printf(TEXT("%d inscriptions, %d steles (%d not carved into the atlas yet)"),
        Asset->Inscriptions.Num(), Asset->Steles.Num(), Unready);
    for (int32 I = 0; I < Problems.Num() && I < 12; ++I)
    {
        OutReport += TEXT("\n  ") + Problems[I];
    }
    return Asset->Steles.Num() > 0;
}

bool USaskartaSteleScanImport::ImportSteleScanFromFiles(USaskartaSteleScanAsset* Asset, const FString& ProjectDir, FString& OutReport)
{
    const FString Path = FPaths::Combine(ProjectDir, TEXT("docs/story/inscriptions.json"));
    FString Json;
    if (!FFileHelper::LoadFileToString(Json, *Path))
    {
        OutReport = FString::Printf(TEXT("cannot read %s"), *Path);
        return false;
    }
    const bool bOk = ParseInscriptionsJson(Json, Asset, OutReport);
    if (bOk && Asset)
    {
        Asset->MarkPackageDirty();
    }
    return bOk;
}

USaskartaSteleScanAsset* USaskartaSteleScanImport::LoadOrImportTransient(UObject* Outer)
{
    if (USaskartaSteleScanAsset* Asset = LoadObject<USaskartaSteleScanAsset>(nullptr, AssetPath, nullptr, LOAD_NoWarn | LOAD_Quiet))
    {
        return Asset;
    }
#if WITH_EDITOR
    USaskartaSteleScanAsset* Transient = NewObject<USaskartaSteleScanAsset>(Outer ? Outer : GetTransientPackage());
    FString Report;
    if (ImportSteleScanFromFiles(Transient, FPaths::ProjectDir(), Report))
    {
        UE_LOG(LogSaskartaSteleImport, Warning,
            TEXT("DA_Saskarta_SteleScan not found; imported a transient copy from docs/story (editor only). %s"), *Report.Left(400));
        return Transient;
    }
#endif
    UE_LOG(LogSaskartaSteleImport, Warning, TEXT("DA_Saskarta_SteleScan not found (%s); the stele scanner is idle."), AssetPath);
    return nullptr;
}
