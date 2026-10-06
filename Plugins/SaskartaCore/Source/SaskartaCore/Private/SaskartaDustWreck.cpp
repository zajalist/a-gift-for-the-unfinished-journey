#include "SaskartaDustWreck.h"
#include "Components/BoxComponent.h"
#include "Components/CapsuleComponent.h"
#include "Components/PointLightComponent.h"
#include "Components/PoseableMeshComponent.h"
#include "Components/SkeletalMeshComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/Scene.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "GameFramework/Character.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "UObject/ConstructorHelpers.h"

DEFINE_LOG_CATEGORY_STATIC(LogSaskartaDustWreck, Log, All);

namespace SaskartaDustWreck
{
    constexpr float LampIntensity = 380.f;
    constexpr float DetourOffsetCm = 320.f;
    constexpr float CollisionClearanceCm = 40.f;
    const FName EmissiveColor(TEXT("EmissiveColor"));
    const FName EmissiveMapWeight(TEXT("EmissiveColorMapWeight"));

    float Flicker(float Time, int32 Channel)
    {
        const float Phase = Time + Channel * 0.31f;
        const float Slow = FMath::Fmod(Phase, 2.7f);
        return Slow < 0.11f || (Slow > 0.26f && Slow < 0.43f) ||
            (Slow > 1.2f && Slow < 1.7f && FMath::Sin(Phase * 53.f) > 0.15f) ? 1.f : 0.01f;
    }

    struct FWreckRenderBounds
    {
        FBox Local;
        FTransform Transform;
        FBox World;
    };

    // Vertical intersection with a component's oriented render bounds. Its underside
    // varies across a tipped vehicle; one global AABB bottom would levitate uphill wheels.
    bool UndersideAt(const FWreckRenderBounds& Bounds, const FVector& Top, const FVector& Bottom, double& OutZ)
    {
        const FVector Start = Bounds.Transform.InverseTransformPosition(Top);
        const FVector Delta = Bounds.Transform.InverseTransformPosition(Bottom) - Start;
        double Enter = 0.0, Exit = 1.0;
        for (int32 Axis = 0; Axis < 3; ++Axis)
        {
            if (FMath::Abs(Delta[Axis]) < UE_SMALL_NUMBER)
            {
                if (Start[Axis] < Bounds.Local.Min[Axis] || Start[Axis] > Bounds.Local.Max[Axis]) return false;
                continue;
            }
            double A = (Bounds.Local.Min[Axis] - Start[Axis]) / Delta[Axis];
            double B = (Bounds.Local.Max[Axis] - Start[Axis]) / Delta[Axis];
            if (A > B) Swap(A, B);
            Enter = FMath::Max(Enter, A);
            Exit = FMath::Min(Exit, B);
            if (Enter > Exit) return false;
        }
        OutZ = FMath::Lerp(Top.Z, Bottom.Z, Exit);
        return true;
    }
}

ASaskartaDustWreck::ASaskartaDustWreck()
{
    PrimaryActorTick.bCanEverTick = true;
    PrimaryActorTick.TickInterval = 0.09f;
    SetRootComponent(CreateDefaultSubobject<USceneComponent>(TEXT("WreckRoot")));
    GetRootComponent()->SetMobility(EComponentMobility::Movable);
    Tags.Add(TEXT("Saskarta.DustWreck"));
    // Hard references keep the tiny fallback lamps available in a packaged build.
    static ConstructorHelpers::FObjectFinder<UStaticMesh> Bulb(TEXT("/Engine/BasicShapes/Sphere.Sphere"));
    static ConstructorHelpers::FObjectFinder<UMaterialInterface> Glow(TEXT("/Game/DemoTemplate/Materials/M_Glow.M_Glow"));
    FallbackLampMesh = Bulb.Object;
    FallbackLampMaterial = Glow.Object;
}

