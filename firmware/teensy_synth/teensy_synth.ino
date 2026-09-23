// Runs an 8-voice FM/wavetable synthesizer on Teensy 4.1 with serial control and I2S output.
//
// Signal path per voice: 
// modulator -> carrier or wavetable oscillator (depends on chosen synth mode) -> source mixer -> envelope
// Voices 0-3 -> voice_mixer_a, Voices 4-7 -> voice_mixer_b; 
// voice_mixer_a + voice_mixer_b -> sum_mixer -> global_filter -> volume_amp -> I2S2 output.
//                                                     ^
//                                                     |
//                                                    lfo
//
// Refer to '/visuals/Synth.png' for a visual representation of the signal path.
// The Wavetable and custom LFO AudioStream objects live in AudioWavetable.h and AudioLfo.h.
//
// Hardware & Protocol Dependencies:
// - Teensy 4.1 via I2S2 audio output
// - Amplifier shutdown (SD) on pin 23
// - Serial with baudrate 115200: note packets "voice_id,carrier_hz,modulator_hz,volume_pct,mod_depth_or_morph_pct,carrier_wave",
//   "L,rate_hz,depth_pct,cutoff_hz,resonance" and "W,offset,count,value0,...,valueN-1\n"

#include <Arduino.h>
#include <Audio.h>
#include <AudioStream.h>
#include <math.h>
#include <Wire.h>
#include <SPI.h>

#include "AudioWavetable.h"
#include "AudioLfo.h"
#include "CustomWavetable.h"

AudioSynthWaveformSine          modulator_0, modulator_1, modulator_2, modulator_3;
AudioSynthWaveformSine          modulator_4, modulator_5, modulator_6, modulator_7;
AudioSynthWaveformModulated     carrier_0, carrier_1, carrier_2, carrier_3;
AudioSynthWaveformModulated     carrier_4, carrier_5, carrier_6, carrier_7;

AudioWavetable                  wavetable_0, wavetable_1, wavetable_2, wavetable_3;
AudioWavetable                  wavetable_4, wavetable_5, wavetable_6, wavetable_7;

AudioMixer4                     source_mixer_0, source_mixer_1, source_mixer_2, source_mixer_3;
AudioMixer4                     source_mixer_4, source_mixer_5, source_mixer_6, source_mixer_7;

AudioEffectEnvelope             envelope_0, envelope_1, envelope_2, envelope_3;
AudioEffectEnvelope             envelope_4, envelope_5, envelope_6, envelope_7;
AudioMixer4                     voice_mixer_a;  // voices 0-3
AudioMixer4                     voice_mixer_b;  // voices 4-7
AudioMixer4                     sum_mixer;      // sum of voice_mixer_a and voice_mixer_b

// Global LFO + filter: the LFO modulates the filter cutoff (shared by all 8 voices).
AudioLfo                        lfo;
AudioFilterStateVariable        global_filter;

AudioAmplifier                  volume_amp;
AudioOutputI2S2                 i2s2_output;

AudioConnection patch_mod_car_0(modulator_0, 0, carrier_0, 0);
AudioConnection patch_mod_car_1(modulator_1, 0, carrier_1, 0);
AudioConnection patch_mod_car_2(modulator_2, 0, carrier_2, 0);
AudioConnection patch_mod_car_3(modulator_3, 0, carrier_3, 0);
AudioConnection patch_mod_car_4(modulator_4, 0, carrier_4, 0);
AudioConnection patch_mod_car_5(modulator_5, 0, carrier_5, 0);
AudioConnection patch_mod_car_6(modulator_6, 0, carrier_6, 0);
AudioConnection patch_mod_car_7(modulator_7, 0, carrier_7, 0);

