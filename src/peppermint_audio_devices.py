#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
peppermint_audio_devices.py
------------------------------------------------------------------
Helper functions for enumerating audio output devices on Linux for
use with SuperCollider / scsynth via ALSA "hw:card,device" names.

This does **not** talk to SuperCollider directly; it shells out to
`aplay -l` (ALSA) and parses the card / device list, building
device strings like "hw:0,0", "hw:1,0", etc.

On non-ALSA systems (or where `aplay` is missing) this will simply
return an empty list.
"""

from __future__ import annotations

import re
import subprocess
from typing import List, Tuple


def list_alsa_devices() -> List[Tuple[str, str]]:
    """
    Return a list of (device_name, description) tuples for ALSA
    playback devices, where `device_name` is suitable to pass to
    SuperCollider's ServerOptions.device on Linux, e.g. "hw:0,0".

    If `aplay -l` is unavailable or parsing fails, returns an empty list.
    """
    try:
        proc = subprocess.run(
            ["aplay", "-l"],
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception:
        return []

    text = proc.stdout or ""
    devices: List[Tuple[str, str]] = []

    # Example lines from `aplay -l`:
    #   card 0: PCH [HDA Intel PCH], device 0: ALC298 Analog [ALC298 Analog]
    card_re = re.compile(
        r"card\s+(?P<card>\d+):\s+(?P<card_id>[^\s]+)\s+\[(?P<card_name>[^\]]+)\],\s*"
        r"device\s+(?P<dev>\d+):\s+(?P<dev_id>[^\s]+)\s+\[(?P<dev_name>[^\]]+)\]"
    )

    for line in text.splitlines():
        m = card_re.search(line)
        if not m:
            continue

        card_index = m.group("card")
        dev_index = m.group("dev")
        card_name = m.group("card_name").strip()
        dev_name = m.group("dev_name").strip()
        dev_id = m.group("dev_id").strip()

        device_name = f"hw:{card_index},{dev_index}"
        description = f"card {card_index} ({card_name}) dev {dev_index} ({dev_id} / {dev_name})"
        devices.append((device_name, description))

    return devices
