// FSaskartaStationLogic, FSaskartaShuffleBag, FSaskartaStationScheduler. See the header.

#include "SaskartaStationLogic.h"

#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

namespace SaskartaStation
{
    static const FName CatId(TEXT("ID"));
    static const FName CatIntro(TEXT("INTRO"));
    static const FName CatOutro(TEXT("OUTRO"));
    static const FName CatRequest(TEXT("REQUEST"));
}

// ============================================================================ shuffle bag

void FSaskartaShuffleBag::Reset(const TArray<int32>& InItems, const TArray<float>& InWeights)
{
    Items = InItems;
    Weights = InWeights;
    Weights.SetNum(Items.Num());
    for (float& W : Weights)
    {
        if (!(W > 0.f)) W = 1.f;
    }
    Remaining = Items;
    LastPlayed = INDEX_NONE;
    bJustRefilled = false;
}

float FSaskartaShuffleBag::WeightOf(int32 Item) const
{
    const int32 I = Items.IndexOfByKey(Item);
    return I == INDEX_NONE ? 1.f : Weights[I];
}

int32 FSaskartaShuffleBag::Draw(FRandomStream& Rand, const TSet<int32>* Excluded)
{
    if (Items.Num() == 0)
    {
        return INDEX_NONE;
    }
    if (Remaining.Num() == 0)
    {
        Remaining = Items;
        bJustRefilled = true;
    }
    TArray<int32> Candidates;
    float Total = 0.f;
    for (const int32 It : Remaining)
    {
        if (Excluded && Excluded->Contains(It))
        {
            continue;
        }
        // The first draw after a refill never repeats the last item played.
        if (bJustRefilled && It == LastPlayed && Items.Num() > 1)
        {
            continue;
        }
        Candidates.Add(It);
        Total += WeightOf(It);
    }
    if (Candidates.Num() == 0)
    {
        return INDEX_NONE;
    }
    float R = Rand.FRand() * Total;
    int32 Pick = Candidates.Last();
    for (const int32 C : Candidates)
    {
        R -= WeightOf(C);
        if (R <= 0.f)
        {
            Pick = C;
            break;
        }
    }
    Remaining.RemoveSingle(Pick);
    LastPlayed = Pick;
    bJustRefilled = false;
    return Pick;
}

void FSaskartaShuffleBag::PutBack(int32 Item)
{
    if (Items.Contains(Item) && !Remaining.Contains(Item))
    {
        Remaining.Add(Item);
    }
}

// ============================================================================ logic

bool FSaskartaStationLogic::MayStartAtRoad(const FSaskartaStationConfig& Config, FName FlowState, float RoadM)
{
    return Config.StartRoadM > 0.f && Config.PlayFlowStates.Contains(FlowState) && RoadM >= Config.StartRoadM;
}

ESaskartaStationMode FSaskartaStationLogic::ModeFor(FName FlowState, bool bStarted, bool bSettingOn, bool bStoppedForGood,
    const FSaskartaStationConfig& Config)
{
    if (bStoppedForGood || (!Config.StopFlowState.IsNone() && FlowState == Config.StopFlowState))
    {
        return ESaskartaStationMode::Stopped;
    }
    if (!bStarted || !bSettingOn)
    {
        return ESaskartaStationMode::Off;
    }
    if (Config.PlayFlowStates.Contains(FlowState))
    {
        return ESaskartaStationMode::On;
    }
    if (Config.HoldFlowStates.Contains(FlowState))
    {
        return ESaskartaStationMode::Held;
    }
    return ESaskartaStationMode::Off;
}

