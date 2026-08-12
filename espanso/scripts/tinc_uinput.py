#!/usr/bin/env python3
"""
tinc_uinput.py — Pure Python uinput input injection (no external libraries).

Sends keystrokes directly to /dev/uinput (kernel-level input device).
This is identical to what Espanso's own EVDEVInjector does:
  - Works in ALL applications: Wayland-native, XWayland, terminal, browser, etc.
  - No X11 portal, no RemoteDesktop popup, no permissions dialog.
  - Never triggers remote interaction requests.

/dev/uinput must be writable by the current user.
On standard Linux with GNOME, the session ACL grants this automatically.
"""

import struct
import fcntl
import os
import time

# /dev/uinput path
UINPUT_PATH = "/dev/uinput"

# Linux input event types
EV_SYN = 0
EV_KEY = 1
SYN_REPORT = 0

# Key codes (from linux/input-event-codes.h)
KEY_BACKSPACE  = 14
KEY_V          = 47
KEY_LEFTCTRL   = 29

# uinput ioctl commands
UI_SET_EVBIT   = 0x40045564
UI_SET_KEYBIT  = 0x40045565
UI_DEV_CREATE  = 0x5501
UI_DEV_DESTROY = 0x5502
# UI_DEV_SETUP = _IOW('U', 3, uinput_setup) where uinput_setup = 92 bytes
UI_DEV_SETUP   = 0x405C5503

# input_event struct: struct timeval (2 longs on 64-bit) + __u16 type + __u16 code + __s32 value
_INPUT_EVENT_FMT = "llHHi"


def _write_ev(fd: int, ev_type: int, code: int, value: int) -> None:
    t = time.time()
    data = struct.pack(_INPUT_EVENT_FMT,
                       int(t), int((t % 1) * 1_000_000),
                       ev_type, code, value)
    os.write(fd, data)


def _send(key_sequence: list, delay: float = 0.03) -> bool:
    """
    Send a sequence of (keycode, 1=press|0=release) via /dev/uinput.
    Returns True on success, False if /dev/uinput is not accessible.
    """
    try:
        fd = os.open(UINPUT_PATH, os.O_WRONLY | os.O_NONBLOCK)
    except (PermissionError, OSError):
        return False

    try:
        # Enable EV_KEY and EV_SYN event types
        fcntl.ioctl(fd, UI_SET_EVBIT, EV_KEY)
        fcntl.ioctl(fd, UI_SET_EVBIT, EV_SYN)
        # Enable each key we'll use
        for kc, _ in key_sequence:
            fcntl.ioctl(fd, UI_SET_KEYBIT, kc)

        # Configure the virtual device via uinput_setup struct:
        #   bustype(H) vendor(H) product(H) version(H) name[80](80s) ff_effects_max(I)
        #   = 2+2+2+2+80+4 = 92 bytes
        setup = struct.pack("HHHH80sI", 6, 0, 0, 1, b"tinc", 0)
        fcntl.ioctl(fd, UI_DEV_SETUP, setup)
        fcntl.ioctl(fd, UI_DEV_CREATE)
        time.sleep(0.15)  # kernel needs a moment to register the virtual device

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


# ─── Public helpers ────────────────────────────────────────────────────────────

def ctrl_v() -> bool:
    """Send Ctrl+V (paste). Works in all apps — no portal, no popup."""
    return _send([
        (KEY_LEFTCTRL, 1),
        (KEY_V,        1),
        (KEY_V,        0),
        (KEY_LEFTCTRL, 0),
    ])


def backspace(n: int) -> bool:
    """Press Backspace n times via uinput."""
    seq = []
    for _ in range(n):
        seq.append((KEY_BACKSPACE, 1))
        seq.append((KEY_BACKSPACE, 0))
    return _send(seq, delay=0.01)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "ctrl+v":
        ok = ctrl_v()
        sys.exit(0 if ok else 1)
    if len(sys.argv) > 2 and sys.argv[1] == "backspace":
        ok = backspace(int(sys.argv[2]))
        sys.exit(0 if ok else 1)
    print("Usage: tinc_uinput.py ctrl+v  |  tinc_uinput.py backspace N")
