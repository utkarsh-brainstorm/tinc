#!/usr/bin/env python3
"""
ai_router.py — Routes all Espanso AI triggers for Tinc.

OUTPUT INJECTION: xdotool type (X11/XWayland)
  wtype is NOT used — compositor rejects virtual keyboard protocol on this system.
  xdotool type handles newlines natively (\\n → Return key) and requires
  zero portal access.

TYPING SPEED: 2000 CPM (30ms per char) for writing/code modes.
              Instant (delay=1) for ai/ad/av.

LOADING TEXT MECHANISM:
  Router outputs LOADING_LEN spaces → Espanso injects them.
  Background worker: move cursor left LOADING_LEN, overwrite with loading text.
  After API: backspace LOADING_LEN, type result.

SUFFIX MAP:
  ai    → direct answer, zero system prompt
  av    → ai + clipboard context (i→v)
  ad    → short, precise 1-2 line answer
  fix   → spelling/grammar fix, preserve tone
  tldr  → 1-2 sentence summary
  ref   → refactor + comment code
  py    → Python only
  cp    → C++ only
  sh    → Bash only
  htm   → HTML only
  csv   → CSV only
  json  → JSON only
  Clipboard variants (replace last char with v):
  fiv tldv rev pv cv sv htv jsov csj
"""
import os
import sys
import re
import subprocess
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tinc_client

LOADING_TEXT = "Bas ittu sa time aur..."
LOADING_LEN  = len(LOADING_TEXT)   # 23

# Typing speed: 2000 CPS = 30ms per char
TYPING_DELAY_MS = 0.5

# ─── Suffix → (base_mode, use_clipboard) ─────────────────────────────────────
SUFFIX_MAP = {
    "ai":   ("ai",   False),
    "av":   ("ai",   True),
    "ad":   ("ad",   False),
    "fix":  ("fix",  False),
    "tldr": ("tldr", False),
    "ref":  ("ref",  False),
    "py":   ("py",   False),
    "cp":   ("cp",   False),
    "sh":   ("sh",   False),
    "htm":  ("htm",  False),
    "csv":  ("csv",  False),
    "json": ("json", False),
    # Clipboard variants
    "fiv":  ("fix",  True),
    "tldv": ("tldr", True),
    "rev":  ("ref",  True),
    "pv":   ("py",   True),
    "cv":   ("cp",   True),
    "sv":   ("sh",   True),
    "htv":  ("htm",  True),
    "jsov": ("json", True),
    "csj":  ("csv",  True),
}

# ─── System prompts ───────────────────────────────────────────────────────────
SYSTEM_PROMPTS = {
    # ai has NO entry — zero system prompt, raw model output
    "ad": (
        "Answer in one or two lines maximum. Be extremely direct and precise. "
        "No introductions, no explanations, no markdown. Just the answer."
    ),
    "fix": (
        "Fix ONLY clear spelling errors and obvious tiny grammar issues. "
        "Do NOT rephrase, restructure, or change the author's voice or style. "
        "Output ONLY the corrected text. Nothing else."
    ),
    "tldr": (
        "Summarize in 1-2 sentences maximum. "
        "Output ONLY the summary. No prefix like 'TL;DR:'."
    ),
    "ref": (
        "Refactor and optimize the code. Add concise inline comments. "
        "Output ONLY the refactored code. No prose."
    ),
    "py":   "Output ONLY valid Python code. No prose. Short inline comments are fine.",
    "cp":   "Output ONLY valid C++ code. No prose. Short inline comments are fine.",
    "sh":   "Output ONLY valid Bash script. No prose. Short inline comments are fine.",
    "htm":  "Output ONLY valid HTML. No prose.",
    "csv":  "Output ONLY valid CSV data. No prose.",
    "json": "Output ONLY valid JSON. No prose.",
}

TYPING_MODES = {"fix", "tldr", "ref", "py", "cp", "sh", "htm", "csv", "json"}


# ─── Helpers ─────────────────────────────────────────────────────────────────

def get_active_window_id() -> str:
    try:
        r = subprocess.run(
            ["xprop", "-root", "_NET_ACTIVE_WINDOW"],
            capture_output=True, text=True, timeout=2
        )
        m = re.search(r"0x[0-9a-f]+", r.stdout)
        if m:
            return m.group(0)
    except Exception:
        pass
    return ""


def get_clipboard() -> str:
    for cmd in [
        ["wl-paste", "--no-newline"],
        ["xclip", "-selection", "clipboard", "-o"],
        ["xsel", "--clipboard", "--output"],
    ]:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout
        except Exception:
            continue
    return ""


