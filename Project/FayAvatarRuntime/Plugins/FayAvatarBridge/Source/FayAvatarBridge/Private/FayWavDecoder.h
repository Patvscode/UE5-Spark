#pragma once

#include "CoreMinimal.h"

namespace FayAvatarBridge
{
struct FDecodedPcm16Wave
{
    TArray<uint8> Pcm16;
    int32 SampleRate = 0;
    int32 NumChannels = 0;
    float DurationSeconds = 0.0f;
};

/** Decode a little-endian RIFF/WAVE containing mono or stereo PCM16. */
bool DecodePcm16Wave(const TArray<uint8>& WaveBytes, FDecodedPcm16Wave& OutWave, FString& OutError);
}
