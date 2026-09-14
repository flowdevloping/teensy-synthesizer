/*
Polyphonic FM synthesizer for Teensy 4.x (8 voices)
Protocol v3: voiceId,carrierHz,modHz,volumePct,modDepthPct,carrierWave\n
  voiceId 0..7  = note on/update for that voice (carrierHz>0)
  voiceId 0..7  = note off for that voice (carrierHz==0)
  voiceId -1    = all notes off
  carrierWave   = 0 sine, 1 saw, 2 square, 3 triangle (applied to all voices)
Protocol v2 packets (5 fields, no carrierWave) keep the current carrier waveform.
Legacy 4-field packets (no voiceId) map to voice 0 and silence voices 1..7.
Audio graph:
  voices 0-3 -> voiceMixerA ─┐
  voices 4-7 -> voiceMixerB ─┴─> sumMixer -> volumeAmp -> I2S
*/

// Libraries
#include <Arduino.h>
#include <Audio.h>
#include <AudioStream.h>
#include <math.h>
#include <Wire.h>
#include <SPI.h>

// Include custom Classes
#include "AudioSynthSerumWavetable.h"
#include "AudioLfo.h"

// Custom Wavetable (audio source for the wavetable synth)
#include "CustomWavetable.h"

// Constants
const int NUM_VOICES = 8;

// Teensy Audio Library components
AudioSynthWaveformSine          modulator0, modulator1, modulator2, modulator3;
AudioSynthWaveformSine          modulator4, modulator5, modulator6, modulator7; 
AudioSynthWaveformModulated     carrier0, carrier1, carrier2, carrier3;
AudioSynthWaveformModulated     carrier4, carrier5, carrier6, carrier7;

// Add:
AudioSynthSerumWavetable        wavetable0, wavetable1, wavetable2, wavetable3; 
AudioSynthSerumWavetable        wavetable4, wavetable5, wavetable6, wavetable7;

// Add:
AudioMixer4                     sourceMixer0, sourceMixer1, sourceMixer2, sourceMixer3;
AudioMixer4                     sourceMixer4, sourceMixer5, sourceMixer6, sourceMixer7;

AudioEffectEnvelope             envelope0, envelope1, envelope2, envelope3;
AudioEffectEnvelope             envelope4, envelope5, envelope6, envelope7;
AudioMixer4                     voiceMixerA;  // voices 0-3
AudioMixer4                     voiceMixerB;  // voices 4-7
AudioMixer4                     sumMixer;     // A + B

// Add:
// Global LFO + filter: the LFO modulates the filter cutoff (global for all 8 voices)
AudioLfo                 lfo;           // LFO shape generator (no audio input)
AudioFilterStateVariable        globalFilter;  // State-variable filter (LFO wobble on cutoff)

AudioAmplifier                  volumeAmp;
AudioOutputI2S2                 i2s2_output;

// Audio connections
AudioConnection patch_Mod_Car_0(modulator0, 0, carrier0, 0);
AudioConnection patch_Mod_Car_1(modulator1, 0, carrier1, 0);
AudioConnection patch_Mod_Car_2(modulator2, 0, carrier2, 0);
AudioConnection patch_Mod_Car_3(modulator3, 0, carrier3, 0);
AudioConnection patch_Mod_Car_4(modulator4, 0, carrier4, 0);
AudioConnection patch_Mod_Car_5(modulator5, 0, carrier5, 0);
AudioConnection patch_Mod_Car_6(modulator6, 0, carrier6, 0);
AudioConnection patch_Mod_Car_7(modulator7, 0, carrier7, 0);