FName FSaskartaStationLogic::PickCategory(const TMap<FName, float>& Weights, FName Last, FRandomStream& Rand)
{
    float Total = 0.f;
    for (const TPair<FName, float>& KV : Weights)
    {
        if (KV.Key != Last && KV.Value > 0.f) Total += KV.Value;
    }
    if (Total <= 0.f)
    {
        return NAME_None;
    }
    float R = Rand.FRand() * Total;
    FName Pick = NAME_None;
    for (const TPair<FName, float>& KV : Weights)
    {
        if (KV.Key == Last || KV.Value <= 0.f) continue;
        Pick = KV.Key;
        R -= KV.Value;
        if (R <= 0.f) break;
    }
    return Pick;
}

ESaskartaStationGate FSaskartaStationLogic::EvaluateGate(const FSaskartaStationGateInput& In, float SegmentS, const FSaskartaStationConfig& Config)
{
    if (In.bIdle)
    {
        return ESaskartaStationGate::Idle;
    }
    if (In.bStoryBusy)
    {
        return ESaskartaStationGate::StoryBusy;
    }
    if (In.SecondsSinceStory < Config.HoldoffAfterLineS)
    {
        return ESaskartaStationGate::Holdoff;
    }
    if (In.SecondsToNextBeat < FMath::Max(Config.LookaheadS, SegmentS + Config.FitMarginS))
    {
        return ESaskartaStationGate::BeatTooClose;
    }
    for (const FVector2f& R : Config.QuietRangesRoadM)
    {
        if (In.RoadM >= R.X && In.RoadM <= R.Y)
        {
            return ESaskartaStationGate::QuietRange;
        }
    }
    return ESaskartaStationGate::Open;
}

float FSaskartaStationLogic::MaxFitS(const FSaskartaStationGateInput& In, const FSaskartaStationConfig& Config)
{
    return In.SecondsToNextBeat - Config.FitMarginS;
}

FString FSaskartaStationLogic::FillTemplate(const FString& Template, const FString& PlainText, const TMap<FString, FString>& Values)
{
    if (Template.IsEmpty())
    {
        return PlainText;
    }
    auto Substitute = [&Values](const FString& In, bool& bAllFilled) -> FString
    {
        FString Out;
        bAllFilled = true;
        int32 i = 0;
        while (i < In.Len())
        {
            if (In[i] == TEXT('{'))
            {
                const int32 Close = In.Find(TEXT("}"), ESearchCase::CaseSensitive, ESearchDir::FromStart, i);
                if (Close != INDEX_NONE)
                {
                    const FString Key = In.Mid(i + 1, Close - i - 1);
                    const FString* V = Values.Find(Key);
                    if (V && !V->IsEmpty())
                    {
                        Out += *V;
                    }
                    else
                    {
                        bAllFilled = false;
                    }
                    i = Close + 1;
                    continue;
                }
            }
            Out.AppendChar(In[i]);
            ++i;
        }
        return Out;
    };

    FString Out;
    int32 i = 0;
    while (i < Template.Len())
    {
        if (Template[i] == TEXT('['))
        {
            const int32 Close = Template.Find(TEXT("]"), ESearchCase::CaseSensitive, ESearchDir::FromStart, i);
            if (Close != INDEX_NONE)
            {
                bool bAll = true;
                const FString Group = Substitute(Template.Mid(i + 1, Close - i - 1), bAll);
                if (bAll)
                {
                    Out += Group;
                }
                i = Close + 1;
                continue;
            }
        }
        Out.AppendChar(Template[i]);
        ++i;
    }
    bool bIgnored = true;
    return Substitute(Out, bIgnored);
}

FString FSaskartaStationLogic::SongCaption(const FString& Title, const FString& Singer)
{
    TArray<FString> Parts;
    if (!Title.TrimStartAndEnd().IsEmpty()) Parts.Add(Title.TrimStartAndEnd());
    if (!Singer.TrimStartAndEnd().IsEmpty()) Parts.Add(Singer.TrimStartAndEnd());
    // The word, not a U+266A note: the caption fonts (Cormorant Garamond, Cinzel, VT323) have no music
    // glyph, and Slate fell back to its last-resort font for it. " · " is in all of them.
    Parts.Insert(FString(TEXT("Song")), 0);
    return FString::Join(Parts, TEXT(" · "));
}

