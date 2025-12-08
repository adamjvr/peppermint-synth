#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
peppermint_midi.py
----------------------------------------------------------------------
MIDI input manager using Mido + python-rtmidi.

- Enumerates available input ports.
- Opens one port at a time.
- Calls note_on_cb(midi_note, velocity) / note_off_cb(midi_note) on MIDI events.
"""

from __future__ import annotations

import threading
from typing import Callable, List, Optional

import mido


class MidiInputManager:
    """
    Lightweight MIDI input helper.

    - Spawns a background thread that listens for MIDI events.
    - Supports dynamic port switching.
    """

    def __init__(
        self,
        note_on_cb: Callable[[int, int], None],
        note_off_cb: Callable[[int], None],
        auto_open_first: bool = True,
    ) -> None:
        self.note_on_cb = note_on_cb
        self.note_off_cb = note_off_cb

        self._port: Optional[mido.ports.BaseInput] = None
        self.current_port_name: Optional[str] = None

        self._running = True
        self._thread = threading.Thread(target=self._thread_main, daemon=True)
        self._thread.start()

        if auto_open_first:
            ports = self.list_input_ports()
            if ports:
                self.open_port_by_name(ports[0])

    # ------------------------------------------------------------------
    # Port management
    # ------------------------------------------------------------------

    def list_input_ports(self) -> List[str]:
        """
        Return a list of available MIDI input port names.
        """
        return list(mido.get_input_names())

    def open_port_by_name(self, name: str) -> None:
        """
        Close any existing port and open the named port.
        """
        self._close_port()
        try:
            self._port = mido.open_input(name)
            self.current_port_name = name
        except Exception:
            self._port = None
            self.current_port_name = None

    def _close_port(self) -> None:
        """
        Close any currently open MIDI input port.
        """
        if self._port is not None:
            try:
                self._port.close()
            except Exception:
                pass
        self._port = None
        self.current_port_name = None

    # ------------------------------------------------------------------
    # Background thread
    # ------------------------------------------------------------------

    def _thread_main(self) -> None:
        """
        Poll the currently open port for messages in a loop.
        """
        while self._running:
            if self._port is None:
                mido.sleep(0.05)
                continue

            for msg in self._port.iter_pending():
                self._handle_message(msg)
            mido.sleep(0.001)

        self._close_port()

    def _handle_message(self, msg: mido.Message) -> None:
        """
        Convert Mido messages to note_on/note_off callbacks.
        """
        if msg.type == "note_on" and msg.velocity > 0:
            if self.note_on_cb:
                self.note_on_cb(msg.note, msg.velocity)
        elif msg.type in ("note_off", "note_on") and msg.velocity == 0:
            if self.note_off_cb:
                self.note_off_cb(msg.note)

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        """
        Stop the background thread and close the MIDI port.
        """
        self._running = False
