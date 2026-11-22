#!/usr/bin/env python3
"""
tinc_client.py — Multi-provider AI client for Tinc.

Provider chain (automatic failover):
  1. Google Gemini (Key 1 -> Key 2)
  2. NVIDIA NIM (Key 1 -> Key 2)
  3. Groq (Key 1 -> Key 2 -> Key 3...)

Config file: ~/.config/tinc/config.json and optional project .env
"""
import os
import sys
import json
import re
import urllib.request
import urllib.error

CONFIG_PATH = os.path.expanduser("~/.config/tinc/config.json")
PROJECT_ENV_PATHS = [
    os.path.expanduser("~/.config/tinc/.env"),
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"),
]


def load_config() -> dict:
    cfg = {}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            pass

    # Read project-isolated .env (never touches machine environment variables)
    for ep in PROJECT_ENV_PATHS:
        if os.path.isfile(ep):
            try:
                with open(ep, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            k = k.strip().lower()
                            v = v.strip().strip('"').strip("'")
                            if k not in cfg or not cfg[k]:
                                if k == "max_tokens":
                                    try:
                                        cfg[k] = int(v)
                                    except Exception:
                                        cfg[k] = v
                                else:
                                    cfg[k] = v
            except Exception:
                pass
    return cfg


# ─── Gemini ──────────────────────────────────────────────────────────────────

def _gemini_chat(messages: list, api_key: str, model: str, web_search: bool = False, max_tokens: int = 16384) -> str:
    """
    Call Google Gemini API.
    Raises urllib.error.HTTPError on quota/auth errors (caller handles fallback).
    """
    if not api_key or not api_key.strip():
        raise ValueError("empty gemini key")

    system_text = ""
    contents = []
    for msg in messages:
        role = msg.get("role", "user")
        text = msg.get("content", "")
        if role == "system":
            system_text = text
        else:
            contents.append({
                "role": "model" if role == "assistant" else "user",
                "parts": [{"text": text}],
            })

    body: dict = {
        "contents": contents,
        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.5},
    }
    if system_text:
        body["systemInstruction"] = {"parts": [{"text": system_text}]}
    if web_search:
        body["tools"] = [{"google_search": {}}]

    payload = json.dumps(body).encode("utf-8")
    url = (f"https://generativelanguage.googleapis.com/v1beta"
           f"/models/{model}:generateContent?key={api_key.strip()}")
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "tinc/1.0"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read().decode("utf-8"))
        parts = result.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        return "".join(p.get("text", "") for p in parts if "text" in p)


# ─── NVIDIA NIM ──────────────────────────────────────────────────────────────

def _nvidia_chat(messages: list, api_key: str, model: str, max_tokens: int = 16384) -> str:
    """
    Call NVIDIA NIM API (OpenAI-compatible endpoint).
    """
    if not api_key or not api_key.strip():
        raise ValueError("empty nvidia key")

    payload = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": 0.5,
        "max_tokens": max_tokens
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://integrate.api.nvidia.com/v1/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key.strip()}",
            "Content-Type": "application/json",
            "User-Agent": "tinc/1.0"
        },
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        msg = data.get("choices", [{}])[0].get("message", {})
        # Support both standard content and reasoning models (Nemotron/R1 style)
        content = msg.get("content") or msg.get("reasoning_content") or ""
        return content.strip()


# ─── Groq ────────────────────────────────────────────────────────────────────

def _groq_chat(messages: list, api_key: str, model: str, max_tokens: int = 16384) -> str:
    """Call Groq API with automatic recovery if model context ceiling is lower."""
    if not api_key or not api_key.strip():
        raise ValueError("empty groq key")

    tokens_to_try = max_tokens
    for attempt in range(2):
        payload = json.dumps({
            "model": model,
            "messages": messages,
            "temperature": 0.5,
            "stream": False,
            "max_tokens": tokens_to_try,
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {api_key.strip()}",
                "Content-Type": "application/json",
                "User-Agent": "tinc/1.0"
            },
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            if e.code == 400 and attempt == 0:
                try:
                    err_msg = e.read().decode("utf-8")
                    m = re.search(r"less than or equal to `?(\d+)`?", err_msg)
                    if m:
                        tokens_to_try = int(m.group(1))
                        continue
                    elif tokens_to_try > 8192:
                        tokens_to_try = 8192
                        continue
                except Exception:
                    pass
            raise e


# ─── Error Helper ────────────────────────────────────────────────────────────

def _parse_wait(e: urllib.error.HTTPError) -> str:
    try:
        body = json.loads(e.read().decode("utf-8"))
        msg = (body.get("error", {}) or {}).get("message", "")
        m = re.search(r"try again in ([\d\w. ]+?)(?:\.|$)", msg, re.IGNORECASE)
        kind = "daily limit" if ("per day" in msg or "TPD" in msg) else "rate limit"
        wait = m.group(1).strip() if m else "a moment"
        return f"{kind} — retry in {wait}"
    except Exception:
        return f"HTTP {e.code}"


# ─── Public Chat Router ──────────────────────────────────────────────────────

def chat(messages: list, web_search: bool = False) -> str:
    """
    Tiered fallback chain:
      1. Gemini (Key 1 -> Key 2)
      2. NVIDIA (Key 1 -> Key 2)
      3. Groq (Key 1 -> Key 2 -> ...)
    """
    cfg = load_config()
    last = "no providers configured"
    try:
        max_tokens = int(cfg.get("max_tokens", 16384))
    except (ValueError, TypeError):
        max_tokens = 16384

    # 1. Gemini
    gemini_keys = [k for k in [cfg.get("gemini_api_key"), cfg.get("gemini_api_key_2")] if k and k.strip()]
    gemini_model = cfg.get("gemini_model", "gemini-2.5-flash")
    for i, gkey in enumerate(gemini_keys):
        try:
            return _gemini_chat(messages, gkey, gemini_model, web_search=web_search, max_tokens=max_tokens)
        except urllib.error.HTTPError as e:
            last = f"Gemini Key {i+1} {_parse_wait(e)}"
            continue
        except Exception as e:
            last = f"Gemini Key {i+1} {type(e).__name__}"
            continue

    # 2. NVIDIA
    nvidia_keys = [k for k in [cfg.get("nvidia_api_key"), cfg.get("nvidia_api_key_2")] if k and k.strip()]
    nvidia_model = cfg.get("nvidia_model", "minimaxai/minimax-m3.1-flash")
    for i, nkey in enumerate(nvidia_keys):
        try:
            return _nvidia_chat(messages, nkey, nvidia_model, max_tokens=max_tokens)
        except urllib.error.HTTPError as e:
            last = f"NVIDIA Key {i+1} {_parse_wait(e)}"
            continue
        except Exception as e:
            last = f"NVIDIA Key {i+1} {type(e).__name__}"
            continue

    # 3. Groq
    groq_keys = cfg.get("groq_api_keys", [])
    groq_model = cfg.get("groq_model", "llama-3.3-70b-versatile")
    for i, grkey in enumerate(groq_keys):
        if not (grkey or "").strip():
            continue
        try:
            return _groq_chat(messages, grkey, groq_model, max_tokens=max_tokens)
        except urllib.error.HTTPError as e:
            last = f"Groq Key {i+1} {_parse_wait(e)}"
            continue
        except Exception as e:
            last = f"Groq Key {i+1} {type(e).__name__}"
            continue

    print(f"[tinc error: all providers failed ({last})]", file=sys.stderr)
    return ""


if __name__ == "__main__":
    if len(sys.argv) > 1:
        print(chat([{"role": "user", "content": " ".join(sys.argv[1:])}],
                   web_search=True))
