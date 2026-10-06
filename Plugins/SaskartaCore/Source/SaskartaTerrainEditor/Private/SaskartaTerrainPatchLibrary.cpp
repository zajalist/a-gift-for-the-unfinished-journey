#include "SaskartaTerrainPatchLibrary.h"

#include "Editor.h"
#include "Engine/Level.h"
#include "Engine/Texture2D.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "FileHelpers.h"
#include "HAL/PlatformFileManager.h"
#include "HAL/FileManager.h"
#include "Landscape.h"
#include "LandscapeComponent.h"
#include "LandscapeEdit.h"
#include "LandscapeEditLayer.h"
#include "LandscapeHeightfieldCollisionComponent.h"
#include "LandscapeInfo.h"
#include "Misc/FileHelper.h"
#include "Misc/PackageName.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "UObject/Package.h"

#if PLATFORM_WINDOWS
#include "Windows/AllowWindowsPlatformTypes.h"
#include <windows.h>
#include <bcrypt.h>
#include "Windows/HideWindowsPlatformTypes.h"
#endif

namespace
{
constexpr int32 X1 = 3643;
constexpr int32 Y1 = 3780;
constexpr int32 X2 = 3854;
constexpr int32 Y2 = 4115;
constexpr int32 Width = X2 - X1 + 1;
constexpr int32 Height = Y2 - Y1 + 1;
constexpr int32 PixelCount = Width * Height;
constexpr TCHAR MapPackage[] = TEXT("/Game/level/Saskarta_WP");
constexpr TCHAR LandscapeLabel[] = TEXT("Landscape");
constexpr TCHAR LandscapeActorName[] = TEXT("Landscape_UAID_D8BBC14136F41C0403_2020373984");

struct FPatchContext
{
    UWorld* World = nullptr;
    ALandscape* Landscape = nullptr;
    ULandscapeInfo* Info = nullptr;
    FGuid LayerGuid;
    TArray<ULandscapeComponent*> Components;
    TArray<UPackage*> Packages;
    TArray<uint16> Source;
    TArray<uint16> Target;
    bool bReviewOnly = true;
    bool bApplyAuthorized = false;
};

FString Fail(const FString& Why)
{
    return FString::Printf(TEXT("FAIL: %s"), *Why);
}

bool ComputeSHA256(const TArray<uint8>& Bytes, FString& OutHex)
{
#if PLATFORM_WINDOWS
    BCRYPT_ALG_HANDLE Algorithm = nullptr;
    BCRYPT_HASH_HANDLE Hash = nullptr;
    TArray<uint8> HashObject;
    bool bSuccess = false;
    do
    {
        if (!BCRYPT_SUCCESS(BCryptOpenAlgorithmProvider(&Algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0))) break;

        ULONG ObjectLength = 0;
        ULONG DigestLength = 0;
        ULONG ResultLength = 0;
        if (!BCRYPT_SUCCESS(BCryptGetProperty(Algorithm, BCRYPT_OBJECT_LENGTH,
                reinterpret_cast<PUCHAR>(&ObjectLength), sizeof(ObjectLength), &ResultLength, 0)) ||
            ResultLength != sizeof(ObjectLength) || ObjectLength == 0 ||
            !BCRYPT_SUCCESS(BCryptGetProperty(Algorithm, BCRYPT_HASH_LENGTH,
                reinterpret_cast<PUCHAR>(&DigestLength), sizeof(DigestLength), &ResultLength, 0)) ||
            ResultLength != sizeof(DigestLength) || DigestLength != 32)
            break;

        HashObject.SetNumUninitialized(ObjectLength);
        if (!BCRYPT_SUCCESS(BCryptCreateHash(Algorithm, &Hash, HashObject.GetData(), ObjectLength,
                nullptr, 0, 0)) ||
            !BCRYPT_SUCCESS(BCryptHashData(Hash, const_cast<PUCHAR>(Bytes.GetData()),
                static_cast<ULONG>(Bytes.Num()), 0)))
            break;

        uint8 Digest[32];
        if (!BCRYPT_SUCCESS(BCryptFinishHash(Hash, Digest, UE_ARRAY_COUNT(Digest), 0))) break;
        OutHex = BytesToHex(Digest, UE_ARRAY_COUNT(Digest));
        bSuccess = true;
    } while (false);

    if (Hash) BCryptDestroyHash(Hash);
    if (Algorithm) BCryptCloseAlgorithmProvider(Algorithm, 0);
    return bSuccess;
#else
    return false;
#endif
}

bool ReadPatchFile(const FString& Path, const FString& ExpectedHash, TArray<uint16>& Out, FString& Error)
{
    TArray<uint8> Bytes;
    if (!FFileHelper::LoadFileToArray(Bytes, *Path) || Bytes.Num() != PixelCount * 2)
    {
        Error = FString::Printf(TEXT("Missing/wrong-sized patch file: %s"), *Path);
        return false;
    }
    FString ActualHash;
    if (!ComputeSHA256(Bytes, ActualHash))
    {
        Error = FString::Printf(TEXT("SHA256 calculation failed: %s"), *Path);
        return false;
    }
    if (!ActualHash.Equals(ExpectedHash, ESearchCase::IgnoreCase))
    {
        Error = FString::Printf(TEXT("SHA256 mismatch: %s"), *Path);
        return false;
    }
    Out.SetNumUninitialized(PixelCount);
    for (int32 I = 0; I < PixelCount; ++I)
    {
        Out[I] = uint16(Bytes[2 * I]) | (uint16(Bytes[2 * I + 1]) << 8);
    }
    return true;
}

bool ReadManifest(FPatchContext& C, FString& Error)
{
    const FString Dir = FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("TerrainRegrade/Local42Patch"));
    FString Json;
    if (!FFileHelper::LoadFileToString(Json, *FPaths::Combine(Dir, TEXT("manifest.json"))))
    {
        Error = TEXT("Patch manifest absent");
        return false;
    }
    TSharedPtr<FJsonObject> Object;
    const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Json);
    if (!FJsonSerializer::Deserialize(Reader, Object) || !Object.IsValid())
    {
        Error = TEXT("Patch manifest invalid JSON");
        return false;
    }
    if (!Object->TryGetBoolField(TEXT("review_only"), C.bReviewOnly) ||
        !Object->TryGetBoolField(TEXT("editor_apply_authorized"), C.bApplyAuthorized))
    {
        Error = TEXT("Patch manifest authorization flags absent");
        return false;
    }
    const TArray<TSharedPtr<FJsonValue>>* Bounds = nullptr;
    const TArray<TSharedPtr<FJsonValue>>* Size = nullptr;
    const TArray<TSharedPtr<FJsonValue>>* Image = nullptr;
    const TArray<TSharedPtr<FJsonValue>>* Origin = nullptr;
    double XYStep = 0.0;
    double ZStep = 0.0;
    if (!Object->TryGetArrayField(TEXT("pixel_bounds_inclusive"), Bounds) || Bounds->Num() != 4 ||
        !Object->TryGetArrayField(TEXT("roi_pixels"), Size) || Size->Num() != 2 ||
        !Object->TryGetArrayField(TEXT("image_pixels"), Image) || Image->Num() != 2 ||
        !Object->TryGetArrayField(TEXT("world_origin_cm"), Origin) || Origin->Num() != 2 ||
        !Object->TryGetNumberField(TEXT("xy_cm_per_pixel"), XYStep) ||
        !Object->TryGetNumberField(TEXT("z_cm_per_u16_step"), ZStep) ||
        (*Bounds)[0]->AsNumber() != X1 || (*Bounds)[1]->AsNumber() != Y1 ||
        (*Bounds)[2]->AsNumber() != X2 || (*Bounds)[3]->AsNumber() != Y2 ||
        (*Size)[0]->AsNumber() != Width || (*Size)[1]->AsNumber() != Height ||
        (*Image)[0]->AsNumber() != 8161 || (*Image)[1]->AsNumber() != 8161 ||
        !FMath::IsNearlyEqual((*Origin)[0]->AsNumber(), -18920.4, 0.01) ||
        !FMath::IsNearlyEqual((*Origin)[1]->AsNumber(), 50.0, 0.01) ||
        !FMath::IsNearlyEqual(XYStep, 100.0, 0.01) ||
        !FMath::IsNearlyEqual(ZStep, 1.5625, 0.00001))
    {
        Error = TEXT("Manifest ROI/full extent differs from compiled allowlist");
        return false;
    }
    FString SourceHash, TargetHash;
    if (!Object->TryGetStringField(TEXT("source_roi_sha256"), SourceHash) ||
        !Object->TryGetStringField(TEXT("target_roi_sha256"), TargetHash) ||
        !ReadPatchFile(FPaths::Combine(Dir, TEXT("source_roi.r16")), SourceHash, C.Source, Error) ||
        !ReadPatchFile(FPaths::Combine(Dir, TEXT("target_roi.r16")), TargetHash, C.Target, Error))
    {
        if (Error.IsEmpty()) Error = TEXT("Manifest hashes absent");
        return false;
    }
    return true;
}

