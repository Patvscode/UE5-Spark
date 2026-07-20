#include "FayWavDecoder.h"

namespace
{
uint16 ReadUInt16LE(const uint8* Data)
{
    return static_cast<uint16>(Data[0]) |
        (static_cast<uint16>(Data[1]) << 8);
}

uint32 ReadUInt32LE(const uint8* Data)
{
    return static_cast<uint32>(Data[0]) |
        (static_cast<uint32>(Data[1]) << 8) |
        (static_cast<uint32>(Data[2]) << 16) |
        (static_cast<uint32>(Data[3]) << 24);
}

bool IsFourCC(const uint8* Data, const ANSICHAR A, const ANSICHAR B, const ANSICHAR C, const ANSICHAR D)
{
    return Data[0] == static_cast<uint8>(A) &&
        Data[1] == static_cast<uint8>(B) &&
        Data[2] == static_cast<uint8>(C) &&
        Data[3] == static_cast<uint8>(D);
}
}

bool FayAvatarBridge::DecodePcm16Wave(const TArray<uint8>& WaveBytes, FDecodedPcm16Wave& OutWave, FString& OutError)
{
    OutWave = FDecodedPcm16Wave();
    OutError.Reset();

    if (WaveBytes.Num() < 12)
    {
        OutError = TEXT("The response is too small to be a RIFF/WAVE file.");
        return false;
    }

    const uint8* Bytes = WaveBytes.GetData();
    if (!IsFourCC(Bytes, 'R', 'I', 'F', 'F') || !IsFourCC(Bytes + 8, 'W', 'A', 'V', 'E'))
    {
        OutError = TEXT("Only little-endian RIFF/WAVE audio is supported.");
        return false;
    }

    bool bFoundFormat = false;
    bool bFoundData = false;
    uint16 AudioFormat = 0;
    uint16 NumChannels = 0;
    uint16 BitsPerSample = 0;
    uint16 BlockAlign = 0;
    uint32 SampleRate = 0;
    int32 PcmOffset = 0;
    int32 PcmSize = 0;

    int64 Offset = 12;
    const int64 TotalSize = WaveBytes.Num();
    while (Offset + 8 <= TotalSize)
    {
        const uint8* ChunkHeader = Bytes + Offset;
        const uint32 ChunkSize = ReadUInt32LE(ChunkHeader + 4);
        const int64 PayloadOffset = Offset + 8;
        const int64 PayloadEnd = PayloadOffset + static_cast<int64>(ChunkSize);

        if (PayloadEnd > TotalSize)
        {
            OutError = TEXT("A WAV chunk extends beyond the HTTP response.");
            return false;
        }

        if (IsFourCC(ChunkHeader, 'f', 'm', 't', ' '))
        {
            if (ChunkSize < 16)
            {
                OutError = TEXT("The WAV fmt chunk is truncated.");
                return false;
            }

            const uint8* Format = Bytes + PayloadOffset;
            AudioFormat = ReadUInt16LE(Format);
            NumChannels = ReadUInt16LE(Format + 2);
            SampleRate = ReadUInt32LE(Format + 4);
            BlockAlign = ReadUInt16LE(Format + 12);
            BitsPerSample = ReadUInt16LE(Format + 14);

            // WAVE_FORMAT_EXTENSIBLE stores the real format tag at the start
            // of its SubFormat GUID.
            if (AudioFormat == 0xfffe && ChunkSize >= 40)
            {
                AudioFormat = ReadUInt16LE(Format + 24);
            }

            bFoundFormat = true;
        }
        else if (IsFourCC(ChunkHeader, 'd', 'a', 't', 'a') && !bFoundData)
        {
            PcmOffset = static_cast<int32>(PayloadOffset);
            PcmSize = static_cast<int32>(ChunkSize);
            bFoundData = true;
        }

        Offset = PayloadEnd + (ChunkSize & 1u);
    }

    if (!bFoundFormat || !bFoundData)
    {
        OutError = TEXT("The WAV file must contain both fmt and data chunks.");
        return false;
    }

    if (AudioFormat != 1 || BitsPerSample != 16)
    {
        OutError = FString::Printf(TEXT("Unsupported WAV format tag %u with %u-bit samples; PCM16 is required."),
            static_cast<uint32>(AudioFormat), static_cast<uint32>(BitsPerSample));
        return false;
    }

    if (NumChannels < 1 || NumChannels > 2)
    {
        OutError = FString::Printf(TEXT("Unsupported channel count %u; mono or stereo is required."),
            static_cast<uint32>(NumChannels));
        return false;
    }

    if (SampleRate < 8000 || SampleRate > 192000)
    {
        OutError = FString::Printf(TEXT("Unsupported sample rate %u Hz."), SampleRate);
        return false;
    }

    const uint16 ExpectedBlockAlign = static_cast<uint16>(NumChannels * sizeof(int16));
    if (BlockAlign != ExpectedBlockAlign || PcmSize <= 0 || (PcmSize % BlockAlign) != 0)
    {
        OutError = TEXT("The WAV data is not complete interleaved PCM16 frames.");
        return false;
    }

    OutWave.Pcm16.Append(Bytes + PcmOffset, PcmSize);
    OutWave.SampleRate = static_cast<int32>(SampleRate);
    OutWave.NumChannels = static_cast<int32>(NumChannels);
    const int32 NumFrames = PcmSize / BlockAlign;
    OutWave.DurationSeconds = static_cast<float>(NumFrames) / static_cast<float>(SampleRate);
    return true;
}