AudioConnection patch_car_source_mixer_0(carrier_0, 0, source_mixer_0, 0);
AudioConnection patch_car_source_mixer_1(carrier_1, 0, source_mixer_1, 0);
AudioConnection patch_car_source_mixer_2(carrier_2, 0, source_mixer_2, 0);
AudioConnection patch_car_source_mixer_3(carrier_3, 0, source_mixer_3, 0);
AudioConnection patch_car_source_mixer_4(carrier_4, 0, source_mixer_4, 0);
AudioConnection patch_car_source_mixer_5(carrier_5, 0, source_mixer_5, 0);
AudioConnection patch_car_source_mixer_6(carrier_6, 0, source_mixer_6, 0);
AudioConnection patch_car_source_mixer_7(carrier_7, 0, source_mixer_7, 0);

AudioConnection patch_wav_source_mixer_0(wavetable_0, 0, source_mixer_0, 1);
AudioConnection patch_wav_source_mixer_1(wavetable_1, 0, source_mixer_1, 1);
AudioConnection patch_wav_source_mixer_2(wavetable_2, 0, source_mixer_2, 1);
AudioConnection patch_wav_source_mixer_3(wavetable_3, 0, source_mixer_3, 1);
AudioConnection patch_wav_source_mixer_4(wavetable_4, 0, source_mixer_4, 1);
AudioConnection patch_wav_source_mixer_5(wavetable_5, 0, source_mixer_5, 1);
AudioConnection patch_wav_source_mixer_6(wavetable_6, 0, source_mixer_6, 1);
AudioConnection patch_wav_source_mixer_7(wavetable_7, 0, source_mixer_7, 1);

AudioConnection patch_source_mixer_env_0(source_mixer_0, 0, envelope_0, 0);
AudioConnection patch_source_mixer_env_1(source_mixer_1, 0, envelope_1, 0);
AudioConnection patch_source_mixer_env_2(source_mixer_2, 0, envelope_2, 0);
AudioConnection patch_source_mixer_env_3(source_mixer_3, 0, envelope_3, 0);
AudioConnection patch_source_mixer_env_4(source_mixer_4, 0, envelope_4, 0);
AudioConnection patch_source_mixer_env_5(source_mixer_5, 0, envelope_5, 0);
AudioConnection patch_source_mixer_env_6(source_mixer_6, 0, envelope_6, 0);
AudioConnection patch_source_mixer_env_7(source_mixer_7, 0, envelope_7, 0);

AudioConnection patch_env_voice_mixer_a_0(envelope_0, 0, voice_mixer_a, 0);
AudioConnection patch_env_voice_mixer_a_1(envelope_1, 0, voice_mixer_a, 1);
AudioConnection patch_env_voice_mixer_a_2(envelope_2, 0, voice_mixer_a, 2);
AudioConnection patch_env_voice_mixer_a_3(envelope_3, 0, voice_mixer_a, 3);
AudioConnection patch_env_voice_mixer_b_0(envelope_4, 0, voice_mixer_b, 0);
AudioConnection patch_env_voice_mixer_b_1(envelope_5, 0, voice_mixer_b, 1);
AudioConnection patch_env_voice_mixer_b_2(envelope_6, 0, voice_mixer_b, 2);
AudioConnection patch_env_voice_mixer_b_3(envelope_7, 0, voice_mixer_b, 3);

AudioConnection patch_voice_mixer_a_sum_mixer(voice_mixer_a, 0, sum_mixer, 0);
AudioConnection patch_voice_mixer_b_sum_mixer(voice_mixer_b, 0, sum_mixer, 1);

// AudioFilterStateVariable: input 0 = signal, input 1 = cutoff modulation;
//                           output 0 = lowpass, 1 = bandpass, 2 = highpass.
AudioConnection patch_sum_mixer_filter(sum_mixer, 0, global_filter, 0);
AudioConnection patch_lfo_filter(lfo, 0, global_filter, 1);
AudioConnection patch_filter_amp(global_filter, 0, volume_amp, 0);  // output 0 = lowpass

AudioConnection patch_amp_out_0(volume_amp, 0, i2s2_output, 0);
AudioConnection patch_amp_out_1(volume_amp, 0, i2s2_output, 1);

const int numVoices = 8;