bool AddAllowedPackage(UPackage* Package, FPatchContext& C, FString& Error)
{
    if (!Package)
    {
        Error = TEXT("Null affected package");
        return false;
    }
    const FString Name = Package->GetName();
    const bool bAllowed = Name == MapPackage ||
        Name.StartsWith(TEXT("/Game/__ExternalActors__/level/Saskarta_WP/")) ||
        Name.StartsWith(TEXT("/Game/__ExternalObjects__/level/Saskarta_WP/"));
    if (!bAllowed)
    {
        Error = FString::Printf(TEXT("Affected package outside Saskarta_WP allowlist: %s"), *Name);
        return false;
    }
    if (!C.Packages.Contains(Package)) C.Packages.Add(Package);
    return true;
}

bool BackupPackages(const FPatchContext& C, FString& OutBackupDirectory, FString& Error)
{
    OutBackupDirectory = FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("TerrainRegrade/Local42Patch/BackupPackages"), FGuid::NewGuid().ToString());
    IPlatformFile& Files = FPlatformFileManager::Get().GetPlatformFile();
    if (!Files.CreateDirectoryTree(*OutBackupDirectory))
    {
        Error = TEXT("Cannot create scoped package backup directory");
        return false;
    }
    TArray<FString> Index;
    for (UPackage* Package : C.Packages)
    {
        FString SourceFilename;
        if (!FPackageName::DoesPackageExist(Package->GetName(), &SourceFilename))
        {
            Error = FString::Printf(TEXT("Affected package absent on disk: %s"), *Package->GetName());
            return false;
        }
        const FString BackupName = Package->GetName().Replace(TEXT("/"), TEXT("_")) + FPaths::GetExtension(SourceFilename, true);
        const FString BackupFilename = FPaths::Combine(OutBackupDirectory, BackupName);
        if (!Files.CopyFile(*BackupFilename, *SourceFilename))
        {
            Error = FString::Printf(TEXT("Cannot back up affected package: %s"), *SourceFilename);
            return false;
        }
        Index.Add(Package->GetName() + TEXT(" -> ") + BackupFilename);
    }
    if (!FFileHelper::SaveStringArrayToFile(Index, *FPaths::Combine(OutBackupDirectory, TEXT("packages.txt"))))
    {
        Error = TEXT("Cannot write backup package index");
        return false;
    }
    return true;
}

