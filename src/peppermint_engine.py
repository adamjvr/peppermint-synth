#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
peppermint_engine.py
---------------------------------------------------------------------
Supriya-based threaded synth engine for "Peppermint Synth - Roth Amplification Ltd."

- Designed for newer Supriya (e.g. 25.11b0-style APIs):
  * NO positional arguments to UGens (all keyword-based)
  * NO 'mul' / 'add' / 'amplitude' kwargs; scaling done via plain math
  * NO .linlin(); use simple arithmetic where needed
- Provides:
  * Mono and poly modes (toggle from GUI)
  * Threaded command queue so GUI never blocks audio thread
  * 'Reboot SC' hook so the GUI can restart the SC server
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
    vco_mix=0.5,        # 0.0 = VCO1, 1.0 = VCO2
    vco1_wave=0.0,      # 0.0..1.0, saw <-> pulse
    vco2_wave=0.0,      # 0.0..1.0, saw <-> pulse
    detune=1.01,        # VCO2 detune ratio

    # Filter section
    cutoff=1200.0,
    res=0.2,
    env_amt=0.5,
    noise_mix=0.0,

    # LFO section
    lfo_freq=5.0,
    lfo_depth=0.0,      # 0..1
    lfo_target=0.0,     # 0 = pitch, 1 = filter

    # ADSR envelope
    atk=0.01,
    dec=0.1,
    sus=0.7,
    rel=0.3,
):
    """
    Dual-VCO subtractive synth voice with:

    - Two oscillators (Saw/Pulse blend each, detuned)
    - White noise
    - Resonant lowpass filter
    - ADSR amplitude envelope
    - LFO routable to pitch or filter cutoff
    """

    # --- Amplitude envelope (ADSR for volume) ---
    amp_env = EnvGen.kr(
        envelope=Envelope.adsr(
            attack_time=atk,
            decay_time=dec,
            sustain=sus,          # NOTE: 'sustain', not 'sustain_level'
            release_time=rel,
        ),
        gate=gate,
        done_action=2,           # free synth when envelope finishes
    )

    # --- Filter envelope (full sustain; amount set by env_amt) ---
    filt_env = EnvGen.kr(
        envelope=Envelope.adsr(
            attack_time=atk,
            decay_time=dec,
            sustain=1.0,         # always full; scaled by env_amt downstream
            release_time=rel,
        ),
        gate=gate,
    )

    # --- LFO (control-rate) ---
    raw_lfo = SinOsc.kr(frequency=lfo_freq)
    lfo = raw_lfo * lfo_depth

    # Crossfade LFO target: 0=pitch, 1=filter
    lfo_pitch = (1.0 - lfo_target) * lfo
    lfo_filter = lfo_target * lfo

    # Pitch modulation: up to +/- 6 semitones at full LFO depth
    pitch_semitones = lfo_pitch * 6.0
    pitch_factor = 2.0 ** (pitch_semitones / 12.0)

    # Wave-shape mix for each oscillator (0=saw,1=pulse mapped to -1..+1)
    v1_mix = (vco1_wave * 2.0) - 1.0
    v2_mix = (vco2_wave * 2.0) - 1.0

    # Apply pitch LFO and detune
    freq1 = frequency * pitch_factor
    freq2 = frequency * detune * pitch_factor

    # VCO1: saw + pulse blend
    vco1_saw = Saw.ar(frequency=freq1)
    vco1_pulse = Pulse.ar(frequency=freq1, width=0.5)
    vco1 = ((1.0 - v1_mix) * 0.5 * vco1_saw) + ((1.0 + v1_mix) * 0.5 * vco1_pulse)

    # VCO2: saw + pulse blend
    vco2_saw = Saw.ar(frequency=freq2)
    vco2_pulse = Pulse.ar(frequency=freq2, width=0.5)
    vco2 = ((1.0 - v2_mix) * 0.5 * vco2_saw) + ((1.0 + v2_mix) * 0.5 * vco2_pulse)

    # Crossfade VCO1 <-> VCO2
    osc_mix = ((1.0 - vco_mix) * vco1) + (vco_mix * vco2)

    # White noise
    noise = WhiteNoise.ar() * noise_mix * 0.3

    # Pre-filter signal
    sig = osc_mix + noise

    # --- Filter cutoff modulation (envelope + LFO) ---
    cutoff_mod = (
        cutoff
        + (filt_env * env_amt * 4000.0)
        + (lfo_filter * 4000.0)
    )
    cutoff_mod = cutoff_mod.clip(50.0, 18000.0)

    # Map res (0..1) -> rq ~ (1.0..0.1)
    rq = 1.0 - (0.9 * res)

    # Resonant low-pass filter
    sig = RLPF.ar(
        source=sig,
        frequency=cutoff_mod,
        reciprocal_of_q=rq,
    )

    # Final output
    sig = sig * amp_env * amp
    Out.ar(bus=0, source=[sig, sig])


