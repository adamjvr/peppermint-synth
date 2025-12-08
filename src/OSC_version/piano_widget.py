#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
piano_widget.py
----------------------------------------------------------------------
25-key on-screen piano keyboard (PyQt6).

Range: C3–C5 inclusive  => MIDI 48..72  (25 keys total)

- White keys: C, D, E, F, G, A, B across that range (15 white keys)
- Black keys: C#, D#, F#, G#, A# (10 black keys), repeated over 2 octaves

The widget is still constructed the same way from the GUI:

    piano = PianoWidget(note_on_cb, note_off_cb)

and it will call:

    note_on_cb(midi_note)
    note_off_cb(midi_note)

when keys are pressed/released.
"""

from typing import Callable, List, Dict

from PyQt6 import QtWidgets, QtCore


# Pitch-class helpers (0 = C, 1 = C#, ..., 11 = B)
WHITE_PITCH_CLASSES = {0, 2, 4, 5, 7, 9, 11}
BLACK_PITCH_CLASSES = {1, 3, 6, 8, 10}


class PianoWidget(QtWidgets.QWidget):
    """
    25-key piano keyboard (C3–C5, MIDI 48–72).

    - White keys are large buttons spanning the width.
    - Black keys are narrower buttons drawn on top.

    Everything is manually laid out in resizeEvent so the keyboard scales
    with the window.
    """

    def __init__(
        self,
        note_on_cb: Callable[[int], None],
        note_off_cb: Callable[[int], None],
        parent=None,
        low_note: int = 48,
        high_note: int = 72,
    ):
        """
        Parameters
        ----------
        note_on_cb : Callable[[int], None]
            Called with MIDI note when a key is pressed.
        note_off_cb : Callable[[int], None]
            Called with MIDI note when a key is released.
        low_note : int
            Lowest MIDI note (default: 48 => C3).
        high_note : int
            Highest MIDI note (default: 72 => C5).
        """
        super().__init__(parent)
        self.note_on_cb = note_on_cb
        self.note_off_cb = note_off_cb
        self.low_note = int(low_note)
        self.high_note = int(high_note)

        # sanity: make sure the range starts on a white key so black placement
        # logic is simple (C3 is white, so default is fine)
        if (self.low_note % 12) not in WHITE_PITCH_CLASSES:
            raise ValueError("low_note must be a white key for this widget")

        self.setMinimumHeight(140)

        # Internal storage for key widgets
        # white_keys = [{"note": int, "button": QPushButton}, ...]
        # black_keys = [{"note": int, "left_index": int, "button": QPushButton}, ...]
        self.white_keys: List[Dict] = []
        self.black_keys: List[Dict] = []

        self._create_keys()

    # ------------------------------------------------------------------
    # key creation
    # ------------------------------------------------------------------

    def _create_keys(self) -> None:
        """
        Create all white and black key buttons based on [low_note, high_note].
        """
        # Clean up any old keys (if we ever rebuild)
        for info in self.white_keys + self.black_keys:
            info["button"].deleteLater()
        self.white_keys.clear()
        self.black_keys.clear()

        # First pass: create all white keys and remember their order
        # We'll also remember the last white key index to assign black keys.
        last_white_index = -1
        white_note_to_index: Dict[int, int] = {}

        # We walk through the note range and create buttons on the fly.
        for note in range(self.low_note, self.high_note + 1):
            pitch_class = note % 12

            if pitch_class in WHITE_PITCH_CLASSES:
                # --- white key ---
                btn = QtWidgets.QPushButton(self)
                btn.setText("")
                btn.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
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

                last_white_index += 1
                white_note_to_index[note] = last_white_index
                self.white_keys.append({"note": note, "button": btn})

        # Second pass: create black keys (using left white-key index)
        last_white_index = -1
        for note in range(self.low_note, self.high_note + 1):
            pitch_class = note % 12

            if pitch_class in WHITE_PITCH_CLASSES:
                last_white_index = white_note_to_index[note]
                continue

            if pitch_class in BLACK_PITCH_CLASSES:
                # This black key sits between the last white key and the next one.
                # We approximate by anchoring to the left white index.
                if last_white_index < 0:
                    continue  # shouldn't happen if low_note is white

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
                        "left_index": last_white_index,
                        "button": btn,
                    }
                )

        # Initial geometry
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

        top_margin = 10
        bottom_margin = 5

        white_h = total_h - top_margin - bottom_margin
        white_count = len(self.white_keys)
        white_w = total_w / white_count

        # --- layout white keys ---
        for idx, info in enumerate(self.white_keys):
            btn = info["button"]
            x = int(idx * white_w)
            y = top_margin
            w = int(white_w)
            h = int(white_h)
            btn.setGeometry(x, y, w, h)
            btn.lower()  # ensure white keys sit underneath

        # --- layout black keys ---
        black_h = int(white_h * 0.6)
        black_w = int(white_w * 0.6)
        black_y = top_margin

        for info in self.black_keys:
            btn = info["button"]
            left_idx = info["left_index"]

            # center black key between left white and the next one
            center_x = (left_idx + 1) * white_w
            x = int(center_x - black_w / 2)

            btn.setGeometry(x, black_y, black_w, black_h)
            btn.raise_()  # draw above whites

    # ------------------------------------------------------------------
    # callbacks
    # ------------------------------------------------------------------

    def _on_key_pressed(self, note: int) -> None:
        if self.note_on_cb:
            self.note_on_cb(note)

    def _on_key_released(self, note: int) -> None:
        if self.note_off_cb:
            self.note_off_cb(note)
