# This file converts a .wav file to a .h C header file that can be used in the Teensy Synth firmware.
# It resamples the audio to 2048 samples per frame and normalizes the audio to 16-bit integer values.
# It then writes the audio data to a header file that can be included in the firmware.

# Import of Libaries
from pathlib import Path
import numpy as np
from scipy.io import wavfile
from scipy.signal import resample # Added

# Define input and output paths
wav_path = Path(__file__).resolve().parents[1] / "wavetables" / "SAMPLES" / "PATCH_3" / "Patch_3_5.wav"
out_path = Path(__file__).resolve().parents[1] / "firmware" / "teensy_synth" / "custom_wavetable.h" 

# 1. Read in the .wav file
rate, data = wavfile.read(wav_path)
if data.ndim > 1: # If the audio data is stereo, take only the left channel
    data = data[:, 0] # [:, 0] means all rows, but only the first column

# Define the frame size
frame_res = 2048

# Get the length of the audio data
sample_len = len(data) 

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

# 3. Check sample length and resample if necessary to make it dividable by frame_res
if sample_len % frame_res != 0: 
    sample_dividor = max(1, round(sample_len / frame_res))
    target_sample_len = sample_dividor * frame_res

    print(f"Sample length {sample_len} is not dividable by {frame_res}. Resampling...")
    data = resample(data, target_sample_len)

# 4. Safe hardware conversion for Teensy I2S DAC (16-Bit Integer)
# Reason: Resampling with FFT can cause small overshoots at the edges of audio signals (Gibbs-phenomenon)
# Example: 32769 would cause an overflow to -32768 
# Therefore: Clip the values to the range of -32767 to 32767.
samples = np.clip(np.round(data * 32767.0), -32767, 32767).astype(np.int16)

# 5. Limit the number of frames to 64 for performance reasons (Teensy 4.1 has limited RAM)
nframes = min(len(samples) // frame_res, 64) #   
#  Cut the samples from first frame to the frame at position nframes * frame_res
samples = samples[: nframes * frame_res] 

# 6. Write the samples to a .h file
with out_path.open("w", encoding="utf-8") as f:
    f.write("#pragma once\n#include <Arduino.h>\n\n")
    # Important: Using const to force ARM-Compiler on Teensy to keep the values in Flash memory instead of SRAM.
    # -> Could cause Out-of-Memory crash on Teensy 4.1
    f.write(f"const uint16_t FRAME_SIZE = {frame_res};\n")
    f.write(f"const uint16_t NUM_FRAMES = {nframes};\n\n")
    f.write("const int16_t customWavetable[NUM_FRAMES * FRAME_SIZE] = {\n")
    for i, s in enumerate(samples):
        f.write(f"{int(s)},")
        if i % 16 == 15:
            f.write("\n")
    f.write("};\n")

print(f"Wrote to file: {out_path} ({nframes} Frames)")