float FSaskartaStationLogic::Quality(const TArray<FVector2f>& Curve, float RoadM)
{
    if (Curve.Num() == 0)
    {
        return 1.f;
    }
    if (RoadM <= Curve[0].X)
    {
        return Curve[0].Y;
    }
    for (int32 i = 0; i + 1 < Curve.Num(); ++i)
    {
        if (RoadM >= Curve[i].X && RoadM <= Curve[i + 1].X)
        {
            const float Span = Curve[i + 1].X - Curve[i].X;
            const float T = Span > 0.f ? (RoadM - Curve[i].X) / Span : 0.f;
            return FMath::Lerp(Curve[i].Y, Curve[i + 1].Y, T);
        }
    }
    return Curve.Last().Y;
}

float FSaskartaStationLogic::MapQ(float Q, const FVector2f& AtQ1AndQLow)
{
    const float T = FMath::Clamp((1.f - Q) / 0.75f, 0.f, 1.f);
    return FMath::Lerp(AtQ1AndQLow.X, AtQ1AndQLow.Y, T);
}

float FSaskartaStationLogic::ReceptionVoiceDb(float Q, const FSaskartaStationConfig& Config)
{
    const float SafeQ = FMath::IsFinite(Q) ? FMath::Clamp(Q, 0.f, 1.f) : 1.f;
    // VoiceGainDbAtQ0 is an endpoint, not another loss added to the q=.25 gain.
    return SafeQ >= 0.25f ? MapQ(SafeQ, Config.VoiceGainDb)
        : FMath::Lerp(Config.VoiceGainDbAtQ0, Config.VoiceGainDb.Y, SafeQ / 0.25f);
}

float FSaskartaStationLogic::ProgrammeGainDb(float Q, const FSaskartaStationConfig& Config)
{
    return FMath::Max(-12.f, ReceptionVoiceDb(Q, Config));
}

float FSaskartaStationLogic::EndingMusicDb(FName Flow)
{
    if (Flow == FName(TEXT("End"))) return 0.f;
    if (Flow == FName(TEXT("Transmit"))) return -16.f;
    return -10.f;
}

float FSaskartaStationLogic::DropoutRate(float Q, const FSaskartaStationConfig& Config)
{
    if (Q >= Config.DropoutStartQ)
    {
        return 0.f;
    }
    const float Span = Config.DropoutStartQ - 0.25f;
    const float T = Span > 0.f ? FMath::Clamp((Config.DropoutStartQ - Q) / Span, 0.f, 1.f) : 1.f;
    return Config.DropoutRateAtLowQ * T;
}

TArray<FString> FSaskartaStationLogic::TakeCandidates(const FString& HostFolder, FName LineId, FName SongId)
{
    TArray<FString> Out;
    auto Add = [&Out](const FString& Folder, const FString& Name)
    {
        Out.Add(FString::Printf(TEXT("%s/%s.%s"), *Folder, *Name, *Name));
    };
    const FString Plain = FString::Printf(TEXT("VO_Station_%s"), *LineId.ToString());
    const FString Recorded = HostFolder + TEXT("/Recorded");
    if (!SongId.IsNone())
    {
        const FString Named = FString::Printf(TEXT("%s__%s"), *Plain, *SongId.ToString());
        Add(Recorded, Named);
        Add(HostFolder, Named);
    }
    Add(Recorded, Plain);
    Add(HostFolder, Plain);
    return Out;
}

FString FSaskartaStationLogic::FirstExistingTakeCandidate(const TArray<FString>& CandidatePaths,
    TFunctionRef<bool(const FString&)> Exists)
{
    for (const FString& Path : CandidatePaths)
    {
        if (Exists(Path))
        {
            return Path;
        }
    }
    return FString();
}

