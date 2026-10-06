// Automation tests for the stele scan (task STELESCAN, docs/look/STELE_SCAN.md section 3.9):
// once per stele, the distance / facing rule, the repetition rule, the voice gate (story Voice channel,
// the Climb, a refused voice passing on), the Custom Primitive Data time write (pure values and a real
// UStaticMeshComponent), the HUD text, pacing, the inscriptions.json import, and the prompted scan
// (Saskarta.Steles.Prompt*: range and view cone, hysteresis, one scan per stele, blocked states, E starts it).
//
// Written offline while the editor held the binaries (fail-first waived, as R33). Run after the build:
//   Automation RunTests Saskarta.Steles

#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "Components/StaticMeshComponent.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "SaskartaEventLogic.h"
#include "SaskartaSteleScanAsset.h"
#include "SaskartaSteleScanLogic.h"
#include "SaskartaSteleScanner.h"
#include "UObject/Package.h"

namespace SaskartaSteleScanTest
{
    using FStele = FSaskartaSteleScanCore::FStele;
    using EKind = ESaskartaSteleReadKind;

    static FStele Stele(const TCHAR* Id, const TCHAR* Inscription, float RoadM, float Wear = 0.2f, bool bDock = false)
    {
        FStele S;
        S.Id = FName(Id);
        S.Inscription = FName(Inscription);
        S.RoadM = RoadM;
        S.Wear = Wear;
        S.bDock = bDock;
        return S;
    }

    /** A stone straight ahead, face-on, in sight, at DistanceM. */
    static FSaskartaSteleView Good(int32 Index, float DistanceM = 10.f)
    {
        FSaskartaSteleView V;
        V.Index = Index;
        V.DistanceM = DistanceM;
        V.ViewAngleDeg = 5.f;
        V.FaceDot = 0.9f;
        V.bLineOfSight = true;
        return V;
    }

    /** The way-stone texts along a short road: I05, W05, I05, W05, I05 (the last one worn). */
    static FSaskartaSteleScanCore Road()
    {
        FSaskartaSteleScanCore C;
        C.Steles.Add(Stele(TEXT("Stele_WayStone_0"), TEXT("I05"), 50.f));
        C.Steles.Add(Stele(TEXT("Stele_WayStone_1"), TEXT("W05"), 200.f));
        C.Steles.Add(Stele(TEXT("Stele_WayStone_2"), TEXT("I05"), 350.f));
        C.Steles.Add(Stele(TEXT("Stele_WayStone_3"), TEXT("W05"), 500.f));
        C.Steles.Add(Stele(TEXT("Stele_WayStone_4"), TEXT("I05"), 650.f, 0.85f));
        C.SortByRoad();
        return C;
    }

