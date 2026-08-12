#!/usr/bin/env python3
"""
tinc_uinput.py — Pure Python uinput input injection (no external libraries).
"""

import struct
import fcntl
import os
import time

UINPUT_PATH = "/dev/uinput"
EV_SYN = 0
EV_KEY = 1
SYN_REPORT = 0

KEY_BACKSPACE  = 14
KEY_V          = 47
KEY_LEFTCTRL   = 29
KEY_LEFTSHIFT  = 42
KEY_INSERT     = 110

UI_SET_EVBIT   = 0x40045564
UI_SET_KEYBIT  = 0x40045565
UI_DEV_CREATE  = 0x5501
UI_DEV_DESTROY = 0x5502
UI_DEV_SETUP   = 0x405C5503

_INPUT_EVENT_FMT = "llHHi"

def _write_ev(fd: int, ev_type: int, code: int, value: int) -> None:
    t = time.time()
    data = struct.pack(_INPUT_EVENT_FMT,
                       int(t), int((t % 1) * 1_000_000),
                       ev_type, code, value)
    os.write(fd, data)

def _send(key_sequence: list, delay: float = 0.03) -> bool:
    try:
        fd = os.open(UINPUT_PATH, os.O_WRONLY | os.O_NONBLOCK)
    except (PermissionError, OSError):
        return False

    try:
        fcntl.ioctl(fd, UI_SET_EVBIT, EV_KEY)
        fcntl.ioctl(fd, UI_SET_EVBIT, EV_SYN)
        for kc, _ in key_sequence:
            fcntl.ioctl(fd, UI_SET_KEYBIT, kc)

        setup = struct.pack("HHHH80sI", 6, 0, 0, 1, b"tinc", 0)
        fcntl.ioctl(fd, UI_DEV_SETUP, setup)
        fcntl.ioctl(fd, UI_DEV_CREATE)
        time.sleep(0.15)

        for kc, val in key_sequence:
            _write_ev(fd, EV_KEY, kc, val)
            _write_ev(fd, EV_SYN, SYN_REPORT, 0)
            time.sleep(delay)
    except Exception:
        return False
    finally:
        try:
            fcntl.ioctl(fd, UI_DEV_DESTROY)
        except Exception:
            pass
        os.close(fd)
    return True

def ctrl_v() -> bool:
    return _send([
        (KEY_LEFTCTRL, 1),
        (KEY_V,        1),
        (KEY_V,        0),
        (KEY_LEFTCTRL, 0),
    ])

def shift_insert() -> bool:
    return _send([
        (KEY_LEFTSHIFT, 1),
        (KEY_INSERT,    1),
        (KEY_INSERT,    0),
        (KEY_LEFTSHIFT, 0),
    ])

def backspace(n: int) -> bool:
    seq = []
    for _ in range(n):
        seq.append((KEY_BACKSPACE, 1))
        seq.append((KEY_BACKSPACE, 0))
    return _send(seq, delay=0.01)