// Add:
AudioConnection patch_Car_SourceMixer_0(carrier0, 0, sourceMixer0, 0);
AudioConnection patch_Car_SourceMixer_1(carrier1, 0, sourceMixer1, 0);
AudioConnection patch_Car_SourceMixer_2(carrier2, 0, sourceMixer2, 0);
AudioConnection patch_Car_SourceMixer_3(carrier3, 0, sourceMixer3, 0);
AudioConnection patch_Car_SourceMixer_4(carrier4, 0, sourceMixer4, 0);
AudioConnection patch_Car_SourceMixer_5(carrier5, 0, sourceMixer5, 0);
AudioConnection patch_Car_SourceMixer_6(carrier6, 0, sourceMixer6, 0);
AudioConnection patch_Car_SourceMixer_7(carrier7, 0, sourceMixer7, 0);

/* Remove: 
AudioConnection patch_Car0(carrier0, 0, envelope0, 0);
AudioConnection patch_Car1(carrier1, 0, envelope1, 0);
AudioConnection patch_Car2(carrier2, 0, envelope2, 0);
AudioConnection patch_Car3(carrier3, 0, envelope3, 0);
AudioConnection patch_Car4(carrier4, 0, envelope4, 0);
AudioConnection patch_Car5(carrier5, 0, envelope5, 0);
AudioConnection patch_Car6(carrier6, 0, envelope6, 0);
AudioConnection patch_Car7(carrier7, 0, envelope7, 0);
*/

// Add: 
AudioConnection patch_Wav_SourceMixer_0(wavetable0, 0, sourceMixer0, 1);
AudioConnection patch_Wav_SourceMixer_1(wavetable1, 0, sourceMixer1, 1);
AudioConnection patch_Wav_SourceMixer_2(wavetable2, 0, sourceMixer2, 1);
AudioConnection patch_Wav_SourceMixer_3(wavetable3, 0, sourceMixer3, 1);
AudioConnection patch_Wav_SourceMixer_4(wavetable4, 0, sourceMixer4, 1);
AudioConnection patch_Wav_SourceMixer_5(wavetable5, 0, sourceMixer5, 1);
AudioConnection patch_Wav_SourceMixer_6(wavetable6, 0, sourceMixer6, 1);
AudioConnection patch_Wav_SourceMixer_7(wavetable7, 0, sourceMixer7, 1);

// Add: 
AudioConnection patch_SourceMixer_Env_0(sourceMixer0, 0, envelope0, 0);
AudioConnection patch_SourceMixer_Env_1(sourceMixer1, 0, envelope1, 0);
AudioConnection patch_SourceMixer_Env_2(sourceMixer2, 0, envelope2, 0);
AudioConnection patch_SourceMixer_Env_3(sourceMixer3, 0, envelope3, 0);
AudioConnection patch_SourceMixer_Env_4(sourceMixer4, 0, envelope4, 0);
AudioConnection patch_SourceMixer_Env_5(sourceMixer5, 0, envelope5, 0);
AudioConnection patch_SourceMixer_Env_6(sourceMixer6, 0, envelope6, 0);
AudioConnection patch_SourceMixer_Env_7(sourceMixer7, 0, envelope7, 0);

AudioConnection patch_Env_VoiceMixerA_0(envelope0, 0, voiceMixerA, 0);
AudioConnection patch_Env_VoiceMixerA_1(envelope1, 0, voiceMixerA, 1);
AudioConnection patch_Env_VoiceMixerA_2(envelope2, 0, voiceMixerA, 2);
AudioConnection patch_Env_VoiceMixerA_3(envelope3, 0, voiceMixerA, 3);
AudioConnection patch_Env_VoiceMixerB_0(envelope4, 0, voiceMixerB, 0);
AudioConnection patch_Env_VoiceMixerB_1(envelope5, 0, voiceMixerB, 1);
AudioConnection patch_Env_VoiceMixerB_2(envelope6, 0, voiceMixerB, 2);
AudioConnection patch_Env_VoiceMixerB_3(envelope7, 0, voiceMixerB, 3);

AudioConnection patch_VoiceMixerA_SumMixer(voiceMixerA, 0, sumMixer, 0);
AudioConnection patch_VoiceMixerB_SumMixer(voiceMixerB, 0, sumMixer, 1);

