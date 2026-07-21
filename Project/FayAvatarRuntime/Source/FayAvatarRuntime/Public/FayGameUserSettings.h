#pragma once

#include "CoreMinimal.h"
#include "GameFramework/GameUserSettings.h"
#include "FayGameUserSettings.generated.h"

/**
 * Project-owned runtime settings with a dependable reviewed frame-rate limit.
 *
 * A stale per-user GameUserSettings.ini must not silently turn the packaged
 * digital-human renderer into an uncapped GPU workload.
 */
UCLASS(Config = GameUserSettings)
class FAYAVATARRUNTIME_API UFayGameUserSettings final : public UGameUserSettings
{
    GENERATED_BODY()

public:
    virtual void SetToDefaults() override;
    virtual float GetEffectiveFrameRateLimit() override;
};
