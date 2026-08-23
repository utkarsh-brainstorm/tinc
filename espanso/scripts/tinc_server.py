#!/usr/bin/env python3
"""
tinc_server.py — Tinc Control Panel backend.

Zero external dependencies. Python stdlib only.
Binds to 127.0.0.1:9876.
"""
import http.server
import json
import os
import re
import sys
import subprocess
import urllib.parse
import webbrowser
import threading

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
_CANDIDATES = [
    os.path.join(os.path.dirname(os.path.dirname(SCRIPT_DIR)), "tinc_ui"),
    os.path.join(os.path.dirname(SCRIPT_DIR), "tinc_ui"),
    os.path.expanduser("~/.config/tinc_ui"),
]
UI_DIR = next((p for p in _CANDIDATES if os.path.isdir(p)), _CANDIDATES[0])

CONFIG_PATH       = os.path.expanduser("~/.config/tinc/config.json")
TINC_YML          = os.path.expanduser("~/.config/espanso/match/tinc.yml")
ESPANSO_CFG       = os.path.expanduser("~/.config/espanso/config/default.yml")
AI_ROUTER         = os.path.expanduser("~/.config/espanso/scripts/ai_router.py")
ESPANSO_BIN       = os.path.expanduser("~/.local/bin/espanso")

sys.path.insert(0, SCRIPT_DIR)

HOST = "127.0.0.1"
PORT = 9876


# ─── Helpers ──────────────────────────────────────────────────────────────────

