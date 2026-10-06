"""Offline ordering contracts; native serialization/runtime acceptance remains an editor task."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
NATIVE = ROOT / 'Plugins/SaskartaCore/Source/SaskartaCore'
RUNNER = (NATIVE / 'Private/SaskartaEventRunner.cpp').read_text(encoding='utf-8')
DRONE = (NATIVE / 'Private/SaskartaDroneSequence.cpp').read_text(encoding='utf-8')


def body(source, signature):
    start = source.index('{', source.index(signature))
    depth = 1
    end = start + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


class HumanCheckpointRestoreContracts(unittest.TestCase):
    def test_hatch_saves_after_native_grounded_handoff(self):
        code = body(RUNNER, 'void USaskartaEventRunner::EndCinematic(')
        self.assertLess(code.index('bSaveHumanAfterHandoff = true'), code.index('EnsureHumanHandoff'))
        self.assertLess(code.index('EnsureHumanHandoff'), code.index('SaveCheckpoint(FName(TEXT("CP4_HUMAN")))'))
        self.assertIn('if (HumanClassAfterHandoff &&', code)

    def test_invalid_checkpoint_rejected_before_stop_or_possession(self):
        code = body(RUNNER, 'bool USaskartaEventRunner::RestoreCheckpointSnapshot(')
        self.assertLess(code.index('Checkpoint rejected:'), code.index('StopAll();'))
        self.assertLess(code.index('StopAll();'), code.index('PC->Possess(Carrier)'))
        self.assertIn('S->CarrierPose.ContainsNaN()', code)
        self.assertIn('S->HumanPose.ContainsNaN()', code)

    def test_human_pose_is_separate_from_rescue_carrier_snapshot(self):
        code = body(RUNNER, 'USaskartaSaveGame* USaskartaEventRunner::CreateCheckpointSnapshot(')
        self.assertIn('bExactCarrierPose && !S->IsHumanCheckpoint()', code)
        self.assertIn('S->HumanCarrierPose = Carrier->GetActorTransform()', code)
        self.assertIn('S->HumanViewRotation = GetPC()->GetControlRotation()', code)

    def test_legacy_human_stages_carrier_before_possession_and_new_pose_before_driver(self):
        code = body(RUNNER, 'bool USaskartaEventRunner::RestoreHumanCheckpoint(')
        self.assertLess(code.index('Collapse->StageNow()'), code.index('Collapse->EnsureHumanHandoff'))
        self.assertLess(code.index('Human->SetActorTransform'), code.index('CallHook(Human, SaskartaEvents::NameStartAnimDriver'))
        self.assertIn('Move->SetMovementMode(MOVE_Walking)', code)
        self.assertIn('CallHook(GetPawn(), TEXT("StopWalk")', code)

    def test_modes_flow_and_pawn_precede_restored_callbacks_and_final_camera(self):
        code = body(RUNNER, 'bool USaskartaEventRunner::RestoreCheckpointSnapshot(')
        callback = code.index('OnRestoredRun.Broadcast')
        for item in ('RestoreHumanCheckpoint(*S)', 'PC->Possess(Carrier)',
                     'SetFlowStateByReflection(RestoredFlow)', 'S->CarrierPose',
                     'ActiveModes.Remove(FName(TEXT("DroneCam")))'):
            self.assertLess(code.index(item), callback)
        self.assertIn('A.Type == ESaskartaActionType::SetMode', code)
        self.assertIn('const TArray<FName> RestoredModes = ActiveModes.Array()', code)
        for item in ('PC->ResetIgnoreMoveInput()', 'PC->ResetIgnoreLookInput()',
                     'CallHook(PC, TEXT("StartHumanWalk")', 'PC->SetViewTarget(ViewTarget ? ViewTarget : GetPawn())'):
            self.assertGreater(code.index(item), callback)
        self.assertLess(code.index('Drone->RestoreHumanEscort(Carrier)'), code.index('PC->SetViewTarget(ViewTarget'))

    def test_escort_recreates_pair_using_explicit_stranded_carrier(self):
        restore = body(DRONE, 'bool USaskartaDroneSequenceSubsystem::RestoreHumanEscort(')
        self.assertLess(restore.index('StopSequence()'), restore.index('BeginHumanEscort(StrandedCarrier)'))
        self.assertIn('UpdateHumanEscort(0.f)', restore)
        escort = body(DRONE, 'void USaskartaDroneSequenceSubsystem::BeginHumanEscort(')
        self.assertLess(escort.index('WreckCarrier = Wreck'), escort.index('BeginSwarm()'))
        carrier = body(DRONE, 'ACharacter* USaskartaDroneSequenceSubsystem::Carrier() const')
        self.assertLess(carrier.index('WreckCarrier.IsValid()'), carrier.index('PC->GetPawn()'))


if __name__ == '__main__':
    unittest.main()
