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
        const int16_t* currentTable = nullptr; // Pointer to the current wavetable, initially set to nullptr.

        uint32_t phaseAcc = 0; // Phase accumulator for the wavetable, initially set to zero.
        uint32_t phaseInc = 0; // Phase increment for the wavetable, initially set to zero.

        uint32_t morphPosition = 0; // Morphing between wavetable waveforms, initially set to zero.
        uint16_t numWaveforms = 64; // Number of waveforms per table
        const uint16_t waveformSize = 2048; // Serum 2 uses 2048 samples per single-cycle waveform

    public: 
        // Constructor
        // AudioStream(nr_of_inputs, inputQueueArray)
        // inputQueueArray: Array of audio block pointers used for the inputs. NULL means no inputs.
        AudioSynthSerumWavetable() : AudioStream(0, NULL) {}

        // Set the frequency of the synth
        void setFrequency(float freqHz) {
            if (freqHz < 0.001f) freqHz = 0.001f; // Prevent frequency = 0 Hz
            // Exact hardware sample rate: AUDIO_SAMPLE_RATE_EXACT (~44117.647 Hz)
            // 32-bit fixed point: 2^32 = 4294967296
            phaseInc = static_cast<uint32_t>((static_cast<double>(freqHz) * 4294967296.0) / AUDIO_SAMPLE_RATE_EXACT);
        }
    
        // Set the morphing between the wavetable waveforms
        void setMorph(float morph) {
            morph = constrain(morph, 0.0f, 1.0f);
            morphPosition = static_cast<uint32_t>(morph * (numWaveforms - 1) * 65536.0f);
            // Example with 64 waveforms: 
            //  morph = 1.0 → 63 * 65536 = 4128768 → >> 16 = 63, Fraction = 0
            // morph = 0.5 → 31.5 * 65536 → Waveform 31, Fraction 32768 (also 50 % Richtung Waveform 32)
        }
    
        // Load the wavetable
        void loadTable(const int16_t* tablePtr, uint16_t waveforms) {
            currentTable = tablePtr;
            numWaveforms = (waveforms < 1) ? 1 : waveforms;
            // A table with fewer waveforms must not be indexed with the old morph position
            //Before: uint32_t maxMorph = (uint32_t)(numWaveforms - 1) * 65536u; // Getting the morph value of exactly the last waveform
            uint32_t maxMorph = static_cast<uint32_t>(numWaveforms - 1) * 65536u;
            if (morphPosition > maxMorph) morphPosition = maxMorph;
        }
    
        // Updates the audio object
        // Notes:
        // Function 'update()' is required by AudioStream.h objects and therefore in the .h and .cpp files -> otherwise compiler error !  
        // The library will call the 'update()' function every 128 samples (approx. every2.9 ms)
        virtual void update(void) override {
            // If no wavetable is loaded, return
            if (!currentTable) return;
            
            // Allocate a block of audio
            audio_block_t *block = allocate();

            // If no block is allocated, return
            if (!block) return;
    
            // Get the index of the current waveform and the next waveform
            uint16_t waveformA_idx = morphPosition >> 16; // Indexing of the upper 16 bit, equal to division through 2^16 (65536)
            uint16_t waveformB_idx = (waveformA_idx + 1 < numWaveforms) ? waveformA_idx + 1 : waveformA_idx;

            // Get the fractional morph
            uint32_t morphFrac = morphPosition & 0xFFFF; // Indexing of bottom 16 bit
    
            // Get the current waveform and the next waveform
            const int16_t* waveformA = &currentTable[waveformA_idx * waveformSize];
            const int16_t* waveformB = &currentTable[waveformB_idx * waveformSize];
    
            // Interpolate between current and next wavetable sample
            for (int i = 0; i < AUDIO_BLOCK_SAMPLES; ++i) {
                uint32_t index = phaseAcc >> (32 - 11); // 2048 samples -> 11 bits
                uint32_t nextIndex = (index + 1) & (waveformSize - 1);
                uint32_t sampleFrac = (phaseAcc << 11) >> 16; // Inter-sample fraction
    
                // Bilinear interpolation: Sample interpolation within waveform + waveform morphing
                int32_t frac = static_cast<int32_t>(sampleFrac);
                int32_t morph = static_cast<int32_t>(morphFrac);

                int32_t sample_A = ((static_cast<int32_t>(waveformA[index]) * (65536 - frac)) +
                            (static_cast<int32_t>(waveformA[nextIndex]) * frac)) >> 16;
                int32_t sample_B = ((static_cast<int32_t>(waveformB[index]) * (65536 - frac)) +
                            (static_cast<int32_t>(waveformB[nextIndex]) * frac)) >> 16;
                int32_t outSample = ((sample_A * (65536 - morph)) + (sample_B * morph)) >> 16;
    
                block->data[i] = static_cast<int16_t>(outSample);
                phaseAcc += phaseInc;
            }
            
            // Transmit the block of audio
            transmit(block, 0);

            // Release the block of audio
            release(block);
        }
};
