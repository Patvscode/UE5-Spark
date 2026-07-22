#include "FayArdyRetargetProfile.h"

UFayArdyRetargetBindingComponent::UFayArdyRetargetBindingComponent()
{
    PrimaryComponentTick.bCanEverTick = false;
}

bool UFayArdyRetargetProfile::ValidateAssetReferences(FString& OutReason) const
{
    OutReason.Reset();
    if (ProfileId.IsNone())
    {
        OutReason = TEXT("the retarget profile ID is empty");
        return false;
    }
    if (Core27SourceMesh.IsNull())
    {
        OutReason = TEXT("the exact Core27 source mesh is unassigned");
        return false;
    }
    if (TargetPostProcessAnimClass.IsNull())
    {
        OutReason = TEXT("the reviewed target post-process AnimBP is unassigned");
        return false;
    }
    if (IKRetargeterAsset.IsNull())
    {
        OutReason = TEXT("the reviewed IK Retargeter is unassigned");
        return false;
    }
    if (TargetBodyBlendMask.IsNull())
    {
        OutReason = TEXT("the reviewed body-only blend mask is unassigned");
        return false;
    }
    if (SourceRetargetPose.IsNone() || TargetRetargetPose.IsNone())
    {
        OutReason = TEXT("the reviewed source and target retarget poses are required");
        return false;
    }
    if (!FMath::IsFinite(MaximumRootOffsetCentimetres) ||
        MaximumRootOffsetCentimetres < 0.0f ||
        MaximumRootOffsetCentimetres > 20.0f)
    {
        OutReason = TEXT("the bounded root offset must be finite and between 0 and 20 cm");
        return false;
    }
    return true;
}