AudioSynthWaveformSine* modulators[numVoices] = {
  &modulator_0, &modulator_1, &modulator_2, &modulator_3,
  &modulator_4, &modulator_5, &modulator_6, &modulator_7
};

AudioSynthWaveformModulated* carriers[numVoices] = {
  &carrier_0, &carrier_1, &carrier_2, &carrier_3,
  &carrier_4, &carrier_5, &carrier_6, &carrier_7
};

AudioWavetable* wavetables[numVoices] = {
  &wavetable_0, &wavetable_1, &wavetable_2, &wavetable_3,
  &wavetable_4, &wavetable_5, &wavetable_6, &wavetable_7
};

AudioMixer4* source_mixers[numVoices] = {
  &source_mixer_0, &source_mixer_1, &source_mixer_2, &source_mixer_3,
  &source_mixer_4, &source_mixer_5, &source_mixer_6, &source_mixer_7
};

AudioEffectEnvelope* envelopes[numVoices] = {
  &envelope_0, &envelope_1, &envelope_2, &envelope_3,
  &envelope_4, &envelope_5, &envelope_6, &envelope_7
};

const float maxCarrierHz = 4000.0f;
const float maxModulatorHz = 300.0f;
const float maxOutputAmplitude = 1.0f;
const float maxModDepth = 1.0f;
const float thresholdModFmOff = 1.0f;

const float envelopeAttackMs = 0.0f;
const float envelopeReleaseMs = 150.0f;
const float modulatorFadeMs = 50.0f;

const float lfoMinRateHz = 0.01f;
const float lfoMaxRateHz = 100.0f;
const float lfoDefaultRateHz = 2.0f;
const float lfoDefaultDepth = 0.0f;
const float filterControlOctaves = 2.0f;
const float filterMinCutoffHz = 20.0f;
const float filterMaxCutoffHz = 12000.0f;
const float filterDefaultCutoffHz = 12000.0f;  // fully open by default
const float filterMinQ = 0.7f;
const float filterMaxQ = 5.0f;
const float filterDefaultQ = 0.7f;
const uint16_t lfoWavetableSize = 256;
const int lfoTableChunkMax = 32;
int16_t lfo_buf[2][lfoWavetableSize];
volatile uint8_t lfo_play = 0;

// A full-scale modulation input shifts the carrier by this many octaves. One octave
// matches the fixed range of AudioSynthWaveformSineModulated, so the mod depth sent
// by the GUI keeps its meaning.
const float carrierFmOctaves = 1.0f;
const int carrierWaveWavetable = 4;
int current_carrier_wave_id = 0;
short current_carrier_wave = WAVEFORM_SINE;

const int ampSdPin = 23; // Physical pin for the amplifier shutdown (SD)
bool amp_enabled = false;
unsigned long amp_mute_at_ms = 0;
const unsigned long ampBootMuteMs = 200;
const unsigned long ampEnableSettleMs = 50;
const unsigned long ampMuteAfterReleaseMs = (unsigned long)envelopeReleaseMs + 20;

// Array to track the active state of each voice (false = inactive, true = active)
bool voice_active[numVoices] = {false, false, false, false, false, false, false, false};
// Array to track the release time for each voice (0 = not releasing, other value = release time in milliseconds)
unsigned long voice_release_until_ms[numVoices] = {0, 0, 0, 0, 0, 0, 0, 0};

// Array to track the target modulation depth for each voice (0 = no modulation, 1 = full modulation)
float target_mod_depth_or_morph[numVoices] = {0, 0, 0, 0, 0, 0, 0, 0};
// Array to track the fade-in state for each voice (false = not fading, true = fading)
bool mod_fade_active[numVoices] = {false, false, false, false, false, false, false, false};
// Array to track the start time of the fade-in for each voice (0 = not fading, other value = start time in milliseconds)
unsigned long mod_fade_start_ms[numVoices] = {0, 0, 0, 0, 0, 0, 0, 0};