/* Remove:
AudioConnection patch_SumMixer_Amp(sumMixer, 0, volumeAmp, 0);
*/
// Add:
// Insert the global filter into the signal path and feed the LFO into its control input.
// AudioFilterStateVariable: input 0 = signal, input 1 = cutoff modulation;
//                           output 0 = lowpass, 1 = bandpass, 2 = highpass.
AudioConnection patch_SumMixer_Filter(sumMixer, 0, globalFilter, 0);
AudioConnection patch_Lfo_Filter(lfo, 0, globalFilter, 1);
AudioConnection patch_Filter_Amp(globalFilter, 0, volumeAmp, 0);  // output 0 = lowpass

AudioConnection patch_Amp_Out_0(volumeAmp, 0, i2s2_output, 0);
AudioConnection patch_Amp_Out_1(volumeAmp, 0, i2s2_output, 1);

// Modulators
AudioSynthWaveformSine* modulators[NUM_VOICES] = {
  &modulator0, &modulator1, &modulator2, &modulator3,
  &modulator4, &modulator5, &modulator6, &modulator7
};
// Carriers
AudioSynthWaveformModulated* carriers[NUM_VOICES] = {
  &carrier0, &carrier1, &carrier2, &carrier3,
  &carrier4, &carrier5, &carrier6, &carrier7
};

// Add:
// Wavetables
AudioSynthSerumWavetable* wavetables[NUM_VOICES] = {
  &wavetable0, &wavetable1, &wavetable2, &wavetable3,
  &wavetable4, &wavetable5, &wavetable6, &wavetable7
};
// SourceMixers
AudioMixer4* sourceMixers[NUM_VOICES] = {
  &sourceMixer0, &sourceMixer1, &sourceMixer2, &sourceMixer3,
  &sourceMixer4, &sourceMixer5, &sourceMixer6, &sourceMixer7
};

// Envelopes
AudioEffectEnvelope* envelopes[NUM_VOICES] = {
  &envelope0, &envelope1, &envelope2, &envelope3,
  &envelope4, &envelope5, &envelope6, &envelope7
};

// Parameters
const float MAX_CARRIER_HZ = 4000.0f; 
const float MAX_MODULATOR_HZ = 300.0f;
const float MAX_OUTPUT_AMPLITUDE = 1.0f; 
const float MAX_MOD_DEPTH = 1.0f; 
const float PURE_SINE_MOD_HZ_THRESHOLD = 1.0f; 

const float ENVELOPE_ATTACK_MS = 0.0f; 
const float ENVELOPE_RELEASE_MS = 150.0f; 
const float MODULATOR_FADE_MS = 50.0f; 

// Add:
// Global LFO + filter parameters
// LFO rate range matches LfoMinHz/LfoMaxHz inside AudioLfo.
const float LFO_MIN_RATE_HZ = 0.01f;
const float LFO_MAX_RATE_HZ = 100.0f;
const float LFO_DEFAULT_RATE_HZ = 2.0f;
const float LFO_DEFAULT_DEPTH = 0.0f;     // 0 = LFO off by default (no wobble)
// A full-scale LFO signal shifts the filter cutoff by this many octaves.
const float FILTER_CONTROL_OCTAVES = 2.0f;
const float FILTER_MIN_CUTOFF_HZ = 20.0f;
const float FILTER_MAX_CUTOFF_HZ = 12000.0f;
const float FILTER_DEFAULT_CUTOFF_HZ = 12000.0f;  // fully open by default
const float FILTER_MIN_Q = 0.7f;
const float FILTER_MAX_Q = 5.0f;
const float FILTER_DEFAULT_Q = 0.7f;
// RAM LFO cycle uploaded from the GUI (W,offset,count,...). Power of two for AudioLfo.
const uint16_t LFO_WAVETABLE_SIZE = 256;
const int LFO_TABLE_CHUNK_MAX = 32;
int16_t lfoBuf[2][LFO_WAVETABLE_SIZE];
volatile uint8_t lfoPlay = 0;

