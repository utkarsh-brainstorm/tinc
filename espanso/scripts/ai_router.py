#!/usr/bin/env python3
"""
ai_router.py — Routes all Espanso AI triggers for Tinc.

Modes (via ESPANSO_MODE env var or --async-worker CLI flag):
  ai    → Open Spotlight GUI (pywebview)
  ac    → Shell command only (async, paste via clipboard)
  ad    → Full AI answer (async, paste via clipboard)
  av    → AI with clipboard as context (async, paste via clipboard)
  fix   → Spelling/grammar fix preserving tone (async, typed)
  tldr  → TL;DR 1-2 sentence summary (async, typed)
  ref   → Refactor + comment code (async, typed)
  py    → Python code only (async, typed)
  cp    → C++ code only (async, typed)
  sh    → Bash script only (async, typed)
  htm   → HTML only (async, typed)
  csv   → CSV data only (async, typed)
  json  → JSON data only (async, typed)
  *v    → Clipboard-content variant of any above mode (empty brackets ok)
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
        "Fix ONLY clear spelling errors and tiny grammar issues (e.g. missing articles, wrong tense). "
        "Do NOT rephrase, restructure, or change the author's voice, vocabulary, or style. "
        "Output ONLY the corrected text — nothing else. No explanations. No quotes."
    ),
    "tldr": (
        "You produce ultra-concise executive summaries. "
        "Summarize the given content in 1-2 sentences maximum. "
        "Output ONLY the summary — no preamble, no 'TL;DR:' prefix, no quotes."
    ),
    "ref": (
        "You are an expert code refactorer. Clean up and optimize the given code. "
        "Add concise inline comments where helpful. "
        "Output ONLY the refactored code. No prose. No markdown fences unless the input already used them."
    ),
    "py":   "Output ONLY valid Python code. No prose. Short inline comments are fine.",
    "cp":   "Output ONLY valid C++ code. No prose. Short inline comments are fine.",
    "sh":   "Output ONLY valid Bash script. No prose. Short inline comments are fine.",
    "htm":  "Output ONLY valid HTML. No prose. No markdown.",
    "csv":  "Output ONLY valid CSV data. No prose. No markdown.",
    "json": "Output ONLY valid JSON. No prose. No markdown.",
}

# Modes that type output char-by-char for a streaming feel
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


def copy_to_clipboard(text: str) -> None:
    for cmd in [["wl-copy"], ["xclip", "-selection", "clipboard"]]:
        try:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            proc.communicate(input=text.encode("utf-8"), timeout=5)
            return
        except Exception:
            continue


def focus_window(win_id: str) -> None:
    if win_id:
        try:
            subprocess.run(["wmctrl", "-ia", win_id],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
            time.sleep(0.15)
        except Exception:
            pass


def paste_clipboard(win_id: str) -> None:
    focus_window(win_id)
    try:
        r = subprocess.run(["wtype", "-M", "ctrl", "-k", "v", "-m", "ctrl"],
                           capture_output=True, timeout=3)
        if r.returncode == 0:
            return
    except Exception:
        pass
    try:
        subprocess.run(["xdotool", "key", "--clearmodifiers", "ctrl+v"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
    except Exception:
        pass


def erase_loading_text(win_id: str) -> None:
    """Backspace over LOADING_TEXT character by character."""
    focus_window(win_id)
    n = len(LOADING_TEXT)
    # Use xdotool to send backspaces — more reliable than wtype for bulk backspace
    try:
        subprocess.run(
            ["xdotool", "key", "--clearmodifiers", "--repeat", str(n), "BackSpace"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5
        )
        return
    except Exception:
        pass
    # Fallback: wtype repeated backspace
    for _ in range(n):
        try:
            subprocess.run(["wtype", "-k", "BackSpace"],
                           capture_output=True, timeout=2)
        except Exception:
            pass
        time.sleep(0.01)


def type_text(text: str, win_id: str) -> None:
    """Type text at ~400 cps (2.5ms/char) via wtype --delay 3, fallback to paste."""
    focus_window(win_id)
    try:
        r = subprocess.run(
            ["wtype", "--delay", "3", "--", text],
            capture_output=True,
            timeout=max(20, len(text) // 30 + 5),
        )
        if r.returncode == 0:
            return
    except Exception:
        pass
    # Fallback: clipboard paste
    copy_to_clipboard(text)
    paste_clipboard(win_id)


def strip_code_fences(text: str) -> str:
    text = re.sub(r"^```[a-z]*\n?", "", text, flags=re.MULTILINE)
    text = re.sub(r"```\s*$", "", text, flags=re.MULTILINE)
    return text.strip()


def build_messages(base_mode: str, prompt: str, clipboard: str = "") -> list:
    sys_prompt = SYSTEM_PROMPTS.get(base_mode, SYSTEM_PROMPTS["ad"])
    msgs = [{"role": "system", "content": sys_prompt}]

    if clipboard:
        if prompt:
            user_content = f"Instruction: {prompt}\n\nContext:\n{clipboard}"
        else:
            user_content = clipboard
    else:
        user_content = prompt

    msgs.append({"role": "user", "content": user_content})
    return msgs


# ─── Async worker ─────────────────────────────────────────────────────────────

def async_worker(base_mode: str, prompt: str, prev_win_id: str, use_clipboard: bool) -> None:
    clipboard = get_clipboard() if use_clipboard else ""
    msgs = build_messages(base_mode, prompt, clipboard)

    result = tinc_client.chat(msgs)          # always blocking, always str
    result = (result or "").strip()

    # Strip code fences from ac AND all code-output modes
    if base_mode in {"ac"} | TYPING_MODES:
        result = strip_code_fences(result)

    # Always erase the loading text first
    erase_loading_text(prev_win_id)

    if not result:
        return

    if base_mode in TYPING_MODES:
        type_text(result, prev_win_id)
    else:
        copy_to_clipboard(result)
        paste_clipboard(prev_win_id)


# ─── Main router ─────────────────────────────────────────────────────────────

def route(mode: str, prompt: str) -> None:
    # Determine base mode and whether to use clipboard
    if mode.endswith("v") and mode != "av":
        base_mode = mode[:-1]   # "fixv" → "fix", "adv" → "ad"
        use_clipboard = True
    elif mode == "av":
        base_mode = "av"
        use_clipboard = True
    else:
        base_mode = mode
        use_clipboard = False

    if base_mode == "ai":
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

    # All other modes: output loading text, process in background
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
