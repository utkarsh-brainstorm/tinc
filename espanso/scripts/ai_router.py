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

# ─── Suffix → (mode, web_search, use_clipboard, paste_mode) ───────────────
# paste_mode: 0 = Shift+Insert, 1 = Ctrl+Shift+V (Ptyxis), 2 = type_string (cmd)
SUFFIX_MAP = {
    # Default (Shift+Insert)
    "ai":   ("ai",   False, False, 0),
    "av":   ("ai",   False, True,  0),
    "ad":   ("ad",   False, False, 0),
    "fix":  ("fix",  False, False, 0),
    "tldr": ("tldr", False, False, 0),
    "ref":  ("ref",  False, False, 0),
    "py":   ("py",   False, False, 0),
    "cp":   ("cp",   False, False, 0),
    "sh":   ("sh",   False, False, 0),
    "htm":  ("htm",  False, False, 0),
    "csv":  ("csv",  False, False, 0),
    "json": ("json", False, False, 0),

    # Translation
    "hi":   ("hi",   False, False, 0),
    "hd":   ("hd",   False, False, 0),
    "hu":   ("hu",   False, False, 0),

    # Clipboard variants
    "fiv":  ("fix",  False, True,  0),
    "tldv": ("tldr", False, True,  0),
    "rev":  ("ref",  False, True,  0),
    "pv":   ("py",   False, True,  0),
    "cv":   ("cp",   False, True,  0),
    "sv":   ("sh",   False, True,  0),
    "htv":  ("htm",  False, True,  0),
    "jsov": ("json", False, True,  0),
    "csj":  ("csv",  False, True,  0),

    # Ptyxis variants (Ctrl+Shift+V)
    "aip":  ("ai",   False, False, 1),
    "adp":  ("ad",   False, False, 1),
    "fixp": ("fix",  False, False, 1),
    "tldrp":("tldr", False, False, 1),
    "refp": ("ref",  False, False, 1),
    "pyp":  ("py",   False, False, 1),
    "cpp":  ("cp",   False, False, 1),
    "shp":  ("sh",   False, False, 1),
    "cmdp": ("cmd",  False, False, 1),

    # Linux command mode
    "cmd":  ("cmd",  False, False, 0),
}

# ─── System prompts ───────────────────────────────────────────────────────────
SYSTEM_PROMPTS = {
    "ai": "You are a helpful assistant. Provide a direct, concise answer without any introductory or conversational filler. Output the raw answer directly.",
    "ad": "Provide a very precise and direct answer in 1 or 2 sentences maximum. No fluff. Do not include markdown if it's a simple text answer.",
    "fix": "Fix all spelling and grammar mistakes in the user's text. You MUST preserve the original tone, meaning, and formatting exactly. Output ONLY the corrected text, without any explanation.",
    "tldr": "Summarize the following text or concept in 1 or 2 concise sentences.",
    "ref": "Refactor the provided code to be more readable, efficient, and idiomatic. Add brief, helpful comments explaining your changes. Output ONLY the code.",
    "py": "Write an elegant, idiomatic Python script to solve the user's request. Output ONLY valid python code. No markdown formatting or explanations.",
    "cp": "Write elegant, idiomatic C++ code to solve the user's request. Output ONLY valid C++ code. No markdown formatting or explanations.",
    "sh": "Write a robust bash script/command to solve the user's request. Output ONLY valid bash code. No markdown formatting or explanations.",
    "htm": "Write semantic HTML to solve the user's request. Include inline CSS/JS if requested. Output ONLY valid HTML code. No markdown formatting or explanations.",
    "csv": "Generate CSV data for the user's request. Output ONLY valid CSV text. No markdown formatting or explanations.",
    "json": "Generate JSON data for the user's request. Output ONLY valid JSON text. No markdown formatting or explanations.",
    "cmd": "Write ONLY the linux terminal command to achieve the user's request. No markdown formatting. No explanations. No newlines.",
    "hi": "Translate the following text to Hindi natively using Devanagari script. Output ONLY the translated Devanagari text. Do not add any quotes, markdown, or English text.",
    "hd": "Transliterate the following Romanized Hindi (Hinglish) text into proper Devanagari script. Keep the exact same words, just change the script. Output ONLY the Devanagari text.",
    "hu": "Translate the following Hinglish (or mix of English/Hindi) text into proper, natural Hindi using Devanagari script. Output ONLY the Devanagari text.",
}

CODE_MODES = {"hi", "hd", "hu", "fix", "tldr", "ref", "py", "cp", "sh", "htm", "csv", "json", "ad", "cmd"}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def copy_to_clipboard(text: str) -> None:
    """Write text to Wayland clipboard AND primary selection, fallback to xclip."""
    for cmd in [["wl-copy"], ["wl-copy", "-p"], ["xclip", "-selection", "clipboard"], ["xclip", "-selection", "primary"]]:
        try:
            p = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                 stdout=open("/tmp/tinc_worker.out", "w"), stderr=subprocess.DEVNULL)
            p.communicate(input=text.encode("utf-8"), timeout=5)
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

def async_worker(mode: str, prompt: str, web_search: bool, use_clipboard: bool, paste_mode: int) -> None:
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

    # Erase loading text, then paste result
    tinc_uinput.backspace(LOADING_LEN)
    copy_to_clipboard(result)
    time.sleep(0.1)   # brief pause so clipboard settles before paste
    
    if paste_mode == 1:
        tinc_uinput.ctrl_shift_v()
    else:
        tinc_uinput.shift_insert()


# ─── Main router ──────────────────────────────────────────────────────────────

def route(mode: str, prompt: str) -> None:
    web_override = False
    if mode.startswith("w") and len(mode) > 1 and mode[1:] in SUFFIX_MAP:
        mode = mode[1:]
        web_override = True

    if mode not in SUFFIX_MAP:
        return
    mode_name, web_search, use_clipboard, paste_mode = SUFFIX_MAP[mode]

    if web_override:
        web_search = True

    # Spawn background worker — inherits full session
    subprocess.Popen(
        [sys.executable, os.path.abspath(__file__),
         "--worker", mode_name, prompt,
         "1" if web_search    else "0",
         "1" if use_clipboard else "0",
         str(paste_mode)],
        stdin=subprocess.DEVNULL,
        stdout=open("/tmp/tinc_worker.out", "w"),
        stderr=open("/tmp/tinc_worker.err", "w"),
    )
    # Print loading text
    print(LOADING_TEXT, end="")


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) >= 7 and sys.argv[1] == "--worker":
        _, _, mode, prompt, web_str, cb_str, paste_str = sys.argv[:7]
        async_worker(mode, prompt,
                     web_search=(web_str == "1"),
                     use_clipboard=(cb_str == "1"),
                     paste_mode=int(paste_str))
        sys.exit(0)

    mode   = os.environ.get("ESPANSO_MODE", "").strip()
    prompt = os.environ.get("ESPANSO_TEXT", "").strip()
    if mode:
        route(mode, prompt)
