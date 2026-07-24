#include "FayCore27Skeleton.h"

#include "Engine/SkeletalMesh.h"

const TArray<FFayCore27Bone>& FayGetCore27Hierarchy()
{
    static const TArray<FFayCore27Bone> Hierarchy = {
        {TEXT("Hips"), INDEX_NONE},
        {TEXT("Spine"), 0},
        {TEXT("Spine1"), 1},
        {TEXT("Spine2"), 2},
        {TEXT("Spine3"), 3},
        {TEXT("Neck"), 4},
        {TEXT("Head"), 5},
        {TEXT("RightShoulder"), 4},
        {TEXT("RightArm"), 7},
        {TEXT("RightForeArm"), 8},
        {TEXT("RightHand"), 9},
        {TEXT("RightHandEnd"), 10},
        {TEXT("RightHandThumb1"), 10},
        {TEXT("LeftShoulder"), 4},
        {TEXT("LeftArm"), 13},
        {TEXT("LeftForeArm"), 14},
        {TEXT("LeftHand"), 15},
        {TEXT("LeftHandEnd"), 16},
        {TEXT("LeftHandThumb1"), 16},
        {TEXT("RightUpLeg"), 0},
        {TEXT("RightLeg"), 19},
        {TEXT("RightFoot"), 20},
        {TEXT("RightToeBase"), 21},
        {TEXT("LeftUpLeg"), 0},
        {TEXT("LeftLeg"), 23},
        {TEXT("LeftFoot"), 24},
        {TEXT("LeftToeBase"), 25},
    };
    return Hierarchy;
}

bool FayValidateExactCore27Mesh(
    const USkeletalMesh* SkeletalMesh,
    FString& OutReason)
{
    OutReason.Reset();
    if (!IsValid(SkeletalMesh))
    {
        OutReason = TEXT("the Core27 source skeletal mesh is null");
        return false;
    }

    const FReferenceSkeleton& ReferenceSkeleton = SkeletalMesh->GetRefSkeleton();
    const TArray<FFayCore27Bone>& Expected = FayGetCore27Hierarchy();
    if (ReferenceSkeleton.GetNum() != Expected.Num())
    {
        OutReason = FString::Printf(
            TEXT("the Core27 source has %d bones instead of exactly %d"),
            ReferenceSkeleton.GetNum(),
            Expected.Num());
        return false;
    }

    for (int32 Index = 0; Index < Expected.Num(); ++Index)
    {
        const FName ActualName = ReferenceSkeleton.GetBoneName(Index);
        const int32 ActualParent = ReferenceSkeleton.GetParentIndex(Index);
        if (ActualName != Expected[Index].Name ||
            ActualParent != Expected[Index].ParentIndex)
        {
            OutReason = FString::Printf(
                TEXT("Core27 bone %d is '%s' parent %d; expected '%s' parent %d"),
                Index,
                *ActualName.ToString(),
                ActualParent,
                *Expected[Index].Name.ToString(),
                Expected[Index].ParentIndex);
            return false;
        }
    }
    return true;
}

