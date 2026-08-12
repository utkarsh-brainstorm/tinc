#!/usr/bin/env python3
"""
tinc_client.py — Multi-provider AI client for Tinc.

Provider chain (auto-fallback on quota/rate-limit):
  1. Google Gemini 2.5 Flash Lite  — primary, web search for ai/ad/av modes
  2. Groq key 1  (llama-3.3-70b-versatile)
  3. Groq key 2
  4. Groq key 3

Config file: ~/.config/tinc/config.json  (never committed to git)
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


def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        return {
            "gemini_api_key": os.environ.get("GEMINI_API_KEY", ""),
            "gemini_model":   "gemini-2.5-flash-lite",
            "groq_api_keys":  [os.environ.get("GROQ_API_KEY", "")],
            "groq_model":     "llama-3.3-70b-versatile",
        }
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ─── Gemini ──────────────────────────────────────────────────────────────────

def _gemini_chat(messages: list, cfg: dict, web_search: bool = False) -> str:
    """
    Call Gemini. web_search=True only for ai/ad/av — code modes must NOT search
    or the model returns prose explanations instead of pure code.
    Raises urllib.error.HTTPError on quota/auth errors (caller handles fallback).
    """
    api_key = cfg.get("gemini_api_key", "").strip()
    model   = cfg.get("gemini_model", "gemini-2.5-flash-lite")
    if not api_key:
        raise ValueError("gemini_api_key not set in config.json")

    system_text = ""
    contents = []
    for msg in messages:
        role = msg.get("role", "user")
        text = msg.get("content", "")
        if role == "system":
            system_text = text
        else:
            contents.append({
                "role":  "model" if role == "assistant" else "user",
                "parts": [{"text": text}],
            })

    body: dict = {
        "contents": contents,
        "generationConfig": {"maxOutputTokens": 1024, "temperature": 0.5},
    }
    if system_text:
        body["systemInstruction"] = {"parts": [{"text": system_text}]}
    if web_search:
        body["tools"] = [{"google_search": {}}]

    payload = json.dumps(body).encode("utf-8")
    url = (f"https://generativelanguage.googleapis.com/v1beta"
           f"/models/{model}:generateContent?key={api_key}")
    req = urllib.request.Request(url, data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "tinc/1.0"},
        method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read().decode("utf-8"))
        parts = result["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts if "text" in p)


# ─── Groq ────────────────────────────────────────────────────────────────────

def _groq_chat(messages: list, api_key: str, model: str) -> str:
    """Call Groq. Raises urllib.error.HTTPError on quota/auth errors."""
    if not api_key or not api_key.strip():
        raise ValueError("empty groq key")
    payload = json.dumps({
        "model": model, "messages": messages,
        "temperature": 0.5, "stream": False, "max_tokens": 1024,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions", data=payload,
        headers={"Authorization": f"Bearer {api_key.strip()}",
                 "Content-Type": "application/json", "User-Agent": "tinc/1.0"},
        method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))["choices"][0]["message"]["content"]


# ─── Error helpers ────────────────────────────────────────────────────────────

def _parse_wait(e: urllib.error.HTTPError) -> str:
    try:
        body = json.loads(e.read().decode("utf-8"))
        msg = (body.get("error", {}) or {}).get("message", "")
        m = re.search(r"try again in ([\d\w. ]+?)(?:\.|$)", msg, re.IGNORECASE)
        kind = "daily limit" if ("per day" in msg or "TPD" in msg) else "rate limit"
        wait = m.group(1).strip() if m else "a moment"
        return f"{kind} — retry in {wait}"
    except Exception:
        return "rate limit"


# ─── Public API ──────────────────────────────────────────────────────────────

def chat(messages: list, web_search: bool = False) -> str:
    """
    Try Gemini → Groq key 1 → Groq key 2 → Groq key 3.
    web_search=True enables Google Search grounding on Gemini (ai/ad/av only).
    """
    cfg = load_config()

    # 1. Gemini
    try:
        return _gemini_chat(messages, cfg, web_search=web_search)
    except urllib.error.HTTPError as e:
        last = f"Gemini HTTP {e.code}: {_parse_wait(e)}" if e.code == 429 else f"Gemini HTTP {e.code}"
    except Exception as e:
        last = f"Gemini {type(e).__name__}"

    # 2-4. Groq fallback chain
    groq_keys  = cfg.get("groq_api_keys", [])
    groq_model = cfg.get("groq_model", "llama-3.3-70b-versatile")
    for i, key in enumerate(groq_keys):
        if not (key or "").strip():
            continue
        try:
            return _groq_chat(messages, key, groq_model)
        except urllib.error.HTTPError as e:
            last = f"Groq{i+1} {_parse_wait(e)}"
            continue
        except Exception as e:
            last = f"Groq{i+1} {type(e).__name__}"
            continue

    return f"[Tinc: all providers exhausted — {last}]"


if __name__ == "__main__":
    if len(sys.argv) > 1:
        print(chat([{"role": "user", "content": " ".join(sys.argv[1:])}],
                   web_search=True))
