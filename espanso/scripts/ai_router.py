#!/usr/bin/env python3
"""
ai_router.py — Routes all Espanso AI triggers for Tinc.

All output is injected directly via wtype (no clipboard involved).
This means: no clipboard contamination, no clipboard manager dialogs,
and output follows app-level input rules just like real keystrokes.

SUFFIX → BASE MODE MAPPING
  ad    → ad  (answer direct)
  ac    → ac  (command only)
  av    → av  (answer from clipboard, no prompt needed)
  fix   → fix (spelling/grammar fix)
  tldr  → tldr (summary)
  ref   → ref (refactor code)
  py    → py  (python only)
  cp    → cp  (c++ only)
  sh    → sh  (bash only)
  htm   → htm (html only)
  csv   → csv (csv only)
  json  → json (json only)

CLIPBOARD VARIANTS (replace last char of suffix with 'v'):
  fiv   → fix  + clipboard
  tldv  → tldr + clipboard
  rev   → ref  + clipboard
  pv    → py   + clipboard
  cv    → cp   + clipboard
  sv    → sh   + clipboard
  htv   → htm  + clipboard
  jsov  → json + clipboard
  csj   → csv  + clipboard
  av    → ad   + clipboard (already named 'av')
"""
import os
import sys
import re
import subprocess
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tinc_client

AI_GUI_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ai_gui.py")
GUI_PYTHON    = "/usr/bin/python3"

LOADING_TEXT = "Bas ittu sa time aur..."

# ─── Suffix → (base_mode, use_clipboard) ─────────────────────────────────────
SUFFIX_MAP = {
    # Core modes
    "ad":   ("ad",   False),
    "ac":   ("ac",   False),
    "av":   ("av",   True),
    "fix":  ("fix",  False),
    "tldr": ("tldr", False),
    "ref":  ("ref",  False),
    "py":   ("py",   False),
    "cp":   ("cp",   False),
    "sh":   ("sh",   False),
    "htm":  ("htm",  False),
    "csv":  ("csv",  False),
    "json": ("json", False),
    # Clipboard variants (last char replaced with 'v')
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
    "ac": (
        "You output ONLY raw shell commands. No explanation. No markdown. "
        "No backticks. No code fences. Just the command, ready to run."
    ),
    "ad": "You are a concise assistant. Answer clearly. Use plain text, no markdown.",
    "av": "You are a concise assistant. Answer clearly. Use plain text, no markdown.",
    "fix": (
        "You are a spell-checker and micro grammar fixer. "
        "Fix ONLY clear spelling errors and tiny grammar issues. "
        "Do NOT rephrase, restructure, or change the author's voice or style. "
        "Output ONLY the corrected text. No explanations. No quotes."
    ),
    "tldr": (
        "Summarize the given content in 1-2 sentences maximum. "
        "Output ONLY the summary — no preamble, no 'TL;DR:' prefix."
    ),
    "ref": (
        "You are an expert code refactorer. Clean up and optimize the given code. "
        "Add concise inline comments where helpful. "
        "Output ONLY the refactored code. No prose. No markdown fences."
    ),
    "py":   "Output ONLY valid Python code. No prose. Short inline comments are fine.",
    "cp":   "Output ONLY valid C++ code. No prose. Short inline comments are fine.",
    "sh":   "Output ONLY valid Bash script. No prose. Short inline comments are fine.",
    "htm":  "Output ONLY valid HTML. No prose. No markdown.",
    "csv":  "Output ONLY valid CSV data. No prose. No markdown.",
    "json": "Output ONLY valid JSON. No prose. No markdown.",
}

# Modes whose output is typed char-by-char (for a streamed feel)
TYPING_MODES = {"fix", "tldr", "ref", "py", "cp", "sh", "htm", "csv", "json"}

# Modes whose output is injected instantly (full speed, no delay)
INSTANT_MODES = {"ad", "ac", "av"}


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
            time.sleep(0.15)
        except Exception:
            pass


def inject_text(text: str, win_id: str, delay_ms: int = 0) -> bool:
    """
    Inject text directly into the focused window via wtype.
    delay_ms=0: instant (full hardware speed) — used for ad/ac/av
    delay_ms=3: ~400 cps — used for fix/tldr/ref/code modes
    Returns True on success.
    """
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


def inject_text_xdotool(text: str, win_id: str) -> None:
    """xdotool fallback for systems without wtype."""
    focus_window(win_id)
    try:
        subprocess.run(
            ["xdotool", "type", "--clearmodifiers", "--delay", "3", "--", text],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=max(20, len(text) // 30 + 10),
        )
    except Exception:
        pass


def erase_loading_text(win_id: str) -> None:
    """Backspace over the loading text."""
    focus_window(win_id)
    n = len(LOADING_TEXT)
    try:
        subprocess.run(
            ["xdotool", "key", "--clearmodifiers", "--repeat", str(n), "BackSpace"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5
        )
        return
    except Exception:
        pass
    # wtype fallback
    bs = "\x08" * n
    try:
        subprocess.run(["wtype", "--", bs], capture_output=True, timeout=5)
    except Exception:
        pass


def strip_code_fences(text: str) -> str:
    text = re.sub(r"^```[a-z]*\n?", "", text, flags=re.MULTILINE)
    text = re.sub(r"```\s*$", "", text, flags=re.MULTILINE)
    return text.strip()


def build_messages(base_mode: str, prompt: str, clipboard: str = "") -> list:
    sys_prompt = SYSTEM_PROMPTS.get(base_mode, SYSTEM_PROMPTS["ad"])
    msgs = [{"role": "system", "content": sys_prompt}]
    if clipboard:
        user_content = f"Instruction: {prompt}\n\nContext:\n{clipboard}" if prompt else clipboard
    else:
        user_content = prompt
    msgs.append({"role": "user", "content": user_content})
    return msgs


# ─── Async worker ─────────────────────────────────────────────────────────────

def async_worker(base_mode: str, prompt: str, prev_win_id: str, use_clipboard: bool) -> None:
    clipboard = get_clipboard() if use_clipboard else ""
    msgs = build_messages(base_mode, prompt, clipboard)

    result = tinc_client.chat(msgs)
    result = (result or "").strip()

    # Strip markdown code fences from all code/command outputs
    if base_mode in TYPING_MODES or base_mode in ("ac",):
        result = strip_code_fences(result)

    # Erase loading text
    erase_loading_text(prev_win_id)

    if not result:
        return

    # Inject via wtype (no clipboard involved)
    if base_mode in TYPING_MODES:
        # Typed at 400 cps for visual streaming effect
        ok = inject_text(result, prev_win_id, delay_ms=3)
    else:
        # Instant injection for ad/ac/av responses
        ok = inject_text(result, prev_win_id, delay_ms=0)

    if not ok:
        # Fallback to xdotool if wtype failed
        inject_text_xdotool(result, prev_win_id)


# ─── Main router ─────────────────────────────────────────────────────────────

def route(mode: str, prompt: str) -> None:
    if mode not in SUFFIX_MAP and mode != "ai":
        return

    if mode == "ai":
        prev_win_id = get_active_window_id()
        subprocess.Popen(
            [GUI_PYTHON, AI_GUI_SCRIPT, prompt, prev_win_id],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print("", end="")
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