// Clamp value to the range [0, max_value].
//
// Args:
// value (float): Input to clamp.
// max_value (float): Inclusive upper bound.
float ClampValue(float value, float max_value) {
  if (value < 0.0f) return 0.0f;
  if (value > max_value) return max_value;
  return value;
}

// Map a protocol waveform ID to a Teensy Audio Library waveform constant.
//
// IDs 1-3 are saw/square/triangle; any other ID (including 0) is sine.
// Wavetable mode uses ID 4 and is handled by ApplyCarrierSource, not here.
//
// Args:
// wave_id (int): Protocol waveform ID from a note packet.
short CarrierWaveformFromId(int wave_id) {
  switch (wave_id) {
    case 1:  return WAVEFORM_SAWTOOTH;
    case 2:  return WAVEFORM_SQUARE;
    case 3:  return WAVEFORM_TRIANGLE;
    default: return WAVEFORM_SINE;
  }
}

// Fill dest (e.g. LFO buffer) with one cycle of a full-scale int16 sine table.
//
// Args:
// dest (int16_t*): Buffer of lfoWavetableSize samples.
void FillLfoSine(int16_t* dest) {
  for (uint16_t i = 0; i < lfoWavetableSize; ++i) {
    float sample = sinf((TWO_PI * (float)i) / (float)lfoWavetableSize);
    long scaled = lroundf(sample * 32767.0f);
    dest[i] = (int16_t)constrain(scaled, -32767L, 32767L);
  }
}

// Point the LFO object at the currently playing RAM wavetable.
void ApplyLfoTable() {
  lfo.SetWaveformTable(lfo_buf[lfo_play], lfoWavetableSize);
}

// Set LFO rate in Hz and depth in [0, 1]. Shape lives in lfo_buf.
//
// Args:
// rate_hz (float): LFO frequency; clamped to [lfoMinRateHz, lfoMaxRateHz].
// depth (float): Output amplitude in [0, 1].
void ApplyLfo(float rate_hz, float depth) {
  lfo.SetFrequency(constrain(rate_hz, lfoMinRateHz, lfoMaxRateHz));
  lfo.SetAmplitude(constrain(depth, 0.0f, 1.0f));
}

// Write a 'W'-prefixed packet into the back buffer and swap tables when the last chunk arrives.
//
// Packet format: "W,offset,count,value0,...,valueN-1" (int16 samples). Incomplete or
// out-of-range packets are ignored so the playing table is never half-updated.
//
// Args:
// input_string (const String&): Full serial line starting with "W,".
void ApplyLfoTableChunk(const String& input_string) {
  int c0 = input_string.indexOf(',');
  int c1 = input_string.indexOf(',', c0 + 1);
  int c2 = input_string.indexOf(',', c1 + 1);
  if (c0 < 0 || c1 < 0 || c2 < 0) {
    return;
  }

  int offset = input_string.substring(c0 + 1, c1).toInt();
  int count = input_string.substring(c1 + 1, c2).toInt();
  if (offset < 0 || count <= 0 || count > lfoTableChunkMax) {
    return;
  }
  if (offset + count > (int)lfoWavetableSize) {
    return;
  }

  uint8_t back = 1 - lfo_play;
  int pos = c2;
  for (int i = 0; i < count; ++i) {
    int next_comma = input_string.indexOf(',', pos + 1);
    String token = (next_comma < 0)
      ? input_string.substring(pos + 1)
      : input_string.substring(pos + 1, next_comma);
    token.trim();
    long val = token.toInt();
    if (val < -32767) val = -32767;
    if (val > 32767) val = 32767;
    lfo_buf[back][offset + i] = (int16_t)val;
    if (next_comma < 0) {
      if (i != count - 1) {
        return;
      }
      break;
    }
    pos = next_comma;
  }

  if (offset + count == (int)lfoWavetableSize) {
    lfo_play = back;
    ApplyLfoTable();
  }
}

