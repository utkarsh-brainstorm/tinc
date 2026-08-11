#!/usr/bin/env python3
"""
tinc_client.py — Zero-dependency Groq streaming client for Tinc.
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


def run_chat(messages: list, stream: bool = False):
    """
    Sends a chat request to Groq API.
    If stream=True, yields text chunks. Otherwise returns the full response string.
    On any error, returns/yields a descriptive [Tinc Error: ...] message.
    """
    cfg = load_config()
    api_key = cfg.get("api_key", "").strip()
    model   = cfg.get("model", "llama-3.3-70b-versatile")

    if not api_key:
        msg = "[Tinc Error: API key not set. Run install.sh or edit ~/.config/tinc/config.json]"
        if stream:
            yield msg
            return
        return msg

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": 0.5,
        "stream": stream,
        "max_tokens": 4096,
    }).encode("utf-8")

    url = "https://api.groq.com/openai/v1/chat/completions"
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")

    try:
        if stream:
            with urllib.request.urlopen(req, timeout=20) as resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8").strip()
                    if not line or not line.startswith("data: "):
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
        else:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                return body["choices"][0]["message"]["content"]

    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        if e.code == 401:
            msg = "[Tinc Error: Unauthorized — Check your API key in ~/.config/tinc/config.json]"
        elif e.code == 429:
            msg = "[Tinc Error: Rate limit exceeded — Wait a moment and try again]"
        elif e.code >= 500:
            msg = f"[Tinc Error: Groq server error ({e.code})]"
        else:
            msg = f"[Tinc Error: HTTP {e.code}]"
        if stream:
            yield msg
        else:
            return msg

    except TimeoutError:
        msg = "[Tinc Error: Timeout — AI took too long to respond]"
        if stream:
            yield msg
        else:
            return msg

    except Exception as e:
        msg = f"[Tinc Error: {type(e).__name__}: {e}]"
        if stream:
            yield msg
        else:
            return msg


if __name__ == "__main__":
    if len(sys.argv) > 1:
        prompt = sys.argv[1]
        msgs = [{"role": "user", "content": prompt}]
        if "--stream" in sys.argv:
            for c in run_chat(msgs, stream=True):
                print(c, end="", flush=True)
            print()
        else:
            print(run_chat(msgs, stream=False))
