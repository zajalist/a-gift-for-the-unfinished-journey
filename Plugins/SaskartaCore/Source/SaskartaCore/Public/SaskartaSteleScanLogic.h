// Stele scan (task STELESCAN, docs/look/STELE_SCAN.md section 3): the pure decisions.
//
// FSaskartaSteleScanCore is engine-free (FName, containers, FString, FMath only), so the
// Saskarta.Steles.* automation tests drive it directly. USaskartaSteleScanner (SaskartaSteleScanner.h)
// is the thin world subsystem that feeds it camera views every 0.25 s and applies its decisions:
// Custom Primitive Data on the stone, the HUD caption, the ping, and the voice through the event
// runner's Voice channel.
//
// Rules (Decide):
//   - read only while the flow allows it (Playing, no cinematic) and one reading at a time (BusyUntilS);
//   - the HUD line (a First Light query) delays a reading up to HudWaitMaxS, then the reading goes ahead
//     (ScanBlock sits under the HUD line);
//   - each stele is read once; of the eligible views the closest wins. Eligible: line of sight, distance
//     MinRangeM..RangeM, the face centre within MaxViewDeg of the camera's forward (DockViewDeg for the
//     dock posts), the front face turned toward the camera (FaceDot >= MinFaceDot);
//   - Full reading when the text is not complete yet and has had fewer than MaxTextOnlyFullReads
//     text-only full readings and the stone is not worn (wear < WornWear); otherwise a Match line;
//   - a full reading tries the voice unless the stone is in a SilentRoadM range (the Climb) or the text's
//     voice policy is never. A voice that played, or a full reading that never tried one, completes the
//     text; a refused voice leaves it open, so the next stone with the same text gets the full reading.
//
// Prompted scan (bPrompted, the default; docs/look/STELE_SCAN.md "Prompted scan"): the poll no longer
// reads by itself. PromptTarget picks the stele the CRT offers ("E · SCAN INSCRIPTION": the closest unread
// stone within PromptRangeM and PromptViewDeg, in sight, face turned toward the camera, with hysteresis
// so the line does not flicker); the E press calls BeginRead on it, which applies the same full-or-match,
// voice and busy rules as Decide. Decide (automatic reading) stays for bPrompted = false and ForceRead.
//
// Every string the HUD shows is built here (Header, FullText, MatchLine), ASCII-safe by default: the
// terminal font (VT323) has no check mark, so the resolved mark is "OK" unless the data asks otherwise.

#pragma once

#include "CoreMinimal.h"

/** Custom Primitive Data slots on a stele's mesh component (M_Saskarta_SteleFace reads them). */
namespace SaskartaSteleCpd
{
    /** Component defaults, written by Tools/Look/build_stele_scan.py cpd. */
    constexpr int32 Wear = 0;
    constexpr int32 Cell = 1;
    constexpr int32 CellRect = 4;   // 4..7: u0, v0, su, sv of one atlas cell on the face's UV1
    /** Runtime, written by the scanner (only these three; never a default at runtime). */
    constexpr int32 ScanStart = 2;  // game time (UWorld::GetTimeSeconds, the material's Time node)
    constexpr int32 ScanMode = 3;   // 0 none, 1 full reading, 0.5 match
    constexpr int32 GlowHold = 8;   // seconds after ScanStart the grooves stay lit
    constexpr int32 Count = 9;
}

enum class ESaskartaSteleReadKind : uint8
{
    None,
    Full,
    Match,
};

struct SASKARTACORE_API FSaskartaSteleScanTuning
{
    float RangeM = 22.f;
    float MinRangeM = 3.f;
    float MaxViewDeg = 35.f;
    float DockViewDeg = 70.f;
    float MinFaceDot = 0.2f;
    /** Candidate window around the carrier's road m. */
    float AheadM = 60.f;
    float BehindM = 10.f;
    float SweepS = 1.4f;
    float MatchSweepS = 0.6f;
    float TextAtS = 1.4f;
    float VoiceAtS = 1.6f;
    /** How long a full reading keeps asking the runner for the Voice channel (= the runner's HintMaxWaitS). */
    float VoiceWaitMaxS = 4.f;
    float VoiceMinGapS = 1.5f;
    /** The next road beat must be at least clip + VoiceLeadS away. */
    float VoiceLeadS = 4.f;
    float HudWaitMaxS = 3.f;
    float HoldAfterVoiceS = 2.f;
    float TextOnlyHoldS = 6.f;
    float MatchHoldS = 3.f;
    int32 MaxTextOnlyFullReads = 2;
    /** Stones at or above this wear only ever give match lines, with "NN % LEGIBLE". */
    float WornWear = 0.65f;
    /** Road ranges (x..y m) where full readings are text only: the Climb. */
    TArray<FVector2f> SilentRoadM = { FVector2f(3490.f, 4460.f) };