def focus_window(win_id: str) -> None:
    if win_id:
        try:
            subprocess.run(["wmctrl", "-ia", win_id],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
            time.sleep(0.12)
        except Exception:
            pass


def xdo_key(key: str, win_id: str, repeat: int = 1) -> None:
    """Send a key press via xdotool key."""
    focus_window(win_id)
    cmd = ["xdotool", "key", "--clearmodifiers"]
    if repeat > 1:
        cmd += ["--repeat", str(repeat)]
    cmd.append(key)
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
    except Exception:
        pass


def paste_clipboard(win_id: str) -> None:
    """Send Ctrl+V to paste clipboard content."""
    focus_window(win_id)
    try:
        subprocess.run(
            ["xdotool", "key", "--clearmodifiers", "ctrl+v"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5
        )
    except Exception:
        pass


def copy_to_clipboard(text: str) -> None:
    """Copy text to clipboard via wl-copy."""
    try:
        proc = subprocess.Popen(
            ["wl-copy"],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        proc.communicate(input=text.encode("utf-8"), timeout=5)
    except Exception:
        try:
            proc = subprocess.Popen(
                ["xclip", "-selection", "clipboard"],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            proc.communicate(input=text.encode("utf-8"), timeout=5)
        except Exception:
            pass


def inject_instant(text: str, win_id: str) -> None:
    """
    For ai/ad/av: copy to clipboard and paste.
    Clipboard preserves ALL formatting including newlines perfectly.
    xdotool type sends linefeed (0xff0a) not Return (0xff0d) for \n —
    which most GUI text fields ignore. Clipboard paste is the only
    reliable way to inject multi-line text.
    """
    copy_to_clipboard(text)
    paste_clipboard(win_id)


def inject_typed(text: str, win_id: str, delay_ms: int = TYPING_DELAY_MS) -> None:
    """
    For typing modes: type char-by-char at 2000 CPM with explicit Return keys.
    Splits on \n and uses xdotool key Return between lines — the only
    reliable way to get actual Return keystrokes instead of linefeed.
    """
    focus_window(win_id)
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line:
            try:
                subprocess.run(
                    ["xdotool", "type", "--clearmodifiers",
                     "--delay", str(delay_ms), "--", line],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=max(30, len(line) // 2 + 10)
                )
            except Exception:
                pass
        if i < len(lines) - 1:
            # Explicit Return key — not \n which xdotool maps to linefeed
            try:
                subprocess.run(
                    ["xdotool", "key", "--clearmodifiers", "Return"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3
                )
            except Exception:
                pass
            if delay_ms > 1:
                time.sleep(delay_ms / 1000.0)


def erase_chars(n: int, win_id: str) -> None:
    """Backspace n characters."""
    xdo_key("BackSpace", win_id, repeat=n)


def move_cursor_left(n: int, win_id: str) -> None:
    """Move cursor left n positions."""
    xdo_key("Left", win_id, repeat=n)


def strip_code_fences(text: str) -> str:
    text = re.sub(r"^```[a-z]*\n?", "", text, flags=re.MULTILINE)
    text = re.sub(r"```\s*$",        "", text, flags=re.MULTILINE)
    return text.strip()


def build_messages(base_mode: str, prompt: str, clipboard: str = "") -> list:
    msgs = []
    sys_prompt = SYSTEM_PROMPTS.get(base_mode)
    if sys_prompt:
        msgs.append({"role": "system", "content": sys_prompt})

    if clipboard:
        user_content = f"Instruction: {prompt}\n\nContext:\n{clipboard}" if prompt else clipboard
    else:
        user_content = prompt

    msgs.append({"role": "user", "content": user_content})
    return msgs


# ─── Async worker ─────────────────────────────────────────────────────────────

def async_worker(base_mode: str, prompt: str, prev_win_id: str, use_clipboard: bool) -> None:
    """
    Erases loading text, calls API, injects result.
    """
    # Step 1: API call
    clipboard_text = get_clipboard() if use_clipboard else ""
    msgs = build_messages(base_mode, prompt, clipboard_text)
    result = tinc_client.chat(msgs)
    result = (result or "").strip()

    # Strip code fences from code/command outputs
    if base_mode in TYPING_MODES or base_mode == "ad":
        result = strip_code_fences(result)

    # Step 2: Erase loading text
    erase_chars(LOADING_LEN, prev_win_id)

    if not result:
        return

    # Step 3: Inject result
    if base_mode in TYPING_MODES:
        inject_typed(result, prev_win_id)
    else:
        inject_instant(result, prev_win_id)


# ─── Main router ─────────────────────────────────────────────────────────────

def route(mode: str, prompt: str) -> None:
    if mode not in SUFFIX_MAP:
        return

    base_mode, use_clipboard = SUFFIX_MAP[mode]
    prev_win_id = get_active_window_id()

    subprocess.Popen(
        [sys.executable, os.path.abspath(__file__),
         "--async-worker", base_mode, prompt, prev_win_id,
         "1" if use_clipboard else "0"],
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Print loading text directly — background worker will backspace it and type result
    print(LOADING_TEXT, end="")


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) >= 6 and sys.argv[1] == "--async-worker":
        _, _, base_mode, prompt, prev_win_id, use_cb_str = sys.argv[:6]
        async_worker(base_mode, prompt, prev_win_id, use_cb_str == "1")
        sys.exit(0)

    mode   = os.environ.get("ESPANSO_MODE", "").strip()
    prompt = os.environ.get("ESPANSO_TEXT", "").strip()

    if not mode and len(sys.argv) >= 3:
        mode, prompt = sys.argv[1].strip(), sys.argv[2].strip()

    if mode:
        route(mode, prompt)
