#pragma once

#include "CoreMinimal.h"
#include "FayBodyMotionTypes.h"

/**
 * Bounded, component-basis corrections for ARDY's ordered foot contacts.
 *
 * These are offsets from the currently retargeted heel/toe locations, not
 * absolute targets. Applying an offset therefore does not assume that Core27
 * and the target character share a component origin, leg length, or rest pose.
 */
struct FAYBODYMOTION_API FFayArdyFootContactOutput
{
    static constexpr int32 ContactCount = 4;

    FVector OffsetsCentimetres[ContactCount] = {
        FVector::ZeroVector,
        FVector::ZeroVector,
        FVector::ZeroVector,
        FVector::ZeroVector};
    float Weights[ContactCount] = {0.0f, 0.0f, 0.0f, 0.0f};
    bool bValid = false;
};

/**
 * Action-scoped foot-contact drift stabilizer for protocol-v2 Core27 poses.
 *
 * A contact acquires an anchor only after the sealed contact signal crosses a
 * high threshold. While held, global joint displacement is converted once to
 * Unreal's component basis and countered by at most six centimetres. Excessive
 * displacement disables that contact until a clean release, so malformed data
 * cannot drag the character. No root, neck, head, face, or finger transform is
 * written by this class.
 */
class FAYBODYMOTION_API FFayArdyContactStabilizer final
{
public:
    void Reset();

    /** Returns false and resets on malformed/non-finite input. */
    bool Update(
        const FFayArdyPoseFrame& Pose,
        float DeltaSeconds,
        FFayArdyFootContactOutput& OutOutput);

    /** Smooth all contact weights to zero while preserving bounded offsets. */
    void FadeOut(float DeltaSeconds, FFayArdyFootContactOutput& OutOutput);

private:
    struct FContactState
    {
        FVector3f AnchorPositionMetres = FVector3f::ZeroVector;
        FVector LastOffsetCentimetres = FVector::ZeroVector;
        float SmoothedWeight = 0.0f;
        bool bAnchored = false;
        bool bBlockedUntilRelease = false;
    };

    void WriteOutput(FFayArdyFootContactOutput& OutOutput) const;

    FContactState ContactStates[FFayArdyFootContactOutput::ContactCount];
};
