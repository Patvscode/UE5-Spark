#pragma once

#include "CoreMinimal.h"
#include "FayBodyMotionTypes.generated.h"

UENUM(BlueprintType)
enum class EFayBodyMotionProvider : uint8
{
    Baked,
    Ardy
};

UENUM(BlueprintType)
enum class EFayBodyMotionState : uint8
{
    Unconfigured,
    Idle,
    Performing,
    FallingBack,
    Error
};

USTRUCT(BlueprintType)
struct FAYBODYMOTION_API FFayBodyMotionRequest
{
    GENERATED_BODY()

    UPROPERTY(BlueprintReadOnly, Category = "Fay|Body Motion")
    FName Behavior = NAME_None;

    UPROPERTY(BlueprintReadOnly, Category = "Fay|Body Motion")
    float Intensity = 0.5f;

    UPROPERTY(BlueprintReadOnly, Category = "Fay|Body Motion")
    float DurationSeconds = 1.0f;

    UPROPERTY(BlueprintReadOnly, Category = "Fay|Body Motion")
    int32 Priority = 0;
};

/** Normalized ARDY pose before conversion into Unreal coordinates. */
USTRUCT(BlueprintType)
struct FAYBODYMOTION_API FFayArdyPoseFrame
{
    GENERATED_BODY()

    UPROPERTY(BlueprintReadOnly, Category = "Fay|Body Motion")
    double TimeSeconds = 0.0;

    /** ARDY Y-up, +Z-forward root translation in metres and XYZW rotation. */
    UPROPERTY(BlueprintReadOnly, Category = "Fay|Body Motion")
    FVector3f RootTranslationMetres = FVector3f::ZeroVector;

    UPROPERTY(BlueprintReadOnly, Category = "Fay|Body Motion")
    FQuat4f RootRotation = FQuat4f::Identity;

    /** Core27 local joint rotations in XYZW order. */
    UPROPERTY(BlueprintReadOnly, Category = "Fay|Body Motion")
    TArray<FQuat4f> JointRotations;

    UPROPERTY(BlueprintReadOnly, Category = "Fay|Body Motion")
    TArray<float> Contacts;
};

USTRUCT(BlueprintType)
struct FAYBODYMOTION_API FFayBodyPoseBatch
{
    GENERATED_BODY()

    UPROPERTY(BlueprintReadOnly, Category = "Fay|Body Motion")
    int32 Version = 1;

    UPROPERTY(BlueprintReadOnly, Category = "Fay|Body Motion")
    int64 Sequence = 0;

    UPROPERTY(BlueprintReadOnly, Category = "Fay|Body Motion")
    int32 FramesPerSecond = 20;

    UPROPERTY(BlueprintReadOnly, Category = "Fay|Body Motion")
    FString CoordinateSystem = TEXT("ardy-y-up-z-forward-meters");

    UPROPERTY(BlueprintReadOnly, Category = "Fay|Body Motion")
    TArray<FFayArdyPoseFrame> Frames;
};
