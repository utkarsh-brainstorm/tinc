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
import time
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

# Find repo root if running from repo or config
REPO_DIR = None
_test_repo = os.path.dirname(os.path.dirname(SCRIPT_DIR))
if os.path.isfile(os.path.join(_test_repo, "tinc")):
    REPO_DIR = _test_repo
elif os.path.isdir(os.path.expanduser("~/tinc")):
    REPO_DIR = os.path.expanduser("~/tinc")

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
        backup_file(target_path)
        try:
            with open(backup_path, "r", encoding="utf-8") as src:
                content = src.read()
            write_file(target_path, content)
            sync_to_repo(filename, content)
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

def sync_to_repo(filename: str, content: str) -> None:
    if not REPO_DIR:
        return
    repo_target = None
    if filename == "tinc.yml":
        repo_target = os.path.join(REPO_DIR, "espanso", "match", "tinc.yml")
    elif filename == "default.yml":
        repo_target = os.path.join(REPO_DIR, "espanso", "config", "default.yml")
    elif filename == "ai_router.py":
        repo_target = os.path.join(REPO_DIR, "espanso", "scripts", "ai_router.py")
    if repo_target and repo_target != os.path.abspath(filename):
        try:
            write_file(repo_target, content)
        except Exception:
            pass

def read_config() -> dict:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def write_project_env(cfg: dict) -> None:
    """Store variables in project-isolated .env files without touching machine environment variables."""
    lines = [
        "# Tinc Project Environment (Isolated to Tinc — NOT machine-wide)",
        f"GEMINI_API_KEY=\"{cfg.get('gemini_api_key', '')}\"",
        f"GEMINI_API_KEY_2=\"{cfg.get('gemini_api_key_2', '')}\"",
        f"GEMINI_MODEL=\"{cfg.get('gemini_model', 'gemini-2.5-flash')}\"",
        f"NVIDIA_API_KEY=\"{cfg.get('nvidia_api_key', '')}\"",
        f"NVIDIA_API_KEY_2=\"{cfg.get('nvidia_api_key_2', '')}\"",
        f"NVIDIA_MODEL=\"{cfg.get('nvidia_model', 'minimaxai/minimax-m3.1-flash')}\"",
        f"GROQ_MODEL=\"{cfg.get('groq_model', 'llama-3.3-70b-versatile')}\"",
    ]
    env_content = "\n".join(lines) + "\n"
    
    paths = [os.path.expanduser("~/.config/tinc/.env")]
    if REPO_DIR:
        paths.append(os.path.join(REPO_DIR, ".env"))

    for p in paths:
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(env_content)
            os.chmod(p, 0o600)
        except Exception:
            pass

def write_config(cfg: dict) -> None:
    backup_file(CONFIG_PATH)
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    write_project_env(cfg)

def mask(key: str) -> str:
    if not key or len(key) < 8:
        return "••••" if key else ""
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
        sync_to_repo("ai_router.py", new_src)
        return True
    except Exception:
        return False