// Carrier waveform (shared by all voices)
// A full-scale modulation input shifts the carrier by this many octaves. One octave
// matches the fixed range of AudioSynthWaveformSineModulated, so the mod depth sent
// by the GUI keeps its meaning.
const float CARRIER_FM_OCTAVES = 1.0f;
const int CARRIER_WAVE_WAVETABLE = 4; 
int currentCarrierWaveId = 0;  
short currentCarrierWave = WAVEFORM_SINE; 

// Amplifier parameters
const int AMP_SD_PIN = 23; 
bool ampEnabled = false; 
unsigned long ampMuteAtMs = 0;  

const unsigned long AMP_BOOT_MUTE_MS = 200; 
const unsigned long AMP_ENABLE_SETTLE_MS = 50; 
const unsigned long AMP_MUTE_AFTER_RELEASE_MS = (unsigned long)ENVELOPE_RELEASE_MS + 20; 

bool voiceActive[NUM_VOICES] = {false, false, false, false, false, false, false, false}; 
unsigned long voiceReleaseUntilMs[NUM_VOICES] = {0, 0, 0, 0, 0, 0, 0, 0}; 

float targetModDepth[NUM_VOICES] = {0, 0, 0, 0, 0, 0, 0, 0}; 
bool modFadeActive[NUM_VOICES] = {false, false, false, false, false, false, false, false}; 
unsigned long modFadeStartMs[NUM_VOICES] = {0, 0, 0, 0, 0, 0, 0, 0}; 
 
float clampValue(float value, float maxValue) {
  if (value < 0.0f) return 0.0f;
  if (value > maxValue) return maxValue;
  return value;
}

// Maps a protocol waveform ID to a waveform of the Teensy Audio Library
short carrierWaveformFromId(int waveId) {
  switch (waveId) {
    case 1:  return WAVEFORM_SAWTOOTH;
    case 2:  return WAVEFORM_SQUARE;
    case 3:  return WAVEFORM_TRIANGLE;
    default: return WAVEFORM_SINE;
  }
}

// Function to fill the LFO sine wavetable
void fillLfoSine(int16_t* dest) {
  for (uint16_t i = 0; i < LFO_WAVETABLE_SIZE; ++i) {
    float sample = sinf((TWO_PI * (float)i) / (float)LFO_WAVETABLE_SIZE);
    long scaled = lroundf(sample * 32767.0f);
    dest[i] = (int16_t)constrain(scaled, -32767L, 32767L);
  }
}

// Function to apply the LFO wavetable
void applyLfoTable() {
  lfo.setWaveformTable(lfoBuf[lfoPlay], LFO_WAVETABLE_SIZE);
}

// Function to apply the LFO rate (frequency [Hz]) and depth (amplitude [0..1]). Shape lives in lfoBuf.
void applyLfo(float rateHz, float depth) {
  lfo.setFrequency(constrain(rateHz, LFO_MIN_RATE_HZ, LFO_MAX_RATE_HZ));
  lfo.setAmplitude(constrain(depth, 0.0f, 1.0f));
}