// Apply cutoff (Hz) and resonance (Q) to the global filter.
//
// Args:
// cutoff_hz (float): Cutoff frequency; clamped to [filterMinCutoffHz, filterMaxCutoffHz].
// resonance (float): Filter Q; clamped to [filterMinQ, filterMaxQ].
void ApplyFilter(float cutoff_hz, float resonance) {
  global_filter.frequency(constrain(cutoff_hz, filterMinCutoffHz, filterMaxCutoffHz));
  global_filter.resonance(constrain(resonance, filterMinQ, filterMaxQ));
}

// Apply a carrier waveform to all voices when it actually changed.
//
// Args:
// waveform (short): Teensy Audio Library WAVEFORM_* constant.
void ApplyCarrierWaveform(short waveform) {
  if (waveform == current_carrier_wave) return;
  current_carrier_wave = waveform;
  for (int i = 0; i < numVoices; i++) {
    carriers[i]->begin(waveform);
  }
}

// Route each voice's source mixer to FM carrier or wavetable based on wave_id.
//
// Channel 0 is the FM carrier, channel 1 is the wavetable oscillator.
// wave_id 4 (carrierWaveWavetable) selects wavetable; all other IDs select FM.
//
// Args:
// wave_id (int): Protocol waveform / source ID.
void ApplyCarrierSource(int wave_id) {
  if (wave_id == current_carrier_wave_id) return;
  current_carrier_wave_id = wave_id;
  bool use_wavetable = (wave_id == carrierWaveWavetable);
  for (int i = 0; i < numVoices; i++) {
    source_mixers[i]->gain(0, use_wavetable ? 0.0f : 1.0f);
    source_mixers[i]->gain(1, use_wavetable ? 1.0f : 0.0f);
  }
}

// Count voices that currently hold a note.
int CountActiveVoices() {
  int n = 0;
  for (int i = 0; i < numVoices; i++) {
    if (voice_active[i]) n++;
  }
  return n;
}

// Count voices that still occupy mixer headroom (held notes plus release tail).
int CountSoundingVoices() {
  unsigned long now = millis();
  int n = 0;
  for (int i = 0; i < numVoices; i++) {
    if (voice_active[i] || (voice_release_until_ms[i] != 0 && now < voice_release_until_ms[i])) {
      n++;
    }
  }
  return n;
}

// Scale voice-mixer gains to 1/N so one voice is full-scale and eight stay in headroom.
void UpdateVoiceMixGains() {
  int n = CountSoundingVoices();
  if (n < 1) n = 1;
  float gain = 1.0f / (float)n;
  for (int ch = 0; ch < 4; ch++) {
    voice_mixer_a.gain(ch, gain);
    voice_mixer_b.gain(ch, gain);
  }
}

// Drive the amplifier SD pin and record the enabled state.
//
// Args:
// enabled (bool): true = amp on (SD high), false = muted.
void SetAmpEnabled(bool enabled) {
  amp_enabled = enabled;
  digitalWrite(ampSdPin, enabled ? HIGH : LOW);
}

// Clear a pending amplifier mute.
void CancelAmpMuteSchedule() {
  amp_mute_at_ms = 0;
}

// Schedule amplifier mute after the envelope release time.
void ScheduleAmpMuteAfterRelease() {
  amp_mute_at_ms = millis() + ampMuteAfterReleaseMs;
}

// Mute the amplifier when the scheduled time is reached and no notes are held.
void UpdateAmpMuteSchedule() {
  if (amp_mute_at_ms != 0 && millis() >= amp_mute_at_ms) {
    amp_mute_at_ms = 0;
    if (CountActiveVoices() == 0) {
      SetAmpEnabled(false);
    }
  }
}

// Enable the amplifier before a new note, waiting for it to settle.
void PrepareAmpForNote() {
  CancelAmpMuteSchedule();
  if (amp_enabled) {
    return;
  }
  SetAmpEnabled(true);
  delay(ampEnableSettleMs);
}

// Set the output amplifier gain.
//
// Args:
// amplitude (float): Linear gain, typically 0..1 from the serial amplitude field.
void SetOutputVolume(float amplitude) {
  volume_amp.gain(amplitude);
}