bool LoadContext(FPatchContext& C, FString& Error, bool bRequireClean)
{
    if (!GEditor || GEditor->PlayWorld || !ReadManifest(C, Error))
    {
        if (Error.IsEmpty()) Error = TEXT("Editor world unavailable or PIE active");
        return false;
    }
    C.World = GEditor->GetEditorWorldContext().World();
    if (!C.World || !C.World->PersistentLevel || C.World->PersistentLevel->GetOutermost()->GetName() != MapPackage)
    {
        Error = TEXT("Wrong editor world (expected /Game/level/Saskarta_WP)");
        return false;
    }
    for (TActorIterator<ALandscape> It(C.World); It; ++It)
    {
        if (C.Landscape)
        {
            Error = TEXT("Multiple loaded Landscape roots; target ambiguous");
            return false;
        }
        C.Landscape = *It;
    }
    if (!C.Landscape || C.Landscape->GetActorLabel() != LandscapeLabel || C.Landscape->GetName() != LandscapeActorName)
    {
        Error = TEXT("Landscape root/label does not match reviewed target");
        return false;
    }
    C.Info = C.Landscape->GetLandscapeInfo();
    if (!C.Info || !C.Info->IsLandscapeEditableWorld() || C.Info->HasUnloadedComponentsInRegion(X1, Y1, X2, Y2))
    {
        Error = TEXT("Landscape not editable or ROI has unloaded components");
        return false;
    }
    const FIntRect Extent = C.Info->GetCompleteLandscapeExtent();
    if (Extent.Min != FIntPoint(0, 0) || Extent.Max != FIntPoint(8160, 8160))
    {
        Error = FString::Printf(TEXT("Landscape extent differs from 0..8160: %s"), *Extent.ToString());
        return false;
    }
    const FTransform T = C.Landscape->GetActorTransform();
    const FVector Position = T.GetLocation();
    const FVector Scale = T.GetScale3D();
    if (!T.GetRotation().Equals(FQuat::Identity, 1e-5) ||
        !FMath::IsNearlyEqual(Position.X, -18920.4, 0.1) ||
        !FMath::IsNearlyEqual(Position.Y, 50.0, 0.1) ||
        !FMath::IsNearlyZero(Position.Z, 0.1) ||
        !FMath::IsNearlyEqual(Scale.X, 100.0, 0.02) ||
        !FMath::IsNearlyEqual(Scale.Y, 100.0, 0.02) ||
        !FMath::IsNearlyEqual(Scale.Z, 200.0, 0.02))
    {
        Error = FString::Printf(TEXT("Landscape transform/mapping differs; location=%s scale=%s"),
            *Position.ToString(), *Scale.ToString());
        return false;
    }
    const TArray<ULandscapeEditLayerBase*> Layers = C.Landscape->GetEditLayers();
    if (Layers.Num() != 1 || !Layers[0] || !Layers[0]->IsVisible() || Layers[0]->IsLocked())
    {
        Error = FString::Printf(TEXT("Expected one visible unlocked edit layer; found %d"), Layers.Num());
        return false;
    }
    C.LayerGuid = Layers[0]->GetGuid();
    if (!C.LayerGuid.IsValid())
    {
        Error = TEXT("Edit layer GUID invalid");
        return false;
    }
    int32 CX1, CY1, CX2, CY2;
    ALandscape::CalcComponentIndicesOverlap(X1, Y1, X2, Y2, C.Info->ComponentSizeQuads, CX1, CY1, CX2, CY2);
    for (int32 CY = CY1; CY <= CY2; ++CY)
    for (int32 CX = CX1; CX <= CX2; ++CX)
    {
        ULandscapeComponent* Component = C.Info->XYtoComponentMap.FindRef(FIntPoint(CX, CY));
        if (!Component || !Component->IsRegistered() || !Component->GetHeightmap(C.LayerGuid) ||
            !Component->GetHeightmap() || !Component->GetCollisionComponent())
        {
            Error = FString::Printf(TEXT("ROI component missing/unloaded/unregistered at %d,%d"), CX, CY);
            return false;
        }
        C.Components.Add(Component);
        if (!AddAllowedPackage(Component->GetOutermost(), C, Error) ||
            !AddAllowedPackage(Component->GetLandscapeProxy()->GetOutermost(), C, Error) ||
            !AddAllowedPackage(Component->GetHeightmap(C.LayerGuid)->GetOutermost(), C, Error) ||
            !AddAllowedPackage(Component->GetHeightmap()->GetOutermost(), C, Error) ||
            !AddAllowedPackage(Component->GetCollisionComponent()->GetOutermost(), C, Error))
            return false;
    }
    if (C.Components.IsEmpty())
    {
        Error = TEXT("No Landscape components in ROI");
        return false;
    }
    if (bRequireClean)
    {
        for (UPackage* Package : C.Packages)
        {
            if (Package->IsDirty())
            {
                Error = FString::Printf(TEXT("Affected package already dirty; save it before terrain import: %s"), *Package->GetName());
                return false;
            }
        }
    }
    return true;
}

