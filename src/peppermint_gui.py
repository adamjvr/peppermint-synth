#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
peppermint_gui.py
----------------------------------------------------------------------
PyQt6 GUI for "Peppermint Synth - Roth Amplification Ltd."

- Talks to PeppermintSynthEngine (Supriya backend).
- Arranges control sections horizontally:
    [ VCO
      FILTER ]   [ LFO ]   [ ENV (ADSR) ]   [ AMP ]
- Uses vertical "ARP-style" sliders.
- Has a 25-key piano widget on the bottom.
"""

from __future__ import annotations

import subprocess
from typing import Dict

from PyQt6 import QtCore, QtWidgets

from peppermint_engine import PeppermintSynthEngine
from peppermint_midi import MidiInputManager
from peppermint_piano import PianoWidget
from peppermint_presets import SynthPresetManager


class ParameterSlider(QtWidgets.QWidget):
    """
    Generic vertical slider for one synth parameter:

        [Label + value]
        [   slider    ]
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
    ) -> None:
        super().__init__(parent)

        self.param_name = param_name
        self.min_val = float(min_val)
        self.max_val = float(max_val)

        self.setFixedWidth(80)

        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.setLayout(layout)

        self.label = QtWidgets.QLabel()
        self.label.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)
        self.label.setStyleSheet("color: black;")
        font = self.label.font()
        font.setPointSize(9)
        self.label.setFont(font)

        self.slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Vertical)
        self.slider.setRange(0, 1000)
        self.slider.setMinimumHeight(140)
        self.slider.setStyleSheet(
            f"""
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
            """
        )

        layout.addWidget(self.label)
        layout.addWidget(self.slider, 1, QtCore.Qt.AlignmentFlag.AlignHCenter)

        self._base_label_text = label_text

        self.set_value(default, emit=False)

        self.slider.valueChanged.connect(self._on_slider_changed)

    def _slider_to_value(self, pos: int) -> float:
        norm = pos / 1000.0
        return self.min_val + norm * (self.max_val - self.min_val)

    def _value_to_slider(self, value: float) -> int:
        clamped = max(self.min_val, min(self.max_val, float(value)))
        norm = (clamped - self.min_val) / (self.max_val - self.min_val)
        return int(norm * 1000)

    def set_value(self, value: float, emit: bool = True) -> None:
        pos = self._value_to_slider(value)

        self.slider.blockSignals(True)
        self.slider.setValue(pos)
        self.slider.blockSignals(False)

        actual = self._slider_to_value(pos)
        self.label.setText(f"{self._base_label_text}\n{actual:.3f}")

        if emit:
            self.valueChanged.emit(self.param_name, actual)

    def get_value(self) -> float:
        return self._slider_to_value(self.slider.value())

    def _on_slider_changed(self, pos: int) -> None:
        value = self._slider_to_value(pos)
        self.label.setText(f"{self._base_label_text}\n{value:.3f}")
        self.valueChanged.emit(self.param_name, value)