// Set or fade in a voice's FM modulator amplitude.
//
// Fade-in starts from 0 over modulatorFadeMs to avoid clicks on a new note.
//
// Args:
// voice (int): Voice index 0..numVoices-1.
// depth (float): Target modulator amplitude in [0, 1].
// fade_in (bool): true = ramp from silence; false = apply immediately.
void ApplyModDepth(int voice, float depth, bool fade_in) {
  target_mod_depth_or_morph[voice] = depth;
  if (!fade_in || modulatorFadeMs <= 0.0f) {
    mod_fade_active[voice] = false;
    modulators[voice]->amplitude(depth);
    return;
  }
  mod_fade_start_ms[voice] = millis();
  mod_fade_active[voice] = true;
  modulators[voice]->amplitude(0.0f);
}

// Advance in-progress modulator fade-ins toward their target depths.
void UpdateModulatorFades() {
  if (modulatorFadeMs <= 0.0f) {
    return;
  }
  for (int i = 0; i < numVoices; i++) {
    if (!mod_fade_active[i]) continue;
    unsigned long elapsed = millis() - mod_fade_start_ms[i];
    float progress = (float)elapsed / modulatorFadeMs;
    if (progress >= 1.0f) {
      progress = 1.0f;
      mod_fade_active[i] = false;
    }
    modulators[i]->amplitude(target_mod_depth_or_morph[i] * progress);
  }
}

// Start or update a voice in FM or wavetable mode.
//
// Both oscillators get frequency so the source can switch mid-note.
// In wavetable mode, mod_depth_or_morph morphs between table frames; in FM mode it is
// modulator amplitude. A missing waveform field (carrier_wave_id < 0) keeps
// the current source.
//
// Args:
// voice (int): Voice index 0..numVoices-1.
// carrier_hz (float): Carrier / wavetable playback frequency.
// mod_hz (float): FM modulator frequency; below thresholdModFmOff disables FM.
// mod_depth_or_morph (float): FM depth or wavetable morph amount in [0, 1].
// carrier_wave_id (int): Source ID, or -1 to leave the current source unchanged.
void NoteOnVoice(int voice, float carrier_hz, float mod_hz, float mod_depth_or_morph, int carrier_wave_id) {
  if (voice < 0 || voice >= numVoices) return;

  int wave_id = (carrier_wave_id >= 0) ? carrier_wave_id : current_carrier_wave_id;

  carriers[voice]->frequency(carrier_hz);
  carriers[voice]->amplitude(1.0f);
  wavetables[voice]->SetFrequency(carrier_hz);

  if (wave_id == carrierWaveWavetable) {
    wavetables[voice]->SetMorph(mod_depth_or_morph);
    mod_fade_active[voice] = false;
    target_mod_depth_or_morph[voice] = 0.0f;
    modulators[voice]->amplitude(0.0f);
  } else {
    bool fm_off = mod_hz < thresholdModFmOff;
    modulators[voice]->frequency(fm_off ? 20.0f : mod_hz);

    if (fm_off) {
      mod_fade_active[voice] = false;
      target_mod_depth_or_morph[voice] = 0.0f;
      modulators[voice]->amplitude(0.0f);
    } else if (!voice_active[voice]) {
      ApplyModDepth(voice, mod_depth_or_morph, true);
    } else {
      ApplyModDepth(voice, mod_depth_or_morph, false);
    }
  }

  if (!voice_active[voice]) {
    PrepareAmpForNote();
    envelopes[voice]->noteOn();
    voice_active[voice] = true;
  }
  voice_release_until_ms[voice] = 0;
  UpdateVoiceMixGains();
}

