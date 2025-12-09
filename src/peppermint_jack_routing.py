#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
peppermint_jack_routing.py
---------------------------------------
Helper utilities for basic JACK / PipeWire JACK routing from Python.

This module does not depend on any JACK Python bindings; it shells out to
`jack_lsp` and `jack_connect` instead. It is intentionally minimal and
defensive: if JACK is not running or tools are missing, it fails gracefully.
"""

from __future__ import annotations

import subprocess
from typing import List, Tuple


def _run_cmd(args: list[str]) -> str:
    """Run a command and return stdout as text; return empty string on error."""
    try:
        proc = subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception:
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout or ""


def list_jack_ports() -> List[str]:
    """Return a flat list of JACK port names (or empty list if unavailable)."""
    output = _run_cmd(["jack_lsp"])
    if not output:
        return []
    ports = [line.strip() for line in output.splitlines() if line.strip()]
    return ports


def list_supercollider_output_ports() -> List[str]:
    """Return a best-effort list of SuperCollider output ports.

    We look for typical names like:
    - 'SuperCollider:out_1', 'SuperCollider:out_2'
    - 'scsynth:out_1', etc.
    """
    ports = list_jack_ports()
    result: List[str] = []
    for name in ports:
        lower = name.lower()
        if ("supercollider:out_" in lower) or ("scsynth:out_" in lower):
            result.append(name)
    return result


def list_playback_ports() -> List[str]:
    """Return a best-effort list of system playback ports.

    On many systems these are named like:
    - 'system:playback_1', 'system:playback_2'
    Under PipeWire JACK they may still appear with 'system:playback_...' names.
    """
    ports = list_jack_ports()
    result: List[str] = []
    for name in ports:
        lower = name.lower()
        if "system:playback" in lower or "playback_" in lower:
            result.append(name)
    return result


def connect_ports(source: str, destination: str) -> bool:
    """Connect source -> destination via `jack_connect`.

    Returns True on success, False on failure.
    """
    if not source or not destination:
        return False
    try:
        proc = subprocess.run(
            ["jack_connect", source, destination],
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception:
        return False
    return proc.returncode == 0


def connect_stereo_pair(
    sc_left: str,
    sc_right: str,
    sys_left: str,
    sys_right: str,
) -> Tuple[bool, bool]:
    """Connect a stereo pair: (sc_left -> sys_left, sc_right -> sys_right)."""
    ok_l = connect_ports(sc_left, sys_left)
    ok_r = connect_ports(sc_right, sys_right)
    return ok_l, ok_r
