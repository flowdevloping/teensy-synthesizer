from pathlib import Path
import numpy as np
from scipy.io import wavfile

wav_path = Path(r".\wavetables\Hyper_06.wav")  # anpassen
out_path = Path(__file__).resolve().parents[1] / "firmware" / "serum_synth" / "serum_table.h"

rate, data = wavfile.read(wav_path)
if data.ndim > 1:
    data = data[:, 0]

if np.issubdtype(data.dtype, np.floating):
    samples = (np.clip(data, -1.0, 1.0) * 32767.0).astype(np.int16)
else:
    samples = data.astype(np.int16)

frame = 2048
assert len(samples) % frame == 0, f"Länge {len(samples)} nicht durch 2048 teilbar"
nframes = min(len(samples) // frame, 64)  # 64 reicht für den Test
samples = samples[: nframes * frame]

with out_path.open("w", encoding="utf-8") as f:
    f.write("#pragma once\n#include <Arduino.h>\n\n")
    f.write(f"const uint16_t SERUM_FRAME_SIZE = {frame};\n")
    f.write(f"const uint16_t SERUM_NUM_FRAMES = {nframes};\n\n")
    f.write("const int16_t serumTable[SERUM_NUM_FRAMES * SERUM_FRAME_SIZE] = {\n")
    for i, s in enumerate(samples):
        f.write(f"{int(s)},")
        if i % 16 == 15:
            f.write("\n")
    f.write("};\n")

print(f"geschrieben: {out_path}  ({nframes} Frames)")