#!/usr/bin/env python3
"""
ai_router.py — Espanso trigger router for Tinc.

Trigger syntax:  [your text]suffix    (typed anywhere on the system)

Espanso calls this script synchronously for the replacement value.
It prints the loading text so Espanso injects it at the cursor, then
spawns a background worker that:
  1. Calls the AI API (Gemini → Groq fallback chain)
  2. Erases the loading text via /dev/uinput BackSpace
  3. Copies the result to Wayland clipboard (wl-copy)
  4. Sends Ctrl+V via /dev/uinput (same as Espanso itself uses)

WHY /dev/uinput FOR OUTPUT:

  Wayland portal Ctrl+V = triggers "Allow remote interaction" popup every restart
  /dev/uinput Ctrl+V   = kernel-level, reaches ALL apps, zero popup, same as Espanso

SUFFIX TABLE:
  Suffix   Mode   Web    Description
  ──────────────────────────────────────────────────────────
  ai       ai     YES    Direct AI answer (no system prompt)
  av       ai     YES    Same + clipboard as context
  ad       ad     YES    Short precise answer (1-2 sentences)
  fix      fix    NO     Fix spelling/grammar, preserve style
  tldr     tldr   NO     1-2 sentence summary
  ref      ref    NO     Refactor + comment code
  py       py     NO     Python code only
  cp       cp     NO     C++ code only
  sh       sh     NO     Bash script only
  htm      htm    NO     HTML only
  csv      csv    NO     CSV only
  json     json   NO     JSON only

  Clipboard variants (replace last char with v):
  fiv  tldv  rev  pv  cv  sv  htv  jsov  csj
"""
import os
import sys
import re
import subprocess
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tinc_client
import tinc_uinput

LOADING_TEXT = "Bas ittu sa time aur..."
LOADING_LEN  = len(LOADING_TEXT)  # 23

# ─── Suffix → (mode, web_search, use_clipboard) ──────────────────────────────
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

# ─── System prompts ───────────────────────────────────────────────────────────
# "ai" has NO system prompt — raw model output with web search
SYSTEM_PROMPTS = {
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
        "Output ONLY the refactored code. No explanation, no prose."
    ),
    "py": (
        "Output ONLY valid Python code. No explanation, no prose. "
        "Do NOT wrap in markdown code fences. Raw code only."
    ),
    "cp": (
        "Output ONLY valid C++ code. No explanation, no prose. "
        "Do NOT wrap in markdown code fences. Raw code only."
    ),
    "sh": (
        "Output ONLY a valid Bash script. No explanation, no prose. "
        "Do NOT wrap in markdown code fences. Raw code only."
    ),
    "htm": (
        "Output ONLY valid HTML. No explanation, no prose. "
        "Do NOT wrap in markdown code fences. Raw HTML only."
    ),
    "csv":  "Output ONLY valid CSV data. No prose, no code fences.",
    "json": (
        "Output ONLY valid JSON. No explanation, no prose. "
        "Do NOT wrap in markdown code fences. Raw JSON only."
    ),
}

CODE_MODES = {"fix", "tldr", "ref", "py", "cp", "sh", "htm", "csv", "json", "ad"}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def copy_to_clipboard(text: str) -> None:
    """Write text to Wayland clipboard (wl-copy). Falls back to xclip."""
    for cmd in [["wl-copy"], ["xclip", "-selection", "clipboard"]]:
        try:
            p = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            p.communicate(input=text.encode("utf-8"), timeout=5)
            if p.returncode == 0:
                return
        except Exception:
            continue


def get_clipboard_text() -> str:
    """Read current clipboard content."""
    for cmd in [["wl-paste", "--no-newline"], ["xclip", "-selection", "clipboard", "-o"]]:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout
        except Exception:
            continue
    return ""


def strip_code_fences(text: str) -> str:
    """Remove markdown ``` code fences from AI output."""
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

def async_worker(mode: str, prompt: str, web_search: bool, use_clipboard: bool) -> None:
    # Fetch clipboard context if needed
    context = get_clipboard_text() if use_clipboard else ""

    # Call AI
    msgs   = build_messages(mode, prompt, context)
    result = tinc_client.chat(msgs, web_search=web_search)
    result = (result or "").strip()

    # Strip markdown fences for code/structured output modes
    if mode in CODE_MODES:
        result = strip_code_fences(result)

    if not result:
        # Erase loading text and leave nothing
        tinc_uinput.backspace(LOADING_LEN)
        return

    # Erase loading text, then paste result — all via /dev/uinput (no portal)
    tinc_uinput.backspace(LOADING_LEN)
    copy_to_clipboard(result)
    time.sleep(0.1)   # brief pause so clipboard settles before paste
    tinc_uinput.ctrl_v()


# ─── Main router ──────────────────────────────────────────────────────────────

def route(mode: str, prompt: str) -> None:
    if mode not in SUFFIX_MAP:
        return
    mode_name, web_search, use_clipboard = SUFFIX_MAP[mode]

    # Spawn background worker — inherits full session (DISPLAY, WAYLAND_DISPLAY, etc.)
    subprocess.Popen(
        [sys.executable, os.path.abspath(__file__),
         "--worker", mode_name, prompt,
         "1" if web_search    else "0",
         "1" if use_clipboard else "0"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Print loading text — Espanso injects this at cursor via EVDEVInjector
    print(LOADING_TEXT, end="")


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) >= 6 and sys.argv[1] == "--worker":
        _, _, mode, prompt, web_str, cb_str = sys.argv[:6]
        async_worker(mode, prompt,
                     web_search=(web_str == "1"),
                     use_clipboard=(cb_str == "1"))
        sys.exit(0)

    mode   = os.environ.get("ESPANSO_MODE", "").strip()
    prompt = os.environ.get("ESPANSO_TEXT", "").strip()
    if mode:
        route(mode, prompt)
