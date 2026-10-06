#include "SaskartaCollapseStageLogic.h"

#include "SaskartaCollapseStageMath.h"
#include "Dom/JsonObject.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

FSaskartaCollapsePose FSaskartaCollapseStageLogic::Pose(const FSaskartaCollapseStageDef& Def, const FVector& SplinePoint,
    const FVector& SplineTangent, const FVector& Behind, const FVector& Ahead)
{
    using namespace SaskartaCollapseStageMath;
    FSaskartaCollapsePose P;
    P.RoadYawDeg = static_cast<float>(TravelYawDeg(SplineTangent.X, SplineTangent.Y, Behind.X, Behind.Y, Ahead.X, Ahead.Y, 0.0));
    P.YawDeg = static_cast<float>(WrapDeg(P.RoadYawDeg + Def.YawOffsetDeg));
    double X = 0.0;
    double Y = 0.0;
    // The lateral offset is across the ROAD (its own yaw), not across the offset carrier.
    LocalToWorld2D(SplinePoint.X, SplinePoint.Y, P.RoadYawDeg, 0.0, Def.LateralCm, X, Y);
    P.Centre = FVector(X, Y, SplinePoint.Z);
    return P;
}

void FSaskartaCollapseStageLogic::Footprint(const FSaskartaCollapseStageDef& Def, TArray<FVector2D>& OutLocal)
{
    OutLocal.Reset(6);
    OutLocal.Add(FVector2D(Def.WheelFrontCm, -Def.WheelHalfTrackCm));
    OutLocal.Add(FVector2D(Def.WheelFrontCm, Def.WheelHalfTrackCm));
    OutLocal.Add(FVector2D(Def.WheelRearCm, -Def.WheelHalfTrackCm));
    OutLocal.Add(FVector2D(Def.WheelRearCm, Def.WheelHalfTrackCm));
    OutLocal.Add(FVector2D(Def.CapsuleWheelXCm, -Def.CapsuleHalfTrackCm));
    OutLocal.Add(FVector2D(Def.CapsuleWheelXCm, Def.CapsuleHalfTrackCm));
}

FVector FSaskartaCollapseStageLogic::FootprintWorld(const FSaskartaCollapsePose& Pose, const FVector2D& Local)
{
    double X = 0.0;
    double Y = 0.0;
    SaskartaCollapseStageMath::LocalToWorld2D(Pose.Centre.X, Pose.Centre.Y, Pose.YawDeg, Local.X, Local.Y, X, Y);
    return FVector(X, Y, Pose.Centre.Z);
}

bool FSaskartaCollapseStageLogic::ParseJson(const FString& Json, FSaskartaCollapseStageDef& Out)
{
    TSharedPtr<FJsonObject> Root;
    const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Json);
    if (!FJsonSerializer::Deserialize(Reader, Root) || !Root.IsValid())
    {
        return false;
    }
    const TSharedPtr<FJsonObject>* StagePtr = nullptr;
    if (!Root->TryGetObjectField(TEXT("collapse_stage"), StagePtr) || !StagePtr || !StagePtr->IsValid())
    {
        return false;
    }
    const FJsonObject& S = **StagePtr;
    FSaskartaCollapseStageDef D = Out;
    auto Num = [&S](const TCHAR* Key, float& Field)
    {
        double V = 0.0;
        if (S.TryGetNumberField(Key, V) && FMath::IsFinite(V))
        {
            Field = static_cast<float>(V);
        }
    };
    auto Name = [&S](const TCHAR* Key, FName& Field)
    {
        FString V;
        if (S.TryGetStringField(Key, V))
        {
            Field = V.IsEmpty() ? NAME_None : FName(*V);
        }
    };
    bool bEnabled = D.bEnabled;
    if (S.TryGetBoolField(TEXT("enabled"), bEnabled))
    {
        D.bEnabled = bEnabled;
    }
    Name(TEXT("beat"), D.Beat);
    Name(TEXT("cinematic"), D.Cinematic);
    Num(TEXT("road_m"), D.RoadM);
    Num(TEXT("lateral_cm"), D.LateralCm);
    Num(TEXT("yaw_offset_deg"), D.YawOffsetDeg);
    Num(TEXT("cover_beyond_m"), D.CoverBeyondM);
    Num(TEXT("cover_hold_s"), D.CoverHoldS);
    Num(TEXT("cover_fade_s"), D.CoverFadeS);
    Num(TEXT("wheel_front_cm"), D.WheelFrontCm);
    Num(TEXT("wheel_rear_cm"), D.WheelRearCm);
    Num(TEXT("wheel_half_track_cm"), D.WheelHalfTrackCm);
    Num(TEXT("capsule_wheel_x_cm"), D.CapsuleWheelXCm);
    Num(TEXT("capsule_half_track_cm"), D.CapsuleHalfTrackCm);
    Num(TEXT("trace_up_cm"), D.TraceUpCm);
    Num(TEXT("trace_down_cm"), D.TraceDownCm);
    Num(TEXT("lift_cm"), D.LiftCm);
    Out = D;
    return true;
}