// Release one voice and schedule amp mute if none remain held.
//
// Args:
// voice (int): Voice index 0..numVoices-1.
void NoteOffVoice(int voice) {
  if (voice < 0 || voice >= numVoices) return;
  if (!voice_active[voice]) return;

  envelopes[voice]->noteOff();
  voice_active[voice] = false;
  voice_release_until_ms[voice] = millis() + (unsigned long)envelopeReleaseMs;
  mod_fade_active[voice] = false;
  target_mod_depth_or_morph[voice] = 0.0f;
  modulators[voice]->amplitude(0.0f);
  UpdateVoiceMixGains();

  if (CountActiveVoices() == 0) {
    ScheduleAmpMuteAfterRelease();
  }
}

// Release all held voices and schedule amplifier mute.
void AllNotesOff() {
  unsigned long until = millis() + (unsigned long)envelopeReleaseMs;
  for (int i = 0; i < numVoices; i++) {
    if (voice_active[i]) {
      envelopes[i]->noteOff();
      voice_active[i] = false;
      voice_release_until_ms[i] = until;
      mod_fade_active[i] = false;
      target_mod_depth_or_morph[i] = 0.0f;
      modulators[i]->amplitude(0.0f);
    }
  }
  UpdateVoiceMixGains();
  ScheduleAmpMuteAfterRelease();
}

// Initialize audio objects, serial, LFO, filter, and keep the amp muted at boot.
void setup() {
  pinMode(ampSdPin, OUTPUT);
  SetAmpEnabled(false);

  AudioMemory(120);
  Serial.begin(115200);

  for (int i = 0; i < numVoices; i++) {
    modulators[i]->frequency(20.0f);
    modulators[i]->amplitude(0.0f);
    carriers[i]->begin(current_carrier_wave);
    carriers[i]->frequencyModulation(carrierFmOctaves);
    carriers[i]->frequency(440.0f);
    carriers[i]->amplitude(0.0f);

    wavetables[i]->LoadTable(customWavetable, nWaveforms);

    source_mixers[i]->gain(0, 1.0f);
    source_mixers[i]->gain(1, 0.0f);

    envelopes[i]->attack(envelopeAttackMs);
    envelopes[i]->decay(0.0f);
    envelopes[i]->sustain(1.0f);
    envelopes[i]->release(envelopeReleaseMs);
  }

  UpdateVoiceMixGains();
  sum_mixer.gain(0, 1.0f);
  sum_mixer.gain(1, 1.0f);
  sum_mixer.gain(2, 0.0f);
  sum_mixer.gain(3, 0.0f);

  global_filter.octaveControl(filterControlOctaves);
  ApplyFilter(filterDefaultCutoffHz, filterDefaultQ);

  FillLfoSine(lfo_buf[0]);
  memcpy(lfo_buf[1], lfo_buf[0], sizeof(lfo_buf[0]));
  lfo_play = 0;
  ApplyLfoTable();
  ApplyLfo(lfoDefaultRateHz, lfoDefaultDepth);

  SetOutputVolume(0.0f);
  delay(ampBootMuteMs);
}

