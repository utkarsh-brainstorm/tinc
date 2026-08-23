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
import glob
from datetime import datetime

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
BACKUP_DIR        = os.path.expanduser("~/.config/tinc/backups")

sys.path.insert(0, SCRIPT_DIR)

HOST = "127.0.0.1"
PORT = 9876


# ─── Backups ──────────────────────────────────────────────────────────────────

def backup_file(filepath: str) -> None:
    if not os.path.exists(filepath):
        return
    os.makedirs(BACKUP_DIR, exist_ok=True)
    filename = os.path.basename(filepath)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(BACKUP_DIR, f"{filename}_{timestamp}")
    
    try:
        with open(filepath, "r", encoding="utf-8") as src, open(backup_path, "w", encoding="utf-8") as dst:
            dst.write(src.read())
    except Exception:
        pass
        
    # Prune old backups (keep last 10)
    try:
        backups = sorted(glob.glob(os.path.join(BACKUP_DIR, f"{filename}_*")))
        while len(backups) > 10:
            os.remove(backups.pop(0))
    except Exception:
        pass

def get_backups(filename: str) -> list:
    try:
        backups = sorted(glob.glob(os.path.join(BACKUP_DIR, f"{filename}_*")), reverse=True)
        return [os.path.basename(b) for b in backups]
    except Exception:
        return []

def restore_backup(filename: str, backup_id: str) -> bool:
    # Ensure backup_id doesn't contain path traversal
    if "/" in backup_id or "\\" in backup_id:
        return False
        
    backup_path = os.path.join(BACKUP_DIR, backup_id)
    if not os.path.exists(backup_path):
        return False
        
    target_path = None
    if filename == "config.json": target_path = CONFIG_PATH
    elif filename == "tinc.yml": target_path = TINC_YML
    elif filename == "default.yml": target_path = ESPANSO_CFG
    elif filename == "ai_router.py": target_path = AI_ROUTER
    else: return False
    
    if target_path:
        # Backup the current state before restoring
        backup_file(target_path)
        try:
            with open(backup_path, "r", encoding="utf-8") as src, open(target_path, "w", encoding="utf-8") as dst:
                dst.write(src.read())
            return True
        except Exception:
            return False
    return False

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
    backup_file(CONFIG_PATH)
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
    try:
        src = read_file(AI_ROUTER)
        m = re.search(r"SYSTEM_PROMPTS\s*=\s*\{(.+?)\n\}", src, re.DOTALL)
        if not m:
            return {}
        block = m.group(1)
        prompts = {}
        for km in re.finditer(r'"(\w+)":\s*"((?:[^"\\]|\\.)*)"', block):
            prompts[km.group(1)] = km.group(2).replace("\\n", "\n").replace('\\"', '"')
        return prompts
    except Exception:
        return {}

def write_prompt_to_router(mode: str, new_prompt: str) -> bool:
    try:
        backup_file(AI_ROUTER)
        src = read_file(AI_ROUTER)
        escaped = new_prompt.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        pattern = rf'("{re.escape(mode)}":\s*)"[^"\\]*(?:\\.[^"\\]*)*"'
        replacement = rf'\g<1>"{escaped}"'
        new_src = re.sub(pattern, replacement, src, count=1)
        if new_src == src:
            return False
        write_file(AI_ROUTER, new_src)
        repo_router = os.path.join(SCRIPT_DIR, "ai_router.py")
        if os.path.exists(repo_router) and repo_router != AI_ROUTER:
            write_file(repo_router, new_src)
        return True
    except Exception:
        return False

def add_ai_shortcut(suffix: str, web: bool, prompt: str, is_code: bool) -> bool:
    """Injects a new AI mode into ai_router.py and tinc.yml."""
    try:
        backup_file(AI_ROUTER)
        backup_file(TINC_YML)
        
        # 1. Update ai_router.py
        router_src = read_file(AI_ROUTER)
        
        # Inject into SUFFIX_MAP
        # Find closing brace of SUFFIX_MAP
        suffix_insert_point = re.search(r"SUFFIX_MAP\s*=\s*\{.*?(?=\n\})", router_src, re.DOTALL)
        if not suffix_insert_point: return False
        map_entry = f'\n    "{suffix}": ("{suffix}", {"True" if web else "False"}, False, 0),'
        router_src = router_src[:suffix_insert_point.end()] + map_entry + router_src[suffix_insert_point.end():]
        
        # Inject into SYSTEM_PROMPTS
        prompt_insert_point = re.search(r"SYSTEM_PROMPTS\s*=\s*\{.*?(?=\n\})", router_src, re.DOTALL)
        if not prompt_insert_point: return False
        escaped_prompt = prompt.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        sys_entry = f'\n    "{suffix}": "{escaped_prompt}",'
        router_src = router_src[:prompt_insert_point.end()] + sys_entry + router_src[prompt_insert_point.end():]
        
        # Inject into CODE_MODES if needed
        if is_code:
            code_modes_match = re.search(r"CODE_MODES\s*=\s*\{(.*?)\}", router_src, re.DOTALL)
            if code_modes_match:
                inner_text = code_modes_match.group(1).strip()
                if inner_text and not inner_text.endswith(","):
                    inner_text += ","
                new_inner_text = inner_text + f' "{suffix}"' if not inner_text.endswith(",") else inner_text + f'"{suffix}"'
                # Just replace the whole group
                router_src = router_src[:code_modes_match.start(1)] + new_inner_text + router_src[code_modes_match.end(1):]
        
        write_file(AI_ROUTER, router_src)
        
        # 2. Update tinc.yml
        yml_src = read_file(TINC_YML)
        
        regex_entry = f'''
  - regex: "\\\\[(?P<prompt>[^\\\\]]*)\\\\](?P<suffix>w?{suffix})$"
    replace: "{{{{out}}}}"
    vars:
      - name: out
        type: shell
        params:
          cmd: "ESPANSO_MODE={{{{suffix}}}} ESPANSO_TEXT='{{{{prompt}}}}' python3 ~/.config/espanso/scripts/ai_router.py"
'''
        insert_marker = "  # ═══════════════════════════════════════════════════════════\n  #  CLIPBOARD VARIANTS"
        if insert_marker in yml_src:
            yml_src = yml_src.replace(insert_marker, regex_entry + "\n" + insert_marker, 1)
        else:
            yml_src = yml_src.rstrip() + "\n" + regex_entry
            
        write_file(TINC_YML, yml_src)
        return True
    except Exception as e:
        print("Error adding ai shortcut:", e)
        return False

