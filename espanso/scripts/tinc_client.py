#!/usr/bin/env python3
"""
tinc_client.py — Zero-dependency Groq API client for Tinc.
Reads the API key and model from ~/.config/tinc/config.json.
"""
import os
import sys
import json
import urllib.request
import urllib.error

CONFIG_PATH = os.path.expanduser("~/.config/tinc/config.json")


def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        return {
            "api_key": os.environ.get("GROQ_API_KEY", ""),
            "model": "llama-3.3-70b-versatile"
        }
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _make_request(messages: list, stream: bool):
    """Low level: returns the urllib response object."""
    cfg = load_config()
    api_key = cfg.get("api_key", "").strip()
    model   = cfg.get("model", "llama-3.3-70b-versatile")

    if not api_key:
        raise ValueError("API key not set. Edit ~/.config/tinc/config.json")

    payload = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": 0.5,
        "stream": stream,
        "max_tokens": 1024,   # conservative: preserves daily free-tier quota
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "tinc/1.0",
        },
        method="POST",
    )
    return urllib.request.urlopen(req, timeout=30)


def _classify_http_error(e: urllib.error.HTTPError) -> str:
    """Parse Groq's error body for a meaningful message."""
    import re
    try:
        body = json.loads(e.read().decode("utf-8"))
        api_msg = body.get("error", {}).get("message", "")
    except Exception:
        api_msg = ""

    if e.code == 401:
        return "[Tinc Error: Unauthorized — check your API key in ~/.config/tinc/config.json]"

    if e.code == 429:
        # Extract 'try again in Xm Ys' from Groq's message
        m = re.search(r"try again in ([\d\w. ]+?)(?:\.|$)", api_msg, re.IGNORECASE)
        wait = m.group(1).strip() if m else "a moment"
        # Check if it's a daily limit (TPD) or per-minute limit (TPM)
        kind = "daily token limit" if "per day" in api_msg or "TPD" in api_msg else "rate limit"
        return f"[Tinc: {kind} hit — retry in {wait}]"

    if e.code >= 500:
        return f"[Tinc Error: Groq server error ({e.code})]"
    return f"[Tinc Error: HTTP {e.code} — {api_msg[:80]}]"


# ─── Public API ───────────────────────────────────────────────────────────────

def chat(messages: list) -> str:
    """Blocking, returns the full response as a string."""
    try:
        with _make_request(messages, stream=False) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return body["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        return _classify_http_error(e)
    except ValueError as e:
        return f"[Tinc Error: {e}]"
    except TimeoutError:
        return "[Tinc Error: Timeout — AI took too long to respond]"
    except Exception as e:
        return f"[Tinc Error: {type(e).__name__}: {e}]"


def stream_chat(messages: list):
    """Generator: yields text chunks one by one."""
    try:
        with _make_request(messages, stream=True) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8").strip()
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                    content = chunk["choices"][0].get("delta", {}).get("content", "")
                    if content:
                        yield content
                except (json.JSONDecodeError, KeyError):
                    continue
    except urllib.error.HTTPError as e:
        yield _classify_http_error(e)
    except ValueError as e:
        yield f"[Tinc Error: {e}]"
    except TimeoutError:
        yield "[Tinc Error: Timeout — AI took too long to respond]"
    except Exception as e:
        yield f"[Tinc Error: {type(e).__name__}: {e}]"


# Keep backwards-compat shim used by ai_gui.py (which calls run_chat with stream=True)
def run_chat(messages: list, stream: bool = False):
    if stream:
        return stream_chat(messages)
    return chat(messages)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        msgs = [{"role": "user", "content": sys.argv[1]}]
        if "--stream" in sys.argv:
            for c in stream_chat(msgs):
                print(c, end="", flush=True)
            print()
        else:
            print(chat(msgs))
