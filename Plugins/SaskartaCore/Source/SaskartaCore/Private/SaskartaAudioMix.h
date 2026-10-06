#pragma once

namespace SaskartaAudioMix
{
    // +6 dB for radio programmes and archive speech (was +3; the author, 2026-09-29: "the radio must be louder than
    // the motor and other sounds"). Static, tuning noise and the carrier voice retain their authored level; user
    // volume still applies.
    inline constexpr float RadioProgramGain = 1.995262315f;
}