    /** Reads stele Index at NowS (clear of pacing) and returns the decision. */
    static FSaskartaSteleReadDecision ReadAt(FSaskartaSteleScanCore& C, int32 Index, double NowS, const FSaskartaSteleScanTuning& T)
    {
        return C.Decide(NowS, true, false, 0.f, { Good(Index) }, T);
    }
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaStelesOncePerSteleTest, "Saskarta.Steles.OncePerStele",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaStelesOncePerSteleTest::RunTest(const FString&)
{
    using namespace SaskartaSteleScanTest;
    FSaskartaSteleScanTuning T;
    FSaskartaSteleScanCore C = Road();
    const FSaskartaSteleReadDecision First = ReadAt(C, 0, 10.0, T);
    TestTrue("the first look reads the stone", First.IsRead());
    TestEqual("its stele", First.Stele, 0);
    TestTrue("marked read", C.Steles[0].bRead);
    const FSaskartaSteleReadDecision Again = ReadAt(C, 0, 100.0, T);
    TestFalse("never twice, even long after", Again.IsRead());

    TArray<int32> Cands;
    C.Candidates(60.f, T, Cands);
    TestFalse("a read stone is no candidate", Cands.Contains(0));
    C.Candidates(160.f, T, Cands);
    TestTrue("the stone 40 m ahead is a candidate", Cands.Contains(1));
    TestFalse("one 190 m ahead is not", Cands.Contains(2));
    C.Candidates(215.f, T, Cands);
    TestTrue("15 m behind is past the window (BehindM 10)", !Cands.Contains(1));

    // The closest eligible view wins; one reading per tick.
    FSaskartaSteleScanCore C2 = Road();
    const FSaskartaSteleReadDecision Closest = C2.Decide(10.0, true, false, 0.f, { Good(2, 18.f), Good(1, 7.f) }, T);
    TestEqual("the closer one", Closest.Stele, 1);
    TestFalse("the other waits", C2.Steles[2].bRead);

    // Continue / GoTo: stones behind count as read.
    FSaskartaSteleScanCore C3 = Road();
    TestEqual("MarkBehind at 400 m marks three", C3.MarkBehind(400.f, T), 3);
    TestFalse("the one at 500 m stays", C3.Steles[3].bRead);
    C3.ResetReadings();
    TestFalse("reset unreads", C3.Steles[0].bRead);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaStelesDistanceFacingTest, "Saskarta.Steles.DistanceFacing",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaStelesDistanceFacingTest::RunTest(const FString&)
{
    using namespace SaskartaSteleScanTest;
    FSaskartaSteleScanTuning T;
    FSaskartaSteleView V = Good(0, 10.f);
    TestTrue("straight ahead at 10 m", FSaskartaSteleScanCore::Eligible(V, false, T));
    V.DistanceM = 23.f;
    TestFalse("past RangeM (22 m)", FSaskartaSteleScanCore::Eligible(V, false, T));
    V.DistanceM = 2.f;
    TestFalse("closer than MinRangeM (3 m)", FSaskartaSteleScanCore::Eligible(V, false, T));
    V = Good(0);
    V.ViewAngleDeg = 40.f;
    TestFalse("40 deg off the view axis: a way-stone must be well inside the frame", FSaskartaSteleScanCore::Eligible(V, false, T));
    TestTrue("but a dock post may be (DockViewDeg 70)", FSaskartaSteleScanCore::Eligible(V, true, T));
    V = Good(0);
    V.FaceDot = 0.1f;
    TestFalse("seen edge-on (FaceDot < 0.2)", FSaskartaSteleScanCore::Eligible(V, false, T));
    V.FaceDot = -0.5f;
    TestFalse("seen from behind", FSaskartaSteleScanCore::Eligible(V, false, T));
    V = Good(0);
    V.bLineOfSight = false;
    TestFalse("blocked", FSaskartaSteleScanCore::Eligible(V, false, T));

    FSaskartaSteleScanCore C = Road();
    FSaskartaSteleView Behind = Good(0);
    Behind.FaceDot = -0.9f;
    TestFalse("Decide skips an ineligible view", C.Decide(10.0, true, false, 0.f, { Behind }, T).IsRead());
    TestFalse("and leaves it unread", C.Steles[0].bRead);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaStelesRepetitionTest, "Saskarta.Steles.Repetition",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaStelesRepetitionTest::RunTest(const FString&)
{
    using namespace SaskartaSteleScanTest;
    FSaskartaSteleScanTuning T;
    FSaskartaSteleScanCore C = Road();
    double Now = 10.0;
    const FSaskartaSteleReadDecision A = ReadAt(C, 0, Now, T);
    TestTrue("first I05: full", A.Kind == EKind::Full);
    TestTrue("tries the voice", A.bTryVoice);
    TestEqual("number 1", A.Number, 1);
    C.OnVoiceResult(FName(TEXT("I05")), true, true);                // voiced
    Now += 30.0;
    const FSaskartaSteleReadDecision B = ReadAt(C, 1, Now, T);
    TestTrue("first W05: full", B.Kind == EKind::Full);
    TestEqual("number 2", B.Number, 2);
    C.OnVoiceResult(FName(TEXT("W05")), true, false);               // refused: text only
    Now += 30.0;
    const FSaskartaSteleReadDecision Cm = ReadAt(C, 2, Now, T);
    TestTrue("second I05: a match (voiced once)", Cm.Kind == EKind::Match);
    TestFalse("a match never speaks", Cm.bTryVoice);
    TestEqual("keeps its number", Cm.Number, 1);
    Now += 30.0;
    const FSaskartaSteleReadDecision D = ReadAt(C, 3, Now, T);
    TestTrue("second W05: full again, the refused voice passes on", D.Kind == EKind::Full && D.bTryVoice);
    TestEqual("W05 keeps number 2", D.Number, 2);
    C.OnVoiceResult(FName(TEXT("W05")), true, false);
    TestTrue("after MaxTextOnlyFullReads (2) refusals the text is matched",
        C.KindFor(Stele(TEXT("x"), TEXT("W05"), 900.f), T) == EKind::Match);
    Now += 30.0;
    const FSaskartaSteleReadDecision Worn = ReadAt(C, 4, Now, T);
    TestTrue("a worn stone only matches", Worn.Kind == EKind::Match);

    // A worn stone never gets the first full reading, even of a new text.
    FSaskartaSteleScanCore W;
    W.Steles.Add(Stele(TEXT("Stele_WayStone_10"), TEXT("W09"), 100.f, 0.85f));
    TestTrue("worn first stone: match", ReadAt(W, 0, 1.0, T).Kind == EKind::Match);

    // A full reading that never tried a voice (none recorded, policy never, the Climb) completes the text.
    FSaskartaSteleScanCore N = Road();
    ReadAt(N, 0, 1.0, T);
    N.OnVoiceResult(FName(TEXT("I05")), false, false);
    TestTrue("no voice tried: the next I05 is a match", N.KindFor(N.Steles[2], T) == EKind::Match);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaStelesVoiceGateTest, "Saskarta.Steles.VoiceGate",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaStelesVoiceGateTest::RunTest(const FString&)
{
    using namespace SaskartaSteleScanTest;
    // The runner's gate for a line outside any beat (FSaskartaEventLogic::CanStartAuxLine).
    const float Clip = 3.f, Gap = 1.5f, Lead = 4.f;
    TestTrue("free channel, quiet, next beat far", FSaskartaEventLogic::CanStartAuxLine(false, false, false, 10.f, 60.f, Clip, Gap, Lead));
    TestFalse("a story or radio line is playing", FSaskartaEventLogic::CanStartAuxLine(true, false, false, 10.f, 60.f, Clip, Gap, Lead));
    TestFalse("a cinematic", FSaskartaEventLogic::CanStartAuxLine(false, true, false, 10.f, 60.f, Clip, Gap, Lead));
    TestFalse("a beat is running or queued", FSaskartaEventLogic::CanStartAuxLine(false, false, true, 10.f, 60.f, Clip, Gap, Lead));
    TestFalse("a line just ended (< MinGapS)", FSaskartaEventLogic::CanStartAuxLine(false, false, false, 1.f, 60.f, Clip, Gap, Lead));
    TestFalse("the next beat is due within clip + LeadS", FSaskartaEventLogic::CanStartAuxLine(false, false, false, 10.f, 6.9f, Clip, Gap, Lead));
    TestTrue("exactly clip + LeadS away is fine", FSaskartaEventLogic::CanStartAuxLine(false, false, false, 10.f, 7.f, Clip, Gap, Lead));

    // The Climb is text only; a voice_policy "never" text is text only.
    FSaskartaSteleScanTuning T;
    TestTrue("3,703 m is in the silent range", FSaskartaSteleScanCore::InSilentRange(3703.f, T));
    TestFalse("3,302 m is not", FSaskartaSteleScanCore::InSilentRange(3302.f, T));
    FSaskartaSteleScanCore C;
    C.Steles.Add(Stele(TEXT("Stele_WayStone_26"), TEXT("W10"), 3703.f, 0.3f));
    FStele Never = Stele(TEXT("Stele_WayStone_23"), TEXT("W09"), 3302.f, 0.1f);
    Never.bNeverVoice = true;
    C.Steles.Add(Never);
    C.SortByRoad();
    const int32 Climb = C.FindStele(FName(TEXT("Stele_WayStone_26")));
    const int32 Quiet = C.FindStele(FName(TEXT("Stele_WayStone_23")));
    const FSaskartaSteleReadDecision OnClimb = ReadAt(C, Climb, 1.0, T);
    TestTrue("the Climb: still a full reading", OnClimb.Kind == EKind::Full);
    TestFalse("but no voice", OnClimb.bTryVoice);
    const FSaskartaSteleReadDecision NoVoice = ReadAt(C, Quiet, 100.0, T);
    TestFalse("policy never: no voice", NoVoice.bTryVoice);

    // A full reading that tries the voice holds the scanner for the whole voice wait.
    const float Hold = FSaskartaSteleScanCore::ReadingHoldS(EKind::Full, true, T);
    TestTrue("the hold covers VoiceAtS + VoiceWaitMaxS + HoldAfterVoiceS", Hold >= T.VoiceAtS + T.VoiceWaitMaxS + T.HoldAfterVoiceS - 1.e-3f);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaStelesCpdWriteTest, "Saskarta.Steles.CpdWrite",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaStelesCpdWriteTest::RunTest(const FString&)
{
    using EKind = ESaskartaSteleReadKind;
    const double Now = 1234.5;
    const TArray<FSaskartaSteleCpdWrite> Full = FSaskartaSteleScanCore::StartCpd(EKind::Full, Now, 7.4f);
    TestEqual("three writes", Full.Num(), 3);
    if (Full.Num() == 3)
    {
        TestEqual("ScanStart slot", Full[0].Index, SaskartaSteleCpd::ScanStart);
        TestEqual("ScanStart = game time", Full[0].Value, 1234.5f);
        TestEqual("ScanMode slot", Full[1].Index, SaskartaSteleCpd::ScanMode);
        TestEqual("full reading = 1", Full[1].Value, 1.f);
        TestEqual("GlowHold slot", Full[2].Index, SaskartaSteleCpd::GlowHold);
        TestEqual("hold", Full[2].Value, 7.4f);
    }
    const TArray<FSaskartaSteleCpdWrite> Match = FSaskartaSteleScanCore::StartCpd(EKind::Match, Now, 0.f);
    TestTrue("match = 0.5", Match.Num() == 3 && Match[1].Value == 0.5f);
    TestEqual("nothing for None", FSaskartaSteleScanCore::StartCpd(EKind::None, Now, 1.f).Num(), 0);
    TestEqual("hold after a voice: (voice start - scan start) + clip + 0.5",
        FSaskartaSteleScanCore::GlowHoldForVoice(100.0, 102.5, 3.f), 6.f);
    TestTrue("the runtime slots are not the defaults' slots",
        SaskartaSteleCpd::ScanStart != SaskartaSteleCpd::Wear && SaskartaSteleCpd::ScanStart != SaskartaSteleCpd::Cell
        && SaskartaSteleCpd::GlowHold >= SaskartaSteleCpd::CellRect + 4);

    // On a real component: the runtime data changes, the saved defaults (Wear, Cell, CellRect) do not.
    UStaticMeshComponent* Comp = NewObject<UStaticMeshComponent>(GetTransientPackage());
    Comp->SetDefaultCustomPrimitiveDataFloat(SaskartaSteleCpd::Wear, 0.35f);
    Comp->SetDefaultCustomPrimitiveDataFloat(SaskartaSteleCpd::Cell, 1.f);
    const int32 Writes = USaskartaSteleScanner::ApplyCpd(Comp, Full);
    TestEqual("applied", Writes, 3);
    const TArray<float>& Runtime = Comp->GetCustomPrimitiveData().Data;
    const TArray<float>& Defaults = Comp->GetDefaultCustomPrimitiveData().Data;
    TestTrue("runtime holds the scan start", Runtime.IsValidIndex(SaskartaSteleCpd::ScanStart) && Runtime[SaskartaSteleCpd::ScanStart] == 1234.5f);
    TestTrue("runtime keeps the wear (copied from the defaults)", Runtime.IsValidIndex(0) && Runtime[0] == 0.35f);
    TestTrue("runtime keeps the cell", Runtime.IsValidIndex(1) && Runtime[1] == 1.f);
    TestTrue("runtime GlowHold", Runtime.IsValidIndex(SaskartaSteleCpd::GlowHold) && Runtime[SaskartaSteleCpd::GlowHold] == 7.4f);
    TestEqual("defaults untouched", Defaults.Num(), 2);
    TestEqual("no component, no writes", USaskartaSteleScanner::ApplyCpd(nullptr, Full), 0);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaStelesPacingTest, "Saskarta.Steles.Pacing",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaStelesPacingTest::RunTest(const FString&)
{
    using namespace SaskartaSteleScanTest;
    FSaskartaSteleScanTuning T;
    FSaskartaSteleScanCore C = Road();
    TestFalse("no reading outside Playing or in a cinematic", C.Decide(1.0, false, false, 0.f, { Good(0) }, T).IsRead());
    TestFalse("the HUD line is up (1 s): wait", C.Decide(1.0, true, true, 1.f, { Good(0) }, T).IsRead());
    TestTrue("the HUD line has been up HudWaitMaxS: go ahead", C.Decide(1.0, true, true, 3.f, { Good(0) }, T).IsRead());
    const double Busy = C.BusyUntilS;
    TestTrue("busy for the reading's hold", Busy > 1.0 + 7.0);
    TestFalse("one reading at a time", C.Decide(2.0, true, false, 0.f, { Good(1) }, T).IsRead());
    C.ExtendBusy(Busy + 5.0);
    TestFalse("a late voice extends the hold", C.Decide(Busy + 1.0, true, false, 0.f, { Good(1) }, T).IsRead());
    TestTrue("then the next stone", C.Decide(Busy + 5.1, true, false, 0.f, { Good(1) }, T).IsRead());
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaStelesTextTest, "Saskarta.Steles.Text",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaStelesTextTest::RunTest(const FString&)
{
    TestEqual("I05", FSaskartaSteleScanCore::MachineTranslit(TEXT("rzag-zrîrit")), FString(TEXT("RZAG-ZRIRIT")));
    TestEqual("I02", FSaskartaSteleScanCore::MachineTranslit(TEXT("dînîgaradzah")), FString(TEXT("DINIGARADZAH")));
    TestEqual("macrons and the ayn", FSaskartaSteleScanCore::MachineTranslit(TEXT("tadēliz wa’edh")), FString(TEXT("TADELIZ WA'EDH")));
    TestEqual("unknown letters become ?", FSaskartaSteleScanCore::MachineTranslit(TEXT("a一b")), FString(TEXT("A?B")));
    TestEqual("resolved", FSaskartaSteleScanCore::CountUnresolved(TEXT("THE WAY ✓")), 0);
    TestEqual("W05", FSaskartaSteleScanCore::CountUnresolved(TEXT("KEEP A LIGHT ✓ · FOR [?] ~UNITS IN TRANSIT")), 2);
    TestEqual("W06", FSaskartaSteleScanCore::CountUnresolved(TEXT("6-8 ✓ · [ERASED]")), 1);
    TestEqual("a name", FSaskartaSteleScanCore::CountUnresolved(TEXT("[NAME: SAMYOR] · GATE ✓")), 1);
    TestEqual("header read", FSaskartaSteleScanCore::Header(1, 0), FString(TEXT("INSCRIPTION 01 · READ")));
    TestEqual("header partial", FSaskartaSteleScanCore::Header(8, 2), FString(TEXT("INSCRIPTION 08 · PARTIAL · 2 ?")));
    TestEqual("reading", FSaskartaSteleScanCore::ReadingHeader(3), FString(TEXT("INSCRIPTION 03 · READING")));
    TestEqual("full text omits resolved marker", FSaskartaSteleScanCore::FullText(1, TEXT("rzag-zrîrit"), FString(), TEXT("THE WAY ✓"), TEXT("")),
        FString(TEXT("INSCRIPTION 01 · READ\n RZAG-ZRIRIT\n ~ EN: THE WAY")));
    TestEqual("an override", FSaskartaSteleScanCore::FullText(2, TEXT("x"), TEXT("OVERRIDE"), TEXT("A"), TEXT("OK")),
        FString(TEXT("INSCRIPTION 02 · READ\n OVERRIDE\n ~ EN: A")));
    TestTrue("AUTHOR placeholder never shows as Saskartan",
        FSaskartaSteleScanCore::FullText(6, TEXT("AUTHOR"), FString(), TEXT("X"), TEXT("OK")).Contains(TEXT("\n ?\n")));
    TestEqual("match", FSaskartaSteleScanCore::MatchLine(2, TEXT("THE WAY ✓"), 0.2f, 0.65f, TEXT("")),
        FString(TEXT("MATCH 02 · THE WAY")));
    TestEqual("worn match", FSaskartaSteleScanCore::MatchLine(2, TEXT("THE WAY ✓"), 0.85f, 0.65f, TEXT("")),
        FString(TEXT("MATCH 02 · THE WAY · 15 % LEGIBLE")));
    TestEqual("marker between translation phrases", FSaskartaSteleScanCore::HudSafe(TEXT("GATE ✓ · ONE [?]"), TEXT("")),
        FString(TEXT("GATE · ONE [?]")));
    TestEqual("a font with the mark keeps it", FSaskartaSteleScanCore::HudSafe(TEXT("A ✓"), TEXT("✓")), FString(TEXT("A ✓")));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaStelesImportTest, "Saskarta.Steles.Import",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaStelesImportTest::RunTest(const FString&)
{
    const FString Json = TEXT(R"JSON({
      "tuning": {"scan_range_m": 20, "silent_road_m": [[3490, 4460]], "caption_target": "Scan",
                 "ping_sound": "/Game/SaskartaGaea/Audio/Scan/SFX_Carrier_ScanPing", "match_sound": "EDITOR"},
      "inscriptions": [
        {"id": "I05", "status": "in_atlas", "saskartan": "rzag-zrîrit", "machine_translit": null,
         "english_approx": "THE WAY ✓", "atlas_cell": 1, "voice_line_id": "INSCR_I05",
         "voice_asset": "/Game/SaskartaGaea/Audio/CarrierVoice/VO_Carrier_INSCR_I05", "voice_policy": "first_full_read",
         "duration_s": null},
        {"id": "W05", "status": "awaiting_author", "saskartan": "AUTHOR", "english_approx": "KEEP A LIGHT",
         "atlas_cell": null, "voice_policy": "never"}
      ],
      "steles": [
        {"id": "Stele_WayStone_0", "mesh": "SM_Stele_WayStone_A", "inscription": "I05", "road_m": 52.7, "wear": 0.2,
         "face_centre_local_cm": [13.5, 0.0, 82.0]},
        {"id": "Stele_DockPost_A", "mesh": "SM_Stele_DockPost", "inscription": "W05", "road_m": 6, "wear": 0.15}
      ]})JSON");
    USaskartaSteleScanAsset* Asset = NewObject<USaskartaSteleScanAsset>(GetTransientPackage());
    FString Report;
    TestTrue("parses", USaskartaSteleScanImport::ParseInscriptionsJson(Json, Asset, Report));
    TestTrue("default resolved marker does not add OK inside English", Asset->ResolvedMark.IsEmpty());
    TestEqual("inscriptions", Asset->Inscriptions.Num(), 2);
    TestEqual("steles", Asset->Steles.Num(), 2);
    const FSaskartaInscriptionDef* I05 = Asset->FindInscription(FName(TEXT("I05")));
    TestTrue("I05 found", I05 != nullptr);
    if (I05)
    {
        TestEqual("Saskartan verbatim", I05->Saskartan, FString(TEXT("rzag-zrîrit")));
        TestEqual("cell", I05->AtlasCell, 1);
        TestTrue("null translit = derived", I05->MachineTranslit.IsEmpty());
        TestEqual("voice path", I05->Voice.ToSoftObjectPath().ToString(),
            FString(TEXT("/Game/SaskartaGaea/Audio/CarrierVoice/VO_Carrier_INSCR_I05.VO_Carrier_INSCR_I05")));
        TestEqual("no duration yet", I05->DurationS, 0.f);
    }
    const FSaskartaInscriptionDef* W05 = Asset->FindInscription(FName(TEXT("W05")));
    TestTrue("never", W05 && W05->bNeverVoice && W05->AtlasCell == INDEX_NONE);
    const FSaskartaSteleDef* Dock = Asset->FindStele(FName(TEXT("Stele_DockPost_A")));
    TestTrue("dock flag from the mesh", Dock && Dock->bDock);
    const FSaskartaSteleDef* Way = Asset->FindStele(FName(TEXT("Stele_WayStone_0")));
    TestTrue("face centre", Way && Way->FaceCentreLocalCm.Equals(FVector(13.5, 0.0, 82.0)));
    TestTrue("a stone showing an uncarved text is reported", Report.Contains(TEXT("not carved into the atlas yet")));
    TestEqual("tuning", Asset->RangeM, 20.f);
    TestTrue("EDITOR is not a path", Asset->MatchSound.IsNull());
    const FSaskartaSteleScanTuning T = Asset->MakeTuning();
    TestTrue("silent range", T.SilentRoadM.Num() == 1 && T.SilentRoadM[0].X == 3490.f);
    TestTrue("prompted by default", T.bPrompted && T.PromptRangeM == 14.f && T.ScanChargeCost == 0.f);
    TestEqual("prompt caption target", Asset->PromptTarget, FName(TEXT("ScanPrompt")));
    TestFalse("bad JSON", USaskartaSteleScanImport::ParseInscriptionsJson(TEXT("{"), Asset, Report));

    // The real data: 36 steles, all carved with a cell.
    FString RealJson;
    if (FFileHelper::LoadFileToString(RealJson, *FPaths::Combine(FPaths::ProjectDir(), TEXT("docs/story/inscriptions.json"))))
    {
        USaskartaSteleScanAsset* Real = NewObject<USaskartaSteleScanAsset>(GetTransientPackage());
        TestTrue("real parses", USaskartaSteleScanImport::ParseInscriptionsJson(RealJson, Real, Report));
        TestEqual("36 steles", Real->Steles.Num(), 36);
        int32 Ready = 0;
        for (const FSaskartaSteleDef& S : Real->Steles)
        {
            const FSaskartaInscriptionDef* Ins = Real->FindInscription(S.Inscription);
            Ready += (Ins && Ins->AtlasCell >= 0) ? 1 : 0;
        }
        TestEqual("every stone shows a carved text", Ready, 36);
    }
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaStelesPromptTargetTest, "Saskarta.Steles.PromptTarget",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaStelesPromptTargetTest::RunTest(const FString&)
{
    using namespace SaskartaSteleScanTest;
    FSaskartaSteleScanTuning T;
    FSaskartaSteleScanCore C = Road();
    TestEqual("in reach and in view: offered", C.PromptTarget(10.0, true, INDEX_NONE, { Good(0, 12.f) }, T), 0);
    TestEqual("beyond 14 m: not offered", C.PromptTarget(10.0, true, INDEX_NONE, { Good(0, 16.f) }, T), INDEX_NONE);
    TestEqual("closer than MinRangeM: not offered", C.PromptTarget(10.0, true, INDEX_NONE, { Good(0, 2.f) }, T), INDEX_NONE);
    FSaskartaSteleView Aside = Good(0, 10.f);
    Aside.ViewAngleDeg = 30.f;
    TestEqual("outside the view cone: not offered", C.PromptTarget(10.0, true, INDEX_NONE, { Aside }, T), INDEX_NONE);
    FSaskartaSteleView Hidden = Good(0, 10.f);
    Hidden.bLineOfSight = false;
    TestEqual("hidden: not offered", C.PromptTarget(10.0, true, INDEX_NONE, { Hidden }, T), INDEX_NONE);
    FSaskartaSteleView Back = Good(0, 10.f);
    Back.FaceDot = -0.5f;
    TestEqual("back of the stone: not offered", C.PromptTarget(10.0, true, INDEX_NONE, { Back }, T), INDEX_NONE);
    TestEqual("the closest of two", C.PromptTarget(10.0, true, INDEX_NONE, { Good(0, 12.f), Good(1, 6.f) }, T), 1);

    // Hysteresis: the offered stone keeps the line to 16 m and 33 degrees, so it does not flicker.
    TestEqual("held at 15 m", C.PromptTarget(10.0, true, 0, { Good(0, 15.f) }, T), 0);
    Aside.ViewAngleDeg = 30.f;
    TestEqual("held at 30 degrees", C.PromptTarget(10.0, true, 0, { Aside }, T), 0);
    TestEqual("the held stone wins over a closer one", C.PromptTarget(10.0, true, 0, { Good(0, 12.f), Good(1, 6.f) }, T), 0);
    TestEqual("let go past the hold", C.PromptTarget(10.0, true, 0, { Good(0, 17.f) }, T), INDEX_NONE);

    // Dock posts use the wider dock cone.
    FSaskartaSteleScanCore D;
    D.Steles.Add(Stele(TEXT("Stele_DockPost_A"), TEXT("I02"), 6.f, 0.2f, true));
    FSaskartaSteleView DockSide = Good(0, 8.f);
    DockSide.ViewAngleDeg = 50.f;
    TestEqual("dock post at 50 degrees", D.PromptTarget(10.0, true, INDEX_NONE, { DockSide }, T), 0);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaStelesPromptBlockedTest, "Saskarta.Steles.PromptBlocked",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaStelesPromptBlockedTest::RunTest(const FString&)
{
    using namespace SaskartaSteleScanTest;
    FSaskartaSteleScanTuning T;
    FSaskartaSteleScanCore C = Road();
    TestEqual("cinematic / story line / ending / another E prompt: none", C.PromptTarget(10.0, false, INDEX_NONE, { Good(0) }, T), INDEX_NONE);
    C.BusyUntilS = 20.0;
    TestEqual("a reading in progress: none", C.PromptTarget(10.0, true, INDEX_NONE, { Good(0) }, T), INDEX_NONE);
    TestEqual("offered again once it ends", C.PromptTarget(20.0, true, INDEX_NONE, { Good(0) }, T), 0);
    C.Steles[0].bRead = true;
    TestEqual("a read stone is offered again (re-scan)", C.PromptTarget(30.0, true, INDEX_NONE, { Good(0) }, T), 0);
    const FSaskartaSteleReadDecision Again = C.BeginRead(30.0, 0, T);
    TestTrue("the re-scan is a full reading", Again.IsRead() && Again.bRescan && Again.Kind == ESaskartaSteleReadKind::Full);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaStelesPromptPressTest, "Saskarta.Steles.PromptPress",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaStelesPromptPressTest::RunTest(const FString&)
{
    using namespace SaskartaSteleScanTest;
    FSaskartaSteleScanTuning T;
    FSaskartaSteleScanCore C = Road();
    const FSaskartaSteleReadDecision First = C.BeginRead(10.0, 0, T);
    TestTrue("E starts the reading", First.IsRead());
    TestEqual("a full reading of a new text", First.Kind, EKind::Full);
    TestTrue("with the author's voice", First.bTryVoice);
    TestEqual("numbered 1", First.Number, 1);
    TestTrue("marked read", C.Steles[0].bRead);
    TestTrue("busy for the reading", C.BusyUntilS > 10.0);
    TestFalse("nothing starts while busy", C.BeginRead(10.5, 1, T).IsRead());
    TestFalse("a bad index does nothing", C.BeginRead(100.0, 99, T).IsRead());
    const FSaskartaSteleReadDecision Rescan = C.BeginRead(100.0, 0, T);
    TestTrue("a second press after the reading replays it", Rescan.IsRead() && Rescan.bRescan);
    TestEqual("re-scan is a full reading", Rescan.Kind, EKind::Full);
    TestEqual("re-scan keeps its number", Rescan.Number, 1);
    TestFalse("another press waits for the re-scan", C.BeginRead(100.5, 0, T).IsRead());

    // The repetition rule still holds: the voiced text reads as a match on the next stone.
    C.OnVoiceResult(FName(TEXT("I05")), true, true);
    const FSaskartaSteleReadDecision Again = C.BeginRead(200.0, 2, T);
    TestEqual("same text again: match", Again.Kind, EKind::Match);
    TestEqual("same number", Again.Number, 1);

    // The Climb: full readings there stay text only.
    FSaskartaSteleScanCore Climb;
    Climb.Steles.Add(Stele(TEXT("Stele_WayStone_26"), TEXT("W10"), 3703.f));
    const FSaskartaSteleReadDecision Silent = Climb.BeginRead(10.0, 0, T);
    TestTrue("full but silent on the Climb", Silent.Kind == EKind::Full && !Silent.bTryVoice);

    TestEqual("prompt line", FSaskartaSteleScanCore::PromptLine(FString()), FString(TEXT("E · SCAN INSCRIPTION")));
    TestEqual("prompt label override", FSaskartaSteleScanCore::PromptLine(TEXT("READ")), FString(TEXT("E · READ")));
    return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
