#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
peppermint_presets.py
----------------------------------------------------------------------
Simple JSON-based preset save / load for Peppermint Synth.
"""

from __future__ import annotations

import json
from typing import Any, Dict


class SynthPresetManager:
    """
    Wraps JSON serialization of preset dictionaries.

    The GUI decides what goes into the preset:
        - slider values
        - poly mode
        - lfo target
        - note choice
        - selected MIDI port name, etc.
    """

    @staticmethod
    def save_preset_to_file(path: str, preset: Dict[str, Any]) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(preset, f, indent=2)

    @staticmethod
    def load_preset_from_file(path: str) -> Dict[str, Any]:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
