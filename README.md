# Tinc: Zero-Telemetry Wayland-Native AI Assistant

Tinc brings the power of LLMs directly into any text field across your Linux desktop. It uses kernel-level `EVDEV` and `/dev/uinput` to natively type and paste text seamlessly, bypassing Wayland restrictions, popup dialogues, and complex GUI loops.

## Features
- **Zero-Telemetry, Privacy First:** Direct communication with the API. No intermediate servers.
- **Universal Compatibility:** Works in all terminals, IDEs (VS Code), Dolphin, web browsers, etc.
- **Wayland Native:** Never prompts for "Remote Desktop" permissions by talking directly to the Linux input subsystem.
- **Context-Aware:** Some suffixes automatically capture your clipboard to feed to the AI.
- **Ptyxis / GTK4 Support:** Dedicated variants (`p` suffixes) specifically for GNOME's new GTK4 terminal implementations that drop legacy primary selection support.

## Usage

Simply type `[your prompt]suffix` anywhere and Tinc will replace it with the response!

### General Commands
| Suffix | Action | Example |
|---|---|---|
| `ai` | General AI Answer | `[capital of france?]ai` |
| `ad` | Direct/Precise Answer (1-2 sentences) | `[what is a mutex?]ad` |
| `fix` | Fix spelling & grammar natively | `[hte dog is cute]fix` |
| `tldr` | 1-2 sentence TL;DR summary | `[quantum computing]tldr` |
| `cmd` | Raw Linux command without newlines | `[update system]cmd` |

### Code Generation
| Suffix | Action | Example |
|---|---|---|
| `py` | Python Code | `[fibonacci series]py` |
| `cp` | C++ Code | `[hello world]cp` |
| `sh` | Bash Script | `[delete all .txt files]sh` |
| `htm` | HTML Code | `[simple login form]htm` |
| `csv` | CSV Data | `[top 3 countries by pop]csv` |
| `json` | JSON Data | `[mock user profile]json` |
| `ref` | Refactor Code (with comments) | `[improve this loop]ref` |

### Clipboard Context Variants
Add `v` to the end of any shortcut to *include your current clipboard* along with the prompt!
* `av` - AI Answer + Clipboard context
* `fiv` - Fix grammar of clipboard
* `tldv` - Summarize clipboard
* `pv` - Python based on clipboard
* *etc...*

### Ptyxis / GTK4 Terminal Variants
If you are using modern GTK4 terminals like **Ptyxis** (where standard `Shift+Insert` universal pasting is blocked), simply append `p` to force the injection engine to use `Ctrl+Shift+V`!
* `aip` - General AI for Ptyxis
* `adp` - Direct answer for Ptyxis
* `cmdp` - Linux command for Ptyxis
* `pyp`, `shp`, `fixp`, etc.

## Installation
Just run `./install.sh` from the repository root. It will prompt you for your API key.

### Web Search Override (The `w` prefix)
By default, only the `ai` command enables web searching to retrieve real-time data. If you want to force web search for **any** other command, simply prefix the suffix with `w`!
* `wcmd` - Web search for a linux command
* `wtldr` - Read the web before summarizing
* `wad` - Web search for a precise answer
