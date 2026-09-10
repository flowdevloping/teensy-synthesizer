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

        uint32_t morphPosition = 0; // Morphing between wavetable frames, initially set to zero.
        uint16_t numFrames = 64; // Number of frames per table
        const uint16_t frameSize = 2048; // Serum 2 uses 2048 samples per single-cycle frame

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
    
        // Set the morphing between the wavetable frames
        void setMorph(float morph) {
            morph = constrain(morph, 0.0f, 1.0f);
            // Before: morphPosition = (uint32_t)(morph * (numFrames - 1) * 65536.0f);
            morphPosition = static_cast<uint32_t>(morph * (numFrames - 1) * 65536.0f);
            // Example with 64 frames: 
            //  morph = 1.0 → 63 * 65536 = 4128768 → >> 16 = 63, Fraction = 0
            // morph = 0.5 → 31.5 * 65536 → Frame 31, Fraction 32768 (also 50 % Richtung Frame 32)
        }
    
        // Load the wavetable
        void loadTable(const int16_t* tablePtr, uint16_t frames) {
            currentTable = tablePtr;
            numFrames = (frames < 1) ? 1 : frames;
            // A table with fewer frames must not be indexed with the old morph position
            //Before: uint32_t maxMorph = (uint32_t)(numFrames - 1) * 65536u; // Getting the morph value of exactly the last frame
            uint32_t maxMorph = static_cast<uint32_t>(numFrames - 1) * 65536u;
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
    
            // Get the index of the current frame and the next frame
            uint16_t frameA_idx = morphPosition >> 16; // Indexing of the upper 16 bit, equal to division through 2^16 (65536)
            uint16_t frameB_idx = (frameA_idx + 1 < numFrames) ? frameA_idx + 1 : frameA_idx;

            // Get the fractional morph
            uint32_t morphFrac = morphPosition & 0xFFFF; // Indexing of bottom 16 bit
    
            // Get the current frame and the next frame
            const int16_t* frameA = &currentTable[frameA_idx * frameSize];
            const int16_t* frameB = &currentTable[frameB_idx * frameSize];
    
            // Interpolate between current and next wavetable sample
            for (int i = 0; i < AUDIO_BLOCK_SAMPLES; ++i) {
                uint32_t index = phaseAcc >> (32 - 11); // 2048 samples -> 11 bits
                uint32_t nextIndex = (index + 1) & (frameSize - 1);
                uint32_t sampleFrac = (phaseAcc << 11) >> 16; // Inter-sample fraction
    
                // Bilinear interpolation: Sample interpolation within frame + frame morphing
                int32_t frac = static_cast<int32_t>(sampleFrac);
                int32_t morph = static_cast<int32_t>(morphFrac);

                int32_t sA = ((static_cast<int32_t>(frameA[index]) * (65536 - frac)) +
                            (static_cast<int32_t>(frameA[nextIndex]) * frac)) >> 16;
                int32_t sB = ((static_cast<int32_t>(frameB[index]) * (65536 - frac)) +
                            (static_cast<int32_t>(frameB[nextIndex]) * frac)) >> 16;
                int32_t outSample = ((sA * (65536 - morph)) + (sB * morph)) >> 16;
    
                block->data[i] = static_cast<int16_t>(outSample);
                phaseAcc += phaseInc;
            }
            
            // Transmit the block of audio
            transmit(block, 0);

            // Release the block of audio
            release(block);
        }
};