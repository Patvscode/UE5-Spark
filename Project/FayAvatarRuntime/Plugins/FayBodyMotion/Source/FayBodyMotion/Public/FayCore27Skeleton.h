#pragma once

#include "CoreMinimal.h"

class USkeletalMesh;

struct FAYBODYMOTION_API FFayCore27Bone
{
    FName Name = NAME_None;
    int32 ParentIndex = INDEX_NONE;
};

/** Exact ordered hierarchy published by nv-tlabs/ardy Core27. */
FAYBODYMOTION_API const TArray<FFayCore27Bone>& FayGetCore27Hierarchy();

/** Fail-closed validation for the hidden runtime source skeletal mesh. */
FAYBODYMOTION_API bool FayValidateExactCore27Mesh(
    const USkeletalMesh* SkeletalMesh,
    FString& OutReason);

