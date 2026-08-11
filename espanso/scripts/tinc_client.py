#!/usr/bin/env python3
"""
tinc_client.py — Multi-provider AI client for Tinc.

PROVIDER CHAIN (auto-fallback on quota exhaustion):
  1. Google Gemini (gemini-2.5-flash-lite) — primary, has web search grounding
  2. Groq key 1  (llama-3.3-70b-versatile)
  3. Groq key 2  (fallback)
  4. Groq key 3  (fallback)

Config: ~/.config/tinc/config.json  (NEVER committed to git)
{
  "gemini_api_key": "...",
  "gemini_model":   "gemini-2.5-flash-lite",
  "groq_api_keys":  ["key1", "key2", "key3"],
  "groq_model":     "llama-3.3-70b-versatile"
}
"""
import os
import sys
import json
import re
import urllib.request
import urllib.error

CONFIG_PATH = os.path.expanduser("~/.config/tinc/config.json")

# ─── Config ──────────────────────────────────────────────────────────────────

def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        return {
            "gemini_api_key":  os.environ.get("GEMINI_API_KEY", ""),
            "gemini_model":    "gemini-2.5-flash-lite",
            "groq_api_keys":   [os.environ.get("GROQ_API_KEY", "")],
            "groq_model":      "llama-3.3-70b-versatile",
        }
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ─── Gemini provider ─────────────────────────────────────────────────────────

def _gemini_chat(messages: list, cfg: dict) -> str:
    """
    Call Google Gemini with Google Search grounding enabled.
    Converts OpenAI-style messages to Gemini format.
    Raises urllib.error.HTTPError on quota/auth errors.
    """
    api_key = cfg.get("gemini_api_key", "").strip()
    model   = cfg.get("gemini_model", "gemini-2.5-flash-lite")

    if not api_key:
        raise ValueError("gemini_api_key not set in config.json")

    # Separate system instruction from conversation
    system_text = ""
    contents = []
    for msg in messages:
        role = msg.get("role", "user")
        text = msg.get("content", "")
        if role == "system":
            system_text = text
        else:
            # Gemini uses "model" not "assistant"
            gemini_role = "model" if role == "assistant" else "user"
            contents.append({"role": gemini_role, "parts": [{"text": text}]})

    body: dict = {
        "contents": contents,
        # Web search grounding — lets Gemini browse the web for current info
        "tools": [{"google_search": {}}],
        "generationConfig": {
            "maxOutputTokens": 1024,
            "temperature": 0.5,
        },
    }
    if system_text:
        body["systemInstruction"] = {"parts": [{"text": system_text}]}

    payload = json.dumps(body).encode("utf-8")
    url = (
        f"https://generativelanguage.googleapis.com/v1beta"
        f"/models/{model}:generateContent?key={api_key}"
    )
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "tinc/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read().decode("utf-8"))
        # Gemini response: candidates[0].content.parts[0].text
        parts = result["candidates"][0]["content"]["parts"]
        # Concatenate all text parts (search results may split them)
        return "".join(p.get("text", "") for p in parts if "text" in p)


# ─── Groq provider ───────────────────────────────────────────────────────────

def _groq_chat(messages: list, api_key: str, model: str) -> str:
    """
    Call Groq API. Raises urllib.error.HTTPError on quota/auth errors.
    """
    if not api_key or not api_key.strip():
        raise ValueError("empty groq api key")

    payload = json.dumps({
        "model":       model,
        "messages":    messages,
        "temperature": 0.5,
        "stream":      False,
        "max_tokens":  1024,
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=payload,
        headers={
            "Authorization":  f"Bearer {api_key.strip()}",
            "Content-Type":   "application/json",
            "User-Agent":     "tinc/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read().decode("utf-8"))
        return body["choices"][0]["message"]["content"]


# ─── Error helpers ───────────────────────────────────────────────────────────

def _is_quota_error(e: urllib.error.HTTPError) -> bool:
    return e.code == 429


def _parse_wait(e: urllib.error.HTTPError) -> str:
    try:
        body = json.loads(e.read().decode("utf-8"))
        msg = (body.get("error", {}) or {}).get("message", "")
        m = re.search(r"try again in ([\d\w. ]+?)(?:\.|$)", msg, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    except Exception:
        pass
    return "a moment"


# ─── Public API ──────────────────────────────────────────────────────────────

def chat(messages: list) -> str:
    """
    Try Gemini first. On quota error (429), fall through each Groq key in order.
    Returns a plain string — either the AI response or a [Tinc Error: ...] message.
    """
    cfg = load_config()

    # ── 1. Gemini ────────────────────────────────────────────────────────────
    try:
        return _gemini_chat(messages, cfg)
    except urllib.error.HTTPError as e:
        if _is_quota_error(e):
            wait = _parse_wait(e)
            _last_err = f"Gemini quota (retry in {wait})"
        elif e.code == 401:
            _last_err = "Gemini: invalid API key"
        else:
            # Non-quota Gemini error — still fall through to Groq
            _last_err = f"Gemini HTTP {e.code}"
    except Exception as e:
        _last_err = f"Gemini: {type(e).__name__}"

    # ── 2. Groq fallback chain ───────────────────────────────────────────────
    groq_keys  = cfg.get("groq_api_keys", [])
    groq_model = cfg.get("groq_model", "llama-3.3-70b-versatile")

    for i, key in enumerate(groq_keys):
        if not key or not key.strip():
            continue
        try:
            return _groq_chat(messages, key, groq_model)
        except urllib.error.HTTPError as e:
            if _is_quota_error(e):
                wait = _parse_wait(e)
                _last_err = f"Groq key {i+1} quota (retry in {wait})"
                continue   # try next key
            elif e.code == 401:
                _last_err = f"Groq key {i+1}: invalid key"
                continue
            else:
                return f"[Tinc Error: Groq HTTP {e.code}]"
        except Exception as e:
            _last_err = f"Groq key {i+1}: {type(e).__name__}"
            continue

    return f"[Tinc: all providers exhausted — {_last_err}]"


# ─── Legacy shims (backwards compat) ─────────────────────────────────────────

def stream_chat(messages: list):
    """Compatibility shim — yields the full result as one chunk."""
    yield chat(messages)


def run_chat(messages: list, stream: bool = False):
    if stream:
        return stream_chat(messages)
    return chat(messages)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        msgs = [{"role": "user", "content": sys.argv[1]}]
        print(chat(msgs))