def read_file(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"# Error reading file: {e}"

def write_file(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

def read_config() -> dict:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def write_config(cfg: dict) -> None:
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

def mask(key: str) -> str:
    if not key or len(key) < 8:
        return "••••"
    return "•" * (len(key) - 4) + key[-4:]

def espanso_run(args: list) -> dict:
    try:
        r = subprocess.run([ESPANSO_BIN] + args,
                           capture_output=True, text=True, timeout=10)
        return {"ok": r.returncode == 0, "out": (r.stdout + r.stderr).strip()}
    except Exception as e:
        return {"ok": False, "out": str(e)}

def extract_prompts_from_router() -> dict:
    """Parse SYSTEM_PROMPTS dict from ai_router.py source."""
    try:
        src = read_file(AI_ROUTER)
        # Find the SYSTEM_PROMPTS dict block
        m = re.search(r"SYSTEM_PROMPTS\s*=\s*\{(.+?)\n\}", src, re.DOTALL)
        if not m:
            return {}
        block = m.group(1)
        # Extract key: "value" pairs (handles multi-line strings via naive regex)
        prompts = {}
        for km in re.finditer(r'"(\w+)":\s*"((?:[^"\\]|\\.)*)"', block):
            prompts[km.group(1)] = km.group(2).replace("\\n", "\n").replace('\\"', '"')
        return prompts
    except Exception:
        return {}

def write_prompt_to_router(mode: str, new_prompt: str) -> bool:
    """Patch a single SYSTEM_PROMPTS entry in ai_router.py."""
    try:
        src = read_file(AI_ROUTER)
        escaped = new_prompt.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        # Replace the value for this key
        pattern = rf'("{re.escape(mode)}":\s*)"[^"\\]*(?:\\.[^"\\]*)*"'
        replacement = rf'\g<1>"{escaped}"'
        new_src = re.sub(pattern, replacement, src, count=1)
        if new_src == src:
            return False
        write_file(AI_ROUTER, new_src)
        # Sync to repo too
        repo_router = os.path.join(SCRIPT_DIR, "ai_router.py")
        if os.path.exists(repo_router) and repo_router != AI_ROUTER:
            write_file(repo_router, new_src)
        return True
    except Exception:
        return False

def extract_shortcuts_from_yml() -> list:
    """Parse simple (non-regex) trigger shortcuts from tinc.yml."""
    try:
        src = read_file(TINC_YML)
        shortcuts = []
        # Match: - trigger: "TSVH0" / replace: "The Sanskar Valley..."
        for m in re.finditer(
            r'-\s+trigger:\s+"([^"]+)"\s*\n\s+replace:\s+"([^"]+)"',
            src
        ):
            shortcuts.append({"trigger": m.group(1), "replace": m.group(2)})
        return shortcuts
    except Exception:
        return []

def add_shortcut_to_yml(trigger: str, replace: str) -> bool:
    """Append a simple trigger/replace pair to tinc.yml before the MISC section."""
    try:
        src = read_file(TINC_YML)
        entry = f'\n  - trigger: "{trigger}"\n    replace: "{replace}"\n'
        # Insert before the MISC section header or before the first regex
        insert_marker = "  # ─────────────────────────────────────────────────────────\n  # MISC"
        if insert_marker in src:
            src = src.replace(insert_marker, entry + insert_marker, 1)
        else:
            # Append near end of matches section
            src = src.rstrip() + "\n" + entry
        write_file(TINC_YML, src)
        repo_yml = os.path.join(os.path.dirname(SCRIPT_DIR), "match", "tinc.yml")
        if os.path.exists(repo_yml):
            write_file(repo_yml, src)
        return True
    except Exception:
        return False

def delete_shortcut_from_yml(trigger: str) -> bool:
    """Remove a simple trigger/replace pair from tinc.yml."""
    try:
        src = read_file(TINC_YML)
        pattern = rf'\n  - trigger: "{re.escape(trigger)}"\n    replace: "[^"]*"\n'
        new_src = re.sub(pattern, "\n", src, count=1)
        if new_src == src:
            return False
        write_file(TINC_YML, new_src)
        return True
    except Exception:
        return False


# ─── Handler ──────────────────────────────────────────────────────────────────

class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n)) if n else {}

    def do_GET(self):
        p = urllib.parse.urlparse(self.path).path

        if p in ("/", "/index.html"):
            return self._file(os.path.join(UI_DIR, "index.html"), "text/html")

        if p == "/api/config":
            cfg = read_config()
            return self._json({
                "gemini_api_key": mask(cfg.get("gemini_api_key", "")),
                "gemini_model":   cfg.get("gemini_model", "gemini-2.5-flash-lite"),
                "groq_api_keys":  [mask(k) for k in cfg.get("groq_api_keys", [])],
                "groq_model":     cfg.get("groq_model", "llama-3.3-70b-versatile"),
                "groq_key_count": len(cfg.get("groq_api_keys", [])),
                "has_gemini":     bool(cfg.get("gemini_api_key", "").strip()),
            })

        if p == "/api/prompts":
            return self._json({"prompts": extract_prompts_from_router()})

        if p == "/api/shortcuts":
            return self._json({"shortcuts": extract_shortcuts_from_yml()})

        if p == "/api/tinc-yml":
            return self._json({"content": read_file(TINC_YML)})

        if p == "/api/espanso-cfg":
            return self._json({"content": read_file(ESPANSO_CFG)})

        if p == "/api/espanso/status":
            r = espanso_run(["status"])
            return self._json({"running": "running" in r["out"].lower(), "out": r["out"]})

        if p == "/api/logs":
            return self._json({
                "stdout": self._tail("/tmp/tinc_worker.out"),
                "stderr": self._tail("/tmp/tinc_worker.err"),
            })

        if p.startswith("/api/"):
            return self._json({"error": "not found"}, 404)

        # static fallback
        fp = os.path.join(UI_DIR, p.lstrip("/"))
        if os.path.isfile(fp):
            ct = {"css": "text/css", "js": "application/javascript"}.get(fp.rsplit(".", 1)[-1], "text/plain")
            return self._file(fp, ct)
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        p = urllib.parse.urlparse(self.path).path
        d = self._body()

        if p == "/api/config":
            cfg = read_config()
            gk = d.get("gemini_api_key", "")
            if gk and "•" not in gk:
                cfg["gemini_api_key"] = gk
            if "gemini_model" in d:
                cfg["gemini_model"] = d["gemini_model"]
            if "groq_model" in d:
                cfg["groq_model"] = d["groq_model"]
            if "groq_api_keys" in d:
                old = cfg.get("groq_api_keys", [])
                new = []
                for i, k in enumerate(d["groq_api_keys"]):
                    if "•" in k and i < len(old):
                        new.append(old[i])
                    elif "•" not in k and k.strip():
                        new.append(k)
                cfg["groq_api_keys"] = new
            write_config(cfg)
            return self._json({"ok": True})

        if p == "/api/prompts":
            mode = d.get("mode", "")
            prompt = d.get("prompt", "")
            ok = write_prompt_to_router(mode, prompt)
            return self._json({"ok": ok})

        if p == "/api/shortcuts/add":
            ok = add_shortcut_to_yml(d.get("trigger", ""), d.get("replace", ""))
            return self._json({"ok": ok})

        if p == "/api/shortcuts/delete":
            ok = delete_shortcut_from_yml(d.get("trigger", ""))
            return self._json({"ok": ok})

        if p == "/api/tinc-yml":
            write_file(TINC_YML, d.get("content", ""))
            repo = os.path.join(os.path.dirname(SCRIPT_DIR), "match", "tinc.yml")
            if os.path.exists(repo):
                write_file(repo, d.get("content", ""))
            return self._json({"ok": True})

        if p == "/api/espanso-cfg":
            write_file(ESPANSO_CFG, d.get("content", ""))
            return self._json({"ok": True})

        if p == "/api/espanso/restart":
            r = espanso_run(["restart"])
            return self._json(r)

        self._json({"error": "not found"}, 404)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _file(self, path, ct):
        try:
            with open(path, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", f"{ct}; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except FileNotFoundError:
            self._json({"error": "file not found"}, 404)

    @staticmethod
    def _tail(path, n=5000):
        try:
            with open(path) as f:
                return f.read()[-n:]
        except Exception:
            return ""


def main():
    server = http.server.HTTPServer((HOST, PORT), H)
    url = f"http://{HOST}:{PORT}"
    print(f"\033[1m Tinc Control Panel → {url}\033[0m")
    print(" Press Ctrl+C to stop.\n")
    threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n Stopped.")
        server.server_close()


if __name__ == "__main__":
    main()
