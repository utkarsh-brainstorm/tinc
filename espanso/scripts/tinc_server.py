#!/usr/bin/env python3
"""
tinc_server.py — Lightweight Control Panel server for Tinc.

Zero external dependencies. Uses Python's built-in http.server.
Binds to 127.0.0.1:9876 only (never exposed to network).

Launch:  python3 tinc_server.py
         → opens http://localhost:9876 in default browser
"""
import http.server
import json
import os
import sys
import subprocess
import urllib.parse
import webbrowser
import threading
import re

# ─── Paths ────────────────────────────────────────────────────────────────────
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
# UI can live in several places depending on install vs repo dev
_CANDIDATES = [
    os.path.join(os.path.dirname(os.path.dirname(SCRIPT_DIR)), "tinc_ui"),  # repo: tinc/tinc_ui
    os.path.join(os.path.dirname(SCRIPT_DIR), "tinc_ui"),                    # installed: espanso/tinc_ui
    os.path.expanduser("~/.config/tinc_ui"),                                 # user config
]
UI_DIR = next((p for p in _CANDIDATES if os.path.isdir(p)), _CANDIDATES[0])
CONFIG_PATH = os.path.expanduser("~/.config/tinc/config.json")
ESPANSO_BIN = os.path.expanduser("~/.local/bin/espanso")

# Import tinc modules
sys.path.insert(0, SCRIPT_DIR)
import tinc_client
import ai_router

HOST = "127.0.0.1"
PORT = 9876


# ─── Config helpers ───────────────────────────────────────────────────────────

def read_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        return {}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def write_config(cfg: dict) -> None:
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

def mask_key(key: str) -> str:
    """Mask an API key, showing only last 4 chars."""
    if not key or len(key) < 8:
        return "****"
    return "•" * (len(key) - 4) + key[-4:]


# ─── Espanso helpers ─────────────────────────────────────────────────────────

def espanso_status() -> dict:
    try:
        r = subprocess.run([ESPANSO_BIN, "status"],
                           capture_output=True, text=True, timeout=5)
        running = "running" in r.stdout.lower()
        return {"running": running, "output": r.stdout.strip()}
    except Exception as e:
        return {"running": False, "output": str(e)}

def espanso_restart() -> dict:
    try:
        r = subprocess.run([ESPANSO_BIN, "restart"],
                           capture_output=True, text=True, timeout=10)
        return {"success": r.returncode == 0, "output": r.stdout.strip() + r.stderr.strip()}
    except Exception as e:
        return {"success": False, "output": str(e)}


# ─── Request Handler ─────────────────────────────────────────────────────────