// Function to write a 'W packet' (W,offset,count,v0,...,vN-1) into the back buffer and swaps on a complete table.
void applyLfoTableChunk(const String& inputString) {
  int c0 = inputString.indexOf(',');
  int c1 = inputString.indexOf(',', c0 + 1);
  int c2 = inputString.indexOf(',', c1 + 1);
  if (c0 < 0 || c1 < 0 || c2 < 0) {
    return;
  }

  int offset = inputString.substring(c0 + 1, c1).toInt();
  int count = inputString.substring(c1 + 1, c2).toInt();
  if (offset < 0 || count <= 0 || count > LFO_TABLE_CHUNK_MAX) {
    return;
  }
  if (offset + count > (int)LFO_WAVETABLE_SIZE) {
    return;
  }

  uint8_t back = 1 - lfoPlay;
  int pos = c2;
  for (int i = 0; i < count; ++i) {
    int nextComma = inputString.indexOf(',', pos + 1);
    String token = (nextComma < 0)
      ? inputString.substring(pos + 1)
      : inputString.substring(pos + 1, nextComma);
    token.trim();
    long val = token.toInt();
    if (val < -32767) val = -32767;
    if (val > 32767) val = 32767;
    lfoBuf[back][offset + i] = (int16_t)val;
    if (nextComma < 0) {
      if (i != count - 1) {
        return;
      }
      break;
    }
    pos = nextComma;
  }

  if (offset + count == (int)LFO_WAVETABLE_SIZE) {
    lfoPlay = back;
    applyLfoTable();
  }
}

// Applies cutoff (Hz) and resonance (Q) to the global filter
void applyFilter(float cutoffHz, float resonance) {
  globalFilter.frequency(constrain(cutoffHz, FILTER_MIN_CUTOFF_HZ, FILTER_MAX_CUTOFF_HZ));
  globalFilter.resonance(constrain(resonance, FILTER_MIN_Q, FILTER_MAX_Q));
}

// Applies a carrier waveform to all voices, only when it actually changed
void applyCarrierWaveform(short waveform) {
  if (waveform == currentCarrierWave) return;
  currentCarrierWave = waveform;
  for (int i = 0; i < NUM_VOICES; i++) {
    carriers[i]->begin(waveform);
  }
}

// Add:
// Applies gain of sourceMixer based on what synthesis method is chosen by the user
void applyCarrierSource(int waveId) {
  if (waveId == currentCarrierWaveId) return; 
  currentCarrierWaveId = waveId; 
  bool useWavetable = (waveId == CARRIER_WAVE_WAVETABLE);
  for (int i = 0; i < NUM_VOICES; i++) {
    sourceMixers[i]->gain(0, useWavetable ? 0.0f : 1.0f);
    sourceMixers[i]->gain(1, useWavetable ? 1.0f : 0.0f);
  }
}

int countActiveVoices() {
  int n = 0;
  for (int i = 0; i < NUM_VOICES; i++) {
    if (voiceActive[i]) n++;
  }
  return n;
}

// Count voices that still occupy mixer headroom (held notes + release tail).
int countSoundingVoices() {
  unsigned long now = millis();
  int n = 0;
  for (int i = 0; i < NUM_VOICES; i++) {
    if (voiceActive[i] || (voiceReleaseUntilMs[i] != 0 && now < voiceReleaseUntilMs[i])) {
      n++;
    }
  }
  return n;
}

// 1.0 / N so one voice is full-scale and eight voices stay within headroom.
void updateVoiceMixGains() {
  int n = countSoundingVoices();
  if (n < 1) n = 1;
  float gain = 1.0f / (float)n;
  for (int ch = 0; ch < 4; ch++) {
    voiceMixerA.gain(ch, gain);
    voiceMixerB.gain(ch, gain);
  }
}

void setAmpEnabled(bool enabled) {
  ampEnabled = enabled;
  digitalWrite(AMP_SD_PIN, enabled ? HIGH : LOW);
}

void cancelAmpMuteSchedule() {
  ampMuteAtMs = 0;
}

void scheduleAmpMuteAfterRelease() {
  ampMuteAtMs = millis() + AMP_MUTE_AFTER_RELEASE_MS;
}

void updateAmpMuteSchedule() {
  if (ampMuteAtMs != 0 && millis() >= ampMuteAtMs) {
    ampMuteAtMs = 0;
    if (countActiveVoices() == 0) {
      setAmpEnabled(false);
    }
  }
}

void prepareAmpForNote() {
  cancelAmpMuteSchedule();
  if (ampEnabled) {
    return;
  }
  setAmpEnabled(true);
  delay(AMP_ENABLE_SETTLE_MS);
}

