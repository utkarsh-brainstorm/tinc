#!/usr/bin/env python3
"""
ai_router.py — Espanso trigger router for Tinc.

All AI triggers follow the pattern  [your text]suffix
Espanso calls this script synchronously. It immediately prints the loading text
so Espanso injects it at the cursor. A background worker then:
  1. Calls the AI API
  2. Backspaces the loading text
  3. Copies the result to clipboard (X11 via xclip — no portal)
  4. Pastes it via xdotool key ctrl+v

SUFFIX TABLE:
  Suffix   Mode   Web    Description
  ──────────────────────────────────────────────────────────
  ai       ai     YES    Direct answer, zero system prompt
  av       ai     YES    Same + clipboard as context (i→v)
  ad       ad     YES    Short precise answer (1-2 lines, no markdown)
  fix      fix    NO     Fix spelling/grammar only, preserve style
  tldr     tldr   NO     1-2 sentence summary
  ref      ref    NO     Refactor + comment code
  py       py     NO     Python code only
  cp       cp     NO     C++ code only
  sh       sh     NO     Bash script only
  htm      htm    NO     HTML only
  csv      csv    NO     CSV only
  json     json   NO     JSON only

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
LOADING_LEN  = len(LOADING_TEXT)  # 23

# ─── Suffix map: suffix → (mode, web_search, use_clipboard) ─────────────────
SUFFIX_MAP = {
    "ai":   ("ai",   True,  False),
    "av":   ("ai",   True,  True),
    "ad":   ("ad",   True,  False),
    "fix":  ("fix",  False, False),
    "tldr": ("tldr", False, False),
    "ref":  ("ref",  False, False),
    "py":   ("py",   False, False),
    "cp":   ("cp",   False, False),
    "sh":   ("sh",   False, False),
    "htm":  ("htm",  False, False),
    "csv":  ("csv",  False, False),
    "json": ("json", False, False),
    # Clipboard variants
    "fiv":  ("fix",  False, True),
    "tldv": ("tldr", False, True),
    "rev":  ("ref",  False, True),
    "pv":   ("py",   False, True),
    "cv":   ("cp",   False, True),
    "sv":   ("sh",   False, True),
    "htv":  ("htm",  False, True),
    "jsov": ("json", False, True),
    "csj":  ("csv",  False, True),
}

# Modes that require a strict code-only system prompt
SYSTEM_PROMPTS = {
    # "ai" intentionally has NO system prompt — raw model output
    "ad": (
        "Answer in one or two sentences maximum. Be direct and precise. "
        "No markdown, no bullet points, no intro. Just the answer."
    ),
    "fix": (
        "Fix ONLY clear spelling errors and obvious grammar mistakes. "
        "Do NOT rephrase, restructure, or change the author's voice. "
        "Output ONLY the corrected text, nothing else."
    ),
    "tldr": (
        "Write a 1-2 sentence summary. "
        "Output ONLY the summary, no prefix like 'TL;DR:'."
    ),
    "ref": (
        "Refactor and optimize the given code. Add concise inline comments. "
        "Output ONLY the refactored code. No prose, no explanation."
    ),
    "py":   ("Output ONLY valid Python code. No explanation, no prose. "
             "Do NOT wrap in markdown code fences. Just the raw code."),
    "cp":   ("Output ONLY valid C++ code. No explanation, no prose. "
             "Do NOT wrap in markdown code fences. Just the raw code."),
    "sh":   ("Output ONLY a valid Bash script. No explanation, no prose. "
             "Do NOT wrap in markdown code fences. Just the raw code."),
    "htm":  ("Output ONLY valid HTML. No explanation, no prose. "
             "Do NOT wrap in markdown code fences. Just the raw HTML."),
    "csv":  "Output ONLY valid CSV data. No prose, no code fences.",
    "json": ("Output ONLY valid JSON. No explanation, no prose. "
             "Do NOT wrap in markdown code fences. Just the raw JSON."),
}


# ─── Helpers ─────────────────────────────────────────────────────────────────

def get_active_window_id() -> str:
    try:
        r = subprocess.run(["xprop", "-root", "_NET_ACTIVE_WINDOW"],
                           capture_output=True, text=True, timeout=2)
        m = re.search(r"0x[0-9a-f]+", r.stdout)
        return m.group(0) if m else ""
    except Exception:
        return ""


def focus_window(win_id: str) -> None:
    if win_id:
        try:
            subprocess.run(["wmctrl", "-ia", win_id],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
            time.sleep(0.1)
        except Exception:
            pass


def copy_to_clipboard(text: str) -> None:
    """X11 clipboard via xclip — no Wayland portal, no popup."""
    try:
        p = subprocess.Popen(["xclip", "-selection", "clipboard"],
                             stdin=subprocess.PIPE,
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        p.communicate(input=text.encode("utf-8"), timeout=5)
    except Exception:
        # wl-copy fallback
        try:
            p = subprocess.Popen(["wl-copy"],
                                 stdin=subprocess.PIPE,
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
            p.communicate(input=text.encode("utf-8"), timeout=5)
        except Exception:
            pass


def paste_clipboard(win_id: str) -> None:
    """Send Ctrl+V to paste. X11 keystroke via xdotool — no portal."""
    focus_window(win_id)
    try:
        subprocess.run(["xdotool", "key", "--clearmodifiers", "ctrl+v"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
    except Exception:
        pass


def erase_chars(n: int, win_id: str) -> None:
    """Backspace n characters via xdotool."""
    focus_window(win_id)
    try:
        subprocess.run(["xdotool", "key", "--clearmodifiers",
                        "--repeat", str(n), "BackSpace"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
    except Exception:
        pass


def get_clipboard_text() -> str:
    """Read current clipboard content."""
    for cmd in [["xclip", "-selection", "clipboard", "-o"],
                ["wl-paste", "--no-newline"]]:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout
        except Exception:
            continue
    return ""


def strip_code_fences(text: str) -> str:
    text = re.sub(r"^```[a-z]*\n?", "", text, flags=re.MULTILINE)
    text = re.sub(r"```\s*$",       "", text, flags=re.MULTILINE)
    return text.strip()


def build_messages(mode: str, prompt: str, context: str = "") -> list:
    msgs = []
    sys_prompt = SYSTEM_PROMPTS.get(mode)
    if sys_prompt:
        msgs.append({"role": "system", "content": sys_prompt})
    if context:
        user_content = f"Instruction: {prompt}\n\nContext:\n{context}" if prompt else context
    else:
        user_content = prompt
    msgs.append({"role": "user", "content": user_content})
    return msgs


# ─── Async worker ─────────────────────────────────────────────────────────────

def async_worker(mode: str, prompt: str, win_id: str,
                 web_search: bool, use_clipboard: bool) -> None:
    # Get clipboard context if needed
    context = get_clipboard_text() if use_clipboard else ""

    # API call
    msgs   = build_messages(mode, prompt, context)
    result = tinc_client.chat(msgs, web_search=web_search)
    result = (result or "").strip()

    # Strip code fences for all modes that output code/structured text
    CODE_MODES = {"fix", "tldr", "ref", "py", "cp", "sh", "htm", "csv", "json", "ad"}
    if mode in CODE_MODES:
        result = strip_code_fences(result)

    # Erase loading text, inject result
    erase_chars(LOADING_LEN, win_id)
    if result:
        copy_to_clipboard(result)
        paste_clipboard(win_id)


# ─── Main router ──────────────────────────────────────────────────────────────

def route(mode: str, prompt: str) -> None:
    if mode not in SUFFIX_MAP:
        return
    mode_name, web_search, use_clipboard = SUFFIX_MAP[mode]
    win_id = get_active_window_id()

    subprocess.Popen(
        [sys.executable, os.path.abspath(__file__),
         "--worker", mode_name, prompt, win_id,
         "1" if web_search else "0",
         "1" if use_clipboard else "0"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        # Do NOT use start_new_session=True — subprocess must inherit
        # the X11/Wayland session so xclip and xdotool work without portal.
    )
    print(LOADING_TEXT, end="")


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) >= 7 and sys.argv[1] == "--worker":
        _, _, mode, prompt, win_id, web_str, cb_str = sys.argv[:7]
        async_worker(mode, prompt, win_id,
                     web_search=(web_str == "1"),
                     use_clipboard=(cb_str == "1"))
        sys.exit(0)

    mode   = os.environ.get("ESPANSO_MODE", "").strip()
    prompt = os.environ.get("ESPANSO_TEXT", "").strip()
    if mode:
        route(mode, prompt)
