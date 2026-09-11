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
        const int16_t* currentTable = nullptr; // Pointer to the current wavetable, initially set to nullptr.

        uint32_t phaseAcc = 0; // Phase accumulator for the LFO, initially set to zero.
        uint32_t phaseInc = 0; // Phase increment for the LFO, initially set to zero.

        int16_t amplitude = INT16_MAX; // Amplitude for the LFO, initially set to max value (= 32767 for int16).
        uint32_t tableMask = 0; // Mask for the wavetable, initially set to zero.
        uint8_t shiftBits = 0; // Shift bits for the wavetable, initially set to zero.

        // LFO specific Parameters
        // static - variable is available for whole class
        // constexpr - variable is a const and is known already at compile time
        static constexpr float LfoMinHz = 0.001f;
        static constexpr float LfoMaxHz = 100.0f; 

    public: 
        // Constructor
        // AudioStream(nr_of_inputs, inputQueueArray)
        // inputQueueArray: Array of audio block pointers used for the inputs. 0 if no inputs are necessary.
        AudioLfo() : AudioStream(0, NULL) {}

        // Set the frequency of the LFO
        void setFrequency(float freqHz) {
            freqHz = constrain(freqHz, LfoMinHz, LfoMaxHz);
            phaseInc = static_cast<uint32_t>(
                (static_cast<double>(freqHz) * 4294967296.0) / AUDIO_SAMPLE_RATE_EXACT);
            // Notes: 
            // Exact hardware sample rate: AUDIO_SAMPLE_RATE_EXACT (~44117.647 Hz)
            // Formula: phaseInc = (freqHz * 2^32) / AUDIO_SAMPLE_RATE_EXACT
            // 32-bit fixed point: 2^32 = 4294967296
        }

        // Set the amplitude of the LFO
        void setAmplitude(float amp) {
            amp = constrain(amp, 0.0f, 1.0f);
            amplitude = static_cast<int16_t>(amp * 32767.0f); // Cut off the decimal part through converting to int16_t.
        }

        // Load the waveform of LFO. sizePowerOfTwo must be a power of two and at least 2.
        void setWaveformTable(const int16_t* tablePtr, uint32_t sizePowerOfTwo) {
            bool sizeOk = (sizePowerOfTwo >= 2) && ((sizePowerOfTwo & (sizePowerOfTwo - 1)) == 0);
            if (!tablePtr || !sizeOk) {
                shiftBits = 0; // update() defused
                currentTable = nullptr;
                tableMask = 0;
                return;
            }
            shiftBits = 0; // update() defused 
            currentTable = tablePtr;
            tableMask = sizePowerOfTwo - 1;
            shiftBits = static_cast<uint8_t>(32 - __builtin_ctz(sizePowerOfTwo)); // update() sharp
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
            // Reason: If shiftBits is > 31, it should not be executed, as we use uint32_t and it would cause undefined behaviour
            if (!currentTable || shiftBits == 0 || shiftBits > 31) {
                // Clear memory of the block -> Set all bytes to 0
                memset(block->data, 0, sizeof(block->data));
                // Transmit the block of audio
                transmit(block, 0);
                // Release the block of audio
                release(block);
                return;
            }
        
            // Process block of 128 samples
            // Interpolate between 2 wavetable samples (idxA and idxB)
            for (int i = 0; i < AUDIO_BLOCK_SAMPLES; ++i) {
                uint32_t idxA = (phaseAcc >> shiftBits) & tableMask;
                uint32_t idxB = (idxA + 1) & tableMask;
        
                // Fractional part for linear interpolation (Q15)
                uint32_t fracMask = (1UL << shiftBits) - 1;
                // Get the fractional part of the phase accumulator
                uint32_t fracBits = phaseAcc & fracMask;
                // Calculate the fractional part of the sample
                uint32_t fracVal = (shiftBits >= 15)
                    ? (fracBits >> (shiftBits - 15))
                    : (fracBits << (15 - shiftBits));
        
                int32_t frac = static_cast<int32_t>(fracVal);
        
                int32_t valA = currentTable[idxA];
                int32_t valB = currentTable[idxB];
        
                int32_t interpolated = valA + (((valB - valA) * frac) >> 15);
        
                block->data[i] = static_cast<int16_t>((interpolated * amplitude) >> 15);
                phaseAcc += phaseInc;
            }
            
            // Transmit the block of audio
            transmit(block, 0);
        
            // Release the block of audio
            release(block);
        }
};
