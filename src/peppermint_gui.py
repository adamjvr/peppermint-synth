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

from typing import Dict

from PyQt6 import QtCore, QtWidgets

from peppermint_engine import PeppermintSynthEngine
from peppermint_midi import MidiInputManager
from peppermint_jack_routing import (
    list_supercollider_output_ports,
    list_playback_ports,
    connect_stereo_pair,
)
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

    # ---------------- value helpers ----------------

    def _slider_to_value(self, pos: int) -> float:
        norm = pos / 1000.0
        return self.min_val + norm * (self.max_val - self.min_val)

    def _value_to_slider(self, value: float) -> int:
        clamped = max(self.min_val, min(self.max_val, float(value)))
        norm = (clamped - self.min_val) / (self.max_val - self.min_val)
        return int(norm * 1000)

    # ---------------- public API ----------------

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

    # ---------------- internal slot ----------------

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

        # Title you asked for:
        self.setWindowTitle("Peppermint Synth - Roth Amplification Ltd.")
        self.setStyleSheet("background-color: white; color: black;")

        self.param_sliders: Dict[str, ParameterSlider] = {}

        self.midi_manager: MidiInputManager | None = None
        self.preset_manager = SynthPresetManager()

        self._build_ui()
        self._setup_midi()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        main_layout = QtWidgets.QVBoxLayout()
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        self.setLayout(main_layout)

        # ---------- Row 1: mode + LFO target + note ----------
        top_layout = QtWidgets.QHBoxLayout()

        # Poly/mono
        mode_lbl = QtWidgets.QLabel("Mode:")
        mode_lbl.setStyleSheet("color: black;")

        self.poly_mode_combo = QtWidgets.QComboBox()
        self.poly_mode_combo.addItem("Mono", False)
        self.poly_mode_combo.addItem("Poly", True)
        self.poly_mode_combo.currentIndexChanged.connect(self._on_poly_mode_changed)

        # LFO target
        lfo_lbl = QtWidgets.QLabel("LFO Target:")
        lfo_lbl.setStyleSheet("color: black;")

        self.lfo_target_combo = QtWidgets.QComboBox()
        self.lfo_target_combo.addItem("LFO → Pitch", 0.0)
        self.lfo_target_combo.addItem("LFO → Filter", 1.0)
        self.lfo_target_combo.currentIndexChanged.connect(self._on_lfo_target_changed)

        # Simple note drop-down + buttons
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

        main_layout.addLayout(top_layout)

        # ---------- Row 2: MIDI + presets ----------
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
        second_layout.addSpacing(20)
        second_layout.addWidget(self.save_preset_button)
        second_layout.addWidget(self.load_preset_button)
        second_layout.addSpacing(20)
        # SuperCollider audio device + controls
        sc_lbl = QtWidgets.QLabel("SC Device:")
        sc_lbl.setStyleSheet("color: black;")
        self.audio_device_edit = QtWidgets.QLineEdit()
        self.audio_device_edit.setPlaceholderText("e.g. hw:0,0 or PipeWire (blank = default)")
        self.reboot_audio_button = QtWidgets.QPushButton("Reboot Audio")
        self.reboot_audio_button.clicked.connect(self._on_reboot_audio)
        self.jack_routing_button = QtWidgets.QPushButton("JACK Routing...")
        self.jack_routing_button.clicked.connect(self._open_jack_routing_dialog)
        second_layout.addWidget(sc_lbl)
        second_layout.addWidget(self.audio_device_edit)
        second_layout.addWidget(self.reboot_audio_button)
        second_layout.addWidget(self.jack_routing_button)

        main_layout.addLayout(second_layout)

        # ---------- Middle: parameter banks in horizontal columns ----------
        panel_layout = QtWidgets.QHBoxLayout()
        panel_layout.setSpacing(30)
        main_layout.addLayout(panel_layout)

        def create_centered_bank(title: str):
            """
            Create:
                [TITLE]
                [  sliders horizontally centered  ]
            """
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

        # Column 1: VCO + FILTER stacked
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

        # ---------- Bottom: piano ----------
        self.piano_widget = PianoWidget(
            note_on_cb=self._on_piano_note_on,
            note_off_cb=self._on_piano_note_off,
        )
        main_layout.addWidget(self.piano_widget)

    
    # ------------------------------------------------------------------
    # SuperCollider audio control helpers
    # ------------------------------------------------------------------

    def _on_reboot_audio(self) -> None:
        """
        Read the SC device string from the line edit and ask the engine to
        reboot audio with that override, if supported.
        """
        text = self.audio_device_edit.text().strip() if hasattr(self, "audio_device_edit") else ""
        device = text if text else None

        # Be defensive in case the engine running on the user's machine
        # doesn't yet expose these newer methods.
        if hasattr(self.engine, "set_audio_device"):
            try:
                self.engine.set_audio_device(device)
            except Exception as exc:
                print(f"[GUI] set_audio_device failed: {exc}")
        else:
            print("[GUI] Engine has no set_audio_device(...) method.")

        if hasattr(self.engine, "reboot_audio"):
            try:
                self.engine.reboot_audio()
            except Exception as exc:
                print(f"[GUI] reboot_audio failed: {exc}")
        else:
            print("[GUI] Engine has no reboot_audio() method.")

    def _open_jack_routing_dialog(self) -> None:
        """Open a simple dialog to connect SC outputs to system playback via JACK."""
        dlg = JackRoutingDialog(self)
        dlg.exec()


