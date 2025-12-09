#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
peppermint_engine.py
---------------------------------------------------------------------
Supriya-based threaded synth engine for "Peppermint Synth - Roth Amplification Ltd."

- Compatible with Supriya 25.11b0
- NO positional arguments to UGens (all keyword-based)
- NO 'mul=' / 'add=' / 'amplitude=' kwargs; scaling done via '*'
- NO .linlin(); simple arithmetic instead
- Supports mono and poly modes (toggle driven from GUI)
"""

from __future__ import annotations

import queue
import threading
from typing import Dict, Optional

import supriya
from supriya import Envelope, synthdef
from supriya.ugens import EnvGen, Out, Pulse, RLPF, Saw, SinOsc, WhiteNoise


# ------------------------------------------------------------------
# SynthDef: one subtractive synth voice
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
    res=0.2,            # 0.0..1.0, mapped to rq
    env_amt=0.5,        # filter env depth
    noise_mix=0.0,      # noise level 0..1

    # LFO section
    lfo_freq=5.0,
    lfo_depth=0.0,      # 0..1
    lfo_target=0.0,     # 0=pitch, 1=filter

    # ADSR envelope
    atk=0.01,
    dec=0.1,
    sus=0.7,
    rel=0.3,
):
    """
    Dual-VCO subtractive synth voice with:

    - Two oscillators (saw/pulse blend each)
    - White noise mix
    - Resonant low-pass filter
    - Shared ADSR for amplitude and filter
    - LFO routable to pitch or filter cutoff
    """

    # --- Amplitude envelope (ADSR for volume) ---
    amp_env = EnvGen.kr(
        envelope=Envelope.adsr(
            attack_time=atk,
            decay_time=dec,
            sustain=sus,          # Supriya uses 'sustain'
            release_time=rel,
        ),
        gate=gate,
        done_action=2,            # free synth on envelope completion
    )

    # --- Filter envelope (always peaking at 1.0) ---
    filt_env = EnvGen.kr(
        envelope=Envelope.adsr(
            attack_time=atk,
            decay_time=dec,
            sustain=1.0,
            release_time=rel,
        ),
        gate=gate,
    )

    # --- LFO (SinOsc, control-rate) ---
    raw_lfo = SinOsc.kr(frequency=lfo_freq)
    lfo = raw_lfo * lfo_depth

    # Route between pitch and filter via lfo_target crossfade
    lfo_pitch = lfo * (1.0 - lfo_target)
    lfo_filter = lfo * lfo_target

    # Small vibrato range on pitch: +/- 5%
    pitch_factor = 1.0 + (lfo_pitch * 0.05)

    # --- VCO section (Saw/Pulse blends) ---
    # Convert 0..1 knob to -1..+1 mix parameter
    v1_mix = (vco1_wave * 2.0) - 1.0
    v2_mix = (vco2_wave * 2.0) - 1.0

    # Apply pitch LFO and detune
    freq1 = frequency * pitch_factor
    freq2 = frequency * detune * pitch_factor

    # VCO1: saw + pulse blend (all keyword args!)
    vco1_saw = Saw.ar(frequency=freq1)
    vco1_pulse = Pulse.ar(frequency=freq1, width=0.5)
    vco1 = ((1.0 - v1_mix) * 0.5 * vco1_saw) + ((1.0 + v1_mix) * 0.5 * vco1_pulse)

    # VCO2: saw + pulse blend
    vco2_saw = Saw.ar(frequency=freq2)
    vco2_pulse = Pulse.ar(frequency=freq2, width=0.5)
    vco2 = ((1.0 - v2_mix) * 0.5 * vco2_saw) + ((1.0 + v2_mix) * 0.5 * vco2_pulse)

    # Crossfade VCO1 <-> VCO2
    osc_mix = ((1.0 - vco_mix) * vco1) + (vco_mix * vco2)

    # --- Noise source (scaled manually, no mul=) ---
    noise = WhiteNoise.ar() * noise_mix * 0.3

    # Pre-filter signal
    sig = osc_mix + noise

    # --- Filter cutoff modulation (env + LFO) ---
    cutoff_mod = (
        cutoff
        + (filt_env * env_amt * 4000.0)
        + (lfo_filter * 4000.0)
    )
    cutoff_mod = cutoff_mod.clip(50.0, 18000.0)

    # Map res (0..1) -> rq (1.0..0.1) via simple math
    rq = 1.0 - (0.9 * res)

    # Resonant low-pass filter (all keyword args)
    sig = RLPF.ar(
        source=sig,
        frequency=cutoff_mod,
        reciprocal_of_q=rq,
    )

    # --- Final output ---
    sig = sig * amp_env * amp
    Out.ar(bus=0, source=[sig, sig])


# ------------------------------------------------------------------
# Threaded Supriya engine with mono/poly modes
# ------------------------------------------------------------------

class PeppermintSynthEngine:
    """Threaded wrapper around Supriya's Server and peppermint_voice SynthDef.

    - Runs Supriya server and synths in a background thread
    - Exposes a simple API for the GUI:
        - set_poly_mode(is_poly: bool)
        - set_param(name: str, value: float)
        - note_on(midi_note: int, velocity: int)
        - note_off(midi_note: int)
        - note_off_all()
        - shutdown()
    """

    def __init__(self) -> None:
        # Command queue from GUI thread -> audio thread
        self._command_queue: "queue.Queue" = queue.Queue()
        self._running: bool = True

        # Supriya server and group, only used on worker thread
        self._server: Optional[supriya.Server] = None
        self._synth_group = None

        # Optional override for SuperCollider audio device name.
        # If None or empty, Supriya / scsynth will use its default device.
        self._audio_device: Optional[str] = None

        # Voice/param state
        self._poly_mode: bool = False
        self._global_params: Dict[str, float] = {}
        self._poly_voices: Dict[int, supriya.synths.Synth] = {}
        self._mono_voice: Optional[supriya.synths.Synth] = None

        # Background worker thread
        self._thread = threading.Thread(
            target=self._thread_main,
            daemon=True,
        )
        self._thread.start()

    # ---------------- Public API (GUI thread) ----------------

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

    def shutdown(self) -> None:
        self._running = False
        self._command_queue.put(("shutdown",))


    # ---------------- SuperCollider audio control (public API) -----------

    def set_audio_device(self, device: Optional[str]) -> None:
        """
        Set the desired SuperCollider audio device string.

        This does NOT immediately reboot the server; it only stores the
        requested device. The next call to reboot_audio() (or the next
        internal boot) will use this value when constructing ServerOptions.

        Examples of valid device strings depend on your SC build, e.g.:
            - "PipeWire"
            - "PulseAudio"
            - "hw:0,0"
        """
        # Normalize empty strings to None
        if device:
            self._audio_device = str(device)
        else:
            self._audio_device = None

    def reboot_audio(self) -> None:
        """
        Request an in-place audio reboot on the worker thread.

        This enqueues a 'reboot' command; the worker thread will:
            - stop all voices
            - free the current group and server
            - boot a new server, using any configured _audio_device override
            - reinstall the SynthDef and re-create the main group
        """
        # If the thread is not running, do nothing.
        if not self._running:
            return
        self._command_queue.put(("reboot",))

    def is_server_running(self) -> bool:
        """
        Lightweight check for GUI polling: True if the Supriya server
        has been created and is still attached.
        """
        return self._server is not None

    # ---------------- Internal boot helper (audio thread only) -----------

    def _boot_server_locked(self) -> None:
        """
        (Worker thread only) Boot / reboot the Supriya server.

        - If an existing server is running, all voices are silenced,
          the main group is freed, and the server is quit.
        - A new server is then booted, optionally using self._audio_device
          as the device string (via supriya.ServerOptions).
        - The peppermint_voice SynthDef is installed and synced.
        - The main synth group and global parameter defaults are re-created.
        """
        # First, stop any existing voices and free group/server if present.
        self._handle_note_off_all()

        # Free group
        try:
            if self._synth_group is not None:
                self._synth_group.free()
        except Exception:
            pass
        self._synth_group = None

        # Quit old server
        try:
            if self._server is not None:
                self._server.quit()
        except Exception:
            pass
        self._server = None

        # Construct options if a device override is present
        server = None
        try:
            options = None
            if self._audio_device:
                try:
                    options = supriya.ServerOptions()
                    options.device = self._audio_device
                except Exception:
                    # Fall back to default options if this fails
                    options = None

            if options is not None:
                server = supriya.Server(options=options).boot()
            else:
                server = supriya.Server().boot()
        except Exception as exc:
            # If boot fails, leave _server as None and re-raise for visibility
            print(f"[ENGINE] Failed to boot Supriya server: {exc}")
            self._server = None
            return

        self._server = server

        # Install SynthDef and sync
        try:
            server.add_synthdefs(peppermint_voice)
            server.sync()
        except Exception as exc:
            print(f"[ENGINE] Failed to install SynthDef: {exc}")
            return

        # Group that contains all voices
        try:
            self._synth_group = server.add_group()
        except Exception as exc:
            print(f"[ENGINE] Failed to create main synth group: {exc}")
            self._synth_group = None
            return

        # Initialize global params (must match SynthDef defaults)
        self._global_params = {
            "vco_mix": 0.5,
            "vco1_wave": 0.0,
            "vco2_wave": 0.0,
            "vco1_tune": 0.0,
            "vco2_tune": 0.0,
            "vco2_detune": 0.0,
            "noise_mix": 0.0,
            "cutoff": 1000.0,
            "res": 0.2,
            "env_amt": 0.5,
            "lfo_freq": 5.0,
            "lfo_depth": 0.0,
            "lfo_target": 0.0,
            "atk": 0.01,
            "dec": 0.1,
            "sus": 0.7,
            "rel": 0.3,
            "amp": 0.2,
        }

    # ---------------- Helper ----------------

    @staticmethod
    def _midi_to_hz(midi_note: int) -> float:
        """Standard 440Hz concert pitch conversion."""
        return 440.0 * (2.0 ** ((midi_note - 69) / 12.0))

    # ---------------- Worker thread entry ----------------

    def _thread_main(self) -> None:
        """Boot server, install SynthDef, process commands until shutdown."""
        server = supriya.Server().boot()
        self._server = server

        # Install SynthDef and sync
        server.add_synthdefs(peppermint_voice)
        server.sync()

        # Group that contains all voices
        self._synth_group = server.add_group()

        # Initialize global params (must match SynthDef defaults)
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
            elif kind == "reboot":
                # In-place audio reboot: stop voices, tear down server,
                # re-boot with current device override and re-create group/params.
                self._boot_server_locked()
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

        try:
            if self._synth_group is not None:
                self._synth_group.free()
        except Exception:
            pass

        try:
            if self._server is not None:
                self._server.quit()
        except Exception:
            pass

    # ---------------- Internal handlers (audio thread only) ----------------

    def _handle_set_param(self, name: str, value: float) -> None:
        # Ignore unknown param names
        if name not in self._global_params:
            return

        self._global_params[name] = value

        # Propagate to any active voices
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
        if self._server is None or self._synth_group is None:
            return

        frequency = self._midi_to_hz(midi_note)
        base_amp = self._global_params.get("amp", 0.2)
        amp = max(0.0, min(1.0, velocity / 127.0)) * base_amp

        if self._poly_mode:
            # One synth per note
            controls = dict(self._global_params)
            controls.update({"frequency": frequency, "amp": amp, "gate": 1.0})
            voice = self._synth_group.add_synth(
                synthdef=peppermint_voice,
                **controls,
            )
            self._poly_voices[midi_note] = voice
        else:
            # Single mono voice reused
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
        # Kill all polyphonic voices
        for midi_note, voice in list(self._poly_voices.items()):
            try:
                voice.set(gate=0.0)
            except Exception:
                pass
        self._poly_voices.clear()

        # Kill mono voice
        if self._mono_voice is not None:
            try:
                self._mono_voice.set(gate=0.0)
            except Exception:
                pass
            self._mono_voice = None