FString FSaskartaStationLogic::SongAssetPath(const FString& SongFolder, FName SongId)
{
    const FString Name = FString::Printf(TEXT("SONG_%s"), *SongId.ToString());
    return FString::Printf(TEXT("%s/%s.%s"), *SongFolder, *Name, *Name);
}

TSet<FName> FSaskartaStationLogic::ParseTtsManifest(const FString& Json)
{
    TSet<FName> Out;
    TArray<TSharedPtr<FJsonValue>> Arr;
    const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Json);
    if (!FJsonSerializer::Deserialize(Reader, Arr))
    {
        return Out;
    }
    for (const TSharedPtr<FJsonValue>& V : Arr)
    {
        const TSharedPtr<FJsonObject>* O = nullptr;
        FString Id;
        if (V.IsValid() && V->TryGetObject(O) && O && (*O)->TryGetStringField(TEXT("id"), Id) && !Id.IsEmpty())
        {
            Out.Add(FName(*Id));
        }
    }
    return Out;
}

FSaskartaStationLogic::ETakeSource FSaskartaStationLogic::ClassifyTake(FName LineId, const TSet<FName>& TtsIds, bool bSelectedWavExists, bool bRawTakeExists)
{
    if (bRawTakeExists)
    {
        return ETakeSource::User;
    }
    if (!bSelectedWavExists)
    {
        return ETakeSource::Missing;
    }
    return TtsIds.Contains(LineId) ? ETakeSource::Tts : ETakeSource::User;
}

// ============================================================================ scheduler

void FSaskartaStationScheduler::Init(const FSaskartaStationConfig& InConfig, int32 Seed)
{
    Config = InConfig;
    Rand.Initialize(Seed);
    Bags.Reset();
    TMap<FName, TArray<int32>> ItemsBy;
    TMap<FName, TArray<float>> WeightsBy;
    for (int32 i = 0; i < Config.Segments.Num(); ++i)
    {
        const FSaskartaStationSegment& S = Config.Segments[i];
        const FName Key = FSaskartaStationLogic::BagKeyFor(S);
        ItemsBy.FindOrAdd(Key).Add(i);
        WeightsBy.FindOrAdd(Key).Add(S.bLeavingHint && S.Weight >= 1.f ? 0.6f : S.Weight);
    }
    for (const TPair<FName, TArray<int32>>& KV : ItemsBy)
    {
        Bags.FindOrAdd(KV.Key).Reset(KV.Value, WeightsBy.FindRef(KV.Key));
    }
    SongBagIds.Reset();
    SongBag.Reset({}, {});
    SlotCount = 0;
    LastCategory = NAME_None;
    SegmentsSinceLeaving = 1000;
    Clock = FSaskartaStationClock();
    Clock.ScheduleNextSongBlock(Rand, Config.SongIntervalS);
}

void FSaskartaStationScheduler::SyncSongBag(const TArray<FName>& AvailableSongs)
{
    if (AvailableSongs == SongBagIds)
    {
        return;
    }
    // New songs are picked up at the next refill; rebuilding keeps it simple and fair.
    SongBagIds = AvailableSongs;
    TArray<int32> Items;
    TArray<float> Weights;
    for (int32 i = 0; i < SongBagIds.Num(); ++i)
    {
        Items.Add(i);
        Weights.Add(1.f);
    }
    SongBag.Reset(Items, Weights);
}

bool FSaskartaStationScheduler::IsLeavingBlocked() const
{
    return SegmentsSinceLeaving < Config.LeavingHintMinSpacing;
}