# ------------------------------------------------------------------
    # MIDI setup
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_poly_mode_changed(self) -> None:
        is_poly = bool(self.poly_mode_combo.currentData())
        self.engine.set_poly_mode(is_poly)

    def _on_lfo_target_changed(self) -> None:
        value = float(self.lfo_target_combo.currentData())
        # lfo_target is a SynthDef control (0.0 or 1.0)
        self.engine.set_param("lfo_target", value)

    def _on_param_slider_changed(self, param_name: str, value: float) -> None:
        self.engine.set_param(param_name, value)

    def _on_note_on_button(self) -> None:
        midi_note = int(self.note_combo.currentData())
        self.engine.note_on(midi_note, velocity=100)
        # Ensure engine has latest params (GUI might have changed before)
        for name, slider in self.param_sliders.items():
            self.engine.set_param(name, slider.get_value())
        self.engine.set_param(
            "lfo_target", float(self.lfo_target_combo.currentData())
        )

    def _on_note_off_button(self) -> None:
        self.engine.note_off_all()

    def _on_piano_note_on(self, midi_note: int) -> None:
        self.engine.note_on(midi_note, velocity=100)
        for name, slider in self.param_sliders.items():
            self.engine.set_param(name, slider.get_value())
        self.engine.set_param(
            "lfo_target", float(self.lfo_target_combo.currentData())
        )

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

    # ---------- Presets ----------

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
        # find matching index
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

        # Restore sliders
        for name, value in preset.get("sliders", {}).items():
            slider = self.param_sliders.get(name)
            if slider is not None:
                slider.set_value(float(value), emit=False)
                self.engine.set_param(name, float(value))


class JackRoutingDialog(QtWidgets.QDialog):
    """
    Simple dialog to connect SuperCollider outputs to system playback ports
    via JACK / PipeWire-JACK (jack_lsp + jack_connect).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("JACK / PipeWire Routing")
        self.setModal(True)

        self.sc_ports = []
        self.playback_ports = []

        self._build_ui()
        self._refresh_ports()

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)

        info_label = QtWidgets.QLabel(
            "Select SuperCollider output ports and system playback ports.\n"
            "Then click 'Connect L/R' to wire them via JACK.\n\n"
            "Requires: JACK or PipeWire-JACK, jack_lsp, jack_connect."
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        hlayout = QtWidgets.QHBoxLayout()

        sc_group = QtWidgets.QGroupBox("SuperCollider outputs")
        sc_layout = QtWidgets.QVBoxLayout(sc_group)
        self.sc_list = QtWidgets.QListWidget()
        sc_layout.addWidget(self.sc_list)
        hlayout.addWidget(sc_group)

        sys_group = QtWidgets.QGroupBox("System playback ports")
        sys_layout = QtWidgets.QVBoxLayout(sys_group)
        self.playback_list = QtWidgets.QListWidget()
        sys_layout.addWidget(self.playback_list)
        hlayout.addWidget(sys_group)

        layout.addLayout(hlayout)

        ctrl_layout = QtWidgets.QHBoxLayout()
        self.refresh_button = QtWidgets.QPushButton("Refresh")
        self.refresh_button.clicked.connect(self._refresh_ports)
        ctrl_layout.addWidget(self.refresh_button)

        self.connect_button = QtWidgets.QPushButton("Connect L/R")
        self.connect_button.clicked.connect(self._connect_lr)
        ctrl_layout.addWidget(self.connect_button)

        ctrl_layout.addStretch(1)

        self.close_button = QtWidgets.QPushButton("Close")
        self.close_button.clicked.connect(self.accept)
        ctrl_layout.addWidget(self.close_button)

        layout.addLayout(ctrl_layout)

    def _refresh_ports(self) -> None:
        """Reload SC and system playback port lists."""
        self.sc_ports = list_supercollider_output_ports()
        self.playback_ports = list_playback_ports()

        self.sc_list.clear()
        for p in self.sc_ports:
            self.sc_list.addItem(p)

        self.playback_list.clear()
        for p in self.playback_ports:
            self.playback_list.addItem(p)

    def _connect_lr(self) -> None:
        """Connect first two selected SC ports to first two selected playback ports."""
        sc_sel = [item.text() for item in self.sc_list.selectedItems()]
        pb_sel = [item.text() for item in self.playback_list.selectedItems()]

        if len(sc_sel) < 2 or len(pb_sel) < 2:
            QtWidgets.QMessageBox.warning(
                self,
                "Selection required",
                "Select at least two SC outputs and two playback ports "
                "to form a stereo L/R pair.",
            )
            return

        sc_left, sc_right = sc_sel[0], sc_sel[1]
        pb_left, pb_right = pb_sel[0], pb_sel[1]

        ok_l, ok_r = connect_stereo_pair(sc_left, sc_right, pb_left, pb_right)

        msg = f"Left: {'OK' if ok_l else 'FAILED'}\nRight: {'OK' if ok_r else 'FAILED'}"
        QtWidgets.QMessageBox.information(self, "JACK connect result", msg)


    # ------------------------------------------------------------------
    # Clean shutdown hook
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self.midi_manager is not None:
            self.midi_manager.shutdown()
        self.engine.shutdown()
        super().closeEvent(event)
