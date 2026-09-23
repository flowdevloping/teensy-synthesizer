// Custom AudioStream object to build a wavetable oscillator.
#pragma once
#include <Arduino.h>
#include <AudioStream.h>

// AudioStream wavetable oscillator with frame morphing.
//
// IMPORTANT: AudioStream requires update(). This object has no audio inputs;
// output 0 is the oscillator. Without a loaded table, update() produces no output.
class AudioWavetable : public AudioStream
{
    private: 
        const int16_t* current_table_ = nullptr; // Pointer to the current wavetable, initially set to nullptr.
        uint32_t morph_position_ = 0;
        uint16_t num_waveforms_ = 64;
        const uint16_t waveform_size_ = 2048;  // Serum 2: 2048 samples per frame
        uint32_t phase_inc_ = 0;
        uint32_t phase_acc_ = 0;

    public:
        // Construct a custom AudioStream object with no audio inputs.
        AudioWavetable() : AudioStream(0, NULL) {}

        // Set the playback frequency of the wavetable oscillator.
        //
        // Converts freq_hz into a 32-bit phase increment using
        // AUDIO_SAMPLE_RATE_EXACT (~44117.647 Hz). Values below 0.001 Hz
        // are raised to 0.001 Hz so the phase accumulator always advances.
        //
        // Args:
        // freq_hz (float): Target frequency in Hertz.
        void SetFrequency(float freq_hz) {
            if (freq_hz < 0.001f) freq_hz = 0.001f;
            phase_inc_ = static_cast<uint32_t>((static_cast<double>(freq_hz) * 4294967296.0) / AUDIO_SAMPLE_RATE_EXACT);
            // Personal Notes: 
            // Exact hardware sample rate: AUDIO_SAMPLE_RATE_EXACT (~44117.647 Hz)
            // Formula: phase_inc_ = (freq_hz * 2^32) / AUDIO_SAMPLE_RATE_EXACT
            // 32-bit fixed point: 2^32 = 4294967296
        }

        // Set the morph position between adjacent wavetable frames.
        //
        // Stores a 16.16 fixed-point index: upper 16 bits = frame A, lower 16
        // bits = fraction toward frame B. Example with 64 frames:
        // morph = 1.0 -> frame 63, fraction 0; morph = 0.5 -> frame 31, 50% to 32.
        //
        // Args:
        // morph (float): Position in [0, 1] across the loaded frames.
        void SetMorph(float morph) {
            morph = constrain(morph, 0.0f, 1.0f);
            morph_position_ = static_cast<uint32_t>(morph * (num_waveforms_ - 1) * 65536.0f);
            // Example with 64 waveforms: 
            // morph = 1.0 → 63 * 65536 = 4128768 → >> 16 = 63, Fraction = 0
            // morph = 0.5 → 31.5 * 65536 → Waveform 31, Fraction = 32768 (so 50 % towards Waveform 32)
        }

        // Load a concatenated wavetable and clamp morph to the new frame count.
        //
        // WARNING: table_ptr is not copied; it must stay valid while this object
        // is rendering. A smaller table must not keep a morph index past the last frame.
        //
        // Args:
        // table_ptr (const int16_t*): waveforms * 2048 int16 samples.
        // waveforms (uint16_t): Number of waveforms; treated as at least 1.
        void LoadTable(const int16_t* table_ptr, uint16_t waveforms) {
            current_table_ = table_ptr;
            num_waveforms_ = (waveforms < 1) ? 1 : waveforms; // Clamp to prevent division by zero in other functions
            uint32_t max_morph = static_cast<uint32_t>(num_waveforms_ - 1) * 65536u;
            if (morph_position_ > max_morph) morph_position_ = max_morph;
        }

        // Render one audio block of bilinear-interpolated wavetable samples.
        //
        // IMPRORTANT: Required function of every AudioStream object
        // INFO: Called by the Teensy Audio Library every 128 samples (~2.9 ms).
        virtual void update(void) override {
            if (!current_table_) return;

            audio_block_t *block = allocate();
            if (!block) return;

            uint16_t waveform_a_idx = morph_position_ >> 16;
            uint16_t waveform_b_idx = (waveform_a_idx + 1 < num_waveforms_) ? waveform_a_idx + 1 : waveform_a_idx;

            uint32_t morph_frac = morph_position_ & 0xFFFF;

            const int16_t* waveform_a = &current_table_[waveform_a_idx * waveform_size_];
            const int16_t* waveform_b = &current_table_[waveform_b_idx * waveform_size_];

            for (int i = 0; i < AUDIO_BLOCK_SAMPLES; ++i) {
                uint32_t index = phase_acc_ >> (32 - 11);  // 2048 samples -> 11 bits
                uint32_t next_index = (index + 1) & (waveform_size_ - 1);
                uint32_t sample_frac = (phase_acc_ << 11) >> 16;

                int32_t frac = static_cast<int32_t>(sample_frac);
                int32_t morph = static_cast<int32_t>(morph_frac);

                int32_t sample_a = ((static_cast<int32_t>(waveform_a[index]) * (65536 - frac)) +
                            (static_cast<int32_t>(waveform_a[next_index]) * frac)) >> 16;
                int32_t sample_b = ((static_cast<int32_t>(waveform_b[index]) * (65536 - frac)) +
                            (static_cast<int32_t>(waveform_b[next_index]) * frac)) >> 16;
                int32_t out_sample = ((sample_a * (65536 - morph)) + (sample_b * morph)) >> 16;

                block->data[i] = static_cast<int16_t>(out_sample);
                phase_acc_ += phase_inc_;
            }

            transmit(block, 0);
            release(block);
        }
};