void setOutputVolume(float amplitude) {
  volumeAmp.gain(amplitude);
}

void applyModDepth(int voice, float depth, bool fadeIn) {
  targetModDepth[voice] = depth;
  if (!fadeIn || MODULATOR_FADE_MS <= 0.0f) {
    modFadeActive[voice] = false;
    modulators[voice]->amplitude(depth);
    return;
  }
  modFadeStartMs[voice] = millis();
  modFadeActive[voice] = true;
  modulators[voice]->amplitude(0.0f);
}

void updateModulatorFades() {
  if (MODULATOR_FADE_MS <= 0.0f) {
    return;
  }
  for (int i = 0; i < NUM_VOICES; i++) {
    if (!modFadeActive[i]) continue;
    unsigned long elapsed = millis() - modFadeStartMs[i];
    float progress = (float)elapsed / MODULATOR_FADE_MS;
    if (progress >= 1.0f) {
      progress = 1.0f;
      modFadeActive[i] = false;
    }
    modulators[i]->amplitude(targetModDepth[i] * progress);
  }
}

/* Remove
void noteOnVoice(int voice, float carrierHz, float modHz, float modDepth)
*/
// Add: 
void noteOnVoice(int voice, float carrierHz, float modHz, float modDepth, int carrierWaveId) {
  if (voice < 0 || voice >= NUM_VOICES) return;

  // Packets without a waveform field keep whatever source is active
  int waveId = (carrierWaveId >= 0) ? carrierWaveId : currentCarrierWaveId; 

  // In both modes the carriers AND wavetables gets a frequency (and amplitude)
  // Bc. through that we can enable mid-note mode switching and it does not cost much
  carriers[voice]->frequency(carrierHz);
  carriers[voice]->amplitude(1.0f);
  wavetables[voice]->setFrequency(carrierHz);

  // Mode: Wavetable Synth 
  if (waveId == CARRIER_WAVE_WAVETABLE) {
    // In wavetable mode, the mod depth positions the morph between frames
    wavetables[voice]->setMorph(modDepth);
    modFadeActive[voice] = false;
    targetModDepth[voice] = 0.0f;
    modulators[voice]->amplitude(0.0f);
  } 
  // Mode: FM Synth  
  else {
    bool usePureSine = modHz < PURE_SINE_MOD_HZ_THRESHOLD;
    modulators[voice]->frequency(usePureSine ? 20.0f : modHz); // 20Hz is the default value for usePureSine mode
    
    if (usePureSine) {
      modFadeActive[voice] = false;
      targetModDepth[voice] = 0.0f;
      modulators[voice]->amplitude(0.0f);
    } else if (!voiceActive[voice]) {
      applyModDepth(voice, modDepth, true);
    } else {
      applyModDepth(voice, modDepth, false);
    }
  }

  if (!voiceActive[voice]) {
    prepareAmpForNote();
    envelopes[voice]->noteOn();
    voiceActive[voice] = true;
  }
  voiceReleaseUntilMs[voice] = 0;
  updateVoiceMixGains();
}

void noteOffVoice(int voice) {
  if (voice < 0 || voice >= NUM_VOICES) return;
  if (!voiceActive[voice]) return;

  envelopes[voice]->noteOff();
  voiceActive[voice] = false;
  voiceReleaseUntilMs[voice] = millis() + (unsigned long)ENVELOPE_RELEASE_MS;
  modFadeActive[voice] = false;
  targetModDepth[voice] = 0.0f;
  modulators[voice]->amplitude(0.0f);
  updateVoiceMixGains();

  if (countActiveVoices() == 0) {
    scheduleAmpMuteAfterRelease();
  }
}

