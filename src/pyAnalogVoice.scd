// pyAnalogVoice.scd
// --------------------------------------------------------------------
// 2-VCO analog-style synth voice for external control via OSC.
//
// Designed to be controlled from Python using the
// SuperColliderSynthController in sc_synth_controller.py.
//
// FEATURES
// --------
// - Two oscillators (VCO1 / VCO2) with saw/pulse morph.
// - Detune between VCO1 and VCO2.
// - Resonant low-pass filter with envelope modulation.
// - ADSR amplitude envelope (also used for filter env amount).
// - LFO that can target either:
//     * pitch (vibrato)
//     * filter cutoff (wah / sweep)
// - Noise mix control.
//
// CONTROL PARAMETERS (all exposed as SynthDef arguments)
// ------------------------------------------------------
//   freq       : base pitch in Hz (set from MIDI note in Python)
//   detune     : ratio for VCO2 relative to VCO1 (1.0 = unison)
//   vco_mix    : blend between VCO1 and VCO2 (0 = only VCO1, 1 = only VCO2)
//   vco1_wave  : waveform morph for VCO1 (0 = saw, 1 = pulse)
//   vco2_wave  : waveform morph for VCO2 (0 = saw, 1 = pulse)
//   cutoff     : base filter cutoff in Hz
//   res        : 0..1, mapped to RLPF rq
//   env_amt    : how strongly the ADSR modulates filter cutoff
//   atk/dec/sus/rel : ADSR envelope times & sustain
//   lfo_freq   : LFO frequency in Hz
//   lfo_depth  : LFO modulation depth (0..1)
//   lfo_target : 0 = LFO -> pitch, 1 = LFO -> filter cutoff
//   noise_mix  : blend of oscillator signal with white noise (0..1)
//   amp        : final output amplitude
//   gate       : envelope gate (1=start, 0=release)
//   out        : audio bus index (0 = main stereo out)
// --------------------------------------------------------------------

(
SynthDef(\pyAnalogVoice, { |out = 0, gate = 1,

    // Core pitch and mixing
    freq       = 110,      // base note (Hz)
    detune     = 1.01,     // VCO2 frequency ratio
    vco_mix    = 0.5,      // 0 = VCO1, 1 = VCO2

    // Waveform morph: 0 = saw, 1 = pulse
    vco1_wave  = 0.0,
    vco2_wave  = 0.0,

    // Filter
    cutoff     = 1200,     // base cutoff (Hz)
    res        = 0.2,      // 0..1 resonance
    env_amt    = 0.5,      // filter env modulation depth

    // ADSR
    atk        = 0.01,
    dec        = 0.1,
    sus        = 0.7,
    rel        = 0.3,

    // LFO
    lfo_freq   = 5.0,
    lfo_depth  = 0.0,
    lfo_target = 0,        // 0 = pitch, 1 = filter

    // Noise
    noise_mix  = 0.0,

    // Output level
    amp        = 0.2
|

    var env, lfo, freq_mod, cutoff_mod;
    var vco1, vco2, vco_mix_sig, noise, mixed, filt, sig;
    var rq, cutoff_with_env;

    // --------------------------------------------------
    // ADSR envelope controlling amp (and filter env_amt)
    // --------------------------------------------------
    env = EnvGen.kr(
        Env.adsr(atk, dec, sus, rel),
        gate,
        doneAction: 2   // free synth when envelope finishes
    );

    // --------------------------------------------------
    // LFO (SinOsc.kr gives -1..1, scaled by lfo_depth)
    // --------------------------------------------------
    lfo = SinOsc.kr(lfo_freq).range(-1.0, 1.0) * lfo_depth;

    // Prepare pitch and filter modulation targets
    freq_mod   = freq;
    cutoff_mod = cutoff;

    // 0 = LFO -> pitch; 1 = keep freq unmodulated
    freq_mod = Select.kr(
        lfo_target,
        [
            freq * (1 + (lfo * 0.05)), // ~±5% vibrato
            freq                       // no pitch mod
        ]
    );

    // 0 = base cutoff; 1 = LFO -> cutoff
    cutoff_mod = Select.kr(
        lfo_target,
        [
            cutoff,                    // no filter mod
            cutoff * (1 + (lfo * 0.5)) // ~±50% sweep
        ]
    );

    // --------------------------------------------------
    // VCOs with saw/pulse morph
    // --------------------------------------------------
    var vco1_saw   = Saw.ar(freq_mod);
    var vco1_pulse = Pulse.ar(freq_mod, 0.5);
    vco1 = XFade2.ar(vco1_saw, vco1_pulse, (vco1_wave * 2 - 1));

    var vco2_saw   = Saw.ar(freq_mod * detune);
    var vco2_pulse = Pulse.ar(freq_mod * detune, 0.5);
    vco2 = XFade2.ar(vco2_saw, vco2_pulse, (vco2_wave * 2 - 1));

    // vco_mix: 0 = only VCO1, 1 = only VCO2
    vco_mix_sig = XFade2.ar(vco1, vco2, (vco_mix * 2 - 1));

    // --------------------------------------------------
    // Noise
    // --------------------------------------------------
    noise = WhiteNoise.ar;
    // noise_mix: 0 = oscillators, 1 = noise only
    mixed = XFade2.ar(vco_mix_sig, noise, (noise_mix * 2 - 1));

    // --------------------------------------------------
    // Filter
    // --------------------------------------------------
    // res (0..1) mapped exponentially to rq:
    //    high res -> lower rq
    rq = LinExp.kr(res, 0.0, 1.0, 0.5, 0.001);

    // ADSR env -> filter modulation
    cutoff_with_env = cutoff_mod + (env * env_amt * cutoff_mod);
    cutoff_with_env = cutoff_with_env.clip(20, 20000);

    filt = RLPF.ar(mixed, cutoff_with_env, rq);

    // --------------------------------------------------
    // Output
    // --------------------------------------------------
    sig = (filt * env * amp).dup;  // stereo

    Out.ar(out, sig);
}).add;
)