void ASaskartaDustWreck::BuildFromCarrier(ACharacter* Carrier, const FTransform& LostPose)
{
    using namespace SaskartaDustWreck;
    if (!Carrier || !GetWorld() || bBuilt) return;
    bBuilt = true;
    const FTransform SourcePose = Carrier->GetActorTransform();
    TArray<AActor*> Sources{Carrier};
    TArray<AActor*> Attached;
    Carrier->GetAttachedActors(Attached, true, true);
    for (AActor* Actor : Attached)
        if (Actor && !Actor->IsHidden() && !Actor->IsA<ACharacter>()) Sources.AddUnique(Actor);
    SetActorTransform(LostPose);
    TArray<UMeshComponent*> RenderMeshes;

    auto AddLamp = [this](const FTransform& Relative)
    {
        UPointLightComponent* Lamp = NewObject<UPointLightComponent>(this);
        AddInstanceComponent(Lamp);
        Lamp->SetMobility(EComponentMobility::Movable);
        Lamp->SetupAttachment(GetRootComponent());
        Lamp->SetRelativeTransform(Relative);
        Lamp->SetLightColor(FLinearColor(1.f, 0.57f, 0.16f));
        Lamp->SetIntensityUnits(ELightUnits::Candelas);
        Lamp->SetIntensity(LampIntensity);
        Lamp->SetAttenuationRadius(320.f);
        Lamp->SetCastShadows(false);
        Lamp->RegisterComponent();
        Lamps.Add(Lamp);
    };

    // Copy only render components; no copied controller, drivetrain, radio or passenger.
    for (AActor* Source : Sources)
    {
        TArray<UMeshComponent*> Meshes;
        Source->GetComponents(Meshes);
        for (UMeshComponent* Mesh : Meshes)
        {
            if (!Mesh || !Mesh->IsVisible() || Mesh->bHiddenInGame) continue;
            UMeshComponent* Copy = nullptr;
            if (UStaticMeshComponent* Static = Cast<UStaticMeshComponent>(Mesh))
            {
                if (!Static->GetStaticMesh()) continue;
                UStaticMeshComponent* NewMesh = NewObject<UStaticMeshComponent>(this);
                NewMesh->SetStaticMesh(Static->GetStaticMesh());
                Copy = NewMesh;
            }
            else if (USkeletalMeshComponent* Skeletal = Cast<USkeletalMeshComponent>(Mesh))
            {
                if (!Skeletal->GetSkeletalMeshAsset()) continue;
                UPoseableMeshComponent* NewMesh = NewObject<UPoseableMeshComponent>(this);
                NewMesh->SetSkinnedAssetAndUpdate(Skeletal->GetSkinnedAsset());
                Copy = NewMesh;
            }
            if (!Copy) continue;
            AddInstanceComponent(Copy);
            Copy->SetMobility(EComponentMobility::Movable);
            Copy->SetupAttachment(GetRootComponent());
            Copy->SetRelativeTransform(Mesh->GetComponentTransform().GetRelativeTransform(SourcePose));
            Copy->SetCollisionEnabled(ECollisionEnabled::NoCollision);
            Copy->SetCanEverAffectNavigation(false);
            Copy->SetCastShadow(true);
            Copy->SetReceivesDecals(true);
            for (int32 Index = 0; Index < Mesh->GetNumMaterials(); ++Index)
            {
                UMaterialInterface* Original = Mesh->GetMaterial(Index);
                if (!Original) continue;
                UMaterialInterface* Parent = Original;
                // A MID parent would continue inheriting the live carrier's changes.
                while (const UMaterialInstanceDynamic* Dynamic = Cast<UMaterialInstanceDynamic>(Parent))
                    Parent = Dynamic->Parent;
                UMaterialInstanceDynamic* Snapshot = Parent ? UMaterialInstanceDynamic::Create(Parent, Copy) : nullptr;
                if (!Snapshot) continue;
                Snapshot->CopyMaterialUniformParameters(Original);
                Copy->SetMaterial(Index, Snapshot);

                // Verified carrier materials inherit FBXLegacyPhongSurfaceMaterial.
                // Only its actual emission parameters are touched; body color remains intact.
                FEmissiveFlicker Glow;
                Glow.Material = Snapshot;
                Glow.Channel = Index % 2;
                if (Original->GetVectorParameterValue(FMaterialParameterInfo(EmissiveColor), Glow.Color) &&
                    FMath::Max3(Glow.Color.R, Glow.Color.G, Glow.Color.B) > UE_SMALL_NUMBER)
                    Glow.ColorParameter = EmissiveColor;
                Glow.bMapWeight = Original->GetScalarParameterValue(FMaterialParameterInfo(EmissiveMapWeight), Glow.MapWeight) &&
                    Glow.MapWeight > UE_SMALL_NUMBER;
                if (!Glow.ColorParameter.IsNone() || Glow.bMapWeight) EmissiveFlickers.Add(Glow);
            }
            Copy->RegisterComponent();
            // Copy effective runtime CPD, including values not serialized on the asset.
            Copy->SetCustomPrimitiveDataFloatArray(0, Mesh->GetCustomPrimitiveData().Data);
            if (UPoseableMeshComponent* Pose = Cast<UPoseableMeshComponent>(Copy))
            {
                Pose->CopyPoseFromSkeletalComponent(CastChecked<USkeletalMeshComponent>(Mesh));
                Pose->RefreshBoneTransforms();
                Pose->SetComponentTickEnabled(false);
            }
            Copy->UpdateBounds();
            RenderMeshes.Add(Copy);
        }
        TArray<ULocalLightComponent*> Lights;
        Source->GetComponents(Lights);
        for (ULocalLightComponent* Light : Lights)
        {
            if (Lamps.Num() >= 4) break;
            if (Light) AddLamp(Light->GetComponentTransform().GetRelativeTransform(SourcePose));
        }
    }

    if (Lamps.IsEmpty())
    {
        // Authored eye-lamp positions from gen_carrier_drive.py, in mesh space (+Y forward).
        const FTransform MeshRelative = Carrier->GetMesh()
            ? Carrier->GetMesh()->GetComponentTransform().GetRelativeTransform(SourcePose) : FTransform::Identity;
        for (const float Side : {-1.f, 1.f})
        {
            FTransform Relative(FQuat::Identity, MeshRelative.TransformPosition(FVector(Side * 22.f, 102.f, 40.f)));
            AddLamp(Relative);
            if (!FallbackLampMesh || !FallbackLampMaterial) continue;
            UStaticMeshComponent* Bulb = NewObject<UStaticMeshComponent>(this);
            AddInstanceComponent(Bulb);
            Bulb->SetMobility(EComponentMobility::Movable);
            Bulb->SetupAttachment(GetRootComponent());
            Bulb->SetStaticMesh(FallbackLampMesh);
            Bulb->SetRelativeLocation(Relative.GetLocation());
            Bulb->SetRelativeScale3D(FVector(0.065f));
            Bulb->SetCollisionEnabled(ECollisionEnabled::NoCollision);
            Bulb->SetCanEverAffectNavigation(false);
            Bulb->SetCastShadow(false);
            UMaterialInstanceDynamic* Material = UMaterialInstanceDynamic::Create(FallbackLampMaterial, Bulb);
            FEmissiveFlicker Glow;
            Glow.Material = Material;
            Glow.ColorParameter = TEXT("Col"); // actual M_Glow vector used by the existing ending glow
            Glow.Color = FLinearColor(8.f, 3.3f, 0.7f);
            Glow.Channel = Lamps.Num() - 1;
            Material->SetVectorParameterValue(Glow.ColorParameter, Glow.Color);
            Bulb->SetMaterial(0, Material);
            Bulb->RegisterComponent();
            RenderMeshes.Add(Bulb);
            EmissiveFlickers.Add(Glow);
        }
    }

    FRotator Sideways = LostPose.Rotator();
    Sideways.Roll = 82.f;
    SetActorRotation(Sideways);
    FBox Footprint(ForceInit);
    TArray<FWreckRenderBounds> Bounds;
    for (UMeshComponent* Mesh : RenderMeshes)
    {
        Mesh->UpdateBounds();
        FWreckRenderBounds B{Mesh->CalcBounds(FTransform::Identity).GetBox(), Mesh->GetComponentTransform(), Mesh->Bounds.GetBox()};
        if (B.Local.IsValid && B.World.IsValid) { Bounds.Add(B); Footprint += B.World; }
    }
    const FVector LostPosition = LostPose.GetLocation();
    int32 GroundHits = 0;
    if (Footprint.IsValid)
    {
        FCollisionQueryParams Params(SCENE_QUERY_STAT(SaskartaDustWreckGround), false, this);
        Params.AddIgnoredActor(Carrier);
        for (AActor* Actor : Attached) if (Actor) Params.AddIgnoredActor(Actor);
        FCollisionObjectQueryParams Objects;
        Objects.AddObjectTypesToQuery(ECC_WorldStatic);
        double Raise = -TNumericLimits<double>::Max();
        auto Probe = [&](double X, double Y)
        {
            const FVector Top(X, Y, Footprint.Max.Z + 600.0), Bottom(X, Y, Footprint.Min.Z - 2400.0);
            double Underside = TNumericLimits<double>::Max();
            for (const FWreckRenderBounds& B : Bounds)
            {
                double Z;
                if (UndersideAt(B, Top, Bottom, Z)) Underside = FMath::Min(Underside, Z);
            }
            if (Underside == TNumericLimits<double>::Max()) return;
            FHitResult Ground;
            if (GetWorld()->LineTraceSingleByObjectType(Ground, Top, Bottom, Objects, Params) && Ground.ImpactNormal.Z > 0.3f)
            {
                Raise = FMath::Max(Raise, Ground.ImpactPoint.Z + 3.0 - Underside);
                ++GroundHits;
            }
        };
        // Whole footprint plus each render component's corners/edges; attached biofuel
        // and trailer meshes must not sink because the carrier origin happened to hit a dip.
        auto ProbeBox = [&](const FBox& Box, int32 Steps)
        {
            for (int32 X = 0; X <= Steps; ++X)
                for (int32 Y = 0; Y <= Steps; ++Y)
                    Probe(FMath::Lerp(Box.Min.X, Box.Max.X, double(X) / Steps),
                          FMath::Lerp(Box.Min.Y, Box.Max.Y, double(Y) / Steps));
        };
        ProbeBox(Footprint, 4);
        for (const FWreckRenderBounds& B : Bounds) ProbeBox(B.World, 2);
        if (GroundHits > 0)
            SetActorLocation(FVector(LostPosition.X, LostPosition.Y, LostPosition.Z + Raise));
        else UE_LOG(LogSaskartaDustWreck, Warning, TEXT("No static ground under wreck at %.1f %.1f; retained failed pose Z"), LostPosition.X, LostPosition.Y);

        // Upright simple collision only when the detouring carrier has measured lateral
        // clearance. Camera/visibility ignore it; no physics simulation or nav rebuild.
        const FTransform Heading(FRotator(0.f, LostPose.Rotator().Yaw, 0.f), GetActorLocation());
        FBox CollisionBounds(ForceInit);
        for (const FWreckRenderBounds& B : Bounds)
        {
            const FVector Shift(0.f, 0.f, GetActorLocation().Z - LostPosition.Z);
            for (int32 Corner = 0; Corner < 8; ++Corner)
            {
                const FVector Local((Corner & 1) ? B.Local.Max.X : B.Local.Min.X,
                    (Corner & 2) ? B.Local.Max.Y : B.Local.Min.Y, (Corner & 4) ? B.Local.Max.Z : B.Local.Min.Z);
                CollisionBounds += Heading.InverseTransformPosition(B.Transform.TransformPosition(Local) + Shift);
            }
        }
        const float CarrierRadius = Carrier->GetCapsuleComponent()->GetScaledCapsuleRadius();
        const double LateralReach = FMath::Max(FMath::Abs(CollisionBounds.Min.Y), FMath::Abs(CollisionBounds.Max.Y));
        if (CollisionBounds.IsValid && LateralReach + CarrierRadius + CollisionClearanceCm < DetourOffsetCm)
        {
            UBoxComponent* Collision = NewObject<UBoxComponent>(this);
            AddInstanceComponent(Collision);
            Collision->SetMobility(EComponentMobility::Movable);
            Collision->SetupAttachment(GetRootComponent());
            Collision->SetWorldTransform(FTransform(Heading.GetRotation(), Heading.TransformPosition(CollisionBounds.GetCenter())));
            Collision->SetBoxExtent(CollisionBounds.GetExtent().ComponentMax(FVector(1.f)));
            Collision->SetCollisionEnabled(ECollisionEnabled::QueryOnly);
            Collision->SetCollisionObjectType(ECC_WorldStatic);
            Collision->SetCollisionResponseToAllChannels(ECR_Ignore);
            Collision->SetCollisionResponseToChannel(ECC_Pawn, ECR_Block);
            Collision->SetCollisionResponseToChannel(ECC_Vehicle, ECR_Block);
            Collision->SetGenerateOverlapEvents(false);
            Collision->SetCanEverAffectNavigation(false);
            Collision->RegisterComponent();
        }
        else UE_LOG(LogSaskartaDustWreck, Log, TEXT("Wreck collision omitted: lateral reach %.1f + carrier %.1f would intrude into the 320 cm rescue detour"), LateralReach, CarrierRadius);
    }
    FlickerTime = FMath::Fmod(FMath::Abs(LostPosition.X + LostPosition.Y) * 0.001f, 7.f);
    Tick(0.f);
    UE_LOG(LogSaskartaDustWreck, Log, TEXT("Wreck retained catch XY %.1f %.1f, roll 82, ground samples %d, lights %d, emissive materials %d"),
        LostPosition.X, LostPosition.Y, GroundHits, Lamps.Num(), EmissiveFlickers.Num());
}

void ASaskartaDustWreck::Tick(float DeltaSeconds)
{
    Super::Tick(DeltaSeconds);
    FlickerTime += DeltaSeconds;
    for (int32 Index = 0; Index < Lamps.Num(); ++Index)
        if (Lamps[Index]) Lamps[Index]->SetIntensity(SaskartaDustWreck::LampIntensity * SaskartaDustWreck::Flicker(FlickerTime, Index));
    for (const FEmissiveFlicker& Glow : EmissiveFlickers)
    {
        if (UMaterialInstanceDynamic* Material = Glow.Material.Get())
        {
            const float Amount = SaskartaDustWreck::Flicker(FlickerTime, Glow.Channel);
            if (!Glow.ColorParameter.IsNone()) Material->SetVectorParameterValue(Glow.ColorParameter, Glow.Color * Amount);
            if (Glow.bMapWeight) Material->SetScalarParameterValue(SaskartaDustWreck::EmissiveMapWeight, Glow.MapWeight * Amount);
        }
    }
}
