"""Narrow source contracts; these do not establish Unreal runtime or visual acceptance."""
from pathlib import Path
import unittest

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "saskartarad.uproject").is_file())
PRIVATE = ROOT / "Plugins/SaskartaCore/Source/SaskartaCore/Private"


class BillowSourceContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.b = (PRIVATE / "SaskartaDustBillows.cpp").read_text(encoding="utf-8")
        cls.f = (PRIVATE / "SaskartaDustFront.cpp").read_text(encoding="utf-8")

    def test_no_sync_load_or_late_callback(self):
        self.assertIn("RequestAsyncLoad", self.b)
        self.assertIn("FStreamableDelegate()", self.b)
        self.assertIn("LoadHandle->HasLoadCompleted()", self.b)
        self.assertIn("LoadHandle->CancelHandle()", self.b)
        for forbidden in ["LoadSynchronous", "TryLoad", "LoadObject<", "LoadAssetBlocking", "AsyncTask"]:
            self.assertNotIn(forbidden, self.b)

    def test_no_plane_until_material_is_ready(self):
        register = self.b.index("Plane->RegisterComponent()")
        for required in ["!Mesh || !LoadedMaterial", "MaterialDomain != MD_Surface",
                         "GetBlendMode() != BLEND_Translucent", "IsCompilingOrHadCompileError",
                         'FHashedMaterialParameterInfo(TEXT("Opacity"))',
                         'FHashedMaterialParameterInfo(TEXT("CloudVariant"))',
                         "Plane->SetMaterial(0, MID)", "Plane->SetVisibility(false)"]:
            self.assertLess(self.b.index(required), register)

    def test_world_position_uses_front_and_camera_changes_facing_only(self):
        self.assertIn("FrontFrame.TransformPositionNoScale(FVector(Shape.X, Shape.Y, Shape.Z))", self.b)
        self.assertIn("const FVector ToView = View - Position", self.b)
        self.assertIn("FRotationMatrix::MakeFromZX(Normal, Right)", self.b)
        self.assertIn("SetActorLocationAndRotation(Centre, Forward.Rotation()", self.f)
        self.assertNotIn("Camera", self.f)
        self.assertIn("Billows->Update(GetActorTransform(), RollTimeS, Near)", self.f)

    def test_budget_and_cheap_component_settings(self):
        self.assertIn("Index < FSaskartaDustBillowLogic::Count", self.b)
        for required in ["ECollisionEnabled::NoCollision", "SetGenerateOverlapEvents(false)",
                         "SetCanEverAffectNavigation(false)", "SetCastShadow(false)",
                         "bCastVolumetricTranslucentShadow = false", "bReceivesDecals = false",
                         "SetVisibleInRayTracing(false)", "SetCullDistance(FSaskartaDustBillowLogic::MaxDistanceCm)"]:
            self.assertIn(required, self.b)
        self.assertIn("PrimaryActorTick.bCanEverTick = false", self.f)
        self.assertLess(self.f.index("Now - LastShapeWorldS < 0.1"), self.f.index("Billows->Update"))

    def test_lifetime_cleanup_and_existing_fog_preserved(self):
        self.assertIn("Billows->Shutdown()", self.f)
        self.assertIn("Plane->DestroyComponent()", self.b)
        self.assertIn("Planes.Reset()", self.b)
        self.assertIn("Materials.Reset()", self.b)
        self.assertIn("OwnerFront.Reset()", self.b)
        self.assertIn("CreateDefaultSubobject<ULocalFogVolumeComponent>", self.f)
        self.assertIn("UE_ARRAY_COUNT(Layout) == ASaskartaDustFront::MaxLobes", self.f)


if __name__ == "__main__":
    unittest.main()
