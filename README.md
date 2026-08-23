# Tinc: This Is Not Copilot

Tinc is a zero-telemetry, Wayland-native AI assistant that brings the power of Large Language Models (like Google Gemini or Groq) directly into **any** text field across your Linux desktop.

By communicating natively with the Linux kernel's input subsystem (`/dev/uinput`), Tinc gracefully bypasses Wayland compositors, restrictive popup portals, and clipboard sandboxes.

## 🚀 Features

* **Zero-Telemetry, Privacy First:** Tinc communicates directly with your preferred LLM provider API. There are no intermediate telemetry servers. 
* **Universal Compatibility:** Works flawlessly in Web Browsers, Discord, IDEs (VS Code/JetBrains), and any Terminal Emulator.
* **Wayland Native:** No more annoying "Share your screen" or "Remote Desktop" popups! Tinc natively injects keystrokes.
* **Control Panel UI:** A stunning glassmorphism web UI to configure everything — API keys, models, commands, system prompts, and Espanso service — all from your browser.
* **Smart Clipboard Context:** Use the `v` suffixes to magically pass your clipboard contents directly to the AI as context alongside your prompt.
* **Dynamic Web Search Override:** Prefix *any* command with `w` to force the AI to browse the web for real-time data before generating an answer.
* **Ptyxis / GTK4 Fallback:** GTK4 terminals drop Wayland's primary selection pasting. Tinc features dedicated `p` variants to automatically switch to `Ctrl+Shift+V` pasting under the hood.

---

## 📦 Installation

```bash
git clone https://github.com/utkarsh-brainstorm/tinc.git
cd tinc
chmod +x install.sh
./install.sh
```
The installer will prompt you for your Default API Key (e.g., Google Gemini or Groq) and configure everything automatically. It registers `tinc.yml` in Espanso, prepares `/dev/uinput` permissions, and installs the `tinc` command.

> **Note:** Because Tinc interacts directly with the kernel's EVDEV subsystem, you may need to log out and log back in for your user's new `input` group permissions to take effect.

---

## 🖥️ Control Panel

Tinc ships with a beautiful, zero-dependency web UI for managing everything.

```bash
tinc
```

This opens **http://127.0.0.1:9876** in your browser with:

| Section | What it does |
|---|---|
| **Dashboard** | System status, quick AI test widget, recent logs |
| **API Keys** | Configure Gemini/Groq keys with live connection testing |
| **Commands** | Browse all 34+ available commands organized by category |
| **System Prompts** | Edit AI behavior for each mode with live preview |
| **Espanso** | Monitor and restart the Espanso service |
| **Logs** | Live tail of worker stdout/stderr with auto-refresh |

The server binds to `127.0.0.1` only — it is never exposed to your network. API keys are masked in responses and only written on explicit save.

**Tech stack:** Python `http.server` (stdlib) + single HTML file with embedded CSS/JS. Zero external packages. Works on every Linux distro with Python 3 + a browser.

---

## 🎮 Usage Guide

To use Tinc, simply type your prompt inside square brackets anywhere on your system, followed immediately by a suffix. Tinc will instantly erase the trigger, show a loading message, and natively inject the response.

### 1. General Commands
| Suffix | Action | Example |
|---|---|---|
| `ai` | General AI Answer | `[capital of france?]ai` |
| `ad` | Direct/Precise Answer (1-2 sentences) | `[what is a mutex?]ad` |
| `fix` | Fix spelling & grammar natively | `[hte dog is cute]fix` |
| `tldr` | 1-2 sentence TL;DR summary | `[quantum computing]tldr` |
| `cmd` | Raw Linux terminal command | `[update system]cmd` |

### 2. Code Generation
These suffixes apply strict system prompts to output **only raw code** (no markdown formatting or prose) so it compiles/runs immediately upon pasting.
| Suffix | Action | Example |
|---|---|---|
| `py` | Python Code | `[fibonacci series]py` |
| `cp` | C++ Code | `[hello world]cp` |
| `sh` | Bash Script | `[delete all .txt files]sh` |
| `htm` | HTML Code | `[simple login form]htm` |
| `csv` | CSV Data | `[top 3 countries by pop]csv` |
| `json` | JSON Data | `[mock user profile]json` |
| `ref` | Refactor Code (with comments) | `[improve this loop]ref` |

### 3. Translation
| Suffix | Action | Example |
|---|---|---|
| `hi` | English → Hindi (Devanagari) | `[apple]hi` → सेब |
| `hd` | Romanized Hindi → Devanagari | `[namaste]hd` → नमस्ते |
| `hu` | Hinglish → Hindi | `[kya haal hai]hu` |

