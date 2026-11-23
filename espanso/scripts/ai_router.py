#!/usr/bin/env python3
"""
ai_router.py — Espanso trigger router for Tinc.

Trigger syntax:  [your text]suffix    (typed anywhere on the system)

Espanso calls this script synchronously for the replacement value.
It prints the loading text so Espanso injects it at the cursor, then
spawns a background worker that:
  1. Calls the AI API (Gemini → Groq fallback chain)
  2. Erases the loading text via /dev/uinput BackSpace
  3. Copies the result to Wayland clipboard (wl-copy) & primary selection
  4. Triggers paste via /dev/uinput
"""
import os
import sys
import re
import subprocess
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tinc_client
import tinc_uinput


LOADING_TEXT = "Abra ka Dabra..."
LOADING_LEN  = len(LOADING_TEXT)  # exactly 16 ASCII chars

# ─── Suffix → (mode, web_search, use_clipboard, paste_mode) ───────────────
# paste_mode: 0 = Shift+Insert, 1 = Ctrl+Shift+V (Ptyxis), 2 = Ctrl+V
SUFFIX_MAP = {
    # Default (Shift+Insert / Primary & Clipboard)
    "ad":   ("ad",   False, False, 0),
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
    "tldv": ("tldr", False, True,  0),
    "rev":  ("ref",  False, True,  0),
    "pv":   ("py",   False, True,  0),
    "cv":   ("cp",   False, True,  0),
    "sv":   ("sh",   False, True,  0),
    "htv":  ("htm",  False, True,  0),
    "jsov": ("json", False, True,  0),
    "csj":  ("csv",  False, True,  0),

    # Ptyxis variants (Ctrl+Shift+V)
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
    "tst": ("tst", True, False, 0),
    "fix": ("fix", False, False, 0),
    "fiv": ("fix", False, True, 0),
    "sujal": ("sujal", False, False, 0),
    "sujac": ("sujal", False, True, 0),
    "sqlite": ("sqlite", False, False, 0),
    "csql": ("sqlite", False, True, 0),
    "fuck": ("fuck", False, False, 0),
    "fucv": ("fuck", False, True, 0),
    "ai": ("ai", True, False, 0),
    "av": ("ai", True, True, 0),
}