int32 FSaskartaStationScheduler::DrawFrom(FName Category, float MaxFitS, FName SongId, FVoiceLenFn VoiceLen, bool bApplyLeaving, float& OutLen)
{
    FSaskartaShuffleBag* Bag = Bags.Find(Category);
    if (!Bag)
    {
        return INDEX_NONE;
    }
    TSet<int32> Excluded;
    if (bApplyLeaving && IsLeavingBlocked())
    {
        for (int32 i = 0; i < Config.Segments.Num(); ++i)
        {
            if (Config.Segments[i].Category == Category && Config.Segments[i].bLeavingHint) Excluded.Add(i);
        }
    }
    const int32 Tries = FMath::Max(1, Config.RedrawsBeforeWait + 1);
    TArray<int32> Rejected;
    int32 Result = INDEX_NONE;
    for (int32 t = 0; t < Tries; ++t)
    {
        const int32 Item = Bag->Draw(Rand, &Excluded);
        if (Item == INDEX_NONE)
        {
            break;
        }
        const float Len = VoiceLen(Item, SongId);
        if (Len >= 0.f && Len <= MaxFitS)
        {
            OutLen = Len;
            Result = Item;
            break;
        }
        // Too long for the gap to the next beat, or no take: back in the bag, try another.
        Rejected.Add(Item);
        Excluded.Add(Item);
    }
    for (const int32 R : Rejected)
    {
        Bag->PutBack(R);
    }
    return Result;
}