def remove_ai_shortcut_internal(suffix: str, clip_suffix: str = None) -> bool:
    try:
        backup_file(AI_ROUTER)
        backup_file(TINC_YML)
        
        router_src = read_file(AI_ROUTER)
        yml_src = read_file(TINC_YML)
        
        # Remove from SUFFIX_MAP
        router_src = re.sub(rf'\n\s*"{re.escape(suffix)}":\s*\("[^"]+",.*?(?:True|False),\s*\d+\),', "", router_src)
        if clip_suffix:
            router_src = re.sub(rf'\n\s*"{re.escape(clip_suffix)}":\s*\("[^"]+",.*?(?:True|False),\s*\d+\),', "", router_src)
            
        # Also clean any remaining entries with mode == suffix
        router_src = re.sub(rf'\n\s*"[a-zA-Z0-9_-]+":\s*\("{re.escape(suffix)}",.*?\),', "", router_src)

        # Remove from SYSTEM_PROMPTS
        router_src = re.sub(rf'\n\s*"{re.escape(suffix)}":\s*"[^"\\]*(?:\\.[^"\\]*)*",', "", router_src)
        
        # Remove from CODE_MODES
        code_modes_match = re.search(r"CODE_MODES\s*=\s*\{(.*?)\}", router_src, re.DOTALL)
        if code_modes_match:
            inner_text = code_modes_match.group(1)
            new_inner = re.sub(rf'"{re.escape(suffix)}"', "", inner_text)
            new_inner = re.sub(r',\s*,', ",", new_inner)
            new_inner = re.sub(r',\s*\}', "}", new_inner).strip(', ')
            router_src = router_src[:code_modes_match.start(1)] + new_inner + router_src[code_modes_match.end(1):]
            
        write_file(AI_ROUTER, router_src)
        sync_to_repo("ai_router.py", router_src)
        
        # Remove from tinc.yml using line-by-line block matching
        def remove_yml_block(text, suf):
            lines = text.split('\n')
            out = []
            skip = 0
            for line in lines:
                if line.strip().startswith("- regex:") and (f"(?P<suffix>w?{suf})$" in line or f"(?P<suffix>{suf})$" in line):
                    skip = 8
                if skip > 0:
                    skip -= 1
                    continue
                out.append(line)
            return '\n'.join(out)
            
        yml_src = remove_yml_block(yml_src, suffix)
        if clip_suffix:
            yml_src = remove_yml_block(yml_src, clip_suffix)
            
        yml_src = re.sub(r'\n{3,}', '\n\n', yml_src)
            
        write_file(TINC_YML, yml_src)
        sync_to_repo("tinc.yml", yml_src)
        return True
    except Exception as e:
        print("Remove error:", e)
        return False

def add_ai_shortcut(suffix: str, web: bool, prompt: str, is_code: bool, clip_suffix: str = None, old_suffix: str = None, old_clip_suffix: str = None) -> bool:
    """Injects or updates an AI mode in ai_router.py and tinc.yml."""
    try:
        backup_file(AI_ROUTER)
        backup_file(TINC_YML)
        
        if old_suffix:
            remove_ai_shortcut_internal(old_suffix, old_clip_suffix)
            
        router_src = read_file(AI_ROUTER)
        
        suffix_insert_point = re.search(r"SUFFIX_MAP\s*=\s*\{.*?(?=\n\})", router_src, re.DOTALL)
        if not suffix_insert_point: return False
        
        map_entry = f'\n    "{suffix}": ("{suffix}", {"True" if web else "False"}, False, 0),'
        if clip_suffix:
            map_entry += f'\n    "{clip_suffix}": ("{suffix}", {"True" if web else "False"}, True, 0),'
            
        router_src = router_src[:suffix_insert_point.end()] + map_entry + router_src[suffix_insert_point.end():]
        
        prompt_insert_point = re.search(r"SYSTEM_PROMPTS\s*=\s*\{.*?(?=\n\})", router_src, re.DOTALL)
        if not prompt_insert_point: return False
        escaped_prompt = prompt.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        sys_entry = f'\n    "{suffix}": "{escaped_prompt}",'
        router_src = router_src[:prompt_insert_point.end()] + sys_entry + router_src[prompt_insert_point.end():]
        
        if is_code:
            code_modes_match = re.search(r"CODE_MODES\s*=\s*\{(.*?)\}", router_src, re.DOTALL)
            if code_modes_match:
                inner_text = code_modes_match.group(1).strip()
                if inner_text and not inner_text.endswith(","):
                    inner_text += ","
                new_inner_text = inner_text + f' "{suffix}"'
                router_src = router_src[:code_modes_match.start(1)] + new_inner_text + router_src[code_modes_match.end(1):]
        
        write_file(AI_ROUTER, router_src)
        sync_to_repo("ai_router.py", router_src)
        
        yml_src = read_file(TINC_YML)
        
        def make_yml_entry(suf):
            return f'''
  - regex: "\\\\[(?P<prompt>[^\\\\]]*)\\\\](?P<suffix>w?{suf})$"
    replace: "{{{{out}}}}"
    vars:
      - name: out
        type: shell
        params:
          cmd: "ESPANSO_MODE={{{{suffix}}}} ESPANSO_TEXT='{{{{prompt}}}}' python3 ~/.config/espanso/scripts/ai_router.py"
'''
        
        regex_entry = make_yml_entry(suffix)
        if clip_suffix:
            regex_entry += make_yml_entry(clip_suffix)
            
        insert_marker = "  # ═══════════════════════════════════════════════════════════\n  #  CLIPBOARD VARIANTS"
        if insert_marker in yml_src:
            yml_src = yml_src.replace(insert_marker, regex_entry + "\n" + insert_marker, 1)
        else:
            yml_src = yml_src.rstrip() + "\n" + regex_entry
            
        write_file(TINC_YML, yml_src)
        sync_to_repo("tinc.yml", yml_src)
        return True
    except Exception as e:
        print("Error adding ai shortcut:", e)
        return False