# ------------------------------------------------------------------
# Threaded Supriya engine with mono/poly modes and reboot support
# ------------------------------------------------------------------


class PeppermintSynthEngine:
    """Threaded wrapper around Supriya's Server and peppermint_voice SynthDef.

    Public API (GUI thread safe):
        - set_poly_mode(is_poly: bool)
        - set_param(name: str, value: float)
        - note_on(midi_note: int, velocity: int)
        - note_off(midi_note: int)
        - note_off_all()
        - reboot_server()
        - shutdown()
        - is_server_running() -> bool
    """

    def __init__(self) -> None:
        # Queue of commands from GUI thread -> audio thread
        self._command_queue: "queue.Queue" = queue.Queue()

        # Supriya state (only touched on audio thread)
        self._server: Optional[supriya.Server] = None
        self._synth_group = None

        # Status reported back to GUI
        self._server_running: bool = False

        # Voice / parameter state
        self._poly_mode: bool = False
        self._global_params: Dict[str, float] = {}
        self._poly_voices: Dict[int, supriya.synths.Synth] = {}
        self._mono_voice: Optional[supriya.synths.Synth] = None

        # Thread control
        self._running: bool = True
        self._thread = threading.Thread(
            target=self._thread_main,
            daemon=True,
        )
        self._thread.start()

    # --------------- Public API (GUI side) ---------------

    def set_poly_mode(self, is_poly: bool) -> None:
        self._command_queue.put(("set_poly_mode", bool(is_poly)))

    def set_param(self, name: str, value: float) -> None:
        self._command_queue.put(("set_param", str(name), float(value)))

    def note_on(self, midi_note: int, velocity: int = 100) -> None:
        self._command_queue.put(("note_on", int(midi_note), int(velocity)))

    def note_off(self, midi_note: int) -> None:
        self._command_queue.put(("note_off", int(midi_note)))

    def note_off_all(self) -> None:
        self._command_queue.put(("note_off_all",))

    def reboot_server(self) -> None:
        """Request a SuperCollider server reboot from the GUI thread."""
        self._command_queue.put(("reboot_server",))

    def shutdown(self) -> None:
        """Request engine shutdown and stop the audio thread."""
        self._running = False
        self._command_queue.put(("shutdown",))

    def is_server_running(self) -> bool:
        """Return True while the Supriya server is booted and running."""
        return bool(self._server_running)

    # --------------- Helpers ---------------

    @staticmethod
    def _midi_to_hz(midi_note: int) -> float:
        """Standard 440 Hz concert pitch conversion."""
        return 440.0 * (2.0 ** ((midi_note - 69) / 12.0))

    # --------------- Worker thread entry ---------------

    def _thread_main(self) -> None:
        """Boot server, install SynthDef, then process commands until shutdown."""
        server: Optional[supriya.Server] = None

        def _boot_server() -> None:
            """(Re)boot the SuperCollider server and install SynthDefs.

            If booting fails (e.g. UDP port already in use), this logs
            the error and leaves _server_running=False so the GUI can
            reflect that state and the user can retry.
            """
            nonlocal server

            # Tear down any existing server/group
            if self._synth_group is not None:
                try:
                    self._synth_group.free()
                except Exception:
                    pass
                self._synth_group = None

            if self._server is not None:
                try:
                    self._server.quit()
                except Exception:
                    pass
                self._server = None

            self._server_running = False
            self._poly_voices.clear()
            self._mono_voice = None

            try:
                server = supriya.Server().boot()
            except Exception as exc:
                print(f"[Peppermint] Failed to boot SuperCollider server: {exc}")
                self._server = None
                self._server_running = False
                return

            self._server = server
            self._server_running = True

            # Install SynthDef and sync
            server.add_synthdefs(peppermint_voice)
            server.sync()

            # Group that contains all voices
            self._synth_group = server.add_group()

            # Initialize global params only once (GUI changes survive reboots)
            if not self._global_params:
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

        # Initial boot when the engine thread starts
        _boot_server()

        # Main command loop
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
            elif kind == "reboot_server":
                _boot_server()
            elif kind == "set_poly_mode":
                self._poly_mode = bool(cmd[1])
            elif kind == "set_param":
                name, value = cmd[1], cmd[2]
                self._handle_set_param(name, value)
            elif kind == "note_on":
                midi_note, velocity = cmd[1], cmd[2]
                self._handle_note_on(midi_note, velocity)
            elif kind == "note_off":
                midi_note = cmd[1]
                self._handle_note_off(midi_note)
            elif kind == "note_off_all":
                self._handle_note_off_all()

        # Cleanup on exit
        self._handle_note_off_all()

        if self._synth_group is not None:
            try:
                self._synth_group.free()
            except Exception:
                pass
            self._synth_group = None

        if self._server is not None:
            try:
                self._server.quit()
            except Exception:
                pass
            self._server = None

        self._server_running = False

    # --------------- Internal handlers (audio thread only) ---------------

    def _handle_set_param(self, name: str, value: float) -> None:
        """Update a global parameter and propagate it to active voices."""
        if name not in self._global_params:
            return

        self._global_params[name] = value

        # Propagate to active voices
        if self._mono_voice is not None:
            try:
                self._mono_voice.set(**{name: value})
            except Exception:
                pass

        for voice in list(self._poly_voices.values()):
            try:
                voice.set(**{name: value})
            except Exception:
                pass

    def _handle_note_on(self, midi_note: int, velocity: int) -> None:
        """Start a note in mono or poly mode."""
        if not self._server_running or self._server is None or self._synth_group is None:
            return

        frequency = self._midi_to_hz(midi_note)
        base_amp = self._global_params.get("amp", 0.2)
        amp = max(0.0, min(1.0, velocity / 127.0)) * base_amp

        if self._poly_mode:
            controls = dict(self._global_params)
            controls.update({"frequency": frequency, "amp": amp, "gate": 1.0})
            voice = self._synth_group.add_synth(
                synthdef=peppermint_voice,
                **controls,
            )
            self._poly_voices[midi_note] = voice
        else:
            if self._mono_voice is None:
                controls = dict(self._global_params)
                controls.update({"frequency": frequency, "amp": amp, "gate": 1.0})
                self._mono_voice = self._synth_group.add_synth(
                    synthdef=peppermint_voice,
                    **controls,
                )
            else:
                try:
                    self._mono_voice.set(frequency=frequency, amp=amp, gate=1.0)
                except Exception:
                    pass

    def _handle_note_off(self, midi_note: int) -> None:
        """Stop a specific note (poly) or gate-off the mono voice."""
        if not self._server_running:
            return

        if self._poly_mode:
            voice = self._poly_voices.pop(midi_note, None)
            if voice is not None:
                try:
                    voice.set(gate=0.0)
                except Exception:
                    pass
        else:
            if self._mono_voice is not None:
                try:
                    self._mono_voice.set(gate=0.0)
                except Exception:
                    pass

    def _handle_note_off_all(self) -> None:
        """Gate off all active voices."""
        for midi_note, voice in list(self._poly_voices.items()):
            try:
                voice.set(gate=0.0)
            except Exception:
                pass
        self._poly_voices.clear()

        if self._mono_voice is not None:
            try:
                self._mono_voice.set(gate=0.0)
            except Exception:
                pass
            self._mono_voice = None
