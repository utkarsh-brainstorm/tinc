#!/usr/bin/env python3
"""
ai_router.py — Routes all Espanso AI triggers for Tinc.

SUFFIX MAP:
  ai    → direct answer, zero system prompt injection
  av    → ai + clipboard context (replace i→v)
  ad    → short, precise answer (no markdown, no padding)
  fix   → spelling/grammar fix, preserve tone
  tldr  → 1-2 sentence TL;DR summary
  ref   → refactor + comment code
  py    → Python code only
  cp    → C++ code only
  sh    → Bash script only
  htm   → HTML only
  csv   → CSV data only
  json  → JSON data only

  CLIPBOARD VARIANTS (replace last char of suffix with 'v'):
  fiv   → fix  + clipboard
  tldv  → tldr + clipboard
  rev   → ref  + clipboard
  pv    → py   + clipboard
  cv    → cp   + clipboard
  sv    → sh   + clipboard
  htv   → htm  + clipboard
  jsov  → json + clipboard
  csj   → csv  + clipboard  (csv already ends in v)

LOADING TEXT MECHANISM:
  Router outputs LOADING_LEN spaces so Espanso injects them.
  Background worker: move cursor left LOADING_LEN, overwrite with loading text.
  After API: backspace LOADING_LEN, type result.
  This guarantees loading text always fits regardless of trigger length.
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

# ─── Suffix → (base_mode, use_clipboard) ─────────────────────────────────────
SUFFIX_MAP = {
    # Core
    "ai":   ("ai",   False),
    "av":   ("ai",   True),    # clipboard variant of ai (replace i→v)
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
# ai has ZERO system prompt — raw model output, user sees exactly what model says
SYSTEM_PROMPTS = {
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

# Modes whose output is typed at 400 cps (streaming feel)
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


def move_cursor_left(n: int, win_id: str) -> None:
    """Send n Left arrow key presses to move cursor back."""
    focus_window(win_id)
    try:
        subprocess.run(
            ["xdotool", "key", "--clearmodifiers", "--repeat", str(n), "Left"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5
        )
    except Exception:
        try:
            # wtype fallback: send Left key repeatedly
            for _ in range(n):
                subprocess.run(["wtype", "-k", "Left"],
                               capture_output=True, timeout=2)
        except Exception:
            pass


def inject_text(text: str, win_id: str, delay_ms: int = 0) -> bool:
    """Inject text via wtype. Returns True on success."""
    focus_window(win_id)
    cmd = ["wtype"]
    if delay_ms > 0:
        cmd += ["--delay", str(delay_ms)]
    cmd += ["--", text]
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            timeout=max(20, len(text) // 30 + 10),
        )
        return r.returncode == 0
    except Exception:
        return False


def inject_text_xdotool(text: str, win_id: str, delay_ms: int = 0) -> None:
    """xdotool fallback for text injection."""
    focus_window(win_id)
    cmd = ["xdotool", "type", "--clearmodifiers"]
    if delay_ms > 0:
        cmd += ["--delay", str(delay_ms)]
    cmd += ["--", text]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=max(20, len(text) // 30 + 10))
    except Exception:
        pass


def erase_chars(n: int, win_id: str) -> None:
    """Backspace n characters in the focused window."""
    focus_window(win_id)
    try:
        subprocess.run(
            ["xdotool", "key", "--clearmodifiers", "--repeat", str(n), "BackSpace"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10
        )
        return
    except Exception:
        pass
    # wtype fallback
    try:
        bs = "\x08" * n
        subprocess.run(["wtype", "--", bs], capture_output=True, timeout=10)
    except Exception:
        pass


def do_inject(text: str, win_id: str, mode: str) -> None:
    """Inject text — typed at 400cps for writing/code modes, instant for others."""
    delay = 3 if mode in TYPING_MODES else 0
    ok = inject_text(text, win_id, delay_ms=delay)
    if not ok:
        inject_text_xdotool(text, win_id, delay_ms=delay)


def strip_code_fences(text: str) -> str:
    text = re.sub(r"^```[a-z]*\n?", "", text, flags=re.MULTILINE)
    text = re.sub(r"```\s*$", "", text, flags=re.MULTILINE)
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
    Step 1: Move cursor left LOADING_LEN, type loading text (overwrites spaces router placed).
    Step 2: Call API.
    Step 3: Erase loading text, inject result.
    """
    # Step 1 — Overwrite the placeholder spaces with the loading text
    time.sleep(0.1)   # tiny delay to let Espanso finish its own injection first
    move_cursor_left(LOADING_LEN, prev_win_id)
    ok = inject_text(LOADING_TEXT, prev_win_id, delay_ms=0)
    if not ok:
        inject_text_xdotool(LOADING_TEXT, prev_win_id, delay_ms=0)

    # Step 2 — API call
    clipboard = get_clipboard() if use_clipboard else ""
    msgs = build_messages(base_mode, prompt, clipboard)
    result = tinc_client.chat(msgs)
    result = (result or "").strip()

    if base_mode in TYPING_MODES or base_mode == "ad":
        result = strip_code_fences(result)

    # Step 3 — Replace loading text with result
    erase_chars(LOADING_LEN, prev_win_id)

    if result:
        do_inject(result, prev_win_id, base_mode)


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

    # Output LOADING_LEN spaces as placeholder.
    # Background worker will move cursor left and overwrite with loading text.
    print(" " * LOADING_LEN, end="")


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