def extract_shortcuts_from_yml() -> list:
    try:
        src = read_file(TINC_YML)
        shortcuts = []
        for m in re.finditer(
            r'-\s+trigger:\s*["\']?([^"\'\n]+)["\']?\s*\n\s+replace:\s*["\']?([^"\'\n]+)["\']?',
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
        sync_to_repo("tinc.yml", src)
        return True
    except Exception:
        return False

def delete_shortcut_from_yml(trigger: str) -> bool:
    try:
        backup_file(TINC_YML)
        src = read_file(TINC_YML)
        pattern = rf'\n\s*-\s*trigger:\s*["\']?{re.escape(trigger)}["\']?\s*\n\s*replace:\s*["\'][^"\']*["\']\n?'
        new_src = re.sub(pattern, "\n", src, count=1)
        if new_src == src:
            return False
        write_file(TINC_YML, new_src)
        sync_to_repo("tinc.yml", new_src)
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
        self.send_header("Access-Control-Allow-Origin", "*")
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
            gk1 = cfg.get("gemini_api_key", "")
            gk2 = cfg.get("gemini_api_key_2", "")
            nk1 = cfg.get("nvidia_api_key", "")
            nk2 = cfg.get("nvidia_api_key_2", "")
            groq_keys = cfg.get("groq_api_keys", [])

            return self._json({
                "gemini_api_key":   mask(gk1),
                "gemini_api_key_2": mask(gk2),
                "gemini_model":     cfg.get("gemini_model", "gemini-2.5-flash"),
                "has_gemini":       bool(gk1.strip() or gk2.strip()),
                "gemini_key_count": sum(1 for k in [gk1, gk2] if k.strip()),

                "nvidia_api_key":   mask(nk1),
                "nvidia_api_key_2": mask(nk2),
                "nvidia_model":     cfg.get("nvidia_model", "minimaxai/minimax-m3.1-flash"),
                "has_nvidia":       bool(nk1.strip() or nk2.strip()),
                "nvidia_key_count": sum(1 for k in [nk1, nk2] if k.strip()),

                "groq_api_keys":    [mask(k) for k in groq_keys],
                "groq_model":       cfg.get("groq_model", "llama-3.3-70b-versatile"),
                "groq_key_count":   len(groq_keys),
            })

        if p == "/api/prompts":
            return self._json({"prompts": extract_prompts_from_router()})

        if p == "/api/shortcuts":
            return self._json({"shortcuts": extract_shortcuts_from_yml()})

        if p == "/api/ai-shortcuts":
            import importlib.util
            spec = importlib.util.spec_from_file_location("ai_router", AI_ROUTER)
            ai_router = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(ai_router)
            
            commands = {}
            for suf, (mode, web, clip, _) in ai_router.SUFFIX_MAP.items():
                if mode not in commands:
                    commands[mode] = {
                        "suffix": mode,
                        "web": web,
                        "clip_suffix": "",
                        "is_code": mode in getattr(ai_router, 'CODE_MODES', set()),
                        "prompt": getattr(ai_router, 'SYSTEM_PROMPTS', {}).get(mode, "")
                    }
                if clip:
                    commands[mode]["clip_suffix"] = suf
                    
            return self._json({"ai_shortcuts": list(commands.values())})

        if p == "/api/tinc-yml":
            return self._json({"content": read_file(TINC_YML)})

        if p == "/api/espanso-cfg":
            return self._json({"content": read_file(ESPANSO_CFG)})

        if p == "/api/ai-router-src":
            return self._json({"content": read_file(AI_ROUTER)})
            
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
            ct = {"css": "text/css", "js": "application/javascript", "png": "image/png", "jpg": "image/jpeg"}.get(fp.rsplit(".", 1)[-1], "text/plain")
            return self._file(fp, ct)
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        p = urllib.parse.urlparse(self.path).path
        d = self._body()

        if p == "/api/config":
            cfg = read_config()

            # Gemini Key 1 & 2
            if "gemini_api_key" in d:
                gk1 = d.get("gemini_api_key", "").strip()
                if gk1 and "•" not in gk1:
                    cfg["gemini_api_key"] = gk1
                elif gk1 == "":
                    cfg["gemini_api_key"] = ""

            if "gemini_api_key_2" in d:
                gk2 = d.get("gemini_api_key_2", "").strip()
                if gk2 and "•" not in gk2:
                    cfg["gemini_api_key_2"] = gk2
                elif gk2 == "":
                    cfg["gemini_api_key_2"] = ""

            if "gemini_model" in d and d["gemini_model"].strip():
                cfg["gemini_model"] = d["gemini_model"].strip()

            # NVIDIA Key 1 & 2
            if "nvidia_api_key" in d:
                nk1 = d.get("nvidia_api_key", "").strip()
                if nk1 and "•" not in nk1:
                    cfg["nvidia_api_key"] = nk1
                elif nk1 == "":
                    cfg["nvidia_api_key"] = ""

            if "nvidia_api_key_2" in d:
                nk2 = d.get("nvidia_api_key_2", "").strip()
                if nk2 and "•" not in nk2:
                    cfg["nvidia_api_key_2"] = nk2
                elif nk2 == "":
                    cfg["nvidia_api_key_2"] = ""

            if "nvidia_model" in d and d["nvidia_model"].strip():
                cfg["nvidia_model"] = d["nvidia_model"].strip()

            # Groq
            if "groq_model" in d and d["groq_model"].strip():
                cfg["groq_model"] = d["groq_model"].strip()

            if "groq_api_keys" in d:
                old = cfg.get("groq_api_keys", [])
                new = []
                for i, k in enumerate(d["groq_api_keys"]):
                    k_str = k.strip()
                    if "•" in k_str and i < len(old):
                        new.append(old[i])
                    elif "•" not in k_str and k_str:
                        new.append(k_str)
                cfg["groq_api_keys"] = new

            write_config(cfg)
            return self._json({"ok": True})

        if p == "/api/config/test":
            provider = d.get("provider", "gemini")
            input_key = d.get("api_key", "").strip()
            model = d.get("model", "").strip()
            slot = int(d.get("key_slot", 1))

            cfg = read_config()
            key_to_use = input_key

            if not key_to_use or "•" in key_to_use:
                if provider == "gemini":
                    key_to_use = cfg.get("gemini_api_key_2" if slot == 2 else "gemini_api_key", "")
                elif provider == "nvidia":
                    key_to_use = cfg.get("nvidia_api_key_2" if slot == 2 else "nvidia_api_key", "")
                else:
                    keys = cfg.get("groq_api_keys", [])
                    key_to_use = keys[slot - 1] if len(keys) >= slot else (keys[0] if keys else "")

            if not key_to_use:
                return self._json({"ok": False, "error": f"No {provider.title()} Key #{slot} provided."})

            if not model:
                if provider == "gemini":
                    model = cfg.get("gemini_model", "gemini-2.5-flash")
                elif provider == "nvidia":
                    model = cfg.get("nvidia_model", "minimaxai/minimax-m3.1-flash")
                else:
                    model = cfg.get("groq_model", "llama-3.3-70b-versatile")

            t0 = time.time()
            try:
                import tinc_client
                if provider == "gemini":
                    res = tinc_client._gemini_chat([{"role": "user", "content": "Ping test, respond only with OK"}], key_to_use, model, web_search=False)
                elif provider == "nvidia":
                    res = tinc_client._nvidia_chat([{"role": "user", "content": "Ping test, respond only with OK"}], key_to_use, model)
                else:
                    res = tinc_client._groq_chat([{"role": "user", "content": "Ping test, respond only with OK"}], key_to_use, model)
                latency = int((time.time() - t0) * 1000)
                return self._json({"ok": True, "latency_ms": latency, "response": (res or "").strip()[:50]})
            except Exception as e:
                latency = int((time.time() - t0) * 1000)
                return self._json({"ok": False, "error": str(e), "latency_ms": latency})

        if p == "/api/prompts":
            mode = d.get("mode", "")
            prompt = d.get("prompt", "")
            ok = write_prompt_to_router(mode, prompt)
            return self._json({"ok": ok})

        if p == "/api/ai-shortcuts/add":
            suffix = d.get("suffix", "").strip()
            prompt = d.get("prompt", "").strip()
            web = bool(d.get("web", False))
            is_code = bool(d.get("is_code", False))
            clip_suffix = d.get("clip_suffix", "").strip() or None
            old_suffix = d.get("old_suffix", "").strip() or None
            old_clip_suffix = d.get("old_clip_suffix", "").strip() or None
            if not suffix or not prompt:
                return self._json({"ok": False, "error": "Suffix and prompt required"})
            ok = add_ai_shortcut(suffix, web, prompt, is_code, clip_suffix, old_suffix, old_clip_suffix)
            return self._json({"ok": ok})

        if p == "/api/ai-shortcuts/delete":
            suffix = d.get("suffix", "").strip()
            clip_suffix = d.get("clip_suffix", "").strip() or None
            if not suffix:
                return self._json({"ok": False, "error": "Suffix required"})
            ok = remove_ai_shortcut_internal(suffix, clip_suffix)
            return self._json({"ok": ok})

        if p == "/api/shortcuts/add":
            ok = add_shortcut_to_yml(d.get("trigger", "").strip(), d.get("replace", "").strip())
            return self._json({"ok": ok})

        if p == "/api/shortcuts/edit":
            old_trigger = d.get("old_trigger", "").strip()
            trigger = d.get("trigger", "").strip()
            replace = d.get("replace", "").strip()
            if not trigger or not replace:
                return self._json({"ok": False, "error": "Trigger and replacement required"})
            if old_trigger:
                delete_shortcut_from_yml(old_trigger)
            ok = add_shortcut_to_yml(trigger, replace)
            return self._json({"ok": ok})

        if p == "/api/shortcuts/delete":
            ok = delete_shortcut_from_yml(d.get("trigger", "").strip())
            return self._json({"ok": ok})

        if p == "/api/tinc-yml":
            backup_file(TINC_YML)
            content = d.get("content", "")
            write_file(TINC_YML, content)
            sync_to_repo("tinc.yml", content)
            return self._json({"ok": True})

        if p == "/api/espanso-cfg":
            backup_file(ESPANSO_CFG)
            content = d.get("content", "")
            write_file(ESPANSO_CFG, content)
            sync_to_repo("default.yml", content)
            return self._json({"ok": True})

        if p == "/api/ai-router-src":
            backup_file(AI_ROUTER)
            content = d.get("content", "")
            write_file(AI_ROUTER, content)
            sync_to_repo("ai_router.py", content)
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
