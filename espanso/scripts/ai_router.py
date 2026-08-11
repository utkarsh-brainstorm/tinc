#!/usr/bin/env python3
"""
ai_router.py — Routes all Espanso AI triggers for Tinc.

Modes (via ESPANSO_MODE env var or --async-paste CLI flag):
  ai    → Open Spotlight GUI (pywebview)
  ac    → Shell command only (async, paste)
  ad    → Full AI answer (async, paste)
  av    → AI with clipboard as context (async, paste)
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

# Ensure we can always import tinc_client from the same directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tinc_client

AI_GUI_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ai_gui.py")
GUI_PYTHON    = "/usr/bin/python3"

# ─── System prompts for each mode ────────────────────────────────────────────
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

# Modes where we type output char-by-char for a streaming feel
TYPING_MODES = {"fix", "tldr", "ref", "py", "cp", "sh", "htm", "csv", "json"}

# Modes that use clipboard content as the primary input
CLIPBOARD_MODES = {m + "v" for m in ["ad", "fix", "tldr", "ref", "py", "cp", "sh", "htm", "csv", "json", "ac"]}


# ─── Helpers ─────────────────────────────────────────────────────────────────

def get_active_window_id() -> str:
    """Get the currently focused X11 window ID."""
    try:
        result = subprocess.run(
            ["bash", "-c",
             "xprop -root _NET_ACTIVE_WINDOW 2>/dev/null | grep -o '0x[0-9a-f]*' | head -1"],
            capture_output=True, text=True, timeout=2
        )
        for line in result.stdout.strip().splitlines():
            if line.startswith("0x") and len(line) > 4:
                return line.strip()
    except Exception:
        pass
    return ""


def get_clipboard() -> str:
    """Read current clipboard content."""
    for cmd in [["wl-paste", "--no-newline"], ["xclip", "-selection", "clipboard", "-o"], ["xsel", "--clipboard", "--output"]]:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout
        except Exception:
            continue
    return ""


def copy_to_clipboard(text: str) -> None:
    """Copy text to clipboard."""
    for cmd in [["wl-copy"], ["xclip", "-selection", "clipboard"]]:
        try:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
            proc.communicate(input=text.encode("utf-8"))
            return
        except FileNotFoundError:
            continue


def focus_window(win_id: str) -> None:
    if win_id:
        try:
            subprocess.run(["wmctrl", "-ia", win_id], timeout=2)
            time.sleep(0.15)
        except Exception:
            pass


def paste_clipboard(win_id: str) -> None:
    """Paste clipboard to the focused window using wtype → xdotool fallback."""
    focus_window(win_id)
    try:
        res = subprocess.run(["wtype", "-M", "ctrl", "-k", "v", "-m", "ctrl"],
                             capture_output=True, timeout=3)
        if res.returncode == 0:
            return
    except Exception:
        pass
    try:
        subprocess.run(["xdotool", "key", "--clearmodifiers", "ctrl+v"], timeout=3)
    except Exception:
        pass


def type_text(text: str, win_id: str) -> None:
    """
    Type text character-by-character at ~1000 cps using wtype --delay 1.
    Falls back to paste on failure.
    """
    focus_window(win_id)
    try:
        res = subprocess.run(
            ["wtype", "--delay", "1", "--", text],
            capture_output=True, timeout=max(10, len(text) // 100 + 5)
        )
        if res.returncode == 0:
            return
    except Exception:
        pass
    # Fallback: paste via clipboard
    copy_to_clipboard(text)
    paste_clipboard(win_id)


def erase_loading_indicator(win_id: str) -> None:
    """
    Erase the ⏳ loading emoji that Espanso typed.
    ⏳ is a multi-byte character — we backspace twice to be safe.
    """
    focus_window(win_id)
    for _ in range(2):
        try:
            subprocess.run(["wtype", "-k", "BackSpace"], capture_output=True, timeout=2)
        except Exception:
            try:
                subprocess.run(["xdotool", "key", "BackSpace"], timeout=2)
            except Exception:
                pass
        time.sleep(0.02)


def strip_code_fences(text: str) -> str:
    text = re.sub(r"^```[a-z]*\n?", "", text, flags=re.MULTILINE)
    text = re.sub(r"```\s*$", "", text, flags=re.MULTILINE)
    return text.strip()


def build_messages(base_mode: str, prompt: str, clipboard: str = "") -> list:
    """Build the messages list for the API call."""
    sys_prompt = SYSTEM_PROMPTS.get(base_mode, SYSTEM_PROMPTS["ad"])
    msgs = [{"role": "system", "content": sys_prompt}]

    if clipboard:
        if prompt:
            user_content = f"Instruction: {prompt}\n\nContext:\n{clipboard}"
        else:
            user_content = clipboard  # instruction is implied by system prompt
    else:
        user_content = prompt

    msgs.append({"role": "user", "content": user_content})
    return msgs


# ─── Async worker ─────────────────────────────────────────────────────────────

def async_worker(base_mode: str, prompt: str, prev_win_id: str, use_clipboard: bool) -> None:
    """
    Runs in a detached background process. Fetches AI response and outputs it.
    """
    clipboard = get_clipboard() if use_clipboard else ""
    msgs = build_messages(base_mode, prompt, clipboard)

    result = tinc_client.run_chat(msgs, stream=False)
    result = (result or "").strip()

    if base_mode == "ac":
        result = strip_code_fences(result)

    if not result:
        return

    # Erase the ⏳ loading indicator then output
    erase_loading_indicator(prev_win_id)

    if base_mode in TYPING_MODES:
        type_text(result, prev_win_id)
    else:
        copy_to_clipboard(result)
        paste_clipboard(prev_win_id)


# ─── Main router ─────────────────────────────────────────────────────────────

def route(mode: str, prompt: str) -> None:
    use_clipboard = mode.endswith("v") and mode != "av"  # 'av' is its own named mode
    if mode == "av":
        use_clipboard = True
        base_mode = "av"
    elif mode.endswith("v") and mode != "av":
        base_mode = mode[:-1]  # e.g. "fixv" → "fix"
    else:
        base_mode = mode

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

    # All other modes: show ⏳ immediately, process in background
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
    # Output ⏳ so Espanso replaces the trigger with a visible loading indicator
    print("⏳", end="")


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
