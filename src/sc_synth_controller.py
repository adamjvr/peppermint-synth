#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sc_synth_controller.py
----------------------------------------------------------------------
Backend: SuperColliderSynthController

This module owns all the logic for talking to SuperCollider's audio
engine (scsynth) over OSC and managing mono/poly voices.

It is intentionally **UI-agnostic** and **MIDI-agnostic**:
- No PyQt imports
- No direct mido usage

The GUI and MIDI layers call its methods:

- set_poly_mode(enabled: bool)
- note_on_midi(note: int, velocity: int = 100)
- note_off_midi(note: int)
- note_off_all()
- set_param(name: str, value: float)
"""

from typing import Dict, Optional

import random
from pythonosc import udp_client


def midi_note_to_freq(note: int) -> float:
    """
    Convert MIDI note number (0-127) to frequency in Hz.

    Standard formula:
        freq = 440 * 2 ** ((note - 69) / 12)

    where:
        note = 69  => A4 = 440 Hz
        note = 60  => C4 ≈ 261.63 Hz
    """
    return 440.0 * (2.0 ** ((note - 69) / 12.0))


class SuperColliderSynthController:
    """
    SuperColliderSynthController
    ============================

    Responsibilities:
    -----------------
    - Maintain an OSC UDP client pointing at scsynth.
    - Handle mono/polyphonic note allocation.
    - Create / release nodes via SuperCollider's /s_new and /n_set.
    - Apply parameter changes to all active voices.

    This class assumes a SynthDef named "pyAnalogVoice" exists in
    SuperCollider (see pyAnalogVoice.scd).
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 57110, max_voices: int = 8):
        """
        Parameters
        ----------
        host : str
            IP address for scsynth OSC input (usually "127.0.0.1").
        port : int
            UDP port for scsynth (default: 57110).
        max_voices : int
            Maximum simultaneous voices in poly mode.
        """
        # OSC client -> scsynth
        self.client = udp_client.SimpleUDPClient(host, port)

        # Voice config
        self.poly_mode: bool = False       # False = mono, True = poly
        self.max_voices: int = max_voices  # polyphony limit

        # MONO STATE
        self.mono_node_id: Optional[int] = None      # active node ID
        self.mono_current_note: Optional[int] = None # MIDI note for mono voice

        # POLY STATE
        self.poly_note_to_node: Dict[int, int] = {}  # MIDI note -> node ID

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _generate_node_id(self) -> int:
        """
        Generate a random positive node ID for scsynth.

        Node IDs are 32-bit integers; we pick a range unlikely to clash
        with system nodes or other clients.
        """
        return random.randint(1000, 9999)

    # ------------------------------------------------------------------
    # Mode control
    # ------------------------------------------------------------------

    def set_poly_mode(self, enabled: bool) -> None:
        """
        Enable or disable polyphonic mode.

        Switching modes does **not** automatically kill existing voices;
        call note_off_all() from the GUI if you want a hard reset.
        """
        self.poly_mode = enabled

    # ------------------------------------------------------------------
    # Note events (from MIDI or GUI)
    # ------------------------------------------------------------------

    def note_on_midi(self, note: int, velocity: int = 100) -> None:
        """
        Handle a note-on from MIDI or GUI.

        Parameters
        ----------
        note : int
            MIDI note number (0-127).
        velocity : int
            MIDI velocity (0-127). If 0, treat as note-off.

        Behavior
        --------
        - Convert note -> frequency.
        - In MONO:
            * kill existing voice (if any),
            * start new voice, track node + note.
        - In POLY:
            * if note already active -> retrigger (kill + recreate),
            * if at max voices -> steal oldest,
            * create new node for this note.
        """
        if velocity <= 0:
            self.note_off_midi(note)
            return

        freq = midi_note_to_freq(note)

        if not self.poly_mode:
            # -----------------------
            # MONO MODE
            # -----------------------
            if self.mono_node_id is not None:
                # Release previous mono voice
                self.client.send_message("/n_set", [self.mono_node_id, "gate", 0.0])
                self.mono_node_id = None
                self.mono_current_note = None

            node_id = self._generate_node_id()
            self.mono_node_id = node_id
            self.mono_current_note = note

            # /s_new SynthDefName, nodeID, addAction, targetID, paramName, paramValue...
            self.client.send_message(
                "/s_new",
                [
                    "pyAnalogVoice",
                    node_id,
                    0,  # add head of group
                    1,  # default group
                    "freq",
                    float(freq),
                ],
            )

        else:
            # -----------------------
            # POLY MODE
            # -----------------------
            # Retrigger if already active
            old_id = self.poly_note_to_node.pop(note, None)
            if old_id is not None:
                self.client.send_message("/n_set", [old_id, "gate", 0.0])

            # Steal oldest if at max_voices
            if len(self.poly_note_to_node) >= self.max_voices:
                oldest_note = next(iter(self.poly_note_to_node.keys()))
                oldest_id = self.poly_note_to_node.pop(oldest_note)
                self.client.send_message("/n_set", [oldest_id, "gate", 0.0])

            node_id = self._generate_node_id()
            self.poly_note_to_node[note] = node_id

            self.client.send_message(
                "/s_new",
                [
                    "pyAnalogVoice",
                    node_id,
                    0,
                    1,
                    "freq",
                    float(freq),
                ],
            )

    def note_off_midi(self, note: int) -> None:
        """
        Handle a note-off for a specific MIDI note.

        - MONO:
            if mono voice is active and matches note, release it.
        - POLY:
            if note exists in map, release that node.
        """
        if not self.poly_mode:
            if self.mono_node_id is not None and self.mono_current_note == note:
                self.client.send_message("/n_set", [self.mono_node_id, "gate", 0.0])
                self.mono_node_id = None
                self.mono_current_note = None
        else:
            node_id = self.poly_note_to_node.pop(note, None)
            if node_id is not None:
                self.client.send_message("/n_set", [node_id, "gate", 0.0])

    def note_off_all(self) -> None:
        """
        Panic / all-notes-off: release every active voice.
        """
        # Mono voice
        if self.mono_node_id is not None:
            self.client.send_message("/n_set", [self.mono_node_id, "gate", 0.0])
            self.mono_node_id = None
            self.mono_current_note = None

        # Poly voices
        for node_id in self.poly_note_to_node.values():
            self.client.send_message("/n_set", [node_id, "gate", 0.0])
        self.poly_note_to_node.clear()

    # ------------------------------------------------------------------
    # Parameter control
    # ------------------------------------------------------------------

    def set_param(self, name: str, value: float) -> None:
        """
        Set a SynthDef parameter on all active voices.

        If there are no active voices, this is a no-op (safe to call
        while tweaking GUI sliders with no notes held).
        """
        value = float(value)

        if not self.poly_mode:
            if self.mono_node_id is None:
                return
            self.client.send_message("/n_set", [self.mono_node_id, name, value])
        else:
            if not self.poly_note_to_node:
                return
            for node_id in self.poly_note_to_node.values():
                self.client.send_message("/n_set", [node_id, name, value])
