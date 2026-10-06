"""Bounded wiring guards for the optional Cistern receiver. No editor connection."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "Plugins/SaskartaCore/Source/SaskartaCore"
cpp = (CORE / "Private/SaskartaRadioRepair.cpp").read_text(encoding="utf-8")
header = (CORE / "Public/SaskartaRadioRepair.h").read_text(encoding="utf-8")
save = (CORE / "Public/SaskartaSaveGame.h").read_text(encoding="utf-8")
station = (CORE / "Public/SaskartaRadioStation.h").read_text(encoding="utf-8")
power = (CORE / "Private/SaskartaPower.cpp").read_text(encoding="utf-8")
runner = (CORE / "Private/SaskartaEventRunner.cpp").read_text(encoding="utf-8")

checks = {
    "explicit reception and real envelope APIs": all(x in station for x in (
        "SetRepairReception(bool bActive, float Signal01)", "GetProgrammeEnvelope() const")),
    "no station stop/picker/seek on interaction": not any(x in cpp for x in (
        "->StopAll(", "->StartNext(", "->PickNext(", "->Seek(", "->SetRadioOn(")),
    "transient layer clears on close": "ClearReception();" in cpp.split(
        "void USaskartaRadioRepairSubsystem::Close(bool bSave)", 1)[1].split(
        "bool USaskartaRadioRepairSubsystem::HandleKey", 1)[0],
    "pause and focus guard": all(x in cpp for x in (
        "World->IsPaused()", "HasAnyUserFocusOrFocusedDescendants()", "HeldKeys.Reset();")),
    "rest charging stays available": "Power->SetRestActivityOpen(true)" in cpp
        and "|| bRestActivityOpen)" in power,
    "additive compatible save field": "struct FSaskartaRadioRepairSave" in save
        and "FSaskartaRadioRepairSave RadioRepair;" in save,
    "exact pose checkpoint and current save hooks": all(x in cpp for x in (
        'CreateCheckpointSnapshot(TEXT("CP_RADIO_REPAIR"), true)',
        "OnWritingRun.AddUObject", "OnRestoredRun.AddUObject", 'Save->FlowState = TEXT("Playing")'))
        and "S->bHasExactCarrierPose ? S->CheckpointRoadM" in runner,
    "layer draw samples bounded": "EnvelopeHistory.Num() >= 120" in cpp
        and "UiAgeS >= 0.1f" in cpp,
    "dark backing outside additive retainer": cpp.index("Card->AddChildToCanvas(Glass)")
        < cpp.index("Card->AddChildToCanvas(Retainer)"),
    "paused subsystem can hide and save": "IsTickableWhenPaused() const override { return true; }" in header,
}
for name, okay in checks.items():
    print(f"{'PASS' if okay else 'FAIL'} {name}")
if not all(checks.values()):
    raise SystemExit(1)
print(f"radio repair source guards: {len(checks)} passed (not a native or runtime test)")
