#pragma once
#include <Arduino.h>
#include <AudioStream.h>

// Required things of AudioStream.h objects: 
// update(): function
// inputQueueArray[]: private variable - size must match the number of inputs

// Class of Custom Wavetable Synthesizer 
class AudioSynthSerumWavetable : public AudioStream
{
    private: 
        const int16_t* current_table_ = nullptr; // Pointer to the current wavetable, initially set to nullptr.

        uint32_t phase_acc_ = 0; // Phase accumulator for the wavetable, initially set to zero.
        uint32_t phase_inc_ = 0; // Phase increment for the wavetable, initially set to zero.

        uint32_t morph_position_ = 0; // Morphing between wavetable waveforms, initially set to zero.
        uint16_t num_waveforms_ = 64; // Number of waveforms per table
        const uint16_t waveform_size_ = 2048; // Serum 2 uses 2048 samples per single-cycle waveform

    public: 
        // Constructor
        // AudioStream(nr_of_inputs, inputQueueArray)
        // inputQueueArray: Array of audio block pointers used for the inputs. NULL means no inputs.
        AudioSynthSerumWavetable() : AudioStream(0, NULL) {}

        // Set the frequency of the synth
        void SetFrequency(float freq_hz) {
            if (freq_hz < 0.001f) freq_hz = 0.001f; // Prevent frequency = 0 Hz
            // Exact hardware sample rate: AUDIO_SAMPLE_RATE_EXACT (~44117.647 Hz)
            // 32-bit fixed point: 2^32 = 4294967296
            phase_inc_ = static_cast<uint32_t>((static_cast<double>(freq_hz) * 4294967296.0) / AUDIO_SAMPLE_RATE_EXACT);
        }
    
        // Set the morphing between the wavetable waveforms
        void SetMorph(float morph) {
            morph = constrain(morph, 0.0f, 1.0f);
            morph_position_ = static_cast<uint32_t>(morph * (num_waveforms_ - 1) * 65536.0f);
            // Example with 64 waveforms: 
            //  morph = 1.0 → 63 * 65536 = 4128768 → >> 16 = 63, Fraction = 0
            // morph = 0.5 → 31.5 * 65536 → Waveform 31, Fraction 32768 (also 50 % Richtung Waveform 32)
        }
    
        // Load the wavetable
        void LoadTable(const int16_t* table_ptr, uint16_t waveforms) {
            current_table_ = table_ptr;
            num_waveforms_ = (waveforms < 1) ? 1 : waveforms;
            // A table with fewer waveforms must not be indexed with the old morph position
            //Before: uint32_t max_morph = (uint32_t)(num_waveforms_ - 1) * 65536u; // Getting the morph value of exactly the last waveform
            uint32_t max_morph = static_cast<uint32_t>(num_waveforms_ - 1) * 65536u;
            if (morph_position_ > max_morph) morph_position_ = max_morph;
        }
    
        // Updates the audio object
        // Notes:
        // Function 'update()' is required by AudioStream.h objects and therefore in the .h and .cpp files -> otherwise compiler error !  
        // The library will call the 'update()' function every 128 samples (approx. every2.9 ms)
        virtual void update(void) override {
            // If no wavetable is loaded, return
            if (!current_table_) return;
            
            // Allocate a block of audio
            audio_block_t *block = allocate();

            // If no block is allocated, return
            if (!block) return;
    
            // Get the index of the current waveform and the next waveform
            uint16_t waveform_a_idx = morph_position_ >> 16; // Indexing of the upper 16 bit, equal to division through 2^16 (65536)
            uint16_t waveform_b_idx = (waveform_a_idx + 1 < num_waveforms_) ? waveform_a_idx + 1 : waveform_a_idx;

            // Get the fractional morph
            uint32_t morph_frac = morph_position_ & 0xFFFF; // Indexing of bottom 16 bit
    
            // Get the current waveform and the next waveform
            const int16_t* waveform_a = &current_table_[waveform_a_idx * waveform_size_];
            const int16_t* waveform_b = &current_table_[waveform_b_idx * waveform_size_];
    
            // Interpolate between current and next wavetable sample
            for (int i = 0; i < AUDIO_BLOCK_SAMPLES; ++i) {
                uint32_t index = phase_acc_ >> (32 - 11); // 2048 samples -> 11 bits
                uint32_t next_index = (index + 1) & (waveform_size_ - 1);
                uint32_t sample_frac = (phase_acc_ << 11) >> 16; // Inter-sample fraction
    
                // Bilinear interpolation: Sample interpolation within waveform + waveform morphing
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
            
            // Transmit the block of audio
            transmit(block, 0);

            // Release the block of audio
            release(block);
        }
};