bool MatchHeightData(FPatchContext& C, const TArray<uint16>& Expected, FString& Error)
{
    TArray<uint16> Raw;
    TArray<uint16> Composed;
    Raw.Init(0, PixelCount);
    Composed.Init(0, PixelCount);
    {
        FLandscapeEditDataInterface Edit(C.Info, C.LayerGuid);
        Edit.GetHeightDataFast(X1, Y1, X2, Y2, Raw.GetData(), Width);
    }
    {
        // Invalid layer GUID explicitly reads the final composed heightmap texture.
        FLandscapeEditDataInterface Edit(C.Info, FGuid());
        Edit.GetHeightDataFast(X1, Y1, X2, Y2, Composed.GetData(), Width);
    }
    for (int32 I = 0; I < PixelCount; ++I)
    {
        if (Raw[I] != Expected[I] || Composed[I] != Expected[I])
        {
            Error = FString::Printf(TEXT("Raw/composed mismatch at pixel %d,%d: raw=%u composed=%u expected=%u"),
                X1 + I % Width, Y1 + I / Width, Raw[I], Composed[I], Expected[I]);
            return false;
        }
    }
    return true;
}

bool CheckCollisionReadback(const FPatchContext& C, FString& Error)
{
    for (ULandscapeComponent* Component : C.Components)
    {
        ULandscapeHeightfieldCollisionComponent* Collision = Component->GetCollisionComponent();
        if (!Collision || !Collision->IsRegistered() || !Collision->IsPhysicsStateCreated())
        {
            Error = FString::Printf(TEXT("Collision not ready for %s"), *Component->GetName());
            return false;
        }
        const FIntPoint Base = Component->GetSectionBase();
        const FIntPoint ComponentIndex(Base.X / C.Info->ComponentSizeQuads,
            Base.Y / C.Info->ComponentSizeQuads);
        const int32 MinX = FMath::Max(X1, ComponentIndex.X * C.Info->ComponentSizeQuads + 1);
        const int32 MaxX = FMath::Min(X2, (ComponentIndex.X + 1) * C.Info->ComponentSizeQuads - 1);
        const int32 MinY = FMath::Max(Y1, ComponentIndex.Y * C.Info->ComponentSizeQuads + 1);
        const int32 MaxY = FMath::Min(Y2, (ComponentIndex.Y + 1) * C.Info->ComponentSizeQuads - 1);
        int32 BestIndex = INDEX_NONE;
        int32 BestChange = 0;
        for (int32 Y = MinY; Y <= MaxY; ++Y)
        for (int32 X = MinX; X <= MaxX; ++X)
        {
            const int32 I = (Y - Y1) * Width + X - X1;
            const int32 Change = FMath::Abs(int32(C.Target[I]) - int32(C.Source[I]));
            if (Change > BestChange)
            {
                BestChange = Change;
                BestIndex = I;
            }
        }
        if (BestIndex == INDEX_NONE) continue;
        const int32 PX = X1 + BestIndex % Width;
        const int32 PY = Y1 + BestIndex / Width;
        const FVector Local(double(PX), double(PY), (double(C.Target[BestIndex]) - 32768.0) / 128.0);
        const FVector World = C.Landscape->GetActorTransform().TransformPosition(Local);
        FHitResult Hit;
        const bool bHit = Collision->LineTraceComponent(Hit, World + FVector(0, 0, 30000),
            World - FVector(0, 0, 30000), FCollisionQueryParams());
        if (!bHit || FMath::Abs(Hit.ImpactPoint.Z - World.Z) > 100.0)
        {
            Error = FString::Printf(TEXT("Collision mismatch at %d,%d on %s: expected Z %.2f, hit Z %.2f"),
                PX, PY, *Component->GetName(), World.Z, bHit ? Hit.ImpactPoint.Z : -999999.0);
            return false;
        }
    }
    return true;
}

