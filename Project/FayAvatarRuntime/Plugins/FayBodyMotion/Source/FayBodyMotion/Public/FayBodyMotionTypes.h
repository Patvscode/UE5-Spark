#pragma once

#include "CoreMinimal.h"
#include "FayBodyMotionTypes.generated.h"

UENUM(BlueprintType)
enum class EFayBodyMotionProvider : uint8
{
    Baked,
    Ardy
};

/** Requested routing mode. Hybrid is the backward-compatible default. */
UENUM(BlueprintType)
enum class EFayBodyMotionRoutingMode : uint8
{
    Hybrid,
    Deterministic
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

    /** Optional generative text condition; empty selects the preset embedding. */
    UPROPERTY(BlueprintReadOnly, Category = "Fay|Body Motion")
    FString Prompt;

    UPROPERTY(BlueprintReadOnly, Category = "Fay|Body Motion")
    float Intensity = 0.5f;

    UPROPERTY(BlueprintReadOnly, Category = "Fay|Body Motion")
    float DurationSeconds = 1.0f;

    UPROPERTY(BlueprintReadOnly, Category = "Fay|Body Motion")
    int32 Priority = 0;

    UPROPERTY(BlueprintReadOnly, Category = "Fay|Body Motion")
    EFayBodyMotionRoutingMode RoutingMode = EFayBodyMotionRoutingMode::Hybrid;
};

/** Normalized ARDY pose before the one reviewed conversion into Unreal coordinates. */
USTRUCT(BlueprintType)
struct FAYBODYMOTION_API FFayArdyPoseFrame
{
    GENERATED_BODY()

    UPROPERTY(BlueprintReadOnly, Category = "Fay|Body Motion")
    double TimeSeconds = 0.0;

    /** ARDY RH +X-left, +Y-up, +Z-forward root transform in metres/XYZW. */
    UPROPERTY(BlueprintReadOnly, Category = "Fay|Body Motion")
    FVector3f RootTranslationMetres = FVector3f::ZeroVector;

    UPROPERTY(BlueprintReadOnly, Category = "Fay|Body Motion")
    FQuat4f RootRotation = FQuat4f::Identity;

    /** Core27 local joint rotations in XYZW order. */
    UPROPERTY(BlueprintReadOnly, Category = "Fay|Body Motion")
    TArray<FQuat4f> JointRotations;

    /** Core27 global posed-joint positions in ARDY metres, exact joint order. */
    UPROPERTY(BlueprintReadOnly, Category = "Fay|Body Motion")
    TArray<FVector3f> JointPositionsMetres;

    UPROPERTY(BlueprintReadOnly, Category = "Fay|Body Motion")
    TArray<float> Contacts;
};

USTRUCT(BlueprintType)
struct FAYBODYMOTION_API FFayBodyPoseBatch
{
    GENERATED_BODY()

    UPROPERTY(BlueprintReadOnly, Category = "Fay|Body Motion")
    int32 Version = 2;

    UPROPERTY(BlueprintReadOnly, Category = "Fay|Body Motion")
    int64 Sequence = 0;

    UPROPERTY(BlueprintReadOnly, Category = "Fay|Body Motion")
    int32 FramesPerSecond = 20;

    UPROPERTY(BlueprintReadOnly, Category = "Fay|Body Motion")
    FString CoordinateSystem =
        TEXT("ardy-rh-x-left-y-up-z-forward-meters");

    UPROPERTY(BlueprintReadOnly, Category = "Fay|Body Motion")
    TArray<FFayArdyPoseFrame> Frames;
};
