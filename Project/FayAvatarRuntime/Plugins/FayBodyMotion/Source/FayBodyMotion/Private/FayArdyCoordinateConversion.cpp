#include "FayArdyCoordinateConversion.h"

FVector FayConvertArdyPositionToUnrealCentimetres(
    const FVector3f& PositionMetres)
{
    // ARDY +X is character-left, therefore Unreal +Y (character-right) is -X.
    return FVector(PositionMetres.Z, -PositionMetres.X, PositionMetres.Y) * 100.0;
}

FQuat FayConvertArdyQuaternionToUnreal(const FQuat4f& Rotation)
{
    // Handedness-changing basis conversion corresponding to position (z,-x,y).
    FQuat Converted(-Rotation.Z, Rotation.X, -Rotation.Y, Rotation.W);
    Converted.Normalize();
    // Keep a deterministic hemisphere at the source-pose boundary. Streaming
    // interpolation also stabilizes each quaternion against the previous frame.
    if (Converted.W < 0.0)
    {
        Converted.X = -Converted.X;
        Converted.Y = -Converted.Y;
        Converted.Z = -Converted.Z;
        Converted.W = -Converted.W;
    }
    return Converted;
}

