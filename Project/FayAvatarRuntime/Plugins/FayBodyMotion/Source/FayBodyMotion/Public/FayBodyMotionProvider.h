#pragma once

#include "CoreMinimal.h"
#include "FayBodyMotionTypes.h"

class UAnimMontage;
class USkeletalMeshComponent;

/** Small provider boundary kept independent of Fay transport and MetaHuman identity. */
class FAYBODYMOTION_API IFayBodyMotionProvider
{
public:
    virtual ~IFayBodyMotionProvider() = default;
    virtual EFayBodyMotionProvider GetKind() const = 0;
    virtual bool IsReady() const = 0;
    virtual bool Perform(const FFayBodyMotionRequest& Request) = 0;
    virtual void Stop(float BlendOutSeconds) = 0;
    virtual void Tick(float DeltaSeconds) = 0;
};