// Service fades, amp mute, mixer gains, and parse serial commands.
//
// Commands:
// - W,offset,count,value0,...,valueN-1: LFO wavetable chunk (int16 samples into RAM)
// - L,rate_hz,depth_pct,cutoff_hz,resonance: global LFO + filter (depth is percent 0..100)
// - voice_id,carrier_hz,modulator_hz,volume_pct,mod_depth_pct,carrier_wave: note on/off; voice_id < 0 = all off
// 3-field packets (no voice_id) play voice_id 0 and release the others.
void loop() {
  UpdateModulatorFades();
  UpdateAmpMuteSchedule();
  UpdateVoiceMixGains();

  if (Serial.available() > 0) {
    String input_string = Serial.readStringUntil('\n');
    input_string.trim();
    if (input_string.length() == 0) {
      return;
    }

    if (input_string.startsWith("W,")) {
      ApplyLfoTableChunk(input_string);
      return;
    }

    if (input_string.startsWith("L,")) {
      int lc[4];
      int lc_count = 0;
      for (unsigned int i = 0; i < input_string.length() && lc_count < 4; i++) {
        if (input_string.charAt(i) == ',') {
          lc[lc_count++] = (int)i;
        }
      }
      if (lc_count == 4) {
        float lfo_rate = input_string.substring(lc[0] + 1, lc[1]).toFloat();
        float lfo_depth = input_string.substring(lc[1] + 1, lc[2]).toFloat() / 100.0f;
        float filter_cutoff = input_string.substring(lc[2] + 1, lc[3]).toFloat();
        float filter_q = input_string.substring(lc[3] + 1).toFloat();
        ApplyLfo(lfo_rate, lfo_depth);
        ApplyFilter(filter_cutoff, filter_q);
      }
      return;
    }

    int commas[5];
    int comma_count = 0;
    for (unsigned int i = 0; i < input_string.length() && comma_count < 5; i++) {
      if (input_string.charAt(i) == ',') {
        commas[comma_count++] = (int)i;
      }
    }

    int voice_id = 0;
    float input_carrier_freq = 0.0f;
    float input_mod_freq = 0.0f;
    float target_amplitude = 0.0f;
    float mod_depth_or_morph = 0.0f;
    int carrier_wave_id = -1;  // -1 = leave waveform/source unchanged

    if (comma_count == 5) {
      voice_id = input_string.substring(0, commas[0]).toInt();
      input_carrier_freq = ClampValue(input_string.substring(commas[0] + 1, commas[1]).toFloat(), maxCarrierHz);
      input_mod_freq = ClampValue(input_string.substring(commas[1] + 1, commas[2]).toFloat(), maxModulatorHz);
      target_amplitude = ClampValue(input_string.substring(commas[2] + 1, commas[3]).toFloat() / 100.0f, maxOutputAmplitude);
      mod_depth_or_morph = ClampValue(input_string.substring(commas[3] + 1, commas[4]).toFloat() / 100.0f, maxModDepth);
      carrier_wave_id = input_string.substring(commas[4] + 1).toInt();
    } else if (comma_count == 4) {
      voice_id = input_string.substring(0, commas[0]).toInt();
      input_carrier_freq = ClampValue(input_string.substring(commas[0] + 1, commas[1]).toFloat(), maxCarrierHz);
      input_mod_freq = ClampValue(input_string.substring(commas[1] + 1, commas[2]).toFloat(), maxModulatorHz);
      target_amplitude = ClampValue(input_string.substring(commas[2] + 1, commas[3]).toFloat() / 100.0f, maxOutputAmplitude);
      mod_depth_or_morph = ClampValue(input_string.substring(commas[3] + 1).toFloat() / 100.0f, maxModDepth);
    } else if (comma_count == 3) {
      voice_id = 0;
      input_carrier_freq = ClampValue(input_string.substring(0, commas[0]).toFloat(), maxCarrierHz);
      input_mod_freq = ClampValue(input_string.substring(commas[0] + 1, commas[1]).toFloat(), maxModulatorHz);
      target_amplitude = ClampValue(input_string.substring(commas[1] + 1, commas[2]).toFloat() / 100.0f, maxOutputAmplitude);
      mod_depth_or_morph = ClampValue(input_string.substring(commas[2] + 1).toFloat() / 100.0f, maxModDepth);
      for (int i = 1; i < numVoices; i++) {
        NoteOffVoice(i);
      }
    } else {
      return;
    }

    SetOutputVolume(target_amplitude);

    if (voice_id < 0) {
      AllNotesOff();
      return;
    }

    if (voice_id >= numVoices) {
      return;
    }

    if (carrier_wave_id >= 0) {
      ApplyCarrierSource(carrier_wave_id);
      if (carrier_wave_id != carrierWaveWavetable) {
        ApplyCarrierWaveform(CarrierWaveformFromId(carrier_wave_id));
      }
    }

    if (input_carrier_freq > 0.0f) {
      NoteOnVoice(voice_id, input_carrier_freq, input_mod_freq, mod_depth_or_morph, carrier_wave_id);
    } else {
      NoteOffVoice(voice_id);
    }
  }
}