FString Apply(bool bRestore)
{
    FPatchContext C;
    FString Error;
    if (!LoadContext(C, Error, !bRestore)) return Fail(Error);
    if (!bRestore && (C.bReviewOnly || !C.bApplyAuthorized))
        return Fail(TEXT("Patch is review-only or editor apply is not authorized by manifest"));
    const TArray<uint16>& Before = bRestore ? C.Target : C.Source;
    const TArray<uint16>& After = bRestore ? C.Source : C.Target;
    if (!MatchHeightData(C, Before, Error)) return Fail(Error);
    FString BackupDirectory;
    if (!bRestore && !BackupPackages(C, BackupDirectory, Error)) return Fail(Error);
    {
        FLandscapeEditDataInterface Edit(C.Info, C.LayerGuid);
        Edit.SetHeightData(X1, Y1, X2, Y2, After.GetData(), Width,
            /*InCalcNormals=*/true, nullptr, nullptr, nullptr,
            /*InCreateComponents=*/false, nullptr, nullptr,
            /*InUpdateBounds=*/true, /*InUpdateCollision=*/true, /*InGenerateMips=*/true);
        Edit.Flush();
    }
    C.Landscape->RequestLayersContentUpdate(Update_Heightmap_All_Modes);
    return bRestore ? TEXT("RESTORED baseline in memory; no save performed") :
        FString::Printf(TEXT("APPLIED in memory; backup=%s; wait for Landscape update, then VerifyAndSaveLocal42"), *BackupDirectory);
}
}

