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

def ctrl_shift_v() -> bool:
    return _send([
        (KEY_LEFTCTRL,  1),
        (KEY_LEFTSHIFT, 1),
        (KEY_V,         1),
        (KEY_V,         0),
        (KEY_LEFTSHIFT, 0),
        (KEY_LEFTCTRL,  0),
    ])

# Mapping from ASCII to (keycode, shift_needed)
_CHAR_MAP = {
    'a': (30, 0), 'A': (30, 1), 'b': (48, 0), 'B': (48, 1),
    'c': (46, 0), 'C': (46, 1), 'd': (32, 0), 'D': (32, 1),
    'e': (18, 0), 'E': (18, 1), 'f': (33, 0), 'F': (33, 1),
    'g': (34, 0), 'G': (34, 1), 'h': (35, 0), 'H': (35, 1),
    'i': (23, 0), 'I': (23, 1), 'j': (36, 0), 'J': (36, 1),
    'k': (37, 0), 'K': (37, 1), 'l': (38, 0), 'L': (38, 1),
    'm': (50, 0), 'M': (50, 1), 'n': (49, 0), 'N': (49, 1),
    'o': (24, 0), 'O': (24, 1), 'p': (25, 0), 'P': (25, 1),
    'q': (16, 0), 'Q': (16, 1), 'r': (19, 0), 'R': (19, 1),
    's': (31, 0), 'S': (31, 1), 't': (20, 0), 'T': (20, 1),
    'u': (22, 0), 'U': (22, 1), 'v': (47, 0), 'V': (47, 1),
    'w': (17, 0), 'W': (17, 1), 'x': (45, 0), 'X': (45, 1),
    'y': (21, 0), 'Y': (21, 1), 'z': (44, 0), 'Z': (44, 1),
    '1': (2, 0), '!': (2, 1), '2': (3, 0), '@': (3, 1),
    '3': (4, 0), '#': (4, 1), '4': (5, 0), '$': (5, 1),
    '5': (6, 0), '%': (6, 1), '6': (7, 0), '^': (7, 1),
    '7': (8, 0), '&': (8, 1), '8': (9, 0), '*': (9, 1),
    '9': (10, 0), '(': (10, 1), '0': (11, 0), ')': (11, 1),
    '-': (12, 0), '_': (12, 1), '=': (13, 0), '+': (13, 1),
    '[': (26, 0), '{': (26, 1), ']': (27, 0), '}': (27, 1),
    '\\': (43, 0), '|': (43, 1), ';': (39, 0), ':': (39, 1),
    "'": (40, 0), '"': (40, 1), '`': (41, 0), '~': (41, 1),
    ',': (51, 0), '<': (51, 1), '.': (52, 0), '>': (52, 1),
    '/': (53, 0), '?': (53, 1), ' ': (57, 0), '\n': (28, 0)
}

def type_string(text: str) -> bool:
    """Type a string character-by-character extremely fast via EVDEV."""
    events = []
    for c in text:
        if c in _CHAR_MAP:
            kc, shift = _CHAR_MAP[c]
            if shift:
                events.append((KEY_LEFTSHIFT, 1))
            events.append((kc, 1))
            events.append((kc, 0))
            if shift:
                events.append((KEY_LEFTSHIFT, 0))
    return _send(events, delay=0.0001)

