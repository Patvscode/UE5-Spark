#pragma once

#include "Animation/AnimInstance.h"
#include "FayBodyMotionTypes.h"
#include "FayCore27EpicAnimInstance.generated.h"

class USkeletalMesh;
struct FAnimInstanceProxy;

/** Thread-safe Core27 snapshot consumed by the native UE5-Epic retarget proxy. */
struct FAYBODYMOTION_API FFayCore27EpicPoseSnapshot
{
    FQuat4f RootRotation = FQuat4f::Identity;
    TArray<FQuat4f> JointRotations;
    FVector RootOffsetCentimetres = FVector::ZeroVector;
    float BlendWeight = 0.0f;
    bool bValid = false;
};

/**
 * Source-only Core27 -> UE5 Epic skeleton adapter.
 *
 * This is the bounded runtime path for characters that use the stock UE5
 * mannequin hierarchy but do not ship a project-authored IK Retargeter or
 * post-process AnimBP.  It applies Core27 component-space rotation deltas to
 * the matching pelvis, spine, arm and leg chains through normal animation
 * evaluation.  Neck, head and finger bones deliberately remain owned by the
 * target reference/face pose.
 *
 * It is an approximate rotational retarget, not a replacement for an
 * editor-reviewed IK Retargeter: target bone lengths are preserved, root
 * motion remains bounded by BodyMotion, and foot-contact translation is not
 * synthesized by this adapter.
 */
UCLASS(Transient, BlueprintType)
class FAYBODYMOTION_API UFayCore27EpicAnimInstance final : public UAnimInstance
{
    GENERATED_BODY()

public:
    static bool SupportsExactEpicSkeleton(
        const USkeletalMesh* SkeletalMesh,
        FString& OutReason);

    void SubmitPose(
        const FFayArdyPoseFrame& Pose,
        const FVector& RootOffsetCentimetres,
        float BlendWeight);
    void ResetPose();

protected:
    virtual FAnimInstanceProxy* CreateAnimInstanceProxy() override;
    virtual void DestroyAnimInstanceProxy(FAnimInstanceProxy* InProxy) override;

private:
    friend class FFayCore27EpicAnimProxy;
    void CopyPendingPose(FFayCore27EpicPoseSnapshot& OutPose) const;

    mutable FCriticalSection PoseMutex;
    FFayCore27EpicPoseSnapshot PendingPose;
};
