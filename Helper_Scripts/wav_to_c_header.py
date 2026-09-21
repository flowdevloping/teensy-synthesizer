"""Convert a .wav file to a .h C header file that can be used in the Teensy Synth firmware.

Resamples the audio to 2048 samples per waveform and normalizes the audio to 16-bit integer values.
Writes the audio data to a header file that can be used on the Teensy.
"""

from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import resample

wav_path = (
    Path(__file__).resolve().parents[1]
    / "wavetables"
    / "Free_Wavetables-2048-44_1khz-32bit"
    / "Additive_Synth"
    / "Add_Synth1.wav"
)
out_path = (
    Path(__file__).resolve().parents[1]
    / "firmware"
    / "teensy_synth"
    / "CustomWavetable.h"
)

# 1. Read in the .wav file
rate, data = wavfile.read(wav_path)
if data.ndim > 1:  # If the audio data is stereo, take only the left channel
    data = data[:, 0]  # [:, 0] means all rows, but only the first column

# Define the waveform size
waveform_size = 2048

# Get the length of the audio data
input_wavetable_length = len(data)

# 2. Normalize data to float range of [-1.0, 1.0]
# Reason: Resampling with big int16 values (up to 32767) can cause overflows and clipping, which can cause distortion and artifacts.
# Therefore: Convert to float first. Using values between -1.0 and 1.0 for resampling-operations.
if np.issubdtype(data.dtype, np.integer):
    # Convert int16/int32 to float by dividing by max possible value
    max_int = np.iinfo(data.dtype).max
    data = data.astype(np.float32) / max_int
    # Notes:
    # 32767/32768 = 1.0
    # 16384/32767 = 0.5
    # 0/32767 = 0.0
    # -16384/32767 = -0.5
    # -32767/ 32768 = -1.0

# Else: Convert float to float32
else:
    data = data.astype(np.float32)

# 3. Check sample length and resample if necessary to make it dividable by waveform_size
if input_wavetable_length % waveform_size != 0:
    n_waveforms_of_input = max(1, round(input_wavetable_length / waveform_size))
    target_wavetable_lenght = n_waveforms_of_input * waveform_size

    print(
        f"Input wavetable length {input_wavetable_length} is not dividable by {waveform_size}. Resampling..."
    )
    data = resample(data, target_wavetable_lenght)

# 4. Safe hardware conversion for Teensy I2S DAC (16-Bit Integer)
# Reason: Resampling with FFT can cause small overshoots at the edges of audio signals (Gibbs-phenomenon)
# Example: 32769 would cause an overflow to -32768
# Therefore: Clip the values to the range of -32767 to 32767.
samples = np.clip(np.round(data * 32767.0), -32767, 32767).astype(np.int16)

# 5. Limit the number of waveforms to 64 for performance reasons (Teensy 4.1 has limited RAM)
n_waveforms = min(len(samples) // waveform_size, 64)
#  Cut the samples from first waveform to the waveform at position n_waveforms * waveform_size
samples = samples[: n_waveforms * waveform_size]

# 6. Write the samples to a .h file
with out_path.open("w", encoding="utf-8") as f:
    f.write("#pragma once\n#include <Arduino.h>\n\n")
    # Important: Using const to force ARM-Compiler on Teensy to keep the values in Flash memory instead of SRAM.
    # -> Could cause Out-of-Memory crash on Teensy 4.1
    f.write(f"const uint16_t WAVEFORM_SIZE = {waveform_size};\n")
    f.write(f"const uint16_t N_WAVEFORMS = {n_waveforms};\n\n")
    f.write("const int16_t customWavetable[N_WAVEFORMS * WAVEFORM_SIZE] = {\n")
    for i, s in enumerate(samples):
        f.write(f"{int(s)},")
        if i % 16 == 15:
            f.write("\n")
    f.write("};\n")

print(f"Wrote to file: {out_path} ({n_waveforms} Frames)")
