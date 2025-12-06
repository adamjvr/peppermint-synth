#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gui_main.py
----------------------------------------------------------------------
SynthControlWindow (PyQt6)

The main GUI front panel for the SuperCollider-based synth.

FEATURES
--------
- ARP Odyssey-style vertical sliders with colored handles.
- Mono / Poly mode toggle.
- LFO target selector (Pitch vs Filter).
- Note selector + Note On / Note Off.
- MIDI input port selector (with refresh).
- On-screen piano keyboard.
- Preset save/load via JSON (using SynthPresetManager).

This module stays focused on UI logic and delegates:
- OSC & voice allocation -> SuperColliderSynthController
- MIDI plumbing          -> MidiInputManager
- Preset serialization   -> SynthPresetManager
"""

from __future__ import annotations

from typing import Dict

from PyQt6 import QtWidgets, QtCore

from sc_synth_controller import SuperColliderSynthController
from midi_input import MidiInputManager
from piano_widget import PianoWidget
from preset_manager import SynthPresetManager


class SynthControlWindow(QtWidgets.QWidget):
    """
    SynthControlWindow
    ==================

    High-level responsibilities:
    ----------------------------
    - Build the synth-like GUI with vertical sliders and keyboard.
    - Keep track of slider values and map them to SynthDef params.
    - Handle user gestures (buttons, piano clicks, MIDI port selection).
    - Talk to:
        * SuperColliderSynthController (for note/param events)
        * MidiInputManager (for external MIDI)
        * SynthPresetManager (for presets)
    """

    def __init__(self, sc_controller: SuperColliderSynthController, parent=None):
        super().__init__(parent)

        self.sc = sc_controller

        self.setWindowTitle("PyQt6 SuperCollider Synth – ARP-style GUI")
        self.setStyleSheet("background-color: white;")

        # Slider bookkeeping: name -> QSlider / QLabel / range meta
        self.sliders: Dict[str, QtWidgets.QSlider] = {}
        self.slider_labels: Dict[str, QtWidgets.QLabel] = {}
        self.slider_meta: Dict[str, Dict[str, float]] = {}

        # MIDI + presets
        self.midi_manager: MidiInputManager | None = None
        self.preset_manager = SynthPresetManager()

        # Build the UI first
        self._build_ui()
        # Then attach MIDI
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
        # Top row: mode, LFO target, note, note on/off
        # ------------------------------
        top_layout = QtWidgets.QHBoxLayout()

        self.poly_mode_combo = QtWidgets.QComboBox()
        self.poly_mode_combo.addItem("Mono", False)
        self.poly_mode_combo.addItem("Poly", True)
        self.poly_mode_combo.currentIndexChanged.connect(self._handle_poly_mode_changed)

        self.lfo_target_combo = QtWidgets.QComboBox()
        self.lfo_target_combo.addItem("LFO → Pitch", 0)
        self.lfo_target_combo.addItem("LFO → Filter", 1)
        self.lfo_target_combo.currentIndexChanged.connect(self._handle_lfo_target_changed)

        self.note_combo = QtWidgets.QComboBox()
        # store MIDI notes as data
        self.note_combo.addItem("A2 (110 Hz)", 45)
        self.note_combo.addItem("A3 (220 Hz)", 57)
        self.note_combo.addItem("A4 (440 Hz)", 69)
        self.note_combo.addItem("A1 (55 Hz)", 33)

        self.note_on_button = QtWidgets.QPushButton("Note On")
        self.note_off_button = QtWidgets.QPushButton("Note Off")
        self.note_on_button.clicked.connect(self._handle_note_on_button)
        self.note_off_button.clicked.connect(self._handle_note_off_button)

        top_layout.addWidget(QtWidgets.QLabel("Mode:"))
        top_layout.addWidget(self.poly_mode_combo)
        top_layout.addSpacing(20)
        top_layout.addWidget(QtWidgets.QLabel("LFO Target:"))
        top_layout.addWidget(self.lfo_target_combo)
        top_layout.addStretch(1)
        top_layout.addWidget(QtWidgets.QLabel("Note:"))
        top_layout.addWidget(self.note_combo)
        top_layout.addWidget(self.note_on_button)
        top_layout.addWidget(self.note_off_button)

        main_layout.addLayout(top_layout)

        # ------------------------------
        # Second row: MIDI port selector + preset buttons
        # ------------------------------
        second_layout = QtWidgets.QHBoxLayout()

        self.midi_port_combo = QtWidgets.QComboBox()
        self.midi_refresh_button = QtWidgets.QPushButton("Refresh MIDI")
        self.midi_refresh_button.clicked.connect(self._handle_midi_refresh)

        self.midi_port_combo.currentIndexChanged.connect(self._handle_midi_port_changed)

        self.save_preset_button = QtWidgets.QPushButton("Save Preset")
        self.load_preset_button = QtWidgets.QPushButton("Load Preset")
        self.save_preset_button.clicked.connect(self._handle_save_preset)
        self.load_preset_button.clicked.connect(self._handle_load_preset)

        second_layout.addWidget(QtWidgets.QLabel("MIDI In:"))
        second_layout.addWidget(self.midi_port_combo)
        second_layout.addWidget(self.midi_refresh_button)
        second_layout.addStretch(1)
        second_layout.addWidget(self.save_preset_button)
        second_layout.addWidget(self.load_preset_button)

        main_layout.addLayout(second_layout)

        # ------------------------------
        # Middle: vertical slider columns
        # ------------------------------
        panel_layout = QtWidgets.QHBoxLayout()
        panel_layout.setSpacing(25)
        main_layout.addLayout(panel_layout)

        def add_vert_slider(
            column_layout: QtWidgets.QVBoxLayout,
            label_text: str,
            param_name: str,
            min_val: float,
            max_val: float,
            default: float,
            color: str,
        ) -> None:
            label = QtWidgets.QLabel(f"{label_text}\n{default:.3f}")
            label.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)
            font = label.font()
            font.setPointSize(9)
            label.setFont(font)

            slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Vertical)
            slider.setMinimum(0)
            slider.setMaximum(1000)

            slider.param_name = param_name
            slider.min_val = float(min_val)
            slider.max_val = float(max_val)

            self.sliders[param_name] = slider
            self.slider_labels[param_name] = label
            self.slider_meta[param_name] = {
                "label_text": label_text,
                "min_val": float(min_val),
                "max_val": float(max_val),
            }

            norm = (float(default) - slider.min_val) / (slider.max_val - slider.min_val)
            slider.setValue(int(norm * 1000))

            slider.setStyleSheet(f"""
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

            slider.valueChanged.connect(self._handle_slider_change)

            column_layout.addWidget(label)
            column_layout.addWidget(slider, 1, QtCore.Qt.AlignmentFlag.AlignHCenter)

        # VCO column
        vco_col = QtWidgets.QVBoxLayout()
        vco_header = QtWidgets.QLabel("VCO")
        vco_header.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)
        vco_header.setStyleSheet("font-weight: bold;")
        vco_col.addWidget(vco_header)

        add_vert_slider(vco_col, "VCO Mix\n(0=1,1=2)", "vco_mix", 0.0, 1.0, 0.5, "#3f88ff")
        add_vert_slider(vco_col, "VCO1\nWave", "vco1_wave", 0.0, 1.0, 0.0, "#3f88ff")
        add_vert_slider(vco_col, "VCO2\nWave", "vco2_wave", 0.0, 1.0, 0.0, "#3f88ff")
        add_vert_slider(vco_col, "Detune\nRatio", "detune", 0.98, 1.08, 1.01, "#3f88ff")
        panel_layout.addLayout(vco_col)

        # FILTER column
        filt_col = QtWidgets.QVBoxLayout()
        filt_header = QtWidgets.QLabel("FILTER")
        filt_header.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)
        filt_header.setStyleSheet("font-weight: bold;")
        filt_col.addWidget(filt_header)

        add_vert_slider(filt_col, "Cutoff\n(Hz)", "cutoff", 100.0, 8000.0, 1200.0, "#ff8800")
        add_vert_slider(filt_col, "Resonance", "res", 0.0, 1.0, 0.2, "#ff8800")
        add_vert_slider(filt_col, "Env Amt", "env_amt", 0.0, 1.0, 0.5, "#ff8800")
        add_vert_slider(filt_col, "Noise\nMix", "noise_mix", 0.0, 1.0, 0.0, "#ff8800")
        panel_layout.addLayout(filt_col)

        # LFO column
        lfo_col = QtWidgets.QVBoxLayout()
        lfo_header = QtWidgets.QLabel("LFO")
        lfo_header.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)
        lfo_header.setStyleSheet("font-weight: bold;")
        lfo_col.addWidget(lfo_header)

        add_vert_slider(lfo_col, "LFO\nFreq", "lfo_freq", 0.1, 20.0, 5.0, "#aa44ff")
        add_vert_slider(lfo_col, "LFO\nDepth", "lfo_depth", 0.0, 1.0, 0.0, "#aa44ff")
        panel_layout.addLayout(lfo_col)

        # ENV column
        env_col = QtWidgets.QVBoxLayout()
        env_header = QtWidgets.QLabel("ENV (ADSR)")
        env_header.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)
        env_header.setStyleSheet("font-weight: bold;")
        env_col.addWidget(env_header)

        add_vert_slider(env_col, "Attack\n(s)", "atk", 0.001, 2.0, 0.01, "#44aa44")
        add_vert_slider(env_col, "Decay\n(s)", "dec", 0.01, 2.0, 0.1, "#44aa44")
        add_vert_slider(env_col, "Sustain", "sus", 0.0, 1.0, 0.7, "#44aa44")
        add_vert_slider(env_col, "Release\n(s)", "rel", 0.01, 4.0, 0.3, "#44aa44")
        panel_layout.addLayout(env_col)

        # AMP column
        amp_col = QtWidgets.QVBoxLayout()
        amp_header = QtWidgets.QLabel("AMP")
        amp_header.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)
        amp_header.setStyleSheet("font-weight: bold;")
        amp_col.addWidget(amp_header)

        add_vert_slider(amp_col, "Level", "amp", 0.0, 0.8, 0.2, "#222222")
        panel_layout.addLayout(amp_col)

        # ------------------------------
        # Bottom: piano keyboard
        # ------------------------------
        self.piano_widget = PianoWidget(
            note_on_cb=self._handle_piano_note_on,
            note_off_cb=self._handle_piano_note_off,
        )
        main_layout.addWidget(self.piano_widget)

    # ------------------------------------------------------------------
    # MIDI setup + refresh
    # ------------------------------------------------------------------

    def _setup_midi(self) -> None:
        """
        Initialize MidiInputManager and populate the port combo box.
        """
        self.midi_manager = MidiInputManager(
            note_on_cb=self.sc.note_on_midi,
            note_off_cb=self.sc.note_off_midi,
            auto_open_first=True,
        )
        self._populate_midi_ports()

    def _populate_midi_ports(self) -> None:
        """
        Refresh MIDI port combo box from MidiInputManager.list_input_ports().
        """
        if self.midi_manager is None:
            return

        ports = self.midi_manager.list_input_ports()
        current_name = self.midi_manager.current_port_name

        self.midi_port_combo.blockSignals(True)
        self.midi_port_combo.clear()

        for name in ports:
            self.midi_port_combo.addItem(name, name)

        # Re-select current port if still present
        if current_name and current_name in ports:
            idx = ports.index(current_name)
            self.midi_port_combo.setCurrentIndex(idx)

        self.midi_port_combo.blockSignals(False)

    # ------------------------------------------------------------------
    # Slider helpers
    # ------------------------------------------------------------------

    def _slider_to_value(self, slider: QtWidgets.QSlider) -> float:
        norm = slider.value() / 1000.0
        return slider.min_val + norm * (slider.max_val - slider.min_val)

    def _set_slider_from_value(self, slider: QtWidgets.QSlider, value: float) -> None:
        min_val = slider.min_val
        max_val = slider.max_val
        clamped = max(min_val, min(max_val, value))
        norm = (clamped - min_val) / (max_val - min_val)
        slider.setValue(int(norm * 1000))

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _handle_poly_mode_changed(self) -> None:
        is_poly = bool(self.poly_mode_combo.currentData())
        self.sc.set_poly_mode(is_poly)

    def _handle_lfo_target_changed(self) -> None:
        target = int(self.lfo_target_combo.currentData())
        self.sc.set_param("lfo_target", float(target))

    def _handle_slider_change(self) -> None:
        slider = self.sender()
        if not hasattr(slider, "param_name"):
            return
        param_name = slider.param_name
        value = self._slider_to_value(slider)

        meta = self.slider_meta.get(param_name, {})
        base_label = meta.get("label_text", param_name)
        self.slider_labels[param_name].setText(f"{base_label}\n{value:.3f}")

        self.sc.set_param(param_name, value)

    def _handle_note_on_button(self) -> None:
        midi_note = int(self.note_combo.currentData())
        self.sc.note_on_midi(midi_note, velocity=100)

        # Push current panel parameters
        for name, slider in self.sliders.items():
            self.sc.set_param(name, self._slider_to_value(slider))
        target = int(self.lfo_target_combo.currentData())
        self.sc.set_param("lfo_target", float(target))

    def _handle_note_off_button(self) -> None:
        self.sc.note_off_all()

    def _handle_piano_note_on(self, midi_note: int) -> None:
        self.sc.note_on_midi(midi_note, velocity=100)
        for name, slider in self.sliders.items():
            self.sc.set_param(name, self._slider_to_value(slider))
        target = int(self.lfo_target_combo.currentData())
        self.sc.set_param("lfo_target", float(target))

    def _handle_piano_note_off(self, midi_note: int) -> None:
        self.sc.note_off_midi(midi_note)

    def _handle_midi_refresh(self) -> None:
        """
        User clicked "Refresh MIDI": re-scan ports and update combo box.
        """
        self._populate_midi_ports()

    def _handle_midi_port_changed(self) -> None:
        """
        User selected a different MIDI input port.
        """
        if self.midi_manager is None:
            return
        port_name = self.midi_port_combo.currentData()
        if port_name:
            self.midi_manager.open_port_by_name(port_name)

    # ------------------------------------------------------------------
    # Preset save/load
    # ------------------------------------------------------------------

    def _handle_save_preset(self) -> None:
        """
        Open a QFileDialog, collect current GUI state, and save via
        SynthPresetManager.
        """
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save Preset",
            "",
            "JSON Files (*.json)",
        )
        if not path:
            return

        # Build preset dict
        preset = {
            "sliders": {},
            "poly_mode": bool(self.poly_mode_combo.currentData()),
            "lfo_target": int(self.lfo_target_combo.currentData()),
            "note_index": int(self.note_combo.currentIndex()),
            "midi_port": self.midi_manager.current_port_name if self.midi_manager else None,
        }

        for name, slider in self.sliders.items():
            preset["sliders"][name] = self._slider_to_value(slider)

        try:
            self.preset_manager.save_preset_to_file(path, preset)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Error Saving Preset", str(exc))

    def _handle_load_preset(self) -> None:
        """
        Open a preset JSON file and apply it to the GUI and synth.
        """
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

        # Restore mode
        poly_mode = bool(preset.get("poly_mode", False))
        self.poly_mode_combo.setCurrentIndex(1 if poly_mode else 0)

        # Restore LFO target
        lfo_target = int(preset.get("lfo_target", 0))
        self.lfo_target_combo.setCurrentIndex(0 if lfo_target == 0 else 1)

        # Restore note index
        note_index = int(preset.get("note_index", 0))
        if 0 <= note_index < self.note_combo.count():
            self.note_combo.setCurrentIndex(note_index)

        # Restore MIDI port (if present and available)
        midi_port = preset.get("midi_port")
        if self.midi_manager and midi_port:
            ports = self.midi_manager.list_input_ports()
            if midi_port in ports:
                self.midi_manager.open_port_by_name(midi_port)
                self._populate_midi_ports()

        # Restore sliders
        sliders_data = preset.get("sliders", {})
        for name, value in sliders_data.items():
            slider = self.sliders.get(name)
            if slider is None:
                continue
            self._set_slider_from_value(slider, float(value))

        # After loading, push all param values into active voices
        for name, slider in self.sliders.items():
            self.sc.set_param(name, self._slider_to_value(slider))
        self.sc.set_param("lfo_target", float(self.lfo_target_combo.currentData()))