class SynthControlWindow(QtWidgets.QWidget):
    """
    Main GUI window for Peppermint Synth.
    """

    def __init__(self, engine: PeppermintSynthEngine, parent=None) -> None:
        super().__init__(parent)

        self.engine = engine
        self.setWindowTitle("Peppermint Synth - Roth Amplification Ltd.")
        self.setStyleSheet("background-color: white; color: black;")

        self.param_sliders: Dict[str, ParameterSlider] = {}
        self.midi_manager: MidiInputManager | None = None
        self.preset_manager = SynthPresetManager()

        self._build_ui()
        self._setup_midi()

        self._sc_status_timer = QtCore.QTimer(self)
        self._sc_status_timer.setInterval(500)
        self._sc_status_timer.timeout.connect(self._poll_sc_status)
        self._sc_status_timer.start()

    def _build_ui(self) -> None:
        main_layout = QtWidgets.QVBoxLayout()
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        self.setLayout(main_layout)

        # ---------- Row 1 ----------
        top_layout = QtWidgets.QHBoxLayout()

        mode_lbl = QtWidgets.QLabel("Mode:")
        mode_lbl.setStyleSheet("color: black;")
        self.poly_mode_combo = QtWidgets.QComboBox()
        self.poly_mode_combo.addItem("Mono", False)
        self.poly_mode_combo.addItem("Poly", True)
        self.poly_mode_combo.currentIndexChanged.connect(self._on_poly_mode_changed)

        lfo_lbl = QtWidgets.QLabel("LFO Target:")
        lfo_lbl.setStyleSheet("color: black;")
        self.lfo_target_combo = QtWidgets.QComboBox()
        self.lfo_target_combo.addItem("LFO → Pitch", 0.0)
        self.lfo_target_combo.addItem("LFO → Filter", 1.0)
        self.lfo_target_combo.currentIndexChanged.connect(self._on_lfo_target_changed)

        note_lbl = QtWidgets.QLabel("Note:")
        note_lbl.setStyleSheet("color: black;")
        self.note_combo = QtWidgets.QComboBox()
        self.note_combo.addItem("A2 (110 Hz)", 45)
        self.note_combo.addItem("A3 (220 Hz)", 57)
        self.note_combo.addItem("A4 (440 Hz)", 69)
        self.note_combo.addItem("A1 (55 Hz)", 33)

        self.note_on_button = QtWidgets.QPushButton("Note On")
        self.note_off_button = QtWidgets.QPushButton("Note Off")
        self.note_on_button.clicked.connect(self._on_note_on_button)
        self.note_off_button.clicked.connect(self._on_note_off_button)

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
        top_layout.addSpacing(20)

        self.sc_status_label = QtWidgets.QLabel("SC: unknown")
        self.sc_status_label.setStyleSheet("color: black; font-weight: bold;")
        top_layout.addWidget(self.sc_status_label)

        main_layout.addLayout(top_layout)

        # ---------- Row 2 (MIDI, JACK, Reboot SC, presets) ----------
        second_layout = QtWidgets.QHBoxLayout()

        midi_lbl = QtWidgets.QLabel("MIDI In:")
        midi_lbl.setStyleSheet("color: black;")
        self.midi_port_combo = QtWidgets.QComboBox()
        self.midi_refresh_button = QtWidgets.QPushButton("Refresh MIDI")
        self.midi_refresh_button.clicked.connect(self._on_midi_refresh)
        self.midi_port_combo.currentIndexChanged.connect(self._on_midi_port_changed)

        self.save_preset_button = QtWidgets.QPushButton("Save Preset")
        self.load_preset_button = QtWidgets.QPushButton("Load Preset")
        self.save_preset_button.clicked.connect(self._on_save_preset)
        self.load_preset_button.clicked.connect(self._on_load_preset)

        second_layout.addWidget(midi_lbl)
        second_layout.addWidget(self.midi_port_combo)
        second_layout.addWidget(self.midi_refresh_button)
        second_layout.addStretch(1)

        # JACK routing helper dialog
        self.jack_button = QtWidgets.QPushButton("JACK Routing…")
        self.jack_button.clicked.connect(self._on_open_jack_routing)
        second_layout.addWidget(self.jack_button)

        # Explicit SuperCollider reboot control
        self.reboot_sc_button = QtWidgets.QPushButton("Reboot SC")
        self.reboot_sc_button.clicked.connect(self._on_reboot_sc_clicked)
        second_layout.addWidget(self.reboot_sc_button)

        second_layout.addWidget(self.save_preset_button)
        second_layout.addWidget(self.load_preset_button)

        main_layout.addLayout(second_layout)

        # ---------- Parameter banks ----------
        panel_layout = QtWidgets.QHBoxLayout()
        panel_layout.setSpacing(30)
        main_layout.addLayout(panel_layout)

        def create_centered_bank(title: str):
            bank_layout = QtWidgets.QVBoxLayout()
            bank_layout.setSpacing(4)

            header = QtWidgets.QLabel(title)
            header.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)
            header.setStyleSheet("font-weight: bold; color: black;")
            bank_layout.addWidget(header)

            sliders_row = QtWidgets.QHBoxLayout()
            sliders_row.setSpacing(6)

            wrapper = QtWidgets.QHBoxLayout()
            wrapper.addStretch(1)
            wrapper.addLayout(sliders_row)
            wrapper.addStretch(1)

            bank_layout.addLayout(wrapper)
            return bank_layout, sliders_row

        def add_slider(
            row_layout: QtWidgets.QHBoxLayout,
            label: str,
            param: str,
            vmin: float,
            vmax: float,
            default: float,
            color: str,
        ):
            slider = ParameterSlider(label, param, vmin, vmax, default, color)
            slider.valueChanged.connect(self._on_param_slider_changed)
            self.param_sliders[param] = slider
            row_layout.addWidget(slider)

        # Column 1: VCO + FILTER
        col_vco_filt = QtWidgets.QVBoxLayout()
        col_vco_filt.setSpacing(12)

        vco_bank, vco_row = create_centered_bank("VCO")
        add_slider(
            vco_row, "VCO Mix\n(0=VCO1, 1=VCO2)", "vco_mix", 0.0, 1.0, 0.5, "#3f88ff"
        )
        add_slider(
            vco_row, "VCO1 Wave\n(0=saw,1=pulse)", "vco1_wave", 0.0, 1.0, 0.0, "#3f88ff"
        )
        add_slider(
            vco_row, "VCO2 Wave\n(0=saw,1=pulse)", "vco2_wave", 0.0, 1.0, 0.0, "#3f88ff"
        )
        add_slider(
            vco_row, "Detune Ratio", "detune", 0.98, 1.08, 1.01, "#3f88ff"
        )
        col_vco_filt.addLayout(vco_bank)

        filt_bank, filt_row = create_centered_bank("FILTER")
        add_slider(filt_row, "Cutoff (Hz)", "cutoff", 100.0, 8000.0, 1200.0, "#ff8800")
        add_slider(filt_row, "Resonance (0–1)", "res", 0.0, 1.0, 0.2, "#ff8800")
        add_slider(
            filt_row, "Filter Env Amount", "env_amt", 0.0, 1.0, 0.5, "#ff8800"
        )
        add_slider(
            filt_row, "Noise Mix (0–1)", "noise_mix", 0.0, 1.0, 0.0, "#ff8800"
        )
        col_vco_filt.addLayout(filt_bank)

        # Column 2: LFO
        col_lfo = QtWidgets.QVBoxLayout()
        col_lfo.setSpacing(12)
        lfo_bank, lfo_row = create_centered_bank("LFO")
        add_slider(lfo_row, "LFO Freq (Hz)", "lfo_freq", 0.1, 20.0, 5.0, "#aa44ff")
        add_slider(lfo_row, "LFO Depth (0–1)", "lfo_depth", 0.0, 1.0, 0.0, "#aa44ff")
        col_lfo.addLayout(lfo_bank)

        # Column 3: ENV (ADSR)
        col_env = QtWidgets.QVBoxLayout()
        col_env.setSpacing(12)
        env_bank, env_row = create_centered_bank("ENV (ADSR)")
        add_slider(env_row, "Attack (s)", "atk", 0.001, 2.0, 0.01, "#44aa44")
        add_slider(env_row, "Decay (s)", "dec", 0.01, 2.0, 0.1, "#44aa44")
        add_slider(env_row, "Sustain (0–1)", "sus", 0.0, 1.0, 0.7, "#44aa44")
        add_slider(env_row, "Release (s)", "rel", 0.01, 4.0, 0.3, "#44aa44")
        col_env.addLayout(env_bank)

        # Column 4: AMP
        col_amp = QtWidgets.QVBoxLayout()
        col_amp.setSpacing(12)
        amp_bank, amp_row = create_centered_bank("AMP")
        add_slider(amp_row, "Level", "amp", 0.0, 0.8, 0.2, "#222222")
        col_amp.addLayout(amp_bank)

        panel_layout.addStretch(1)
        panel_layout.addLayout(col_vco_filt)
        panel_layout.addLayout(col_lfo)
        panel_layout.addLayout(col_env)
        panel_layout.addLayout(col_amp)
        panel_layout.addStretch(1)

        # Piano
        self.piano_widget = PianoWidget(
            note_on_cb=self._on_piano_note_on,
            note_off_cb=self._on_piano_note_off,
        )
        main_layout.addWidget(self.piano_widget)

    def _setup_midi(self) -> None:
        self.midi_manager = MidiInputManager(
            note_on_cb=self.engine.note_on,
            note_off_cb=self.engine.note_off,
            auto_open_first=True,
        )
        self._populate_midi_ports()

    def _populate_midi_ports(self) -> None:
        if self.midi_manager is None:
            return

        ports = self.midi_manager.list_input_ports()
        current = self.midi_manager.current_port_name

        self.midi_port_combo.blockSignals(True)
        self.midi_port_combo.clear()

        for name in ports:
            self.midi_port_combo.addItem(name, name)

        if current and current in ports:
            self.midi_port_combo.setCurrentIndex(ports.index(current))

        self.midi_port_combo.blockSignals(False)

    def _poll_sc_status(self) -> None:
        if self.engine.is_server_running():
            self.sc_status_label.setText("SC: running")
            self.sc_status_label.setStyleSheet("color: green; font-weight: bold;")
        else:
            self.sc_status_label.setText("SC: stopped")
            self.sc_status_label.setStyleSheet("color: red; font-weight: bold;")

    # ----- event handlers -----

    def _on_poly_mode_changed(self) -> None:
        is_poly = bool(self.poly_mode_combo.currentData())
        self.engine.set_poly_mode(is_poly)

    def _on_lfo_target_changed(self) -> None:
        value = float(self.lfo_target_combo.currentData())
        self.engine.set_param("lfo_target", value)

    def _on_param_slider_changed(self, param_name: str, value: float) -> None:
        self.engine.set_param(param_name, value)

    def _on_note_on_button(self) -> None:
        midi_note = int(self.note_combo.currentData())
        self.engine.note_on(midi_note, velocity=100)
        for name, slider in self.param_sliders.items():
            self.engine.set_param(name, slider.get_value())
        self.engine.set_param("lfo_target", float(self.lfo_target_combo.currentData()))

    def _on_note_off_button(self) -> None:
        self.engine.note_off_all()

    def _on_piano_note_on(self, midi_note: int) -> None:
        self.engine.note_on(midi_note, velocity=100)
        for name, slider in self.param_sliders.items():
            self.engine.set_param(name, slider.get_value())
        self.engine.set_param("lfo_target", float(self.lfo_target_combo.currentData()))

    def _on_piano_note_off(self, midi_note: int) -> None:
        self.engine.note_off(midi_note)

    def _on_midi_refresh(self) -> None:
        self._populate_midi_ports()

    def _on_midi_port_changed(self) -> None:
        if self.midi_manager is None:
            return
        name = self.midi_port_combo.currentData()
        if name:
            self.midi_manager.open_port_by_name(str(name))

    def _on_save_preset(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save Preset", "", "JSON Files (*.json)"
        )
        if not path:
            return

        preset = {
            "sliders": {name: slider.get_value() for name, slider in self.param_sliders.items()},
            "poly_mode": bool(self.poly_mode_combo.currentData()),
            "lfo_target": float(self.lfo_target_combo.currentData()),
            "note_index": int(self.note_combo.currentIndex()),
            "midi_port": (
                self.midi_manager.current_port_name if self.midi_manager else None
            ),
        }

        try:
            self.preset_manager.save_preset_to_file(path, preset)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Error Saving Preset", str(exc))

    def _on_load_preset(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Load Preset", "", "JSON Files (*.json)"
        )
        if not path:
            return
        try:
            preset = self.preset_manager.load_preset_from_file(path)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Error Loading Preset", str(exc))
            return

        poly_mode = bool(preset.get("poly_mode", False))
        self.poly_mode_combo.setCurrentIndex(1 if poly_mode else 0)
        self.engine.set_poly_mode(poly_mode)

        lfo_target = float(preset.get("lfo_target", 0.0))
        idx = 0 if lfo_target < 0.5 else 1
        self.lfo_target_combo.setCurrentIndex(idx)
        self.engine.set_param("lfo_target", lfo_target)

        note_index = int(preset.get("note_index", 0))
        if 0 <= note_index < self.note_combo.count():
            self.note_combo.setCurrentIndex(note_index)

        if self.midi_manager:
            midi_port = preset.get("midi_port")
            if midi_port:
                self.midi_manager.open_port_by_name(midi_port)
            self._populate_midi_ports()

        for name, value in preset.get("sliders", {}).items():
            slider = self.param_sliders.get(name)
            if slider is not None:
                slider.set_value(float(value), emit=False)
                self.engine.set_param(name, float(value))

    # ----- JACK + Reboot SC -----

    def _on_open_jack_routing(self) -> None:
        """Open the JACK routing helper dialog."""
        dlg = JackRoutingDialog(self)
        dlg.exec()

    def _on_reboot_sc_clicked(self) -> None:
        """Request a SuperCollider server reboot from the engine.

        This stops any currently held notes, asks the engine to reboot
        the Supriya server on its audio thread, and gives the user
        immediate visual feedback in the status label.
        """
        self.engine.note_off_all()
        self.sc_status_label.setText("SC: rebooting…")
        self.sc_status_label.setStyleSheet("color: orange; font-weight: bold;")
        self.engine.reboot_server()

    # ----- Clean shutdown -----

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self.midi_manager is not None:
            self.midi_manager.shutdown()
        self.engine.shutdown()
        super().closeEvent(event)


