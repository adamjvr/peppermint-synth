#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
piano_widget.py
----------------------------------------------------------------------
On-screen piano keyboard widget (PyQt6).

This version draws a *real* one-octave keyboard (C4–B4):

    White keys: C, D, E, F, G, A, B  (MIDI 60,62,64,65,67,69,71)
    Black keys: C#,D#,   F#,G#,A#    (MIDI 61,63,   66,68,70)

Implementation notes
--------------------
- Keys are plain QPushButtons with **manual geometry** (no layout),
  recalculated in resizeEvent so they stretch with the window.
- White keys are created first; black keys are created afterward and
  `raise_()`'d so they sit visually on top.
- Background is white; white keys use slightly off-white fill and a
  dark border so they stand out clearly.
- The public API is the same as before:

      PianoWidget(note_on_cb, note_off_cb)

  and it calls:

      note_on_cb(midi_note)
      note_off_cb(midi_note)

  on mouse press / release.
"""

from typing import Callable, List, Dict

from PyQt6 import QtWidgets, QtCore


class PianoWidget(QtWidgets.QWidget):
    """
    One-octave piano keyboard (C4–B4, MIDI 60–71).

    - White keys: large buttons across the full width.
    - Black keys: narrower buttons placed between white keys.

    Used by the main GUI as the bottom play surface.
    """

    def __init__(
        self,
        note_on_cb: Callable[[int], None],
        note_off_cb: Callable[[int], None],
        parent=None,
    ):
        super().__init__(parent)
        self.note_on_cb = note_on_cb
        self.note_off_cb = note_off_cb

        # We manage geometry manually, so no layout here
        self.setMinimumHeight(140)

        # Data structures to hold key widgets
        self.white_keys: List[Dict] = []
        self.black_keys: List[Dict] = []

        self._create_keys()

    # ------------------------------------------------------------------
    # key creation
    # ------------------------------------------------------------------

    def _create_keys(self) -> None:
        """
        Create white + black key QPushButtons and connect their signals.

        Geometry is handled later in resizeEvent.
        """
        # Clear any existing keys (if we ever recreate)
        for info in self.white_keys + self.black_keys:
            info["button"].deleteLater()
        self.white_keys.clear()
        self.black_keys.clear()

        # White key MIDI notes for C4–B4
        white_notes = [60, 62, 64, 65, 67, 69, 71]

        # Create white keys
        for note in white_notes:
            btn = QtWidgets.QPushButton(self)
            btn.setText("")  # purely visual
            btn.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)

            # Slightly off-white so they show against the global white bg
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #fdfdfd;
                    border: 2px solid #444444;
                    border-radius: 3px;
                }
                QPushButton:pressed {
                    background-color: #e0e0e0;
                }
            """)

            btn.pressed.connect(lambda n=note: self._on_key_pressed(n))
            btn.released.connect(lambda n=note: self._on_key_released(n))

            self.white_keys.append({"note": note, "button": btn})

        # Black key MIDI notes + their *left* white key index
        #   C# above between C (index 0) and D (1)  -> left index 0
        #   D# between D (1) and E (2)              -> left index 1
        #   F# between F (3) and G (4)              -> left index 3
        #   G# between G (4) and A (5)              -> left index 4
        #   A# between A (5) and B (6)              -> left index 5
        black_spec = [
            (61, 0),  # C#
            (63, 1),  # D#
            (66, 3),  # F#
            (68, 4),  # G#
            (70, 5),  # A#
        ]

        for note, left_index in black_spec:
            btn = QtWidgets.QPushButton(self)
            btn.setText("")
            btn.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)

            btn.setStyleSheet("""
                QPushButton {
                    background-color: black;
                    border: 2px solid #000000;
                    border-radius: 3px;
                }
                QPushButton:pressed {
                    background-color: #444444;
                }
            """)

            btn.pressed.connect(lambda n=note: self._on_key_pressed(n))
            btn.released.connect(lambda n=note: self._on_key_released(n))

            self.black_keys.append(
                {
                    "note": note,
                    "left_index": left_index,  # we layout based on this later
                    "button": btn,
                }
            )

        # Initial layout based on current size
        self._layout_keys()

    # ------------------------------------------------------------------
    # geometry / layout
    # ------------------------------------------------------------------

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._layout_keys()

    def _layout_keys(self) -> None:
        """
        Position white and black keys based on current widget size.
        """
        if not self.white_keys:
            return

        total_w = self.width()
        total_h = self.height()

        # Reserve a bit of top/bottom margin
        top_margin = 10
        bottom_margin = 5

        white_h = total_h - top_margin - bottom_margin
        white_w = total_w / len(self.white_keys)

        # --- layout white keys ---
        for idx, info in enumerate(self.white_keys):
            btn = info["button"]
            x = int(idx * white_w)
            y = top_margin
            w = int(white_w)
            h = int(white_h)
            btn.setGeometry(x, y, w, h)
            btn.lower()  # ensure white keys are underneath

        # --- layout black keys ---
        black_h = int(white_h * 0.6)
        black_w = int(white_w * 0.6)
        black_y = top_margin  # start at the same top as whites

        for info in self.black_keys:
            btn = info["button"]
            left_idx = info["left_index"]

            # Center the black key between left and next white key
            center_x = (left_idx + 1) * white_w
            x = int(center_x - black_w / 2)

            btn.setGeometry(x, black_y, black_w, black_h)
            btn.raise_()  # ensure black keys sit on top

    # ------------------------------------------------------------------
    # callbacks
    # ------------------------------------------------------------------

    def _on_key_pressed(self, note: int) -> None:
        if self.note_on_cb:
            self.note_on_cb(note)

    def _on_key_released(self, note: int) -> None:
        if self.note_off_cb:
            self.note_off_cb(note)
