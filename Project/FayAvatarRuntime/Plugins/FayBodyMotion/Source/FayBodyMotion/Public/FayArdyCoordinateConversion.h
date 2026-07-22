#pragma once

#include "CoreMinimal.h"

/**
 * Convert ARDY's right-handed (+X character-left, +Y up, +Z forward) basis
 * into Unreal's left-handed (+X forward, +Y right, +Z up) basis.
 *
 * Pose transport deliberately remains in the source basis. Conversion occurs
 * exactly once, while producing the hidden Core27 source pose that the runtime
 * IK Retargeter consumes.
 */
FAYBODYMOTION_API FVector FayConvertArdyPositionToUnrealCentimetres(
    const FVector3f& PositionMetres);

/** Convert and normalize an ARDY XYZW quaternion into Unreal coordinates. */
FAYBODYMOTION_API FQuat FayConvertArdyQuaternionToUnreal(
    const FQuat4f& Rotation);

