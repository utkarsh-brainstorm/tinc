#!/usr/bin/env python3
"""
ai_router.py — Routes Espanso AI triggers.

Modes (ESPANSO_MODE env var):
  ai  → Open persistent Spotlight chat window (pywebview)
  ac  → Return ONLY a shell command (async)
  ad  → Return AI answer and paste directly (async)
"""
import os
import sys
import re
import subprocess
import time

import tinc_client

AI_GUI_SCRIPT  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ai_gui.py")
GUI_PYTHON     = "/usr/bin/python3"   # has pywebview + WebKit2GTK


def get_active_window_id() -> str:
    """Get the currently focused window ID using wmctrl/xprop."""
    try:
        result = subprocess.run(
            ["bash", "-c",
             "wmctrl -l | head -1 | awk '{print $1}' 2>/dev/null; "
             "xprop -root _NET_ACTIVE_WINDOW 2>/dev/null | grep -o '0x[0-9a-f]*' | head -1"],
            capture_output=True, text=True, timeout=2
        )
        lines = result.stdout.strip().splitlines()
        for line in reversed(lines):
            if line.startswith("0x") and len(line) > 4:
                return line.strip()
    except Exception:
        pass
    return ""


def run_aichat(prompt: str, timeout: int = 30) -> str:
    """Run via tinc_client."""
    msgs = [{"role": "user", "content": prompt}]
    return tinc_client.run_chat(msgs, stream=False)


def run_and_paste_async(mode: str, prompt: str, prev_win_id: str) -> None:
    """Runs AI request in background and pastes result to the active window."""
    result = ""
    if mode == "ac":
        full_prompt = (
            "RULE: Output ONLY the raw shell command. No explanation. "
            "No markdown. No backticks. No code fences. "
            "Just the command, ready to run.\n\n"
            f"Task: {prompt}"
        )
        result = run_aichat(full_prompt)
        result = re.sub(r"^```[a-z]*\n?", "", result, flags=re.MULTILINE)
        result = re.sub(r"```\s*$", "", result, flags=re.MULTILINE)
        result = result.strip()
    elif mode == "ad":
        result = run_aichat(prompt)

    if not result:
        return

    # Copy to clipboard
    try:
        proc = subprocess.Popen(["wl-copy"], stdin=subprocess.PIPE)
        proc.communicate(input=result.encode("utf-8"))
    except FileNotFoundError:
        try:
            proc = subprocess.Popen(["xclip", "-selection", "clipboard"], stdin=subprocess.PIPE)
            proc.communicate(input=result.encode("utf-8"))
        except Exception:
            pass

    # Focus window and send Ctrl+V
    if prev_win_id:
        try:
            subprocess.run(["wmctrl", "-ia", prev_win_id], timeout=2)
            time.sleep(0.15)
        except Exception:
            pass

    sent = False
    try:
        res = subprocess.run(["wtype", "-M", "ctrl", "-k", "v", "-m", "ctrl"], timeout=2, capture_output=True)
        if res.returncode == 0:
            sent = True
    except Exception:
        pass

    if not sent:
        try:
            subprocess.run(["xdotool", "key", "--clearmodifiers", "ctrl+v"], timeout=2)
        except Exception:
            pass


def route(mode: str, prompt: str) -> None:
    if mode == "ai":
        prev_win_id = get_active_window_id()
        subprocess.Popen(
            [GUI_PYTHON, AI_GUI_SCRIPT, prompt, prev_win_id],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Output empty string so Espanso instantly deletes the trigger
        print("", end="")

    elif mode in ["ac", "ad"]:
        prev_win_id = get_active_window_id()
        
        # Spawn this script itself in the background with a special flag
        subprocess.Popen(
            [sys.executable, os.path.abspath(__file__), "--async-paste", mode, prompt, prev_win_id],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        
        # Output empty string so Espanso immediately clears the typed command
        # The background script will paste the actual result later
        print("", end="")


if __name__ == "__main__":
    if len(sys.argv) >= 5 and sys.argv[1] == "--async-paste":
        mode, prompt, prev_win_id = sys.argv[2], sys.argv[3], sys.argv[4]
        run_and_paste_async(mode, prompt, prev_win_id)
        sys.exit(0)

    mode   = os.environ.get("ESPANSO_MODE", "").strip()
    prompt = os.environ.get("ESPANSO_TEXT", "").strip()

    if not mode and len(sys.argv) >= 3:
        mode, prompt = sys.argv[1].strip(), sys.argv[2].strip()

    if mode and prompt:
        route(mode, prompt)