class JackRoutingDialog(QtWidgets.QDialog):
    """Utility dialog to wire SuperCollider → system playback via JACK/PipeWire."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("JACK Routing - Peppermint Synth")
        self.resize(640, 400)

        layout = QtWidgets.QVBoxLayout(self)

        desc = QtWidgets.QLabel(
            "Select up to two SuperCollider output ports and two playback ports,\n"
            "then click 'Connect L/R' to wire them together."
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)

        lists_layout = QtWidgets.QHBoxLayout()
        layout.addLayout(lists_layout)

        self.sc_list = QtWidgets.QListWidget()
        self.sc_list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.sc_list.setMinimumWidth(260)
        lists_layout.addWidget(self.sc_list)

        self.playback_list = QtWidgets.QListWidget()
        self.playback_list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.playback_list.setMinimumWidth(260)
        lists_layout.addWidget(self.playback_list)

        btn_layout = QtWidgets.QHBoxLayout()
        layout.addLayout(btn_layout)
        btn_layout.addStretch(1)

        refresh_btn = QtWidgets.QPushButton("Refresh")
        refresh_btn.clicked.connect(self._refresh_ports)
        btn_layout.addWidget(refresh_btn)

        connect_btn = QtWidgets.QPushButton("Connect L/R")
        connect_btn.clicked.connect(self._on_connect)
        btn_layout.addWidget(connect_btn)

        close_btn = QtWidgets.QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)

        self._refresh_ports()

    def _run_jack_lsp(self) -> list[str]:
        try:
            proc = subprocess.run(
                ["jack_lsp"],
                check=False,
                capture_output=True,
                text=True,
            )
        except Exception:
            return []
        if proc.returncode != 0:
            return []
        return [line.strip() for line in proc.stdout.splitlines() if line.strip()]

    def _refresh_ports(self) -> None:
        ports = self._run_jack_lsp()
        sc_ports = [p for p in ports if "SuperCollider" in p or "supercollider" in p]
        playback_ports = [p for p in ports if "playback" in p or "system" in p]

        self.sc_list.clear()
        self.playback_list.clear()

        for p in sc_ports:
            self.sc_list.addItem(p)
        for p in playback_ports:
            self.playback_list.addItem(p)

    def _on_connect(self) -> None:
        sc_selected = [i.text() for i in self.sc_list.selectedItems()]
        pb_selected = [i.text() for i in self.playback_list.selectedItems()]

        if len(sc_selected) < 2 or len(pb_selected) < 2:
            QtWidgets.QMessageBox.warning(
                self,
                "Selection Error",
                "Please select at least two SuperCollider outputs and two playback ports.",
            )
            return

        sc_l, sc_r = sc_selected[0], sc_selected[1]
        pb_l, pb_r = pb_selected[0], pb_selected[1]

        def _jack_connect(a: str, b: str) -> bool:
            try:
                proc = subprocess.run(
                    ["jack_connect", a, b],
                    check=False,
                    capture_output=True,
                    text=True,
                )
            except Exception:
                return False
            return proc.returncode == 0

        ok_l = _jack_connect(sc_l, pb_l)
        ok_r = _jack_connect(sc_r, pb_r)

        if ok_l and ok_r:
            QtWidgets.QMessageBox.information(
                self,
                "Connected",
                f"Connected\n  {sc_l} → {pb_l}\n  {sc_r} → {pb_r}",
            )
        else:
            QtWidgets.QMessageBox.warning(
                self,
                "Connection Error",
                "Failed to connect one or more JACK ports.\n"
                "Check 'jack_lsp' and 'jack_connect' on your system.",
            )
