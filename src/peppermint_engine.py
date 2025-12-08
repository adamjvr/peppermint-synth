#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
peppermint_engine.py
---------------------------------------------------------------------
Supriya-based threaded synth engine for "Peppermint Synth - Roth Amplification Ltd."

Compatible with Supriya 25.11b0:
- NO UGen 'mul=' keyword arguments
- NO SinOsc positional args, only SinOsc.kr(frequency=...)
- NO .linlin() (replaced with raw arithmetic)
- Every UGen is manually amplitude-scaled with *
"""

from __future__ import annotations

import queue
import threading
from typing import Dict, Optional

import supriya
from supriya import Envelope, synthdef
from supriya.ugens import EnvGen, Out, Pulse, RLPF, Saw, SinOsc, WhiteNoise


# ------------------------------------------------------------------
# SynthDef
# ------------------------------------------------------------------

@synthdef()
def peppermint_voice(
    frequency=440.0,
    amp=0.2,
    gate=1.0,

    # VCO section
    vco_mix=0.5,
    vco1_wave=0.0,
    vco2_wave=0.0,
    detune=1.01,

    # Filter section
    cutoff=1200.0,
    res=0.2,
    env_amt=0.5,
    noise_mix=0.0,

    # LFO
    lfo_freq=5.0,
    lfo_depth=0.0,
    lfo_target=0.0,

    # ADSR
    atk=0.01,
    dec=0.1,
    sus=0.7,
    rel=0.3,
):
    """
    Dual VCO subtractive synth with noise, ADSR, filter env, and LFO.
    """

    # --- Amplitude envelope ---
    amp_env = EnvGen.kr(
        envelope=Envelope.adsr(
            attack_time=atk,
            decay_time=dec,
            sustain=sus,
            release_time=rel,
        ),
        gate=gate,
        done_action=2,
    )

    # --- Filter envelope ---
    filt_env = EnvGen.kr(
        envelope=Envelope.adsr(
            attack_time=atk,
            decay_time=dec,
            sustain=1.0,
            release_time=rel,
        ),
        gate=gate,
    )

    # --- LFO ---
    raw_lfo = SinOsc.kr(frequency=lfo_freq)
    lfo = raw_lfo * lfo_depth

    lfo_pitch = lfo * (1.0 - lfo_target)
    lfo_filter = lfo * lfo_target

    pitch_factor = 1.0 + (lfo_pitch * 0.05)

    # --- VCO wave selection ---
    v1_mix = (vco1_wave * 2.0) - 1.0
    v2_mix = (vco2_wave * 2.0) - 1.0

    freq1 = frequency * pitch_factor
    freq2 = frequency * detune * pitch_factor

    vco1_saw = Saw.ar(frequency=freq1)
    vco1_pulse = Pulse.ar(frequency=freq1, width=0.5)
    vco1 = ((1.0 - v1_mix) * 0.5 * vco1_saw) + ((1.0 + v1_mix) * 0.5 * vco1_pulse)

    vco2_saw = Saw.ar(frequency=freq2)
    vco2_pulse = Pulse.ar(frequency=freq2, width=0.5)
    vco2 = ((1.0 - v2_mix) * 0.5 * vco2_saw) + ((1.0 + v2_mix) * 0.5 * vco2_pulse)

    osc_mix = ((1.0 - vco_mix) * vco1) + (vco_mix * vco2)

    # --- Noise ---
    noise = WhiteNoise.ar() * noise_mix * 0.3
    sig = osc_mix + noise

    # --- Filter ---
    cutoff_mod = cutoff \
        + (filt_env * env_amt * 4000.0) \
        + (lfo_filter * 4000.0)

    cutoff_mod = cutoff_mod.clip(50.0, 18000.0)

    # Supriya 25.11: no linlin(), so use math:
    #  res = 0.0 → rq = 1.0
    #  res = 1.0 → rq = 0.1
    rq = 1.0 - (0.9 * res)

    sig = RLPF.ar(
        source=sig,
        frequency=cutoff_mod,
        reciprocal_of_q=rq,
    )

    # --- Output ---
    sig = sig * amp_env * amp
    Out.ar(bus=0, source=[sig, sig])


# ------------------------------------------------------------------
# Threaded Engine
# ------------------------------------------------------------------

class PeppermintSynthEngine:
    """Threaded Supriya engine used by the PyQt6 GUI."""

    def __init__(self) -> None:
        self._command_queue: queue.Queue = queue.Queue()
        self._running = True

        self._server: Optional[supriya.Server] = None
        self._synth_group = None

        self._poly_mode: bool = False
        self._global_params: Dict[str, float] = {}
        self._poly_voices: Dict[int, supriya.synths.Synth] = {}
        self._mono_voice: Optional[supriya.synths.Synth] = None

        self._thread = threading.Thread(
            target=self._thread_main,
            daemon=True,
        )
        self._thread.start()

    # --------------- Public API ---------------

    def set_poly_mode(self, is_poly: bool) -> None:
        self._command_queue.put(("set_poly_mode", bool(is_poly)))

    def set_param(self, name: str, value: float) -> None:
        self._command_queue.put(("set_param", name, float(value)))

    def note_on(self, midi_note: int, velocity: int = 100) -> None:
        self._command_queue.put(("note_on", midi_note, velocity))

    def note_off(self, midi_note: int) -> None:
        self._command_queue.put(("note_off", midi_note))

    def note_off_all(self) -> None:
        self._command_queue.put(("note_off_all",))

    def shutdown(self) -> None:
        self._running = False
        self._command_queue.put(("shutdown",))

    # --------------- Helper ---------------

    @staticmethod
    def _midi_to_hz(midi_note: int) -> float:
        return 440.0 * (2.0 ** ((midi_note - 69) / 12.0))

    # --------------- Worker Thread ---------------

    def _thread_main(self) -> None:
        server = supriya.Server().boot()
        self._server = server

        server.add_synthdefs(peppermint_voice)
        server.sync()

        self._synth_group = server.add_group()

        self._global_params = {
            "vco_mix": 0.5,
            "vco1_wave": 0.0,
            "vco2_wave": 0.0,
            "detune": 1.01,
            "cutoff": 1200.0,
            "res": 0.2,
            "env_amt": 0.5,
            "noise_mix": 0.0,
            "lfo_freq": 5.0,
            "lfo_depth": 0.0,
            "lfo_target": 0.0,
            "atk": 0.01,
            "dec": 0.1,
            "sus": 0.7,
            "rel": 0.3,
            "amp": 0.2,
        }

        while self._running:
            try:
                cmd = self._command_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            if not cmd:
                continue

            kind = cmd[0]

            if kind == "shutdown":
                break

            elif kind == "set_poly_mode":
                self._poly_mode = bool(cmd[1])

            elif kind == "set_param":
                name, value = cmd[1], cmd[2]
                if name in self._global_params:
                    self._global_params[name] = value
                    self._update_active_voices(name, value)

            elif kind == "note_on":
                self._handle_note_on(cmd[1], cmd[2])

            elif kind == "note_off":
                self._handle_note_off(cmd[1])

            elif kind == "note_off_all":
                self._handle_note_off_all()

        self._handle_note_off_all()

        try:
            self._synth_group.free()
        except Exception:
            pass

        try:
            server.quit()
        except Exception:
            pass

    # --------------- Internal Handlers ---------------

    def _update_active_voices(self, name: str, value: float) -> None:
        if self._mono_voice is not None:
            try:
                self._mono_voice.set(**{name: value})
            except Exception:
                pass

        for voice in self._poly_voices.values():
            try:
                voice.set(**{name: value})
            except Exception:
                pass

    def _handle_note_on(self, midi_note: int, velocity: int) -> None:
        if self._server is None or self._synth_group is None:
            return

        frequency = self._midi_to_hz(midi_note)
        base_amp = self._global_params.get("amp", 0.2)
        amp = max(0.0, min(1.0, velocity / 127.0)) * base_amp

        if self._poly_mode:
            params = dict(self._global_params)
            params.update({"frequency": frequency, "amp": amp, "gate": 1.0})
            voice = self._synth_group.add_synth(synthdef=peppermint_voice, **params)
            self._poly_voices[midi_note] = voice

        else:
            if self._mono_voice is None:
                params = dict(self._global_params)
                params.update({"frequency": frequency, "amp": amp, "gate": 1.0})
                self._mono_voice = self._synth_group.add_synth(
                    synthdef=peppermint_voice,
                    **params
                )
            else:
                try:
                    self._mono_voice.set(frequency=frequency, amp=amp, gate=1.0)
                except Exception:
                    pass

    def _handle_note_off(self, midi_note: int) -> None:
        if self._poly_mode:
            voice = self._poly_voices.pop(midi_note, None)
            if voice:
                try:
                    voice.set(gate=0.0)
                except Exception:
                    pass
        else:
            if self._mono_voice:
                try:
                    self._mono_voice.set(gate=0.0)
                except Exception:
                    pass

    def _handle_note_off_all(self) -> None:
        for voice in list(self._poly_voices.values()):
            try:
                voice.set(gate=0.0)
            except Exception:
                pass
        self._poly_voices.clear()

        if self._mono_voice:
            try:
                self._mono_voice.set(gate=0.0)
            except Exception:
                pass
            self._mono_voice = None