void allNotesOff() {
  unsigned long until = millis() + (unsigned long)ENVELOPE_RELEASE_MS;
  for (int i = 0; i < NUM_VOICES; i++) {
    if (voiceActive[i]) {
      envelopes[i]->noteOff();
      voiceActive[i] = false;
      voiceReleaseUntilMs[i] = until;
      modFadeActive[i] = false;
      targetModDepth[i] = 0.0f;
      modulators[i]->amplitude(0.0f);
    }
  }
  updateVoiceMixGains();
  scheduleAmpMuteAfterRelease();
}

void setup() {
  pinMode(AMP_SD_PIN, OUTPUT);
  setAmpEnabled(false);

  AudioMemory(120);
  Serial.begin(115200);

  for (int i = 0; i < NUM_VOICES; i++) {
    modulators[i]->frequency(20.0f);
    modulators[i]->amplitude(0.0f);
    carriers[i]->begin(currentCarrierWave);
    carriers[i]->frequencyModulation(CARRIER_FM_OCTAVES);
    carriers[i]->frequency(440.0f);
    carriers[i]->amplitude(0.0f);

    // Add:
    wavetables[i]->loadTable(customWavetable, N_WAVEFORMS);

    // Add:
    sourceMixers[i]->gain(0, 1.0f);
    sourceMixers[i]->gain(1, 0.0f);

    envelopes[i]->attack(ENVELOPE_ATTACK_MS);
    envelopes[i]->decay(0.0f);
    envelopes[i]->sustain(1.0f);
    envelopes[i]->release(ENVELOPE_RELEASE_MS);
  }

  updateVoiceMixGains();
  sumMixer.gain(0, 1.0f);
  sumMixer.gain(1, 1.0f);
  sumMixer.gain(2, 0.0f);
  sumMixer.gain(3, 0.0f);

  // Global filter: how many octaves a full-scale LFO signal shifts the cutoff.
  globalFilter.octaveControl(FILTER_CONTROL_OCTAVES);
  applyFilter(FILTER_DEFAULT_CUTOFF_HZ, FILTER_DEFAULT_Q);

  // Global LFO: sine in RAM until the GUI uploads a table; depth 0 until L,... arrives.
  fillLfoSine(lfoBuf[0]);
  memcpy(lfoBuf[1], lfoBuf[0], sizeof(lfoBuf[0]));
  lfoPlay = 0;
  applyLfoTable();
  applyLfo(LFO_DEFAULT_RATE_HZ, LFO_DEFAULT_DEPTH);

  setOutputVolume(0.0f);
  delay(AMP_BOOT_MUTE_MS);
}

