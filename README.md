# Tinc — This is Not Copilot

A system-wide AI text expansion tool for Linux. Type any trigger in **any application** — browser, editor, terminal, messaging app — and get AI output injected instantly at your cursor.

---

## What It Does

Tinc hooks into your keyboard at the OS level (via Espanso + EVDEV). You type a trigger like `[explain recursion]ai` anywhere and it gets replaced with the AI's answer — right there, in place, in whatever app you're in.

No window switching. No copy-paste. No GUI. Just type and get.

**Primary AI**: Google Gemini 2.5 Flash Lite (with web search for general queries)  
**Automatic fallback**: Up to 3 Groq API keys tried in sequence when Gemini quota is exhausted

---

## Installation

### Quick Install (one command)
```bash
curl -fsSL https://raw.githubusercontent.com/utkarsh-brainstorm/tinc/main/install.sh | bash
```

The installer will:
1. Check and install dependencies (Espanso, xclip, xdotool, wmctrl, python3)
2. Copy config files to `~/.config/espanso/`
3. Ask for your Gemini API key and optionally Groq API keys
4. Start Espanso

### Manual Install
```bash
git clone https://github.com/utkarsh-brainstorm/tinc.git
cd tinc
bash install.sh
```

### API Keys
Get a free Gemini API key from [Google AI Studio](https://aistudio.google.com/app/apikey).  
Get a free Groq API key from [console.groq.com](https://console.groq.com).

Keys are stored locally in `~/.config/tinc/config.json` — never in the repo.

---

## Trigger Syntax

```
[your text or prompt here]suffix
```

Type the bracket + text + suffix anywhere. Espanso detects it, calls the AI, and injects the result back at the cursor.

---

## All Commands

### General AI

| Trigger | What it does |
|---------|-------------|
| `[question]ai` | Direct AI answer. No system prompt — raw model output. **Web search enabled.** |
| `[question]ad` | Short, precise answer — 1-2 sentences max, no markdown. **Web search enabled.** |
| `[instruction]av` | Same as `ai` but also attaches your clipboard content as context. Copy a large block of text first, then type the instruction. |

### Writing

| Trigger | What it does |
|---------|-------------|
| `[text]fix` | Fix spelling and grammar only. Preserves your tone and style exactly. |
| `[text]tldr` | 1-2 sentence summary of the given text. |

### Code Output

| Trigger | Output |
|---------|--------|
| `[prompt]py` | Python only |
| `[prompt]cp` | C++ only |
| `[prompt]sh` | Bash script only |
| `[prompt]htm` | HTML only |
| `[prompt]csv` | CSV data only |
| `[prompt]json` | JSON only |
| `[prompt]ref` | Refactored + commented version of pasted code |

### Clipboard Variants

For large inputs that can't be typed in brackets, copy text to clipboard first, then use the `v` variant:

| Trigger | Equivalent to |
|---------|--------------|
| `[]fiv` | `[clipboard]fix` |
| `[]tldv` | `[clipboard]tldr` |
| `[]rev` | `[clipboard]ref` |
| `[]pv` | `[clipboard]py` |
| `[]cv` | `[clipboard]cp` |
| `[]sv` | `[clipboard]sh` |
| `[]htv` | `[clipboard]htm` |
| `[]jsov` | `[clipboard]json` |
| `[]csj` | `[clipboard]csv` |

### Translation

| Trigger | What it does |
|---------|-------------|
| `[text]hi` | Translate text to Hindi |
| `[text]hd` | Romanized Hindi → Devanagari script |
| `[text]hu` | Hinglish → proper Hindi |

### Utilities

| Trigger | Output |
|---------|--------|
| `:today` | Today's date (`2026-08-12`) |
| `:time` | Current time (`14:37:21`) |
| `:myip` | Your public IP address |

---

## How It Works

```
You type:   [summarize this paper]tldr
              │
              ▼
         Espanso detects trigger (EVDEV — reads /dev/input, kernel-level)
              │
              ▼
         Replaces with "Bas ittu sa time aur..." (loading indicator)
              │
              ▼
         Background process calls AI API
         (Gemini → Groq key 1 → Groq key 2 → Groq key 3)
              │
              ▼
         Backspaces loading text
         Copies result to X11 clipboard (xclip)
         Sends Ctrl+V to paste result at cursor
```

**Why no popup / no portal:**  
Espanso uses EVDEV (Linux kernel input subsystem) for detection — no Wayland portal needed. Output injection uses X11 clipboard (xclip) + xdotool — also no portal. Zero permission dialogs, even after reboots.

---

## Configuration

### Config file: `~/.config/tinc/config.json`

```json
{
  "gemini_api_key": "your-gemini-key",
  "gemini_model":   "gemini-2.5-flash-lite",
  "groq_api_keys":  ["key1", "key2", "key3"],
  "groq_model":     "llama-3.3-70b-versatile"
}
```

| Field | Description |
|-------|-------------|
| `gemini_api_key` | Primary provider. Free tier: very generous daily quota. |
| `gemini_model` | Model to use. Default: `gemini-2.5-flash-lite`. |
| `groq_api_keys` | List of Groq keys. Tried in order when Gemini quota is hit. |
| `groq_model` | Groq model. Default: `llama-3.3-70b-versatile` (100k TPD free). |

### Espanso config: `~/.config/espanso/config/default.yml`

Key settings:

```yaml
backend: "auto"               # EVDEV — kernel-level, no portal
force_clipboard: true         # Espanso injects its own replacements via clipboard
max_regex_buffer_size: 10000  # Allows long prompts in brackets
```

### Adding your own triggers: `~/.config/espanso/match/tinc.yml`

Add any Espanso trigger. Example — add a `:sig` trigger for your email signature:
```yaml
  - trigger: ":sig"
    replace: "Regards,\nUtkarsh Yadav"
```

---

## Updating

```bash
cd ~/tinc
git pull
bash install.sh --update
```

Or just copy the scripts manually:
```bash
cp espanso/scripts/*.py ~/.config/espanso/scripts/
cp espanso/match/tinc.yml ~/.config/espanso/match/
cp espanso/config/default.yml ~/.config/espanso/config/
espanso restart
```

---

## Troubleshooting

**Trigger not firing:**
- Make sure there are no spaces between `[`, the text, `]` and the suffix
- Run `espanso log` to see what Espanso is detecting
- Check `espanso status` — it should say `running`

**AI output replaces wrong text:**
- This happens when another application grabs keyboard focus between trigger and output
- Type the trigger in one go without pausing

**Rate limit error:**
- Error message shows the wait time: `[Tinc: daily limit — retry in 3m11]`
- Add more Groq API keys to `~/.config/tinc/config.json` under `groq_api_keys`
- Or switch to a model with higher limits: `llama-3.1-8b-instant` has 500k TPD

**Output has no line breaks:**
- Should not happen — output uses clipboard paste which preserves all formatting
- If it does: check `xclip` is installed (`which xclip`)

**Espanso not starting:**
```bash
espanso service start    # start
espanso service register # register as systemd service (auto-start)
espanso log              # view logs
```

---

## Project Structure

```
tinc/
├── install.sh                    # One-shot installer
├── config.example.json           # Config schema (no real keys)
└── espanso/
    ├── config/
    │   └── default.yml           # Espanso settings
    ├── match/
    │   └── tinc.yml              # All trigger definitions
    └── scripts/
        ├── ai_router.py          # Trigger routing + output injection
        ├── tinc_client.py        # Multi-provider AI client (Gemini + Groq)
        └── translate_client.py   # Translation triggers
```

---

## Dependencies

| Tool | Purpose | Install |
|------|---------|---------|
| `espanso` | Trigger detection and text replacement | [espanso.org](https://espanso.org) |
| `python3` | Scripts runtime | Usually pre-installed |
| `xclip` | X11 clipboard (no portal) | `sudo apt install xclip` |
| `xdotool` | X11 keystroke injection | `sudo apt install xdotool` |
| `wmctrl` | Window focus management | `sudo apt install wmctrl` |

---

## License

MIT — do whatever you want.

---

*Tinc — This is Not Copilot*