FSaskartaStationPick FSaskartaStationScheduler::PickSlot(float MaxFitS, const TArray<FName>& AvailableSongs, FVoiceLenFn VoiceLen, FSongLenFn SongLen)
{
    using namespace SaskartaStation;
    FSaskartaStationPick Pick;
    SyncSongBag(AvailableSongs);

    if (Clock.SongBlockDue())
    {
        if (SongBagIds.Num() == 0)
        {
            // No song asset: skip the block, restart its clock.
            Clock.ScheduleNextSongBlock(Rand, Config.SongIntervalS);
        }
        else
        {
            const int32 SongIndex = SongBag.Draw(Rand);
            const FName SongId = SongBagIds.IsValidIndex(SongIndex) ? SongBagIds[SongIndex] : NAME_None;
            const float SongS = SongId.IsNone() ? -1.f : SongLen(SongId);
            if (SongS > 0.f)
            {
                const FName Lead = Rand.FRand() < Config.IntroChance ? CatIntro : CatRequest;
                float LinkS = 0.f, OutroS = 0.f;
                const float Budget = MaxFitS - SongS - Config.GapAfterLinkS - Config.GapBeforeOutroS;
                const int32 Link = DrawFrom(Lead, Budget, SongId, VoiceLen, false, LinkS);
                const int32 Outro = Link != INDEX_NONE ? DrawFrom(CatOutro, Budget - LinkS, SongId, VoiceLen, false, OutroS) : INDEX_NONE;
                if (Link != INDEX_NONE && Outro != INDEX_NONE)
                {
                    Pick.bValid = true;
                    Pick.bSongBlock = true;
                    Pick.Category = Lead;
                    FSaskartaStationPart P;
                    P.Kind = FSaskartaStationPart::EKind::Voice; P.SegmentIndex = Link; P.SongId = SongId; P.DurationS = LinkS;
                    Pick.Parts.Add(P);
                    P = FSaskartaStationPart(); P.Kind = FSaskartaStationPart::EKind::Static; P.DurationS = Config.GapAfterLinkS;
                    Pick.Parts.Add(P);
                    P = FSaskartaStationPart(); P.Kind = FSaskartaStationPart::EKind::Song; P.SongId = SongId; P.DurationS = SongS;
                    Pick.Parts.Add(P);
                    P = FSaskartaStationPart(); P.Kind = FSaskartaStationPart::EKind::Static; P.DurationS = Config.GapBeforeOutroS;
                    Pick.Parts.Add(P);
                    P = FSaskartaStationPart(); P.Kind = FSaskartaStationPart::EKind::Voice; P.SegmentIndex = Outro; P.SongId = SongId; P.DurationS = OutroS;
                    Pick.Parts.Add(P);
                    Pick.TotalS = LinkS + Config.GapAfterLinkS + SongS + Config.GapBeforeOutroS + OutroS;
                    return Pick;
                }
                // The whole block does not fit before the next beat: put it all back.
                if (Link != INDEX_NONE)
                {
                    if (FSaskartaShuffleBag* B = Bags.Find(Lead)) B->PutBack(Link);
                }
            }
            SongBag.PutBack(SongIndex);
        }
    }

    const int32 SlotNumber = SlotCount + 1;
    TArray<FName> Order;
    if (FSaskartaStationLogic::IsIdSlot(SlotNumber, Config.IdEveryNthSegment))
    {
        Order.Add(CatId);
    }
    else
    {
        const FName First = FSaskartaStationLogic::PickCategory(Config.CategoryWeights, LastCategory, Rand);
        if (!First.IsNone())
        {
            Order.Add(First);
        }
        // Then any other allowed category (a too-long draw retries elsewhere).
        TMap<FName, float> Rest = Config.CategoryWeights;
        Rest.Remove(First);
        while (Rest.Num() > 0)
        {
            const FName Next = FSaskartaStationLogic::PickCategory(Rest, LastCategory, Rand);
            if (Next.IsNone()) break;
            Order.Add(Next);
            Rest.Remove(Next);
        }
    }
    // LANE5 + second batch: FRAG lines while the signal breaks up, then ZONE lines for the ground being crossed.
    auto InRange = [this](const FVector2f& R) { return R.X < 0.f || (CurrentRoadM >= R.X && CurrentRoadM <= R.Y); };
    auto TakeFrom = [&](FName Key, FSaskartaStationPick& Out) -> bool
    {
        const FSaskartaShuffleBag* Bag = Bags.Find(Key);
        if (!Bag || Bag->NumRemaining() == 0) return false;
        float BagLen = 0.f;
        const int32 Seg = DrawFrom(Key, MaxFitS, NAME_None, VoiceLen, false, BagLen);
        if (Seg == INDEX_NONE) return false;
        Out.bValid = true;
        Out.Category = Config.Segments[Seg].Category;
        FSaskartaStationPart Part;
        Part.Kind = FSaskartaStationPart::EKind::Voice;
        Part.SegmentIndex = Seg;
        Part.DurationS = BagLen;
        Out.Parts.Add(Part);
        Out.TotalS = BagLen;
        return true;
    };
    const bool bIdSlot = Order.Num() > 0 && Order[0] == CatId;
    if (!bIdSlot && InRange(Config.FragmentRoadM) && CurrentQuality <= Config.FragmentMaxQuality
        && Config.FragmentEveryNthSlot > 0 && SlotNumber % Config.FragmentEveryNthSlot == 0 && TakeFrom(TEXT("FRAG"), Pick))
    {
        return Pick;
    }
    if (!bIdSlot && Rand.FRand() < Config.ZoneShare)
    {
        TArray<FName> Keys;
        for (const FSaskartaStationSegment& S : Config.Segments)
        {
            const FName Key = FSaskartaStationLogic::BagKeyFor(S);
            if (Key != S.Category && S.RoadMRange.X >= 0.f && InRange(S.RoadMRange)) Keys.AddUnique(Key);
        }
        while (Keys.Num() > 0)
        {
            const int32 i = Rand.RandRange(0, Keys.Num() - 1);
            if (TakeFrom(Keys[i], Pick)) return Pick;
            Keys.RemoveAt(i);
        }
    }
    for (const FName& Cat : Order)
    {
        float Len = 0.f;
        const int32 Seg = DrawFrom(Cat, MaxFitS, NAME_None, VoiceLen, true, Len);
        if (Seg != INDEX_NONE)
        {
            Pick.bValid = true;
            Pick.Category = Cat;
            FSaskartaStationPart P;
            P.Kind = FSaskartaStationPart::EKind::Voice;
            P.SegmentIndex = Seg;
            P.DurationS = Len;
            Pick.Parts.Add(P);
            Pick.TotalS = Len;
            return Pick;
        }
    }
    return Pick;
}

