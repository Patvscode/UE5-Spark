#pragma once

#include "Animation/AnimInstance.h"
#include "FayBodyMotionTypes.h"
#include "FayCore27SourceAnimInstance.generated.h"

class FAnimInstanceProxy;

/** Thread-safe snapshot consumed by the hidden Core27 source AnimInstance. */
struct FAYBODYMOTION_API FFayCore27SourcePoseSnapshot
{
    FQuat4f RootRotation = FQuat4f::Identity;
    TArray<FQuat4f> JointRotations;
    FVector RootOffsetCentimetres = FVector::ZeroVector;
    bool bValid = false;
};

/**
 * Native ref-pose producer for the exact hidden Core27 mesh.
 *
 * ARDY data is evaluated through Unreal's animation pipeline. It never writes
 * into another component's finalized transform buffer. A reviewed target
 * post-process AnimBP consumes this source through Retarget Pose From Mesh.
 */
UCLASS(Transient, BlueprintType)
class FAYBODYMOTION_API UFayCore27SourceAnimInstance final : public UAnimInstance
{
    GENERATED_BODY()

public:
    void SubmitPose(
        const FFayArdyPoseFrame& Pose,
        const FVector& RootOffsetCentimetres);
    void ResetPose();

protected:
    virtual FAnimInstanceProxy* CreateAnimInstanceProxy() override;
    virtual void DestroyAnimInstanceProxy(FAnimInstanceProxy* InProxy) override;

private:
    friend class FFayCore27SourceAnimProxy;
    void CopyPendingPose(FFayCore27SourcePoseSnapshot& OutPose) const;

    mutable FCriticalSection PoseMutex;
    FFayCore27SourcePoseSnapshot PendingPose;
};