# ─── System prompts ───────────────────────────────────────────────────────────
SYSTEM_PROMPTS = {
    "ad": "Provide a very precise and direct answer in 1 or 2 sentences maximum. No fluff. Do not include markdown if it's a simple text answer.",
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
    "tst": "This is a test AI prompt",
    "fix": "Fix all spelling and grammar mistakes in the user's text. You MUST preserve the original tone, meaning, and formatting exactly. Output ONLY the corrected text, without any explanation.IF THE TEXT IS A CODEBLOCK, THEN GIVE THE CORRECT CODE ALONG WITH A COMMENT ABOUT THE MISTAKE IN THE CODE (IN CODE CASE ONLY, RETURN THE CODE AS OUTPUT WITHOUT ANY EXTRA TEXT).",
    "sujal": "Whenenever you reply, add the {To, Sujal at the starting} and reply in short.",
    "sqlite": "Given a natural language question or a context describing a data requirement, generate a single, error-free SQL query that directly addresses the user's intent. Assume a well-structured relational database. Provide only the SQL query as the output.",
    "fuck": "# School Communication Assistant – AI Prompt\n\nYou are a professional School Communication Assistant. Your job is to help a school administrator quickly generate short, clear, polite, and effective messages to send to students, parents, teachers, staff members, and other stakeholders.\n\n## 1. Understand My Context\nI will provide information in casual language, incomplete sentences, Hinglish, Hindi, or English.\n\nYour job is to understand my intention and convert it into a properly written message.\n\nDo not expect me to write grammatically correct sentences or provide a perfectly structured context.\n\n## 2. Language Support\nGenerate every message in two versions:\n\n**English:** Natural, simple, professional English.\n\n**Hindi:** Natural, conversational Hindi. Use Devanagari script, not unnecessarily complicated or overly formal Hindi.\n\nBoth versions must communicate exactly the same information.\n\n## 3. Message Writing Rules\n- Keep messages SHORT and concise.\n- Prefer 1–4 sentences.\n- Use simple language that everyone can understand.\n- Maintain a respectful, polite, and professional school-administration tone.\n- Avoid unnecessary greetings, introductions, and explanations.\n- Make important dates, deadlines, instructions, and actions clear.\n- Use appropriate urgency when required.\n- Avoid robotic, AI-generated-sounding language.\n- Do not use excessive emojis, decorative symbols, or unnecessary formatting.\n- Make messages ready to copy and send directly through WhatsApp or SMS.\n\n## 4. Understand the Audience\nAdapt the tone according to the intended recipient:\n\n- **Parents:** Respectful, clear, and considerate.\n- **Students:** Friendly, simple, and motivating.\n- **Teachers:** Professional, direct, and cooperative.\n- **School Staff:** Clear, practical, and instruction-oriented.\n- **General Announcements:** Neutral, informative, and concise.\n\nIf I don't specify the audience, infer it from the context.\n\n## 5. Handling My Input\nI may provide context like:\n\n- \"Kal sabhi baccho ko 8 baje school aana hai.\"\n- \"Parents ko fees jama karne ke liye remind karna hai.\"\n- \"Teachers ko kal meeting ke liye bulana hai.\"\n- \"School band rahega due to heavy rain.\"\n- \"Sabhi students apni diary lekar aaye.\"\n\nConvert these into polished, ready-to-send messages.\n\nDo not change the actual meaning, invent dates, add unsupported instructions, or assume information I haven't provided.\n\nIf an essential detail is missing, ask only one short clarification question. Otherwise, make the best reasonable interpretation.\n\n## 6. Output Format\n\nAlways follow this format:\n\n**English 🇬🇧**\n[Ready-to-send English message]\n\n**Hindi 🇮🇳**\n[Ready-to-send Hindi message]\n\nKeep the two versions separate and easy to copy.\n\n## 7. Important Behaviour\n- Do not explain how you wrote the message.\n- Do not provide multiple alternatives unless I explicitly request them.\n- Do not add unnecessary commentary.\n- Prioritize accuracy, clarity, brevity, and natural language.\n- If I say \"make it shorter\", shorten both versions.\n- If I say \"make it more formal\", adjust both versions.\n- If I say \"WhatsApp style\", make it conversational but professional.\n- If I say \"urgent\", communicate urgency without sounding rude.\n\n**Your ultimate goal:** I should be able to type a rough instruction in my own language and immediately receive a professional English and Hindi message that I can copy and broadcast to hundreds of people.",
    "ai": "You are a helpful assistant. Provide a direct, concise answer without any introductory or conversational filler. Output the raw answer directly.",
}

CODE_MODES = {"hi", "hd", "hu", "tldr", "ref", "py", "cp", "sh", "htm", "csv", "json", "ad", "cmd", "tst", "fix", "sqlite"}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def copy_to_clipboard(text: str) -> None:
    """Write text to Wayland clipboard AND primary selection, fallback to xclip."""
    # Wayland: set both regular clipboard and primary selection
    for cmd in [["wl-copy"], ["wl-copy", "-p"]]:
        try:
            subprocess.run(
                cmd,
                input=text.encode("utf-8"),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=1
            )
        except Exception:
            pass

    # X11 / Xwayland fallback: set both clipboard and primary selection
    for cmd in [["xclip", "-selection", "clipboard"], ["xclip", "-selection", "primary"]]:
        try:
            subprocess.run(
                cmd,
                input=text.encode("utf-8"),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=0.5
            )
        except Exception:
            pass


def get_clipboard_text() -> str:
    """Read current clipboard content."""
    for cmd in [["wl-paste", "--no-newline"], ["xclip", "-selection", "clipboard", "-o"]]:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
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
    # Grace period to ensure Espanso has completed backspacing trigger and writing loading text
    time.sleep(0.12)

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

    # Set both clipboard and primary selection to the AI result
    copy_to_clipboard(result)
    time.sleep(0.04)   # brief pause so clipboard registers before paste

    # Atomically erase loading text and paste
    ok = tinc_uinput.erase_and_paste(LOADING_LEN, paste_mode)
    if not ok:
        # Fallback if atomic uinput failed
        tinc_uinput.backspace(LOADING_LEN)
        time.sleep(0.05)
        if paste_mode == 1:
            tinc_uinput.ctrl_shift_v()
        elif paste_mode == 2:
            tinc_uinput.ctrl_v()
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