void FSaskartaStationScheduler::CommitPick(const FSaskartaStationPick& Pick)
{
    if (!Pick.bValid)
    {
        return;
    }
    if (Pick.bSongBlock)
    {
        // Song blocks are not slots; any category may follow.
        LastCategory = NAME_None;
        Clock.ScheduleNextSongBlock(Rand, Config.SongIntervalS);
        return;
    }
    ++SlotCount;
    if (Pick.Category != SaskartaStation::CatId)
    {
        LastCategory = Pick.Category;
    }
    ++SegmentsSinceLeaving;
    for (const FSaskartaStationPart& P : Pick.Parts)
    {
        if (Config.Segments.IsValidIndex(P.SegmentIndex) && Config.Segments[P.SegmentIndex].bLeavingHint)
        {
            SegmentsSinceLeaving = 0;
        }
    }
}

void FSaskartaStationScheduler::ReturnSegment(int32 SegmentIndex)
{
    if (!Config.Segments.IsValidIndex(SegmentIndex))
    {
        return;
    }
    if (FSaskartaShuffleBag* Bag = Bags.Find(FSaskartaStationLogic::BagKeyFor(Config.Segments[SegmentIndex])))
    {
        Bag->PutBack(SegmentIndex);
    }
}

void FSaskartaStationScheduler::Unpick(const FSaskartaStationPick& Pick)
{
    for (const FSaskartaStationPart& P : Pick.Parts)
    {
        if (P.Kind == FSaskartaStationPart::EKind::Voice)
        {
            ReturnSegment(P.SegmentIndex);
        }
        else if (P.Kind == FSaskartaStationPart::EKind::Song)
        {
            const int32 SongIndex = SongBagIds.IndexOfByKey(P.SongId);
            if (SongIndex != INDEX_NONE) SongBag.PutBack(SongIndex);
        }
    }
}

FString FSaskartaStationScheduler::DescribeBags() const
{
    FString Out = FString::Printf(TEXT("slot %d, last %s, station time %.0f s, next song block at %.0f s, songs %d;"),
        SlotCount, *LastCategory.ToString(), Clock.StationTimeS, Clock.NextSongBlockAtS, SongBagIds.Num());
    for (const TPair<FName, FSaskartaShuffleBag>& KV : Bags)
    {
        Out += FString::Printf(TEXT(" %s %d/%d"), *KV.Key.ToString(), KV.Value.NumRemaining(), KV.Value.NumItems());
    }
    return Out;
}

// ============================================================================ dry run

