# Tinc: Tinc Is Not Copilot

Tinc is a zero-telemetry, Wayland-native AI assistant that brings the power of Large Language Models (like Google Gemini or Groq) directly into **any** text field across your Linux desktop.

By communicating natively with the Linux kernel's input subsystem (`/dev/uinput`), Tinc gracefully bypasses Wayland compositors, restrictive popup portals, and clipboard sandboxes.

## 🚀 Features

* **Zero-Telemetry, Privacy First:** Tinc communicates directly with your preferred LLM provider API. There are no intermediate telemetry servers. 
* **Universal Compatibility:** Works flawlessly in Web Browsers, Discord, IDEs (VS Code/JetBrains), and any Terminal Emulator.
* **Wayland Native:** No more annoying "Share your screen" or "Remote Desktop" popups! Tinc natively injects keystrokes.
* **Smart Clipboard Context:** Use the `v` suffixes to magically pass your clipboard contents directly to the AI as context alongside your prompt.
* **Dynamic Web Search Override:** Prefix *any* command with `w` to force the AI to browse the web for real-time data before generating an answer.
* **Ptyxis / GTK4 Fallback:** GTK4 terminals drop Wayland's primary selection pasting. Tinc features dedicated `p` variants to automatically switch to `Ctrl+Shift+V` pasting under the hood.

---

## 📦 Installation

Tinc depends on a few core system utilities to manage clipboards, UI events, and python scripts.

```bash
git clone https://github.com/utkarsh-brainstorm/tinc.git
cd tinc
chmod +x install.sh
./install.sh
```
The installer will prompt you for your Default API Key (e.g., Google Gemini or Groq) and configure everything automatically. It registers `tinc.yml` in Espanso and prepares `/dev/uinput` permissions.

> [!NOTE]
> Because Tinc interacts directly with the kernel's EVDEV subsystem, you may need to log out and log back in for your user's new `input` group permissions to take effect.

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

### 3. Clipboard Context (`v` variants)
Replace the last character of any suffix with `v` to securely bundle your clipboard text as context.
* `[explain this]av` - Explains what is in your clipboard.
* `[rewrite more professionally]fiv` - Fixes the grammar of your clipboard text.
* `[convert to python]pv` - Takes the code in your clipboard and rewrites it in Python.

### 4. Dynamic Web Search (`w` prefix)
By default, only `ai` performs web searches. If you need real-time data for another command, simply prefix it with `w`.
* `[latest ubuntu version]wcmd` - Web searches the latest version, then writes the bash command to download it.
* `[summarize today's news]wtldr` - Browses the news before providing a TL;DR.

### 5. Ptyxis & GTK4 Terminal Support (`p` suffix)
Standard Linux pasting (`Shift+Insert`) is disabled by default in modern GTK4 applications (like Ptyxis). To bypass this, append `p` to any command to inject `Ctrl+Shift+V` natively!
* `[docker run syntax]aip` - General AI query for Ptyxis.
* `[delete all containers]cmdp` - Linux command for Ptyxis.

---

## 🛠 Developer & Contribution Guide

Tinc is built to be highly extensible. You can easily add your own models, APIs, and custom AI behavior modes by touching just a few files in `~/.config/espanso/`.

### Architecture Overview
1. **Espanso Matcher (`tinc.yml`)**
   Espanso listens globally for regex triggers. When matched, it spawns `ai_router.py`.
2. **AI Router (`ai_router.py`)**
   The router parses the requested suffix, builds the system messages, and fires a non-blocking asynchronous worker.
3. **API Client (`tinc_client.py`)**
   Handles the fallback logic between multiple API keys and initiates web-search tool calling using the Gemini/Groq API.
4. **Kernel Injector (`tinc_uinput.py`)**
   A completely raw Python EVDEV controller. It creates a virtual keyboard device in the kernel using `ioctl`, bypassing all desktop environment display servers to flawlessly delete strings, type characters, and trigger paste buffers.

### Adding a Custom AI Mode
Want to add a custom command, like `sql` to only generate SQL queries?
1. **Edit `ai_router.py`**
   Add your suffix mapping:
   ```python
   SUFFIX_MAP = {
       ...
       "sql": ("sql", False, False, 0), # mode_name, web_search, use_clipboard, paste_mode
   }
   ```
   Add a strict System Prompt:
   ```python
   SYSTEM_PROMPTS = {
       ...
       "sql": "Output ONLY valid SQL. No markdown fences. No explanations.",
   }
   ```
   Add `"sql"` to the `CODE_MODES` set so the router knows to strip rogue markdown formatting!

2. **Regex Injection (Automated)**
   Because Tinc uses an advanced dynamic regex capture in `tinc.yml` (`(?P<suffix>w?<base_suffix>)`), **you do not need to edit the YAML**!
   Just restart Espanso and your new `sql` command will automatically inherit Web Search (`wsql`), Clipboard Support (`sqv`), and Ptyxis Support (`sqlp`) functionality!

### Debugging
If a background worker fails or you suspect an API error, check the output logs:
```bash
cat /tmp/tinc_worker.out
cat /tmp/tinc_worker.err
```

### Extending UInput (`tinc_uinput.py`)
If you need Tinc to perform complex macros (like tabbing through forms or pressing Enter), you can write new methods mapping the standard ASCII keys to Linux kernel Input Event codes.
```python
def hit_enter():
    _send([(KEY_ENTER, 1), (KEY_ENTER, 0)])
```