FString USaskartaTerrainPatchLibrary::PreflightLocal42()
{
    FPatchContext C;
    FString Error;
    if (!LoadContext(C, Error, true) || !MatchHeightData(C, C.Source, Error)) return Fail(Error);
    return FString::Printf(TEXT("PASS: %d raw/composed heights match source; %d loaded components; %d clean scoped packages"),
        PixelCount, C.Components.Num(), C.Packages.Num());
}

FString USaskartaTerrainPatchLibrary::ApplyLocal42()
{
    return Apply(false);
}

FString USaskartaTerrainPatchLibrary::VerifyAndSaveLocal42()
{
    FPatchContext C;
    FString Error;
    if (!LoadContext(C, Error, false)) return Fail(Error);
    C.Landscape->ForceUpdateLayersContent();
    if (!MatchHeightData(C, C.Target, Error)) return Fail(Error);
    if (!CheckCollisionReadback(C, Error)) return Fail(Error);
    if (!UEditorLoadingAndSavingUtils::SavePackages(C.Packages, /*bOnlyDirty=*/true))
        return Fail(TEXT("Scoped package save failed; terrain remains dirty"));
    return FString::Printf(TEXT("PASS: %d target heights/collision checked; %d scoped packages saved"), PixelCount, C.Packages.Num());
}

FString USaskartaTerrainPatchLibrary::RestoreLocal42()
{
    return Apply(true);
}