    // --- prompted scan
    /** true: the CRT offers the scan and E starts it; false: the old automatic reading. */
    bool bPrompted = true;
    float PromptRangeM = 14.f;
    /** Half-angle of the view cone around the camera's forward (dock posts use DockViewDeg if wider). */
    float PromptViewDeg = 25.f;
    /** The offered stele keeps the prompt out to PromptRangeM + this and PromptViewDeg + HoldDeg. */
    float PromptHoldM = 2.f;
    float PromptHoldDeg = 8.f;
    /** Energy hook: charge one scan costs. 0 = free; not spent anywhere yet (USaskartaSteleScanner::ScanChargeHook). */
    float ScanChargeCost = 0.f;
};

/** One candidate stele as the camera sees it this tick. */
struct SASKARTACORE_API FSaskartaSteleView
{
    /** Index into FSaskartaSteleScanCore::Steles. */
    int32 Index = INDEX_NONE;
    float DistanceM = 0.f;
    /** Angle between the camera's forward and the direction to the face centre. */
    float ViewAngleDeg = 180.f;
    /** dot(face normal, direction from the face to the camera): 1 = straight on. */
    float FaceDot = -1.f;
    bool bLineOfSight = false;
};

struct SASKARTACORE_API FSaskartaSteleReadDecision
{
    int32 Stele = INDEX_NONE;
    ESaskartaSteleReadKind Kind = ESaskartaSteleReadKind::None;
    bool bTryVoice = false;
    /** The stone was read before: a re-scan asked for with E (the reading and the voice play again). */
    bool bRescan = false;
    /** The machine's number for this text: 1, 2, 3 ... in first-read order. */
    int32 Number = 0;

    bool IsRead() const { return Kind != ESaskartaSteleReadKind::None; }
};

/** One Custom Primitive Data write (index, value). */
struct SASKARTACORE_API FSaskartaSteleCpdWrite
{
    int32 Index = 0;
    float Value = 0.f;
};

struct SASKARTACORE_API FSaskartaSteleScanCore
{
    struct FStele
    {
        FName Id;
        FName Inscription;
        float RoadM = 0.f;
        float Wear = 0.f;
        bool bDock = false;
        /** The inscription's voice_policy is "never". */
        bool bNeverVoice = false;
        bool bRead = false;
    };

    /** Sorted by road m (SortByRoad). */
    TArray<FStele> Steles;
    /** Inscription -> the machine's number (first-read order). */
    TMap<FName, int32> Numbers;
    /** Texts whose full reading is done: voiced, or read without a voice attempt. */
    TSet<FName> Completed;
    /** Full readings whose voice was refused, per text. */
    TMap<FName, int32> TextOnlyFullReads;
    /** One reading at a time: no new reading before this (game time). */
    double BusyUntilS = 0.0;

    void SortByRoad();
    int32 FindStele(FName Id) const;
    /** Clears every read flag, number and text state (Saskarta.Steles.Reset, a new run). */
    void ResetReadings();

    /** Unread steles whose road m is within [RoadM - BehindM, RoadM + AheadM]. */
    void Candidates(float RoadM, const FSaskartaSteleScanTuning& T, TArray<int32>& Out) const;

    /** Range, view angle, face angle and line of sight. */
    static bool Eligible(const FSaskartaSteleView& V, bool bDock, const FSaskartaSteleScanTuning& T);

    /**
     * The reading to start now, if any; marks the stele read, numbers its text and sets BusyUntilS.
     * bCanRead: FlowState Playing (or unknown) and no cinematic. HudBusyForS: how long the HUD line has
     * been up (ignored when !bHudBusy).
     */
    FSaskartaSteleReadDecision Decide(double NowS, bool bCanRead, bool bHudBusy, float HudBusyForS,
        const TArray<FSaskartaSteleView>& Views, const FSaskartaSteleScanTuning& T);