### 4. Clipboard Context (`v` variants)
Replace the last character of any suffix with `v` to securely bundle your clipboard text as context.
* `[explain this]av` - Explains what is in your clipboard.
* `[rewrite more professionally]fiv` - Fixes the grammar of your clipboard text.
* `[convert to python]pv` - Takes the code in your clipboard and rewrites it in Python.

### 5. Dynamic Web Search (`w` prefix)
By default, web search is **disabled**. To force real-time web data for any command, simply prefix it with `w`.
* `[latest ubuntu version]wcmd` - Web searches the latest version, then writes the bash command.
* `[summarize today's news]wtldr` - Browses the news before providing a TL;DR.
* `[capital of france]wai` - Forces web search even for a simple question.

### 6. Ptyxis & GTK4 Terminal Support (`p` suffix)
Standard Linux pasting (`Shift+Insert`) is disabled by default in modern GTK4 applications (like Ptyxis). To bypass this, append `p` to any command to inject `Ctrl+Shift+V` natively!
* `[docker run syntax]aip` - General AI query for Ptyxis.
* `[delete all containers]cmdp` - Linux command for Ptyxis.

---

## 🛠 Developer & Contribution Guide

Tinc is built to be highly extensible. You can easily add your own models, APIs, and custom AI behavior modes by touching just a few files.

### Architecture Overview

```
tinc/
├── tinc                    # CLI launcher for Control Panel
├── install.sh              # Universal installer
├── tinc_ui/
│   └── index.html          # Control Panel SPA (single file, zero deps)
└── espanso/
    ├── config/default.yml   # Espanso backend config
    ├── match/tinc.yml       # All regex triggers
    └── scripts/
        ├── ai_router.py     # Suffix routing + system prompts
        ├── tinc_client.py   # Gemini → Groq fallback API client
        ├── tinc_uinput.py   # Kernel-level /dev/uinput injection
        └── tinc_server.py   # Control Panel HTTP server
```

**Data flow:**
1. **Espanso** (`tinc.yml`) listens globally for regex triggers like `[prompt]suffix`
2. **AI Router** (`ai_router.py`) parses the suffix, builds system messages, spawns an async worker
3. **API Client** (`tinc_client.py`) calls Gemini → falls back through Groq keys on rate-limit
4. **Kernel Injector** (`tinc_uinput.py`) erases loading text via BackSpace, copies result to clipboard, and pastes via `Shift+Insert` or `Ctrl+Shift+V`

### Adding a Custom AI Mode

1. **Edit `ai_router.py`** — Add your suffix mapping and system prompt:
   ```python
   SUFFIX_MAP = {
       ...
       "sql": ("sql", False, False, 0),  # (mode, web_search, clipboard, paste_mode)
   }
   
   SYSTEM_PROMPTS = {
       ...
       "sql": "Output ONLY valid SQL. No markdown fences. No explanations.",
   }
   ```
   Add `"sql"` to the `CODE_MODES` set so markdown fences get stripped.

2. **Add the regex trigger to `tinc.yml`:**
   ```yaml
   - regex: "\\[(?P<prompt>[^\\]]*)\\](?P<suffix>w?sql)$"
     replace: "{{out}}"
     vars:
       - name: out
         type: shell
         params:
           cmd: "ESPANSO_MODE={{suffix}} ESPANSO_TEXT='{{prompt}}' python3 ~/.config/espanso/scripts/ai_router.py"
   ```
   The `w?` in the regex automatically gives your new command web search support via `wsql`.

3. **Restart Espanso:** `espanso restart` (or use the Control Panel UI)

### Configuration File

`~/.config/tinc/config.json`:
```json
{
  "gemini_api_key": "your-gemini-key",
  "gemini_model": "gemini-2.5-flash-lite",
  "groq_api_keys": ["key1", "key2", "key3"],
  "groq_model": "llama-3.3-70b-versatile"
}
```

### Debugging

```bash
cat /tmp/tinc_worker.out    # Last AI response
cat /tmp/tinc_worker.err    # Last error (if any)
```
Or use the **Logs** section of the Control Panel for live monitoring.

### Extending UInput (`tinc_uinput.py`)

The kernel injector maps ASCII to Linux input event codes. To add new macros:
```python
def hit_enter():
    _send([(KEY_ENTER, 1), (KEY_ENTER, 0)])
```

---

## License

MIT
