#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gui_main.py
----------------------------------------------------------------------
SynthControlWindow (PyQt6)

Main front-panel GUI for the SuperCollider-based synth.

This version makes ALL continuous parameters (VCO, Filter, LFO, ENV, AMP)
use the exact same "ParameterSlider" widget, so they share:

- Vertical ARP-style fader look.
- Label + current numeric value.
- Colored handle on white background.

Also includes:
- Mono / Poly selector
- LFO target selector
- Note selector + Note On / Note Off
- MIDI input selector + Refresh button
- Preset save/load via JSON
- On-screen piano keyboard
"""

from __future__ import annotations

from typing import Dict

from PyQt6 import QtWidgets, QtCore

from sc_synth_controller import SuperColliderSynthController
from midi_input import MidiInputManager
from piano_widget import PianoWidget
from preset_manager import SynthPresetManager


class ParameterSlider(QtWidgets.QWidget):
    """
    ParameterSlider
    ===============

    A reusable widget for a single continuous synth parameter:

        [Label + current value]
        [   vertical slider    ]

    - `param_name` is the SynthDef control name (e.g. "cutoff").
    - `min_val` / `max_val` define the numeric range.
    - `default` is the initial value.
    - `color` controls the handle color.

    The enclosing SynthControlWindow will:
      - read/write the slider value via methods
      - forward changes to the SuperColliderSynthController.
    """

    valueChanged = QtCore.pyqtSignal(str, float)  # (param_name, value)

    def __init__(
        self,
        label_text: str,
        param_name: str,
        min_val: float,
        max_val: float,
        default: float,
        color: str,
        parent=None,
    ):
        super().__init__(parent)

        self.param_name = param_name
        self.min_val = float(min_val)
        self.max_val = float(max_val)

        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.setLayout(layout)

        # Label shows "name + current value"
        self.label = QtWidgets.QLabel()
        self.label.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)
        self.label.setStyleSheet("color: black;")
        font = self.label.font()
        font.setPointSize(9)
        self.label.setFont(font)

        # Vertical slider
        self.slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Vertical)
        self.slider.setRange(0, 1000)

        # Style: ARP-style colored handle on grey track
        self.slider.setStyleSheet(f"""
            QSlider::groove:vertical {{
                background: #e0e0e0;
                border: 1px solid #b0b0b0;
                width: 10px;
                margin: 5px 0;
            }}
            QSlider::handle:vertical {{
                background: {color};
                border: 1px solid #444444;
                height: 16px;
                margin: -4px -8px;
                border-radius: 3px;
            }}
        """)

        layout.addWidget(self.label)
        layout.addWidget(self.slider, 1, QtCore.Qt.AlignmentFlag.AlignHCenter)

        # store for label updates
        self._base_label_text = label_text

        # Init value
        self.set_value(default, emit=False)

        self.slider.valueChanged.connect(self._on_slider_changed)

    # --------------------------------------------------------------
    # value mapping helpers
    # --------------------------------------------------------------

    def _slider_to_value(self, pos: int) -> float:
        norm = pos / 1000.0
        return self.min_val + norm * (self.max_val - self.min_val)

    def _value_to_slider(self, value: float) -> int:
        clamped = max(self.min_val, min(self.max_val, float(value)))
        norm = (clamped - self.min_val) / (self.max_val - self.min_val)
        return int(norm * 1000)

    # --------------------------------------------------------------
    # public API
    # --------------------------------------------------------------

    def set_value(self, value: float, emit: bool = True) -> None:
        """
        Set the parameter value and update slider + label.

        If emit=False, the valueChanged signal is not emitted (useful
        when restoring a preset without re-triggering logic).
        """
        slider_pos = self._value_to_slider(value)
        self.slider.blockSignals(True)
        self.slider.setValue(slider_pos)
        self.slider.blockSignals(False)

        actual_val = self._slider_to_value(slider_pos)
        self.label.setText(f"{self._base_label_text}\n{actual_val:.3f}")

        if emit:
            self.valueChanged.emit(self.param_name, actual_val)

    def get_value(self) -> float:
        return self._slider_to_value(self.slider.value())

    # --------------------------------------------------------------
    # internal slot
    # --------------------------------------------------------------

    def _on_slider_changed(self, pos: int) -> None:
        value = self._slider_to_value(pos)
        self.label.setText(f"{self._base_label_text}\n{value:.3f}")
        self.valueChanged.emit(self.param_name, value)


class SynthControlWindow(QtWidgets.QWidget):
    """
    SynthControlWindow
    ==================

    Main synth front panel.

    Owns:
    - SuperColliderSynthController (backend synth engine control)
    - MidiInputManager              (hardware / virtual MIDI in)
    - SynthPresetManager            (JSON presets)

    Composed of:
    - ParameterSlider widgets for all continuous controls
    - Combo boxes/buttons for mode, LFO target, note, MIDI port
    - PianoWidget for on-screen keyboard
    """

    def __init__(self, sc_controller: SuperColliderSynthController, parent=None):
        super().__init__(parent)

        self.sc = sc_controller

        # Explicitly set white bg + black text so labels always visible
        self.setWindowTitle("PyQt6 SuperCollider Synth – ARP-style GUI")
        self.setStyleSheet("background-color: white; color: black;")

        # Param sliders by name
        self.param_sliders: Dict[str, ParameterSlider] = {}

        # MIDI + presets
        self.midi_manager: MidiInputManager | None = None
        self.preset_manager = SynthPresetManager()

        # Build full UI and attach MIDI
        self._build_ui()
        self._setup_midi()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        main_layout = QtWidgets.QVBoxLayout()
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        self.setLayout(main_layout)

        # ------------------------------
        # Row 1: mode / LFO target / note / Note On/Off
        # ------------------------------
        top_layout = QtWidgets.QHBoxLayout()

        mode_lbl = QtWidgets.QLabel("Mode:")
        mode_lbl.setStyleSheet("color: black;")

        self.poly_mode_combo = QtWidgets.QComboBox()
        self.poly_mode_combo.addItem("Mono", False)
        self.poly_mode_combo.addItem("Poly", True)
        self.poly_mode_combo.currentIndexChanged.connect(
            self._handle_poly_mode_changed
        )

        lfo_lbl = QtWidgets.QLabel("LFO Target:")
        lfo_lbl.setStyleSheet("color: black;")

        self.lfo_target_combo = QtWidgets.QComboBox()
        self.lfo_target_combo.addItem("LFO → Pitch", 0)
        self.lfo_target_combo.addItem("LFO → Filter", 1)
        self.lfo_target_combo.currentIndexChanged.connect(
            self._handle_lfo_target_changed
        )

        note_lbl = QtWidgets.QLabel("Note:")
        note_lbl.setStyleSheet("color: black;")

        self.note_combo = QtWidgets.QComboBox()
        # store MIDI notes in .currentData()
        self.note_combo.addItem("A2 (110 Hz)", 45)
        self.note_combo.addItem("A3 (220 Hz)", 57)
        self.note_combo.addItem("A4 (440 Hz)", 69)
        self.note_combo.addItem("A1 (55 Hz)", 33)

        self.note_on_button = QtWidgets.QPushButton("Note On")
        self.note_off_button = QtWidgets.QPushButton("Note Off")
        self.note_on_button.clicked.connect(self._handle_note_on_button)
        self.note_off_button.clicked.connect(self._handle_note_off_button)

        top_layout.addWidget(mode_lbl)
        top_layout.addWidget(self.poly_mode_combo)
        top_layout.addSpacing(20)
        top_layout.addWidget(lfo_lbl)
        top_layout.addWidget(self.lfo_target_combo)
        top_layout.addStretch(1)
        top_layout.addWidget(note_lbl)
        top_layout.addWidget(self.note_combo)
        top_layout.addWidget(self.note_on_button)
        top_layout.addWidget(self.note_off_button)

        main_layout.addLayout(top_layout)

        # ------------------------------
        # Row 2: MIDI selector + presets
        # ------------------------------
        second_layout = QtWidgets.QHBoxLayout()

        midi_lbl = QtWidgets.QLabel("MIDI In:")
        midi_lbl.setStyleSheet("color: black;")

        self.midi_port_combo = QtWidgets.QComboBox()
        self.midi_refresh_button = QtWidgets.QPushButton("Refresh MIDI")
        self.midi_refresh_button.clicked.connect(self._handle_midi_refresh)
        self.midi_port_combo.currentIndexChanged.connect(
            self._handle_midi_port_changed
        )

        self.save_preset_button = QtWidgets.QPushButton("Save Preset")
        self.load_preset_button = QtWidgets.QPushButton("Load Preset")
        self.save_preset_button.clicked.connect(self._handle_save_preset)
        self.load_preset_button.clicked.connect(self._handle_load_preset)

        second_layout.addWidget(midi_lbl)
        second_layout.addWidget(self.midi_port_combo)
        second_layout.addWidget(self.midi_refresh_button)
        second_layout.addStretch(1)
        second_layout.addWidget(self.save_preset_button)
        second_layout.addWidget(self.load_preset_button)

        main_layout.addLayout(second_layout)

        # ------------------------------
        # Row 3: vertical slider columns
        # ------------------------------
        panel_layout = QtWidgets.QHBoxLayout()
        panel_layout.setSpacing(25)
        main_layout.addLayout(panel_layout)

        def add_param_slider_column(title: str) -> QtWidgets.QVBoxLayout:
            """
            Utility: create a column with a bold header for a group
            of ParameterSlider widgets.
            """
            col = QtWidgets.QVBoxLayout()
            header = QtWidgets.QLabel(title)
            header.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)
            header.setStyleSheet("font-weight: bold; color: black;")
            col.addWidget(header)
            return col

        def add_param_slider(
            col_layout: QtWidgets.QVBoxLayout,
            label_text: str,
            param_name: str,
            min_val: float,
            max_val: float,
            default: float,
            color: str,
        ):
            slider = ParameterSlider(
                label_text=label_text,
                param_name=param_name,
                min_val=min_val,
                max_val=max_val,
                default=default,
                color=color,
            )
            slider.valueChanged.connect(self._handle_param_slider_changed)
            self.param_sliders[param_name] = slider
            col_layout.addWidget(slider, 1)

        # VCO
        vco_col = add_param_slider_column("VCO")
        add_param_slider(vco_col, "VCO Mix\n(0=VCO1, 1=VCO2)", "vco_mix",
                         0.0, 1.0, 0.5, "#3f88ff")
        add_param_slider(vco_col, "VCO1 Wave\n(0=saw, 1=pulse)", "vco1_wave",
                         0.0, 1.0, 0.0, "#3f88ff")
        add_param_slider(vco_col, "VCO2 Wave\n(0=saw, 1=pulse)", "vco2_wave",
                         0.0, 1.0, 0.0, "#3f88ff")
        add_param_slider(vco_col, "Detune Ratio", "detune",
                         0.98, 1.08, 1.01, "#3f88ff")
        panel_layout.addLayout(vco_col)

        # FILTER
        filt_col = add_param_slider_column("FILTER")
        add_param_slider(filt_col, "Cutoff (Hz)", "cutoff",
                         100.0, 8000.0, 1200.0, "#ff8800")
        add_param_slider(filt_col, "Resonance (0–1)", "res",
                         0.0, 1.0, 0.2, "#ff8800")
        add_param_slider(filt_col, "Filter Env Amount", "env_amt",
                         0.0, 1.0, 0.5, "#ff8800")
        add_param_slider(filt_col, "Noise Mix (0–1)", "noise_mix",
                         0.0, 1.0, 0.0, "#ff8800")
        panel_layout.addLayout(filt_col)

        # LFO
        lfo_col = add_param_slider_column("LFO")
        add_param_slider(lfo_col, "LFO Freq (Hz)", "lfo_freq",
                         0.1, 20.0, 5.0, "#aa44ff")
        add_param_slider(lfo_col, "LFO Depth (0–1)", "lfo_depth",
                         0.0, 1.0, 0.0, "#aa44ff")
        panel_layout.addLayout(lfo_col)

        # ENV
        env_col = add_param_slider_column("ENV (ADSR)")
        add_param_slider(env_col, "Attack (s)", "atk",
                         0.001, 2.0, 0.01, "#44aa44")
        add_param_slider(env_col, "Decay (s)", "dec",
                         0.01, 2.0, 0.1, "#44aa44")
        add_param_slider(env_col, "Sustain (0–1)", "sus",
                         0.0, 1.0, 0.7, "#44aa44")
        add_param_slider(env_col, "Release (s)", "rel",
                         0.01, 4.0, 0.3, "#44aa44")
        panel_layout.addLayout(env_col)

        # AMP
        amp_col = add_param_slider_column("AMP")
        add_param_slider(amp_col, "Level", "amp",
                         0.0, 0.8, 0.2, "#222222")
        panel_layout.addLayout(amp_col)

        # ------------------------------
        # Row 4: Piano keyboard
        # ------------------------------
        self.piano_widget = PianoWidget(
            note_on_cb=self._handle_piano_note_on,
            note_off_cb=self._handle_piano_note_off,
        )
        main_layout.addWidget(self.piano_widget)

    # ------------------------------------------------------------------
    # MIDI setup
    # ------------------------------------------------------------------

    def _setup_midi(self) -> None:
        self.midi_manager = MidiInputManager(
            note_on_cb=self.sc.note_on_midi,
            note_off_cb=self.sc.note_off_midi,
            auto_open_first=True,
        )
        self._populate_midi_ports()

    def _populate_midi_ports(self) -> None:
        if self.midi_manager is None:
            return

        ports = self.midi_manager.list_input_ports()
        current_name = self.midi_manager.current_port_name

        self.midi_port_combo.blockSignals(True)
        self.midi_port_combo.clear()
        for name in ports:
            self.midi_port_combo.addItem(name, name)

        if current_name and current_name in ports:
            idx = ports.index(current_name)
            self.midi_port_combo.setCurrentIndex(idx)

        self.midi_port_combo.blockSignals(False)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _handle_poly_mode_changed(self) -> None:
        is_poly = bool(self.poly_mode_combo.currentData())
        self.sc.set_poly_mode(is_poly)

    def _handle_lfo_target_changed(self) -> None:
        target = int(self.lfo_target_combo.currentData())
        self.sc.set_param("lfo_target", float(target))

    def _handle_param_slider_changed(self, param_name: str, value: float) -> None:
        """
        Called whenever ANY ParameterSlider's value changes.
        """
        self.sc.set_param(param_name, value)

    def _handle_note_on_button(self) -> None:
        midi_note = int(self.note_combo.currentData())
        self.sc.note_on_midi(midi_note, velocity=100)

        # Push current panel state into the active voice
        for name, slider in self.param_sliders.items():
            self.sc.set_param(name, slider.get_value())
        target = int(self.lfo_target_combo.currentData())
        self.sc.set_param("lfo_target", float(target))

    def _handle_note_off_button(self) -> None:
        self.sc.note_off_all()

    def _handle_piano_note_on(self, midi_note: int) -> None:
        self.sc.note_on_midi(midi_note, velocity=100)
        for name, slider in self.param_sliders.items():
            self.sc.set_param(name, slider.get_value())
        target = int(self.lfo_target_combo.currentData())
        self.sc.set_param("lfo_target", float(target))

    def _handle_piano_note_off(self, midi_note: int) -> None:
        self.sc.note_off_midi(midi_note)

    def _handle_midi_refresh(self) -> None:
        self._populate_midi_ports()

    def _handle_midi_port_changed(self) -> None:
        if self.midi_manager is None:
            return
        port_name = self.midi_port_combo.currentData()
        if port_name:
            self.midi_manager.open_port_by_name(port_name)

    # ------------------------------------------------------------------
    # Preset save/load
    # ------------------------------------------------------------------

    def _handle_save_preset(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save Preset",
            "",
            "JSON Files (*.json)",
        )
        if not path:
            return

        preset = {
            "sliders": {},
            "poly_mode": bool(self.poly_mode_combo.currentData()),
            "lfo_target": int(self.lfo_target_combo.currentData()),
            "note_index": int(self.note_combo.currentIndex()),
            "midi_port": self.midi_manager.current_port_name if self.midi_manager else None,
        }

        for name, slider in self.param_sliders.items():
            preset["sliders"][name] = slider.get_value()

        try:
            self.preset_manager.save_preset_to_file(path, preset)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Error Saving Preset", str(exc))

    def _handle_load_preset(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Load Preset",
            "",
            "JSON Files (*.json)",
        )
        if not path:
            return

        try:
            preset = self.preset_manager.load_preset_from_file(path)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Error Loading Preset", str(exc))
            return

        # Mode
        poly_mode = bool(preset.get("poly_mode", False))
        self.poly_mode_combo.setCurrentIndex(1 if poly_mode else 0)

        # LFO target
        lfo_target = int(preset.get("lfo_target", 0))
        self.lfo_target_combo.setCurrentIndex(0 if lfo_target == 0 else 1)

        # Note selection
        note_index = int(preset.get("note_index", 0))
        if 0 <= note_index < self.note_combo.count():
            self.note_combo.setCurrentIndex(note_index)

        # MIDI port
        midi_port = preset.get("midi_port")
        if self.midi_manager and midi_port:
            ports = self.midi_manager.list_input_ports()
            if midi_port in ports:
                self.midi_manager.open_port_by_name(midi_port)
            self._populate_midi_ports()

        # Sliders
        sliders_data = preset.get("sliders", {})
        for name, value in sliders_data.items():
            slider = self.param_sliders.get(name)
            if slider is None:
                continue
            slider.set_value(float(value), emit=False)

        # After loading, push all param values into active voices
        for name, slider in self.param_sliders.items():
            self.sc.set_param(name, slider.get_value())
        self.sc.set_param("lfo_target", float(self.lfo_target_combo.currentData()))