void loop() {
  updateModulatorFades();
  updateAmpMuteSchedule();
  updateVoiceMixGains();

  if (Serial.available() > 0) {
    String inputString = Serial.readStringUntil('\n');
    inputString.trim();
    if (inputString.length() == 0) {
      return;
    }

    // LFO wavetable chunk: "W,offset,count,v0,...,vN-1" (int16 samples into RAM).
    if (inputString.startsWith("W,")) {
      applyLfoTableChunk(inputString);
      return;
    }

    // Global LFO + filter command: "L,rate,depth,cutoff,res"
    //   rate    = LFO frequency in Hz
    //   depth   = LFO depth in percent (0..100)
    //   cutoff  = filter cutoff in Hz
    //   res     = filter resonance (Q)
    // Handled here, before the per-voice note logic, because it is a global command.
    if (inputString.startsWith("L,")) {
      int lc[4];
      int lcCount = 0;
      for (unsigned int i = 0; i < inputString.length() && lcCount < 4; i++) {
        if (inputString.charAt(i) == ',') {
          lc[lcCount++] = (int)i;
        }
      }
      if (lcCount == 4) {
        float lfoRate = inputString.substring(lc[0] + 1, lc[1]).toFloat();
        float lfoDepth = inputString.substring(lc[1] + 1, lc[2]).toFloat() / 100.0f;
        float filterCutoff = inputString.substring(lc[2] + 1, lc[3]).toFloat();
        float filterQ = inputString.substring(lc[3] + 1).toFloat();
        applyLfo(lfoRate, lfoDepth);
        applyFilter(filterCutoff, filterQ);
      }
      return;
    }

    int commas[5];
    int commaCount = 0;
    for (unsigned int i = 0; i < inputString.length() && commaCount < 5; i++) {
      if (inputString.charAt(i) == ',') {
        commas[commaCount++] = (int)i;
      }
    }

    int voiceId = 0;
    float inputCarrierFreq = 0.0f;
    float inputModFreq = 0.0f;
    float targetAmplitude = 0.0f;
    float modDepth = 0.0f;
    int carrierWaveId = -1; // -1 = Let waveform unchanged

    if (commaCount == 5) {
      voiceId = inputString.substring(0, commas[0]).toInt();
      inputCarrierFreq = clampValue(inputString.substring(commas[0] + 1, commas[1]).toFloat(), MAX_CARRIER_HZ);
      inputModFreq = clampValue(inputString.substring(commas[1] + 1, commas[2]).toFloat(), MAX_MODULATOR_HZ);
      targetAmplitude = clampValue(inputString.substring(commas[2] + 1, commas[3]).toFloat() / 100.0f, MAX_OUTPUT_AMPLITUDE);
      modDepth = clampValue(inputString.substring(commas[3] + 1, commas[4]).toFloat() / 100.0f, MAX_MOD_DEPTH);
      /* Remove:
      carrierWave = carrierWaveformFromId(inputString.substring(commas[4] + 1).toInt());
      */
      // Add: 
      carrierWaveId = inputString.substring(commas[4] + 1).toInt();
    } else if (commaCount == 4) {
      voiceId = inputString.substring(0, commas[0]).toInt();
      inputCarrierFreq = clampValue(inputString.substring(commas[0] + 1, commas[1]).toFloat(), MAX_CARRIER_HZ);
      inputModFreq = clampValue(inputString.substring(commas[1] + 1, commas[2]).toFloat(), MAX_MODULATOR_HZ);
      targetAmplitude = clampValue(inputString.substring(commas[2] + 1, commas[3]).toFloat() / 100.0f, MAX_OUTPUT_AMPLITUDE);
      modDepth = clampValue(inputString.substring(commas[3] + 1).toFloat() / 100.0f, MAX_MOD_DEPTH);
    } else if (commaCount == 3) {
      voiceId = 0;
      inputCarrierFreq = clampValue(inputString.substring(0, commas[0]).toFloat(), MAX_CARRIER_HZ);
      inputModFreq = clampValue(inputString.substring(commas[0] + 1, commas[1]).toFloat(), MAX_MODULATOR_HZ);
      targetAmplitude = clampValue(inputString.substring(commas[1] + 1, commas[2]).toFloat() / 100.0f, MAX_OUTPUT_AMPLITUDE);
      modDepth = clampValue(inputString.substring(commas[2] + 1).toFloat() / 100.0f, MAX_MOD_DEPTH);
      for (int i = 1; i < NUM_VOICES; i++) {
        noteOffVoice(i);
      }
    } else {
      return;
    }

    setOutputVolume(targetAmplitude);

    if (voiceId < 0) {
      allNotesOff();
      return;
    }

    if (voiceId >= NUM_VOICES) {
      return;
    }

    if (carrierWaveId >= 0) {
      applyCarrierSource(carrierWaveId); 
      if (carrierWaveId != CARRIER_WAVE_WAVETABLE) { 
        applyCarrierWaveform(carrierWaveformFromId(carrierWaveId));
      }
    }

    if (inputCarrierFreq > 0.0f) {
      /* Remove
      noteOnVoice(voiceId, inputCarrierFreq, inputModFreq, modDepth);
      */
      // Add: 
      noteOnVoice(voiceId, inputCarrierFreq, inputModFreq, modDepth, carrierWaveId);

    } else {
      noteOffVoice(voiceId);
    }
  }
}
