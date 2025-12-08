#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
peppermint_main.py
----------------------------------------------------------------------
Entry point for the Supriya-based "Peppermint Synth - Roth Amplification Ltd."
"""

import sys

from PyQt6 import QtWidgets

from peppermint_engine import PeppermintSynthEngine
from peppermint_gui import SynthControlWindow


def main() -> None:
    app = QtWidgets.QApplication(sys.argv)

    engine = PeppermintSynthEngine()
    window = SynthControlWindow(engine=engine)
    window.resize(1100, 700)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
