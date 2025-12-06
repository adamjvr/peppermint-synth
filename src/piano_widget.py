#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
piano_widget.py
----------------------------------------------------------------------
On-screen piano keyboard widget (PyQt6).

CLASSES
-------
- PianoKeyButton: A single key (white or black).
- PianoWidget:    A one-octave keyboard (C4–B4).

This widget is UI-only and does not know about MIDI or SuperCollider.
It simply calls note_on_cb(note) / note_off_cb(note) when keys are
pressed/released.
"""

from typing import Callable

from PyQt6 import QtWidgets, QtCore


class PianoKeyButton(QtWidgets.QPushButton):
    """
    A single piano key (white or black).

    Responsibilities:
    -----------------
    - Visual representation (size, color).
    - Emit callbacks on press/release for a given MIDI note.
    """

    def __init__(
        self,
        note: int,
        is_black: bool,
        note_on_cb: Callable[[int], None],
        note_off_cb: Callable[[int], None],
        parent=None,
    ):
        """
        Parameters
        ----------
        note : int
            MIDI note number associated with this key.
        is_black : bool
            True if black key, False if white.
        note_on_cb : Callable[[int], None]
            Called when key is pressed.
        note_off_cb : Callable[[int], None]
            Called when key is released.
        parent : QWidget, optional
        """
        super().__init__(parent)
        self.note = note
        self.is_black = is_black
        self.note_on_cb = note_on_cb
        self.note_off_cb = note_off_cb

        self.setText("")
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)

        if self.is_black:
            self.setFixedSize(24, 60)
            self.setStyleSheet("""
                QPushButton {
                    background-color: black;
                    border: 1px solid #333333;
                    border-radius: 2px;
                }
                QPushButton:pressed {
                    background-color: #444444;
                }
            """)
            self.raise_()
        else:
            self.setFixedSize(30, 100)
            self.setStyleSheet("""
                QPushButton {
                    background-color: white;
                    border: 1px solid #555555;
                    border-radius: 2px;
                }
                QPushButton:pressed {
                    background-color: #dddddd;
                }
            """)

        self.pressed.connect(self._on_pressed)
        self.released.connect(self._on_released)

    def _on_pressed(self) -> None:
        if self.note_on_cb:
            self.note_on_cb(self.note)

    def _on_released(self) -> None:
        if self.note_off_cb:
            self.note_off_cb(self.note)


class PianoWidget(QtWidgets.QWidget):
    """
    One-octave piano keyboard (C4–B4, MIDI 60–71).

    Layout:
    -------
    - White keys in a row.
    - Black keys on top using a stacked layout.

    We approximate the black-key spacing with simple spacer widgets.
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

        self._build_ui()

    def _build_ui(self) -> None:
        outer_layout = QtWidgets.QHBoxLayout()
        outer_layout.setContentsMargins(10, 0, 10, 0)
        outer_layout.setSpacing(0)
        self.setLayout(outer_layout)

        container = QtWidgets.QWidget()
        container.setMinimumHeight(110)
        container.setMaximumHeight(110)

        # White keys layout
        white_layout = QtWidgets.QHBoxLayout()
        white_layout.setContentsMargins(0, 0, 0, 0)
        white_layout.setSpacing(1)

        # Black keys layout (on top)
        black_layout = QtWidgets.QHBoxLayout()
        black_layout.setContentsMargins(15, 0, 0, 0)
        black_layout.setSpacing(1)

        white_notes = [60, 62, 64, 65, 67, 69, 71]  # C, D, E, F, G, A, B
        black_notes = [
            (61, 0.7),  # C#
            (63, 1.7),  # D#
            (66, 3.7),  # F#
            (68, 4.7),  # G#
            (70, 5.7),  # A#
        ]

        # Build white keys
        for note in white_notes:
            key = PianoKeyButton(
                note=note,
                is_black=False,
                note_on_cb=self.note_on_cb,
                note_off_cb=self.note_off_cb,
            )
            white_layout.addWidget(key)

        # Build black keys using simple spacers
        for (note, stretch_factor) in black_notes:
            spacer = QtWidgets.QWidget()
            spacer.setFixedWidth(int(30 * (stretch_factor - 1.0)))
            black_layout.addWidget(spacer)

            key = PianoKeyButton(
                note=note,
                is_black=True,
                note_on_cb=self.note_on_cb,
                note_off_cb=self.note_off_cb,
            )
            black_layout.addWidget(key)

        white_widget = QtWidgets.QWidget()
        white_widget.setLayout(white_layout)

        black_widget = QtWidgets.QWidget()
        black_widget.setLayout(black_layout)

        stack = QtWidgets.QStackedLayout()
        stack.setStackingMode(QtWidgets.QStackedLayout.StackingMode.StackAll)
        stack.addWidget(white_widget)
        stack.addWidget(black_widget)

        container.setLayout(stack)
        outer_layout.addWidget(container)
