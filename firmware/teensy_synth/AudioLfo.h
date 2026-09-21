#pragma once
#include <Arduino.h>
#include <AudioStream.h>

// Required things of AudioStream.h objects: 
// update(): function
// inputQueueArray[]: private variable - size must match the number of inputs

// Class of LFO element for complex shapes (not just sine, saw, etc.)
class AudioLfo : public AudioStream
{
    private: 
        const int16_t* current_table_ = nullptr; // Pointer to the current wavetable, initially set to nullptr.

        uint32_t phase_acc_ = 0; // Phase accumulator for the LFO, initially set to zero.
        uint32_t phase_inc_ = 0; // Phase increment for the LFO, initially set to zero.

        int16_t amplitude_ = INT16_MAX; // Amplitude for the LFO, initially set to max value (= 32767 for int16).
        uint32_t table_mask_ = 0; // Mask for the wavetable, initially set to zero.
        uint8_t shift_bits_ = 0; // Shift bits for the wavetable, initially set to zero.

        // LFO specific Parameters
        // static - variable is available for whole class
        // constexpr - variable is a const and is known already at compile time
        static constexpr float lfoMinHz = 0.001f;
        static constexpr float lfoMaxHz = 100.0f; 

    public: 
        // Constructor
        // AudioStream(nr_of_inputs, inputQueueArray)
        // inputQueueArray: Array of audio block pointers used for the inputs. 0 if no inputs are necessary.
        AudioLfo() : AudioStream(0, NULL) {}

        // Set the frequency of the LFO
        void SetFrequency(float freq_hz) {
            freq_hz = constrain(freq_hz, lfoMinHz, lfoMaxHz);
            phase_inc_ = static_cast<uint32_t>(
                (static_cast<double>(freq_hz) * 4294967296.0) / AUDIO_SAMPLE_RATE_EXACT);
            // Notes: 
            // Exact hardware sample rate: AUDIO_SAMPLE_RATE_EXACT (~44117.647 Hz)
            // Formula: phase_inc_ = (freq_hz * 2^32) / AUDIO_SAMPLE_RATE_EXACT
            // 32-bit fixed point: 2^32 = 4294967296
        }

        // Set the amplitude of the LFO
        void SetAmplitude(float amp) {
            amp = constrain(amp, 0.0f, 1.0f);
            amplitude_ = static_cast<int16_t>(amp * 32767.0f); // Cut off the decimal part through converting to int16_t.
        }

        // Load the waveform of LFO. size_power_of_two must be a power of two and at least 2.
        void SetWaveformTable(const int16_t* table_ptr, uint32_t size_power_of_two) {
            bool size_ok = (size_power_of_two >= 2) && ((size_power_of_two & (size_power_of_two - 1)) == 0);
            if (!table_ptr || !size_ok) {
                shift_bits_ = 0; // update() defused
                current_table_ = nullptr;
                table_mask_ = 0;
                return;
            }
            shift_bits_ = 0; // update() defused 
            current_table_ = table_ptr;
            table_mask_ = size_power_of_two - 1;
            shift_bits_ = static_cast<uint8_t>(32 - __builtin_ctz(size_power_of_two)); // update() sharp
            // Notes: 
            // ctz - count trailing zeros
        }
    
        // Updates the audio object
        // Notes:
        // Function 'update()' is required by AudioStream.h objects -> otherwise compiler error !  
        // The library will call the 'update()' function every 128 samples (approx. every 2.9 ms)
        virtual void update(void) override {
            // Allocate a block of audio
            audio_block_t *block = allocate();
        
            // If no block is allocated, return
            if (!block) return;
        
            // If no wavetable is loaded or the shift bits are not valid, transmit silence
            // Reason: If shift_bits_ is > 31, it should not be executed, as we use uint32_t and it would cause undefined behaviour
            if (!current_table_ || shift_bits_ == 0 || shift_bits_ > 31) {
                // Clear memory of the block -> Set all bytes to 0
                memset(block->data, 0, sizeof(block->data));
                // Transmit the block of audio
                transmit(block, 0);
                // Release the block of audio
                release(block);
                return;
            }
        
            // Process block of 128 samples
            // Interpolate between 2 wavetable samples (idx_a and idx_b)
            for (int i = 0; i < AUDIO_BLOCK_SAMPLES; ++i) {
                uint32_t idx_a = (phase_acc_ >> shift_bits_) & table_mask_;
                uint32_t idx_b = (idx_a + 1) & table_mask_;
        
                // Fractional part for linear interpolation (Q15)
                uint32_t frac_mask = (1UL << shift_bits_) - 1;
                // Get the fractional part of the phase accumulator
                uint32_t frac_bits = phase_acc_ & frac_mask;
                // Calculate the fractional part of the sample
                uint32_t frac_val = (shift_bits_ >= 15)
                    ? (frac_bits >> (shift_bits_ - 15))
                    : (frac_bits << (15 - shift_bits_));
        
                int32_t frac = static_cast<int32_t>(frac_val);
        
                int32_t val_a = current_table_[idx_a];
                int32_t val_b = current_table_[idx_b];
        
                int32_t interpolated = val_a + (((val_b - val_a) * frac) >> 15);
        
                block->data[i] = static_cast<int16_t>((interpolated * amplitude_) >> 15);
                phase_acc_ += phase_inc_;
            }
            
            // Transmit the block of audio
            transmit(block, 0);
        
            // Release the block of audio
            release(block);
        }
};
