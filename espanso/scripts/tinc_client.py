#!/usr/bin/env python3
"""
tinc_client.py — Zero-dependency Groq streaming client for Tinc.
Reads the API key and model from ~/.config/tinc/config.json.
"""
import os
import sys
import json
import requests

CONFIG_PATH = os.path.expanduser("~/.config/tinc/config.json")

def load_config():
    if not os.path.exists(CONFIG_PATH):
        # Fallback to hardcoded or environment variable for flexibility
        return {
            "api_key": os.environ.get("GROQ_API_KEY", ""),
            "model": "llama-3.3-70b-versatile"
        }
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def run_chat(messages, stream=False):
    """
    Sends a chat request to Groq API.
    Messages format: [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]
    If stream=True, yields chunks. Otherwise returns the full response string.
    """
    cfg = load_config()
    api_key = cfg.get("api_key")
    model = cfg.get("model", "llama-3.3-70b-versatile")

    if not api_key:
        if stream:
            yield "[Error: Groq API key not configured. Run 'tinc-setup' or add it to ~/.config/tinc/config.json]"
            return
        else:
            return "[Error: Groq API key not configured. Run 'tinc-setup' or add it to ~/.config/tinc/config.json]"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.5,
        "stream": stream
    }

    url = "https://api.groq.com/openai/v1/chat/completions"

    try:
        if stream:
            response = requests.post(url, headers=headers, json=payload, stream=True, timeout=10)
            response.raise_for_status()
            for line in response.iter_lines():
                if line:
                    line = line.decode("utf-8")
                    if line.startswith("data: "):
                        data = line[6:]
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                            delta = chunk["choices"][0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield content
                        except json.JSONDecodeError:
                            continue
        else:
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
            
    except requests.exceptions.RequestException as e:
        err_msg = f"[API Error: {e}]"
        if hasattr(e, 'response') and e.response is not None:
             err_msg += f" {e.response.text}"
        if stream:
            yield err_msg
        else:
            return err_msg

if __name__ == "__main__":
    # Test execution
    if len(sys.argv) > 1:
        prompt = sys.argv[1]
        msgs = [{"role": "user", "content": prompt}]
        if "--stream" in sys.argv:
            for c in run_chat(msgs, stream=True):
                print(c, end="", flush=True)
            print()
        else:
            print(run_chat(msgs, stream=False))