    /** Prompt range and view cone (+ the hold margins when bHold: the stele already offered). */
    static bool EligibleForPrompt(const FSaskartaSteleView& V, bool bDock, bool bHold, const FSaskartaSteleScanTuning& T);

    /**
     * The stele the CRT prompt offers now, or INDEX_NONE: bCanPrompt false (not Playing, cinematic, story
     * line, ending, another E prompt), a reading in progress (BusyUntilS), or no unread eligible view.
     * Current (the stele offered last poll) wins while it stays inside the hold margins; else the closest.
     */
    int32 PromptTarget(double NowS, bool bCanPrompt, int32 Current, const TArray<FSaskartaSteleView>& Views,
        const FSaskartaSteleScanTuning& T) const;

    /**
     * E pressed on stele Index: marks it read, numbers its text, sets BusyUntilS and returns the reading
     * (None when the index is invalid, the stele is already read or a reading is in progress).
     */
    FSaskartaSteleReadDecision BeginRead(double NowS, int32 Index, const FSaskartaSteleScanTuning& T);

    /** "E · SCAN INSCRIPTION" (Label empty) or "E · " + Label. */
    static FString PromptLine(const FString& Label);

    /** The full-or-match rule for one stele (no state change). */
    ESaskartaSteleReadKind KindFor(const FStele& S, const FSaskartaSteleScanTuning& T) const;

    /** After a full reading: bAttempted = the voice was tried at all; bPlayed = it got the channel. */
    void OnVoiceResult(FName Inscription, bool bAttempted, bool bPlayed);

    /** Keeps the scanner busy until at least UntilS (a voice that started late). */
    void ExtendBusy(double UntilS) { BusyUntilS = FMath::Max(BusyUntilS, UntilS); }

    /** Continue / GoTo: stones behind RoadM - BehindM count as read. Returns how many were marked. */
    int32 MarkBehind(float RoadM, const FSaskartaSteleScanTuning& T);

    // ------------------------------------------------------------------ helpers (tested)
    static bool InSilentRange(float RoadM, const FSaskartaSteleScanTuning& T);

    /** How long the HUD and the reading hold before the next one may start. */
    static float ReadingHoldS(ESaskartaSteleReadKind Kind, bool bTryVoice, const FSaskartaSteleScanTuning& T);

    /** The CPD writes that start a reading: ScanStart = NowS, ScanMode 1 / 0.5, GlowHold. */
    static TArray<FSaskartaSteleCpdWrite> StartCpd(ESaskartaSteleReadKind Kind, double NowS, float GlowHoldS);

    /** GlowHold once the voice has started: (voice start - scan start) + clip + 0.5 s. */
    static float GlowHoldForVoice(double ScanStartS, double VoiceStartS, float ClipS);

    /** The author's transliteration with diacritics stripped, upper case: rzag-zrîrit -> RZAG-ZRIRIT. */
    static FString MachineTranslit(const FString& Saskartan);

    /** [?], [ERASED], [NAME: ...] and ~ markers in an approximate English line. */
    static int32 CountUnresolved(const FString& EnglishApprox);

    /** Omits the check mark (U+2713) when ResolvedMark is empty, or substitutes a supported glyph. */
    static FString HudSafe(const FString& Text, const FString& ResolvedMark);

    /** "INSCRIPTION 08 · READING" while the line sweeps. */
    static FString ReadingHeader(int32 Number);

    /** "INSCRIPTION 01 · READ" or "INSCRIPTION 08 · PARTIAL · 2 ?". */
    static FString Header(int32 Number, int32 Unresolved);

    /** Header, the machine transliteration, "~ EN: ..." (three lines). */
    static FString FullText(int32 Number, const FString& Saskartan, const FString& MachineTranslitOverride,
        const FString& EnglishApprox, const FString& ResolvedMark);

    /** "MATCH 02 · THE WAY", plus " · 15 % LEGIBLE" on a worn stone. */
    static FString MatchLine(int32 Number, const FString& EnglishApprox, float Wear, float WornWear,
        const FString& ResolvedMark);
};

// The voice gate itself is FSaskartaEventLogic::CanStartAuxLine (SaskartaEventLogic.h), used by
// USaskartaEventRunner::TryPlayAuxCarrierLine.
