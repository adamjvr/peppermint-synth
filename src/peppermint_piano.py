#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
peppermint_piano.py
----------------------------------------------------------------------
25-key on-screen piano keyboard widget (C3–C5 inclusive).

- White keys laid out across the widget width
- Black keys overlayed in correct positions
- Emits callbacks: note_on_cb(midi_note), note_off_cb(midi_note)
"""

from typing import Callable, Dict, List

from PyQt6 import QtCore, QtWidgets


WHITE_PITCH_CLASSES = {0, 2, 4, 5, 7, 9, 11}
BLACK_PITCH_CLASSES = {1, 3, 6, 8, 10}


class PianoWidget(QtWidgets.QWidget):
    """
    Simple 25-key piano widget (C3=48 .. C5=72).
    """

    def __init__(
        self,
        note_on_cb: Callable[[int], None],
        note_off_cb: Callable[[int], None],
        parent=None,
        low_note: int = 48,
        high_note: int = 72,
    ) -> None:
        super().__init__(parent)

        self.note_on_cb = note_on_cb
        self.note_off_cb = note_off_cb
        self.low_note = int(low_note)
        self.high_note = int(high_note)

        if (self.low_note % 12) not in WHITE_PITCH_CLASSES:
            raise ValueError("low_note must be a white key (C, D, E, F, G, A, B).")

        self.setMinimumHeight(140)

        self.white_keys: List[Dict] = []
        self.black_keys: List[Dict] = []

        self._create_keys()

    # ------------------------------------------------------------------
    # Key creation
    # ------------------------------------------------------------------

    def _create_keys(self) -> None:
        # Clean up any existing buttons
        for info in self.white_keys + self.black_keys:
            info["button"].deleteLater()
        self.white_keys.clear()
        self.black_keys.clear()

        last_white_index = -1
        white_note_to_index: Dict[int, int] = {}

        # First pass: create white keys
        for note in range(self.low_note, self.high_note + 1):
            pitch_class = note % 12

            if pitch_class in WHITE_PITCH_CLASSES:
                btn = QtWidgets.QPushButton(self)
                btn.setText("")
                btn.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
                btn.setStyleSheet(
                    """
                    QPushButton {
                        background-color: #fdfdfd;
                        border: 2px solid #444444;
                        border-radius: 3px;
                    }
                    QPushButton:pressed {
                        background-color: #e0e0e0;
                    }
                    """
                )
                btn.pressed.connect(lambda n=note: self._on_key_pressed(n))
                btn.released.connect(lambda n=note: self._on_key_released(n))

                last_white_index += 1
                white_note_to_index[note] = last_white_index
                self.white_keys.append({"note": note, "button": btn})

        # Second pass: create black keys, anchored between neighboring whites
        last_white_index = -1
        for note in range(self.low_note, self.high_note + 1):
            pitch_class = note % 12

            if pitch_class in WHITE_PITCH_CLASSES:
                last_white_index = white_note_to_index[note]
                continue

            if pitch_class in BLACK_PITCH_CLASSES and last_white_index >= 0:
                btn = QtWidgets.QPushButton(self)
                btn.setText("")
                btn.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
                btn.setStyleSheet(
                    """
                    QPushButton {
                        background-color: black;
                        border: 2px solid #000000;
                        border-radius: 3px;
                    }
                    QPushButton:pressed {
                        background-color: #444444;
                    }
                    """
                )
                btn.pressed.connect(lambda n=note: self._on_key_pressed(n))
                btn.released.connect(lambda n=note: self._on_key_released(n))

                self.black_keys.append(
                    {"note": note, "left_index": last_white_index, "button": btn}
                )

        self._layout_keys()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._layout_keys()

    def _layout_keys(self) -> None:
        if not self.white_keys:
            return

        total_w = self.width()
        total_h = self.height()

        top_margin = 10
        bottom_margin = 5
        white_h = total_h - top_margin - bottom_margin
        white_count = len(self.white_keys)
        white_w = total_w / white_count

        # White keys
        for idx, info in enumerate(self.white_keys):
            btn = info["button"]
            x = int(idx * white_w)
            y = top_margin
            w = int(white_w)
            h = int(white_h)
            btn.setGeometry(x, y, w, h)
            btn.lower()

        # Black keys
        black_h = int(white_h * 0.6)
        black_w = int(white_w * 0.6)
        black_y = top_margin

        for info in self.black_keys:
            btn = info["button"]
            left_idx = info["left_index"]
            center_x = (left_idx + 1) * white_w
            x = int(center_x - black_w / 2)
            btn.setGeometry(x, black_y, black_w, black_h)
            btn.raise_()

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def _on_key_pressed(self, note: int) -> None:
        if self.note_on_cb:
            self.note_on_cb(note)

    def _on_key_released(self, note: int) -> None:
        if self.note_off_cb:
            self.note_off_cb(note)