def extract_shortcuts_from_yml() -> list:
    try:
        src = read_file(TINC_YML)
        shortcuts = []
        for m in re.finditer(
            r'-\s+trigger:\s+"([^"]+)"\s*\n\s+replace:\s+"([^"]+)"',
            src
        ):
            shortcuts.append({"trigger": m.group(1), "replace": m.group(2)})
        return shortcuts
    except Exception:
        return []

def add_shortcut_to_yml(trigger: str, replace: str) -> bool:
    try:
        backup_file(TINC_YML)
        src = read_file(TINC_YML)
        entry = f'\n  - trigger: "{trigger}"\n    replace: "{replace}"\n'
        insert_marker = "  # ─────────────────────────────────────────────────────────\n  # MISC"
        if insert_marker in src:
            src = src.replace(insert_marker, entry + insert_marker, 1)
        else:
            src = src.rstrip() + "\n" + entry
        write_file(TINC_YML, src)
        repo_yml = os.path.join(os.path.dirname(SCRIPT_DIR), "match", "tinc.yml")
        if os.path.exists(repo_yml):
            write_file(repo_yml, src)
        return True
    except Exception:
        return False

def delete_shortcut_from_yml(trigger: str) -> bool:
    try:
        backup_file(TINC_YML)
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
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)

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

        if p == "/api/ai-shortcuts":
            # Extract from SUFFIX_MAP
            src = read_file(AI_ROUTER)
            m = re.search(r"SUFFIX_MAP\s*=\s*\{(.+?)\n\}", src, re.DOTALL)
            ai_list = []
            if m:
                for km in re.finditer(r'"(\w+)":\s*\("([^"]+)",\s*(True|False),\s*(True|False),\s*(\d+)\)', m.group(1)):
                    ai_list.append({
                        "suffix": km.group(1),
                        "mode": km.group(2),
                        "web": km.group(3) == "True",
                        "clipboard": km.group(4) == "True",
                    })
            return self._json({"ai_shortcuts": ai_list})

        if p == "/api/tinc-yml":
            return self._json({"content": read_file(TINC_YML)})

        if p == "/api/espanso-cfg":
            return self._json({"content": read_file(ESPANSO_CFG)})
            
        if p == "/api/backups":
            filename = query.get("file", [""])[0]
            if filename not in ["config.json", "tinc.yml", "default.yml", "ai_router.py"]:
                return self._json({"error": "Invalid file"}, 400)
            return self._json({"backups": get_backups(filename)})

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

        if p == "/api/ai-shortcuts/add":
            suffix = d.get("suffix", "").strip()
            prompt = d.get("prompt", "").strip()
            web = d.get("web", False)
            is_code = d.get("is_code", False)
            if not suffix or not prompt:
                return self._json({"ok": False, "error": "Suffix and prompt required"})
            ok = add_ai_shortcut(suffix, web, prompt, is_code)
            return self._json({"ok": ok})

        if p == "/api/shortcuts/add":
            ok = add_shortcut_to_yml(d.get("trigger", ""), d.get("replace", ""))
            return self._json({"ok": ok})

        if p == "/api/shortcuts/delete":
            ok = delete_shortcut_from_yml(d.get("trigger", ""))
            return self._json({"ok": ok})

        if p == "/api/tinc-yml":
            backup_file(TINC_YML)
            write_file(TINC_YML, d.get("content", ""))
            repo = os.path.join(os.path.dirname(SCRIPT_DIR), "match", "tinc.yml")
            if os.path.exists(repo):
                write_file(repo, d.get("content", ""))
            return self._json({"ok": True})

        if p == "/api/espanso-cfg":
            backup_file(ESPANSO_CFG)
            write_file(ESPANSO_CFG, d.get("content", ""))
            return self._json({"ok": True})
            
        if p == "/api/backups/restore":
            filename = d.get("filename", "")
            backup_id = d.get("backup_id", "")
            if not filename or not backup_id:
                return self._json({"ok": False})
            ok = restore_backup(filename, backup_id)
            return self._json({"ok": ok})

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
