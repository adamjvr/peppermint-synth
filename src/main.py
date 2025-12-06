#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
main.py
----------------------------------------------------------------------
Entry point for the PyQt6 + SuperCollider synth GUI.

Make sure SuperCollider is running and pyAnalogVoice.scd is loaded:

    s.boot;
    // evaluate contents of pyAnalogVoice.scd

Then run:

    python main.py
"""

import sys
from PyQt6 import QtWidgets

from sc_synth_controller import SuperColliderSynthController
from gui_main import SynthControlWindow


def main() -> None:
    app = QtWidgets.QApplication(sys.argv)

    sc_controller = SuperColliderSynthController(
        host="127.0.0.1",
        port=57110,
        max_voices=8,
    )

    window = SynthControlWindow(sc_controller)
    window.resize(900, 600)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