FSaskartaStationDryRunStats SaskartaStationDryRun(const FSaskartaStationConfig& Config, float StationSeconds, int32 Seed,
    const TArray<FName>& Songs, float SongLengthS, TArray<FString>* OutLog)
{
    FSaskartaStationDryRunStats Stats;
    FSaskartaStationScheduler S;
    S.Init(Config, Seed);
    double T = S.DrawFirstDelayS();
    S.Clock.Advance(T, true);
    FName PrevCategory;
    int32 SlotsSinceLeaving = 1000;
    double LastSongStart = -1.0;
    while (T < StationSeconds)
    {
        const FSaskartaStationPick Pick = S.PickSlot(1.0e6f, Songs,
            [&Config](int32 Seg, FName) { return Config.Segments.IsValidIndex(Seg) ? Config.Segments[Seg].TargetS : -1.f; },
            [SongLengthS](FName) { return SongLengthS; });
        if (!Pick.bValid)
        {
            T += Config.RetryS;
            S.Clock.Advance(Config.RetryS, true);
            continue;
        }
        const int32 SlotBefore = S.GetSlotCount();
        S.CommitPick(Pick);
        if (Pick.bSongBlock)
        {
            ++Stats.SongBlocks;
            if (LastSongStart >= 0.0) Stats.MinSongSpacingS = FMath::Min(Stats.MinSongSpacingS, static_cast<float>(T - LastSongStart));
            LastSongStart = T;
            PrevCategory = NAME_None;
        }
        else
        {
            ++Stats.Segments;
            const FSaskartaStationSegment& Seg = Config.Segments[Pick.Parts[0].SegmentIndex];
            const bool bIdSlot = FSaskartaStationLogic::IsIdSlot(SlotBefore + 1, Config.IdEveryNthSegment);
            if (Pick.Category == SaskartaStation::CatId) ++Stats.Ids;
            if (bIdSlot != (Pick.Category == SaskartaStation::CatId)) ++Stats.IdSlotViolations;
            if (Pick.Category != SaskartaStation::CatId)
            {
                if (Pick.Category == PrevCategory) ++Stats.SameCategoryRepeats;
                PrevCategory = Pick.Category;
            }
            ++SlotsSinceLeaving;
            if (Seg.bLeavingHint)
            {
                if (SlotsSinceLeaving < Config.LeavingHintMinSpacing) ++Stats.LeavingSpacingViolations;
                SlotsSinceLeaving = 0;
            }
        }
        if (OutLog)
        {
            FString What;
            for (const FSaskartaStationPart& P : Pick.Parts)
            {
                if (P.Kind == FSaskartaStationPart::EKind::Voice) What += Config.Segments[P.SegmentIndex].Id.ToString() + TEXT(" ");
                else if (P.Kind == FSaskartaStationPart::EKind::Song) What += TEXT("SONG_") + P.SongId.ToString() + TEXT(" ");
            }
            OutLog->Add(FString::Printf(TEXT("%7.1fs  %-8s %s(%.1f s)"), T, *Pick.Category.ToString(), *What, Pick.TotalS));
        }
        T += Pick.TotalS;
        S.Clock.Advance(Pick.TotalS, true);
        const float Gap = S.DrawGapS();
        Stats.MinGapS = FMath::Min(Stats.MinGapS, Gap);
        Stats.MaxGapS = FMath::Max(Stats.MaxGapS, Gap);
        T += Gap;
        S.Clock.Advance(Gap, true);
    }
    if (OutLog)
    {
        OutLog->Add(FString::Printf(TEXT("DryRun %.0f s: %d segments (%d IDs), %d song blocks, repeats %d, ID violations %d, leaving violations %d, gaps %.0f-%.0f s"),
            StationSeconds, Stats.Segments, Stats.Ids, Stats.SongBlocks, Stats.SameCategoryRepeats, Stats.IdSlotViolations,
            Stats.LeavingSpacingViolations, Stats.MinGapS, Stats.MaxGapS));
    }
    return Stats;
}

// ============================================================================ LANE5: zones and labels

FName FSaskartaStationLogic::ZoneAt(const TArray<FSaskartaStationZone>& Zones, float RoadM)
{
    for (const FSaskartaStationZone& Z : Zones)
    {
        if (RoadM >= Z.FromRoadM && RoadM < Z.ToRoadM)
        {
            return Z.Name;
        }
    }
    return NAME_None;
}

FName FSaskartaStationLogic::BagKeyFor(const FSaskartaStationSegment& Segment)
{
    return (Segment.Zone.IsNone() || Segment.Category != FName(TEXT("ZONE"))) ? Segment.Category : FName(*(FString(TEXT("ZONE_")) + Segment.Zone.ToString()));
}

FString FSaskartaStationLogic::CategoryLabel(const TMap<FName, FString>& Labels, FName Category)
{
    if (const FString* L = Labels.Find(Category))
    {
        return *L;
    }
    FString S = Category.ToString().ToLower();
    if (S.Len() > 0)
    {
        S[0] = FChar::ToUpper(S[0]);
    }
    return S;
}
