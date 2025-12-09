#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
peppermint_midi.py
------------------
MIDI input handling for Peppermint Synth.

This version restores a class named **MidiInputManager** with the
API expected by ``peppermint_gui.py``:

    - MidiInputManager(note_on_cb, note_off_cb, auto_open_first=True)
    - list_input_ports() -> list[str]
    - current_port_name  (str | None attribute)
    - open_port_by_name(name: str) -> None
    - shutdown() -> None

Internally it:

    * Uses the ``mido`` library to access MIDI input ports.
    * Runs a background thread that polls the selected input port.
    * Calls the provided note_on_cb / note_off_cb functions when
      note_on / note_off messages arrive.

This file is **self-contained** and does not depend on the engine
directly; the GUI passes callbacks from PeppermintSynthEngine.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, List, Optional

import mido


class MidiInputManager:
    """Background MIDI input manager with a simple callback-based API.

    Parameters
    ----------
    note_on_cb :
        Callable that accepts (midi_note: int, velocity: int) when a
        note-on message is received (velocity > 0).

    note_off_cb :
        Callable that accepts (midi_note: int) when a note-off message
        is received, or when a note-on with velocity 0 is received.

    auto_open_first : bool, optional
        If True (default), the manager will automatically open the
        first available MIDI input port on startup (if any ports exist).
    """

    def __init__(
        self,
        note_on_cb: Callable[[int, int], None],
        note_off_cb: Callable[[int], None],
        auto_open_first: bool = True,
    ) -> None:
        # Store user callbacks (engine methods or wrappers)
        self._note_on_cb = note_on_cb
        self._note_off_cb = note_off_cb

        # Background thread control
        self._running: bool = True
        self._thread: Optional[threading.Thread] = None

        # Currently-open input port (at most one at a time)
        self._input_port: Optional[mido.ports.BaseInput] = None
        self.current_port_name: Optional[str] = None

        # If requested, open the first available input port
        if auto_open_first:
            self._open_first_available_port()

        # Start background thread that polls the selected port
        self._thread = threading.Thread(
            target=self._thread_main,
            name="PeppermintMidiThread",
            daemon=True,
        )
        self._thread.start()

    # ------------------------------------------------------------------
    # Public API used by peppermint_gui.SynthControlWindow
    # ------------------------------------------------------------------

    def list_input_ports(self) -> List[str]:
        """Return a list of available MIDI input port names."""
        try:
            return mido.get_input_names()
        except Exception as exc:
            print("[MIDI] Failed to list input ports:", exc)
            return []

    def open_port_by_name(self, name: str) -> None:
        """Close any existing input and open the named MIDI input port."""
        # Close previous port if any
        self._close_current_port()

        if not name:
            self.current_port_name = None
            return

        try:
            port = mido.open_input(name)
        except Exception as exc:
            print(f"[MIDI] Failed to open MIDI input port {name!r}: {exc}")
            self.current_port_name = None
            self._input_port = None
            return

        self._input_port = port
        self.current_port_name = name
        print(f"[MIDI] Opened input port: {name!r}")

    def shutdown(self) -> None:
        """Stop the background thread and close any open ports."""
        self._running = False

        # Wait briefly for the thread to finish
        if self._thread is not None and self._thread.is_alive():
            try:
                self._thread.join(timeout=1.0)
            except Exception:
                pass

        # Ensure port is closed
        self._close_current_port()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _open_first_available_port(self) -> None:
        """Open the first available MIDI input port, if any exist."""
        names = self.list_input_ports()
        if not names:
            print("[MIDI] No MIDI input ports available to auto-open.")
            return

        first = names[0]
        self.open_port_by_name(first)

    def _close_current_port(self) -> None:
        """Close the currently open MIDI input port, if any."""
        if self._input_port is not None:
            try:
                self._input_port.close()
            except Exception:
                pass
        self._input_port = None
        self.current_port_name = None

    def _handle_message(self, msg: mido.Message) -> None:
        """Decode one Mido message and invoke user callbacks."""
        try:
            if msg.type == "note_on":
                # Velocity 0 is a 'note_off' in MIDI semantics
                if msg.velocity > 0:
                    if self._note_on_cb:
                        self._note_on_cb(msg.note, msg.velocity)
                else:
                    if self._note_off_cb:
                        self._note_off_cb(msg.note)

            elif msg.type == "note_off":
                if self._note_off_cb:
                    self._note_off_cb(msg.note)

            # Extend here (CC, pitch bend, etc.) if desired:
            # elif msg.type == "control_change":
            #     ...
            # elif msg.type == "pitchwheel":
            #     ...

        except Exception as exc:
            print(f"[MIDI] Error while handling message {msg!r}: {exc}")

    # ------------------------------------------------------------------
    # Background thread
    # ------------------------------------------------------------------

    def _thread_main(self) -> None:
        """Background loop that polls the currently selected MIDI port.

        This loop:
            - Checks if a port is open.
            - Uses port.iter_pending() to pull any waiting messages.
            - Dispatches them to _handle_message().
            - Sleeps briefly to avoid busy-waiting.
        """
        print("[MIDI] MIDI thread started.")

        while self._running:
            port = self._input_port

            if port is not None:
                try:
                    for msg in port.iter_pending():
                        self._handle_message(msg)
                except (IOError, OSError) as exc:
                    # Port may have disappeared; drop it and try again later.
                    print("[MIDI] Port error, closing current port:", exc)
                    self._close_current_port()

            # Use time.sleep (NOT mido.sleep) to avoid hammering the CPU
            time.sleep(0.001)

        print("[MIDI] MIDI thread stopping; closing port...")
        self._close_current_port()
        print("[MIDI] MIDI thread exited.")


__all__ = ["MidiInputManager"]
