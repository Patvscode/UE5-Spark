#include "FayGameUserSettings.h"

namespace
{
constexpr float ReviewedFrameRateLimit = 30.0f;
}

void UFayGameUserSettings::SetToDefaults()
{
    Super::SetToDefaults();
    SetFrameRateLimit(ReviewedFrameRateLimit);
}

float UFayGameUserSettings::GetEffectiveFrameRateLimit()
{
    return ReviewedFrameRateLimit;
}
