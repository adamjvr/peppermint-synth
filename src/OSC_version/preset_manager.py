#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
preset_manager.py
----------------------------------------------------------------------
SynthPresetManager

A small, GUI-agnostic utility for saving and loading synth presets
to/from JSON files.

The GUI creates a dict describing the current state and hands it to
SynthPresetManager.save_preset(...). To restore, the GUI calls
SynthPresetManager.load_preset(...) and applies the result.
"""

from __future__ import annotations

from typing import Any, Dict
import json


class SynthPresetManager:
    """
    SynthPresetManager
    ==================

    Responsibilities:
    -----------------
    - Serialize a "preset dict" to JSON.
    - Deserialize JSON back to a dict.

    It does NOT:
    - Know about Qt widgets.
    - Know about SuperCollider or MIDI.

    The preset dict format is flexible, but the GUI uses something like:
        {
            "sliders": {
                "cutoff": 1200.0,
                "res": 0.2,
                ...
            },
            "poly_mode": true,
            "lfo_target": 1,
            "note_index": 2,
            "midi_port": "Some Port Name" or null
        }
    """

    @staticmethod
    def save_preset_to_file(path: str, preset_data: Dict[str, Any]) -> None:
        """
        Write the given preset_data dict to a JSON file.

        Parameters
        ----------
        path : str
            File path (e.g. chosen by QFileDialog).
        preset_data : Dict[str, Any]
            Arbitrary dict describing synth state.
        """
        with open(path, "w", encoding="utf-8") as f:
            json.dump(preset_data, f, indent=4)

    @staticmethod
    def load_preset_from_file(path: str) -> Dict[str, Any]:
        """
        Read a JSON file and return the preset dict.

        Raises whatever exceptions the underlying json/file calls raise;
        the GUI layer can catch and show a QMessageBox.
        """
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
