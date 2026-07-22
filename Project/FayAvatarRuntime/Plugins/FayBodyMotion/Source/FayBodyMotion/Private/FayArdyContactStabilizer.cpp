#include "FayArdyContactStabilizer.h"

#include "FayArdyCoordinateConversion.h"

namespace
{
constexpr int32 FayContactCore27JointCount = 27;
constexpr int32 FayContactCount = FFayArdyFootContactOutput::ContactCount;

// Protocol-v2 contact order is left heel, left toe, right heel, right toe.
// Core27 has ankle/foot and toe-base joints; the foot joint is the stable heel
// proxy used by the reviewed target IK layer.
constexpr int32 FayContactJointIndices[FayContactCount] = {25, 26, 21, 22};
constexpr float FayContactAcquireThreshold = 0.65f;
constexpr float FayContactReleaseThreshold = 0.35f;
constexpr float FayMaximumContactCorrectionCentimetres = 6.0f;
constexpr float FayMaximumContactAnchorDriftCentimetres = 18.0f;
constexpr float FayMaximumContactJointDistanceMetres = 3.0f;
constexpr float FayContactWeightSmoothingSpeed = 12.0f;
constexpr float FayContactMaximumDeltaSeconds = 0.1f;

bool FayIsFiniteContactVector(const FVector3f& Value)
{
    return FMath::IsFinite(Value.X) && FMath::IsFinite(Value.Y) &&
        FMath::IsFinite(Value.Z);
}
}

void FFayArdyContactStabilizer::Reset()
{
    for (FContactState& State : ContactStates)
    {
        State = FContactState();
    }
}

bool FFayArdyContactStabilizer::Update(
    const FFayArdyPoseFrame& Pose,
    const float DeltaSeconds,
    FFayArdyFootContactOutput& OutOutput)
{
    OutOutput = FFayArdyFootContactOutput();
    if (Pose.JointPositionsMetres.Num() != FayContactCore27JointCount ||
        Pose.Contacts.Num() != FayContactCount ||
        !FMath::IsFinite(DeltaSeconds) || DeltaSeconds < 0.0f)
    {
        Reset();
        return false;
    }

    const float SafeDeltaSeconds = FMath::Min(
        DeltaSeconds,
        FayContactMaximumDeltaSeconds);
    for (int32 ContactIndex = 0; ContactIndex < FayContactCount; ++ContactIndex)
    {
        FContactState& State = ContactStates[ContactIndex];
        const FVector3f& JointPosition =
            Pose.JointPositionsMetres[FayContactJointIndices[ContactIndex]];
        const FVector3f JointFromRoot =
            JointPosition - Pose.RootTranslationMetres;
        const float ContactSignal = Pose.Contacts[ContactIndex];
        if (!FayIsFiniteContactVector(JointPosition) ||
            !FayIsFiniteContactVector(JointFromRoot) ||
            JointFromRoot.Size() > FayMaximumContactJointDistanceMetres ||
            !FMath::IsFinite(ContactSignal) || ContactSignal < 0.0f ||
            ContactSignal > 1.0f)
        {
            Reset();
            return false;
        }

        if (ContactSignal <= FayContactReleaseThreshold)
        {
            State.bAnchored = false;
            State.bBlockedUntilRelease = false;
            State.LastOffsetCentimetres = FVector::ZeroVector;
        }
        else if (!State.bAnchored && !State.bBlockedUntilRelease &&
            ContactSignal >= FayContactAcquireThreshold)
        {
            State.AnchorPositionMetres = JointPosition;
            State.LastOffsetCentimetres = FVector::ZeroVector;
            State.bAnchored = true;
        }

        if (State.bAnchored)
        {
            const FVector DriftCentimetres =
                FayConvertArdyPositionToUnrealCentimetres(
                    JointPosition - State.AnchorPositionMetres);
            if (!DriftCentimetres.ContainsNaN() &&
                DriftCentimetres.Size() <=
                    FayMaximumContactAnchorDriftCentimetres)
            {
                State.LastOffsetCentimetres =
                    (-DriftCentimetres).GetClampedToMaxSize(
                        FayMaximumContactCorrectionCentimetres);
            }
            else
            {
                State.bAnchored = false;
                State.bBlockedUntilRelease = true;
                State.LastOffsetCentimetres = FVector::ZeroVector;
            }
        }

        const float DesiredWeight = State.bAnchored ? ContactSignal : 0.0f;
        State.SmoothedWeight = FMath::FInterpTo(
            State.SmoothedWeight,
            DesiredWeight,
            SafeDeltaSeconds,
            FayContactWeightSmoothingSpeed);
        State.SmoothedWeight = FMath::Clamp(State.SmoothedWeight, 0.0f, 1.0f);
    }

    WriteOutput(OutOutput);
    OutOutput.bValid = true;
    return true;
}

void FFayArdyContactStabilizer::FadeOut(
    const float DeltaSeconds,
    FFayArdyFootContactOutput& OutOutput)
{
    const float SafeDeltaSeconds = FMath::IsFinite(DeltaSeconds)
        ? FMath::Clamp(DeltaSeconds, 0.0f, FayContactMaximumDeltaSeconds)
        : FayContactMaximumDeltaSeconds;
    for (FContactState& State : ContactStates)
    {
        State.SmoothedWeight = FMath::FInterpTo(
            State.SmoothedWeight,
            0.0f,
            SafeDeltaSeconds,
            FayContactWeightSmoothingSpeed);
        State.SmoothedWeight = FMath::Clamp(State.SmoothedWeight, 0.0f, 1.0f);
    }
    WriteOutput(OutOutput);
    OutOutput.bValid = true;
}

void FFayArdyContactStabilizer::WriteOutput(
    FFayArdyFootContactOutput& OutOutput) const
{
    OutOutput = FFayArdyFootContactOutput();
    for (int32 ContactIndex = 0; ContactIndex < FayContactCount; ++ContactIndex)
    {
        OutOutput.OffsetsCentimetres[ContactIndex] =
            ContactStates[ContactIndex].LastOffsetCentimetres;
        OutOutput.Weights[ContactIndex] =
            ContactStates[ContactIndex].SmoothedWeight;
    }
}
