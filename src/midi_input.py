#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
midi_input.py
----------------------------------------------------------------------
MidiInputManager

Small helper class that:

- Enumerates available MIDI input ports (via mido + python-rtmidi).
- Opens one port and listens in a background thread.
- Forwards note_on / note_off events to user-supplied callbacks.

Used by the GUI to hook up a hardware or virtual MIDI keyboard.
"""

from typing import Optional, Callable

try:
    import mido
    _MIDO_AVAILABLE = True
except ImportError:  # pragma: no cover - environment-dependent
    mido = None
    _MIDO_AVAILABLE = False


class MidiInputManager:
    """
    MidiInputManager
    =================

    Example usage
    -------------
        manager = MidiInputManager(
            note_on_cb=controller.note_on_midi,
            note_off_cb=controller.note_off_midi,
            auto_open_first=True,
        )

    The GUI can then:
        - list_input_ports()
        - open_port_by_name("My MIDI Device")

    while the manager forwards messages to the controller.
    """

    def __init__(
        self,
        note_on_cb: Callable[[int, int], None],
        note_off_cb: Callable[[int], None],
        auto_open_first: bool = True,
    ) -> None:
        """
        Parameters
        ----------
        note_on_cb : Callable[[int, int], None]
            Called as note_on_cb(note, velocity) when a note-on is received.
        note_off_cb : Callable[[int], None]
            Called as note_off_cb(note) when a note-off is received.
        auto_open_first : bool
            If True, automatically open the first available input port.
        """
        self.note_on_cb = note_on_cb
        self.note_off_cb = note_off_cb
        self._input_port: Optional["mido.ports.BaseInput"] = None
        self.current_port_name: Optional[str] = None

        if auto_open_first:
            self.open_first_available_port()

    # ------------------------------------------------------------------
    # Port enumeration
    # ------------------------------------------------------------------

    @staticmethod
    def list_input_ports() -> list[str]:
        """
        Return a list of available MIDI input port names.

        Returns empty list if mido is unavailable or an error occurs.
        """
        if not _MIDO_AVAILABLE:
            return []
        try:
            return mido.get_input_names()
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Port control
    # ------------------------------------------------------------------

    def open_first_available_port(self) -> None:
        """
        Open the first available MIDI input port, if any.
        """
        ports = self.list_input_ports()
        if not ports:
            print("[MIDI] No MIDI input ports found or mido unavailable.")
            return
        self.open_port_by_name(ports[0])

    def open_port_by_name(self, port_name: str) -> None:
        """
        Open a specific MIDI input port by name.

        Any previously-open port is closed first.
        """
        if not _MIDO_AVAILABLE:
            print("[MIDI] mido not available; cannot open MIDI ports.")
            return

        # Close existing port (if any)
        if self._input_port is not None:
            try:
                self._input_port.close()
            except Exception:
                pass
            self._input_port = None

        print(f"[MIDI] Opening input port: {port_name}")
        self.current_port_name = port_name

        def _midi_callback(msg):
            """
            Called in a background thread when a MIDI message arrives.

            We only care about note_on / note_off events.
            """
            try:
                if msg.type == "note_on":
                    note = msg.note
                    vel = msg.velocity
                    if vel > 0:
                        self.note_on_cb(note, vel)
                    else:
                        # note_on with velocity 0 => note_off
                        self.note_off_cb(note)
                elif msg.type == "note_off":
                    self.note_off_cb(msg.note)
            except Exception as exc:
                print(f"[MIDI] Callback error: {exc}")

        try:
            self._input_port = mido.open_input(port_name, callback=_midi_callback)
        except Exception as exc:
            print(f"[MIDI] Failed to open MIDI input '{port_name}': {exc}")
            self._input_port = None
            self.current_port_name = None

    def close(self) -> None:
        """
        Close any open MIDI input port.
        """
        if self._input_port is not None:
            try:
                self._input_port.close()
            except Exception:
                pass
            self._input_port = None
            self.current_port_name = None
