#!/usr/bin/env python3
"""
translate_client.py
===================
Ultra-fast client for the translation daemon.
Talks to the Unix socket, gets result instantly.
If daemon is down, auto-starts it and retries.
"""
import os
import sys
import json
import socket
import subprocess
import time

SOCKET_PATH = "/tmp/espanso_translate.sock"
DAEMON_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "translate_daemon.py")


def start_daemon() -> None:
    """Start the daemon in the background if it's not running."""
    subprocess.Popen(
        [sys.executable, DAEMON_SCRIPT],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    # Wait up to 2 seconds for socket to appear
    for _ in range(20):
        if os.path.exists(SOCKET_PATH):
            time.sleep(0.05)  # Let server bind completely
            return
        time.sleep(0.1)


def ask_daemon(mode: str, text: str) -> str:
    """Send request to daemon, return translation."""
    payload = json.dumps({"mode": mode, "text": text}) + "\n"
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(6.0)
            sock.connect(SOCKET_PATH)
            sock.sendall(payload.encode("utf-8"))
            # Read response
            result = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                result += chunk
            return result.decode("utf-8")
    except (FileNotFoundError, ConnectionRefusedError, OSError):
        return None


def translate(mode: str, text: str) -> str:
    """Translate text via daemon, auto-starting daemon if needed."""
    # Try once
    result = ask_daemon(mode, text)
    if result is not None:
        return result

    # Daemon not running — start it and retry
    start_daemon()
    result = ask_daemon(mode, text)
    if result is not None:
        return result

    # Final fallback: direct call (slow path)
    import urllib.request
    import urllib.parse
    try:
        encoded = urllib.parse.quote(text, safe="")
        url = (
            "https://translate.googleapis.com/translate_a/single"
            f"?client=gtx&sl=auto&tl=hi&dt=t&q={encoded}"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return "".join(p[0] for p in data[0] if p and p[0]).strip() or text
    except Exception:
        return text


if __name__ == "__main__":
    mode = os.environ.get("ESPANSO_MODE", "").strip()
    text = os.environ.get("ESPANSO_TEXT", "").strip()

    if not mode and len(sys.argv) >= 3:
        mode = sys.argv[1]
        text = sys.argv[2]

    if not mode or not text:
        sys.exit(0)

    print(translate(mode, text), end="")
