#include <Audio.h>
#include <Wire.h>
#include <SPI.h>
#include <SD.h>
#include <SerialFlash.h>

// GUItool: begin automatically generated code
AudioSynthWaveform       AudioSynthWaveformSine_(modulator_0); //xy=660.4285278320312,95
AudioSynthWaveform       AudioSynthWaveformSine_(modulator_2); //xy=659.4285278320312,450
AudioSynthWaveform       AudioSynthWaveformSine_(modulator_1); //xy=663.4285278320312,264
AudioSynthWaveform       AudioSynthWaveformSine_(modulator_3); //xy=663.4285278320312,652
AudioSynthWaveform       AudioSynthWaveformSine_(modulator_6); //xy=663.4285278320312,1266
AudioSynthWaveform       AudioSynthWaveformSine_(modulator_4)_; //xy=665.4285278320312,912
AudioSynthWaveform       AudioSynthWaveformSine_(modulator_5); //xy=667.4285278320312,1080
AudioSynthWaveform       AudioSynthWaveformSine_(modulator_7); //xy=667.4285278320312,1468
AudioSynthWaveformModulated AudioSynthWaveformModulated_(carrier_2); //xy=1038.4285278320312,450
AudioSynthWaveformModulated AudioSynthWaveformModulated_(carrier_1); //xy=1042.4285278320312,264
AudioSynthWaveformModulated AudioSynthWaveformModulated_(carrier_3); //xy=1042.4285278320312,652
AudioSynthWaveformModulated AudioSynthWaveformModulated_(carrier_0); //xy=1046.4285278320312,90
AudioSynthWaveformModulated AudioSynthWaveformModulated_(carrier_6); //xy=1042.4285278320312,1267
AudioSynthWaveformModulated AudioSynthWaveformModulated_(carrier_4); //xy=1044.4285278320312,912
AudioSynthWaveformModulated AudioSynthWaveformModulated_(carrier_5); //xy=1046.4285278320312,1081
AudioSynthWaveformModulated AudioSynthWaveformModulated_(carrier_7); //xy=1046.4285278320312,1469
AudioSynthWavetable      AudioWavetable_(wavetable_2); //xy=1051.4285278320312,524
AudioSynthWavetable      AudioWavetable_(wavetable_0); //xy=1053.4285278320312,169
AudioSynthWavetable      AudioWavetable_(wavetable_1); //xy=1055.4285278320312,338
AudioSynthWavetable      AudioWavetable_(wavetable_3); //xy=1055.4285278320312,726
AudioSynthWavetable      AudioWavetable_(wavetable_4); //xy=1057.4285278320312,986
AudioSynthWavetable      AudioWavetable_(wavetable_6); //xy=1056.4285278320312,1341
AudioSynthWavetable      AudioWavetable_(wavetable_5); //xy=1060.4285278320312,1155
AudioSynthWavetable      AudioWavetable_(wavetable_7); //xy=1060.4285278320312,1543
AudioMixer4              AudioMixer4_(source_mixer_0); //xy=1415.4285278320312,111
AudioMixer4              AudioMixer4_(source_mixer_2); //xy=1414.4285278320312,466
AudioMixer4              AudioMixer4_(source_mixer_1); //xy=1418.4285278320312,280
AudioMixer4              AudioMixer4_(source_mixer_3); //xy=1418.4285278320312,668
AudioMixer4              AudioMixer4_(source_mixer_6); //xy=1418.4285278320312,1283
AudioMixer4              AudioMixer4_(source_mixer_4); //xy=1420.4285278320312,928
AudioMixer4              AudioMixer4_(source_mixer_5); //xy=1422.4285278320312,1097
AudioMixer4              AudioMixer4_(source_mixer_7); //xy=1422.4285278320312,1485
AudioEffectEnvelope      AudioEffectEnvelope_(envelope_0); //xy=1789.4285278320312,119
AudioEffectEnvelope      AudioEffectEnvelope_(envelope_2); //xy=1788.4285278320312,474
AudioEffectEnvelope      AudioEffectEnvelope_(envelope_1); //xy=1792.4285278320312,288
AudioEffectEnvelope      AudioEffectEnvelope_(envelope_3); //xy=1792.4285278320312,676
AudioEffectEnvelope      AudioEffectEnvelope_(envelope_4); //xy=1794.4285278320312,936
AudioEffectEnvelope      AudioEffectEnvelope_(envelope_5); //xy=1796.4285278320312,1105
AudioEffectEnvelope      AudioEffectEnvelope_(envelope_7); //xy=1796.4285278320312,1493
AudioEffectEnvelope      AudioEffectEnvelope_(envelope_6); //xy=1800.9999542236328,1289.5715169906616
AudioMixer4              AudioMixer4_(voice_mixer_a); //xy=2157.4285278320312,393
AudioMixer4              AudioMixer4_(voice_mixer_b); //xy=2163.4285278320312,1225
AudioMixer4              AudioMixer4_(sum_mixer); //xy=2461.428741455078,801.3333549499512
AudioSynthWaveform       AudioLfo_(lfo);      //xy=2497.857208251953,960.8505811691284
AudioFilterStateVariable AudioFilterStateVariable_(global_filter);        //xy=2842.891403198242,843.9456214904785
AudioAmplifier           AudioAmplifier_(volume_amp); //xy=3203.905433654785,849.619288444519
AudioOutputI2S2          AudioOutputI2S2_(i2s2_output); //xy=3554.5720138549805,853.9525680541992
AudioConnection          patchCord1(AudioSynthWaveformSine_(modulator_0), 0, AudioSynthWaveformModulated_(carrier_0), 0);
AudioConnection          patchCord2(AudioSynthWaveformSine_(modulator_2), 0, AudioSynthWaveformModulated_(carrier_2), 0);
AudioConnection          patchCord3(AudioSynthWaveformSine_(modulator_1), 0, AudioSynthWaveformModulated_(carrier_1), 0);
AudioConnection          patchCord4(AudioSynthWaveformSine_(modulator_3), 0, AudioSynthWaveformModulated_(carrier_3), 0);
AudioConnection          patchCord5(AudioSynthWaveformSine_(modulator_6), 0, AudioSynthWaveformModulated_(carrier_6), 0);
AudioConnection          patchCord6(AudioSynthWaveformSine_(modulator_4)_, 0, AudioSynthWaveformModulated_(carrier_4), 0);
AudioConnection          patchCord7(AudioSynthWaveformSine_(modulator_5), 0, AudioSynthWaveformModulated_(carrier_5), 0);
AudioConnection          patchCord8(AudioSynthWaveformSine_(modulator_7), 0, AudioSynthWaveformModulated_(carrier_7), 0);
AudioConnection          patchCord9(AudioSynthWaveformModulated_(carrier_2), 0, AudioMixer4_(source_mixer_2), 0);
AudioConnection          patchCord10(AudioSynthWaveformModulated_(carrier_1), 0, AudioMixer4_(source_mixer_1), 0);
AudioConnection          patchCord11(AudioSynthWaveformModulated_(carrier_3), 0, AudioMixer4_(source_mixer_3), 0);
AudioConnection          patchCord12(AudioSynthWaveformModulated_(carrier_0), 0, AudioMixer4_(source_mixer_0), 0);
AudioConnection          patchCord13(AudioSynthWaveformModulated_(carrier_6), 0, AudioMixer4_(source_mixer_6), 0);
AudioConnection          patchCord14(AudioSynthWaveformModulated_(carrier_4), 0, AudioMixer4_(source_mixer_4), 0);
AudioConnection          patchCord15(AudioSynthWaveformModulated_(carrier_5), 0, AudioMixer4_(source_mixer_5), 0);
AudioConnection          patchCord16(AudioSynthWaveformModulated_(carrier_7), 0, AudioMixer4_(source_mixer_7), 0);
AudioConnection          patchCord17(AudioWavetable_(wavetable_2), 0, AudioMixer4_(source_mixer_2), 1);
AudioConnection          patchCord18(AudioWavetable_(wavetable_0), 0, AudioMixer4_(source_mixer_0), 1);
AudioConnection          patchCord19(AudioWavetable_(wavetable_1), 0, AudioMixer4_(source_mixer_1), 1);
AudioConnection          patchCord20(AudioWavetable_(wavetable_3), 0, AudioMixer4_(source_mixer_3), 1);
AudioConnection          patchCord21(AudioWavetable_(wavetable_4), 0, AudioMixer4_(source_mixer_4), 1);
AudioConnection          patchCord22(AudioWavetable_(wavetable_6), 0, AudioMixer4_(source_mixer_6), 1);
AudioConnection          patchCord23(AudioWavetable_(wavetable_5), 0, AudioMixer4_(source_mixer_5), 1);
AudioConnection          patchCord24(AudioWavetable_(wavetable_7), 0, AudioMixer4_(source_mixer_7), 1);
AudioConnection          patchCord25(AudioMixer4_(source_mixer_0), AudioEffectEnvelope_(envelope_0));
AudioConnection          patchCord26(AudioMixer4_(source_mixer_2), AudioEffectEnvelope_(envelope_2));
AudioConnection          patchCord27(AudioMixer4_(source_mixer_1), AudioEffectEnvelope_(envelope_1));
AudioConnection          patchCord28(AudioMixer4_(source_mixer_3), AudioEffectEnvelope_(envelope_3));
AudioConnection          patchCord29(AudioMixer4_(source_mixer_6), AudioEffectEnvelope_(envelope_6));
AudioConnection          patchCord30(AudioMixer4_(source_mixer_4), AudioEffectEnvelope_(envelope_4));
AudioConnection          patchCord31(AudioMixer4_(source_mixer_5), AudioEffectEnvelope_(envelope_5));
AudioConnection          patchCord32(AudioMixer4_(source_mixer_7), AudioEffectEnvelope_(envelope_7));
AudioConnection          patchCord33(AudioEffectEnvelope_(envelope_0), 0, AudioMixer4_(voice_mixer_a), 0);
AudioConnection          patchCord34(AudioEffectEnvelope_(envelope_2), 0, AudioMixer4_(voice_mixer_a), 2);
AudioConnection          patchCord35(AudioEffectEnvelope_(envelope_1), 0, AudioMixer4_(voice_mixer_a), 1);
AudioConnection          patchCord36(AudioEffectEnvelope_(envelope_3), 0, AudioMixer4_(voice_mixer_a), 3);
AudioConnection          patchCord37(AudioEffectEnvelope_(envelope_4), 0, AudioMixer4_(voice_mixer_b), 0);
AudioConnection          patchCord38(AudioEffectEnvelope_(envelope_5), 0, AudioMixer4_(voice_mixer_b), 1);
AudioConnection          patchCord39(AudioEffectEnvelope_(envelope_7), 0, AudioMixer4_(voice_mixer_b), 3);
AudioConnection          patchCord40(AudioEffectEnvelope_(envelope_6), 0, AudioMixer4_(voice_mixer_b), 2);
AudioConnection          patchCord41(AudioMixer4_(voice_mixer_a), 0, AudioMixer4_(sum_mixer), 0);
AudioConnection          patchCord42(AudioMixer4_(voice_mixer_b), 0, AudioMixer4_(sum_mixer), 1);
AudioConnection          patchCord43(AudioMixer4_(sum_mixer), 0, AudioFilterStateVariable_(global_filter), 0);
AudioConnection          patchCord44(AudioLfo_(lfo), 0, AudioFilterStateVariable_(global_filter), 1);
AudioConnection          patchCord45(AudioFilterStateVariable_(global_filter), 0, AudioAmplifier_(volume_amp), 0);
AudioConnection          patchCord46(AudioAmplifier_(volume_amp), 0, AudioOutputI2S2_(i2s2_output), 0);
// GUItool: end automatically generated code
