// Custom AudioStream object to build a LFO to integrate into the signal path.
#pragma once
#include <Arduino.h>
#include <AudioStream.h>

#include <stdio.h>
#include <string.h>

// Custom AudioStream object to build an LFO to integrate into the signal path.
//
// IMPORTANT: AudioStream requires function 'update()'. This object has no audio inputs;
// output 0 is the LFO. An invalid or missing table transmits silence.
class AudioLfo : public AudioStream
{
    private:
        const int16_t* current_table_ = nullptr; // Pointer to the current wavetable, initially set to nullptr.
        uint32_t phase_acc_ = 0;
        uint32_t phase_inc_ = 0;

        int16_t amplitude_ = INT16_MAX;
        uint32_t table_mask_ = 0;
        uint8_t shift_bits_ = 0;

        static constexpr float lfoMinHz = 0.001f;
        static constexpr float lfoMaxHz = 100.0f;

    public:
        // Construct a custom AudioStream object with no audio inputs
        AudioLfo() : AudioStream(0, NULL) {}

        // Set the LFO frequency in Hertz.
        //
        // Converts freq_hz into a 32-bit phase increment:
        // phase_inc_ = (freq_hz * 2^32) / AUDIO_SAMPLE_RATE_EXACT (~44117.647 Hz).
        //
        // Args:
        // freq_hz (float): Target rate; clamped to [lfoMinHz, lfoMaxHz].
        void SetFrequency(float freq_hz) {
            freq_hz = constrain(freq_hz, lfoMinHz, lfoMaxHz);
            phase_inc_ = static_cast<uint32_t>(
                (static_cast<double>(freq_hz) * 4294967296.0) / AUDIO_SAMPLE_RATE_EXACT);
            // Personal Notes: 
            // Exact hardware sample rate: AUDIO_SAMPLE_RATE_EXACT (~44117.647 Hz)
            // Formula: phase_inc_ = (freq_hz * 2^32) / AUDIO_SAMPLE_RATE_EXACT
            // 32-bit fixed point: 2^32 = 4294967296
        }

        // Set the LFO output amplitude.
        //
        // Args:
        // amp (float): Linear amplitude in [0, 1]; stored as Q15 int16.
        void SetAmplitude(float amp) {
            amp = constrain(amp, 0.0f, 1.0f);
            amplitude_ = static_cast<int16_t>(amp * 32767.0f);
        }

        // Load a power-of-two wavetable and arm the phase-to-index shift.
        //
        // A null pointer or size that is not a power of two (>= 2) clears the
        // table so update() outputs silence. shift_bits_ is set to 0 first so
        // a concurrent update() cannot index a half-installed table.
        //
        // Args:
        // table_ptr (const int16_t*): int16 samples; must remain valid while in use.
        // size_power_of_two (uint32_t): Table length (power of two, at least 2).
        void SetWaveformTable(const int16_t* table_ptr, uint32_t size_power_of_two) {
            bool size_ok = (size_power_of_two >= 2) && ((size_power_of_two & (size_power_of_two - 1)) == 0);
            if (!table_ptr || !size_ok) {
                shift_bits_ = 0; // update() defused if table_ptr or size_ok are invalid
                current_table_ = nullptr;
                table_mask_ = 0;
                return;
            }
            shift_bits_ = 0; // update() defused initially even if table_ptr and size_ok are valid (to avoid undefined behavior)
            current_table_ = table_ptr; // Then first set the pointer to the new table
            table_mask_ = size_power_of_two - 1;
            // 32 - ctz(size) = bits to shift phase_acc_ down to a table index.
            shift_bits_ = static_cast<uint8_t>(32 - __builtin_ctz(size_power_of_two)); // update() sharp 
            // Notes: 
            // __builtin_ctz - count trailing zeros
        }

        // Render one audio block of interpolated LFO samples.
        //
        // IMPRORTANT: Required function of every AudioStream object
        // INFO: Called by the Teensy Audio Library every 128 samples(~ every 2.9 ms).
        virtual void update(void) override {
            audio_block_t *block = allocate(); // Allocate a block of audio (memory is allocated)
            if (!block) return; 
        
            // If no wavetable is loaded or shift_bits_ is invalid, transmit silence
            // Reason: If shift_bits_ is > 31, it should not be executed, as we use uint32_t and it would cause undefined behaviour
            if (!current_table_ || shift_bits_ == 0 || shift_bits_ > 31) {
                memset(block->data, 0, sizeof(block->data)); // Clear memory of the block -> Set all bytes to 0 
                transmit(block, 0); // Transmit the block of audio -> Silence
                release(block); // Release the block of audio (memory is freed)
                return;
            }
        
            // Process audio block of 128 samples
            // Interpolate between 2 wavetable samples (idx_a and idx_b)
            for (int i = 0; i < AUDIO_BLOCK_SAMPLES; ++i) {
                uint32_t idx_a = (phase_acc_ >> shift_bits_) & table_mask_;
                uint32_t idx_b = (idx_a + 1) & table_mask_;

                // Fractional part for linear interpolation (Q15).
                uint32_t frac_mask = (1UL << shift_bits_) - 1; 
                uint32_t frac_bits = phase_acc_ & frac_mask; // Get the fractional part of the phase accumulator
                // When left and right shift are used?
                // - Left shift: If shift_bits_ is greater than 15, we need to shift the fractional part to the left to avoid overflow
                // - Right shift: If shift_bits_ is less than 15, we need to shift the fractional part to the right to avoid overflow
                uint32_t frac_val = (shift_bits_ >= 15) ? (frac_bits >> (shift_bits_ - 15)) : (frac_bits << (15 - shift_bits_));
                int32_t frac = static_cast<int32_t>(frac_val);
                int32_t val_a = current_table_[idx_a];
                int32_t val_b = current_table_[idx_b];
                int32_t interpolated = val_a + (((val_b - val_a) * frac) >> 15);
                block->data[i] = static_cast<int16_t>((interpolated * amplitude_) >> 15);
                phase_acc_ += phase_inc_;
            }

            transmit(block, 0); // Transmit the block of audio
            release(block); // Release the block of audio (memory is freed)
        }
};