class TincHandler(http.server.BaseHTTPRequestHandler):
    """Handles REST API + static file serving."""

    def log_message(self, format, *args):
        """Suppress default access logs for cleaner terminal output."""
        pass

    def _json_response(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    # ── GET routes ────────────────────────────────────────────────────────

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            self._serve_file(os.path.join(UI_DIR, "index.html"), "text/html")

        elif path == "/api/config":
            cfg = read_config()
            # Mask keys for safety
            masked = {
                "gemini_api_key": mask_key(cfg.get("gemini_api_key", "")),
                "gemini_model": cfg.get("gemini_model", "gemini-2.5-flash-lite"),
                "groq_api_keys": [mask_key(k) for k in cfg.get("groq_api_keys", [])],
                "groq_model": cfg.get("groq_model", "llama-3.3-70b-versatile"),
                "has_gemini_key": bool(cfg.get("gemini_api_key", "").strip()),
                "has_groq_keys": any(k.strip() for k in cfg.get("groq_api_keys", [])),
                "groq_key_count": len(cfg.get("groq_api_keys", [])),
            }
            self._json_response(masked)

        elif path == "/api/suffixes":
            suffixes = {}
            for key, (mode, web, clip, paste) in ai_router.SUFFIX_MAP.items():
                suffixes[key] = {
                    "mode": mode,
                    "web_search": web,
                    "use_clipboard": clip,
                    "paste_mode": paste,
                    "paste_mode_label": ["Shift+Insert", "Ctrl+Shift+V"][paste] if paste < 2 else "type",
                }
            self._json_response({"suffixes": suffixes})

        elif path == "/api/prompts":
            self._json_response({"prompts": dict(ai_router.SYSTEM_PROMPTS)})

        elif path == "/api/espanso/status":
            self._json_response(espanso_status())

        elif path == "/api/logs":
            out_log = ""
            err_log = ""
            try:
                with open("/tmp/tinc_worker.out", "r") as f:
                    out_log = f.read()[-5000:]  # last 5KB
            except Exception:
                pass
            try:
                with open("/tmp/tinc_worker.err", "r") as f:
                    err_log = f.read()[-5000:]
            except Exception:
                pass
            self._json_response({"stdout": out_log, "stderr": err_log})

        elif path.startswith("/api/"):
            self._json_response({"error": "Not found"}, 404)

        else:
            # Try serving static files from UI_DIR
            safe_path = path.lstrip("/")
            file_path = os.path.join(UI_DIR, safe_path)
            if os.path.isfile(file_path):
                ctype = "text/html"
                if file_path.endswith(".css"):
                    ctype = "text/css"
                elif file_path.endswith(".js"):
                    ctype = "application/javascript"
                elif file_path.endswith(".png"):
                    ctype = "image/png"
                elif file_path.endswith(".svg"):
                    ctype = "image/svg+xml"
                self._serve_file(file_path, ctype)
            else:
                self._json_response({"error": "Not found"}, 404)

    # ── POST routes ───────────────────────────────────────────────────────

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path

        if path == "/api/config":
            data = self._read_body()
            cfg = read_config()
            # Only update fields that are provided and not masked
            if "gemini_api_key" in data and "••••" not in data["gemini_api_key"]:
                cfg["gemini_api_key"] = data["gemini_api_key"]
            if "gemini_model" in data:
                cfg["gemini_model"] = data["gemini_model"]
            if "groq_api_keys" in data:
                # Only update keys that aren't masked
                new_keys = []
                old_keys = cfg.get("groq_api_keys", [])
                for i, k in enumerate(data["groq_api_keys"]):
                    if "••••" in k or "•" in k:
                        # Keep old key
                        if i < len(old_keys):
                            new_keys.append(old_keys[i])
                    else:
                        new_keys.append(k)
                cfg["groq_api_keys"] = new_keys
            if "groq_model" in data:
                cfg["groq_model"] = data["groq_model"]
            write_config(cfg)
            self._json_response({"success": True})

        elif path == "/api/prompts":
            data = self._read_body()
            mode = data.get("mode", "")
            prompt = data.get("prompt", "")
            if mode and mode in ai_router.SYSTEM_PROMPTS:
                ai_router.SYSTEM_PROMPTS[mode] = prompt
                self._json_response({"success": True})
            else:
                self._json_response({"error": f"Unknown mode: {mode}"}, 400)

        elif path == "/api/test":
            data = self._read_body()
            prompt = data.get("prompt", "Hello")
            mode = data.get("mode", "ai")
            web_search = data.get("web_search", False)
            try:
                msgs = ai_router.build_messages(mode, prompt)
                result = tinc_client.chat(msgs, web_search=web_search)
                if mode in ai_router.CODE_MODES:
                    result = ai_router.strip_code_fences(result or "")
                self._json_response({"result": result or "(empty response)"})
            except Exception as e:
                self._json_response({"error": str(e)}, 500)

        elif path == "/api/espanso/restart":
            self._json_response(espanso_restart())

        elif path == "/api/test-key":
            data = self._read_body()
            provider = data.get("provider", "gemini")
            key = data.get("key", "")
            try:
                test_msgs = [{"role": "user", "content": "Say 'OK' and nothing else."}]
                if provider == "gemini":
                    test_cfg = {"gemini_api_key": key, "gemini_model": data.get("model", "gemini-2.5-flash-lite")}
                    result = tinc_client._gemini_chat(test_msgs, test_cfg, web_search=False)
                    self._json_response({"success": True, "response": result.strip()})
                else:
                    result = tinc_client._groq_chat(test_msgs, key, data.get("model", "llama-3.3-70b-versatile"))
                    self._json_response({"success": True, "response": result.strip()})
            except Exception as e:
                self._json_response({"success": False, "error": str(e)}, 200)

        else:
            self._json_response({"error": "Not found"}, 404)

    # ── OPTIONS (CORS preflight) ──────────────────────────────────────────

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    # ── File serving helper ───────────────────────────────────────────────

    def _serve_file(self, filepath: str, content_type: str):
        try:
            with open(filepath, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except FileNotFoundError:
            self._json_response({"error": "File not found"}, 404)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    server = http.server.HTTPServer((HOST, PORT), TincHandler)
    url = f"http://{HOST}:{PORT}"
    print(f"\033[1;36m╔══════════════════════════════════════╗\033[0m")
    print(f"\033[1;36m║   Tinc Control Panel                 ║\033[0m")
    print(f"\033[1;36m║   {url}              ║\033[0m")
    print(f"\033[1;36m╚══════════════════════════════════════╝\033[0m")
    print(f"\033[0;90mPress Ctrl+C to stop.\033[0m\n")

    # Open browser after a short delay
    threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n\033[0;90mTinc Control Panel stopped.\033[0m")
        server.server_close()


if __name__ == "__main__":
    main()
