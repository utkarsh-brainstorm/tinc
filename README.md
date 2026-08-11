# Tinc (This Is Not Copilot)

**Tinc** is an open-source, universally compatible, zero-telemetry, history-free AI assistant and translation engine for Linux (Wayland & X11).

Instead of relying on bloated corporate software that steals your data in the name of "convenience", Tinc lives locally on your machine, leveraging the lightning-fast Groq API and Espanso to provide instant AI responses and translations perfectly integrated into any application you are using.

*No telemetry. No history tracking. Just you, your keyboard, and instant intelligence.*

## Philosophy
*   **Privacy First**: Tinc does not record your prompts. It does not phone home. It uses a custom, lightweight Python client (`tinc_client.py`) that strictly talks directly to the Groq API.
*   **Zero Bloat**: No electron apps running in the background constantly eating RAM. It relies on native tools like `espanso`, `pywebview`, and `wtype/xdotool`.
*   **Speed is King**: It is designed to be sub-100ms fast. By using Groq's LPU architecture combined with an aggressive caching translation daemon, Tinc types the answers out before you even finish blinking.

## Installation

You can install and configure Tinc with a single command on any modern Linux distro (Ubuntu/Debian recommended):

```bash
curl -fsSL https://raw.githubusercontent.com/utkarsh-brainstorm/tinc/main/install.sh | bash
```

During installation, you will be prompted for:
1.  **Groq API Key**: Get a free one at [console.groq.com](https://console.groq.com).
2.  **Model Selection**: It defaults to the official recommendation `llama-3.3-70b-versatile` for the perfect balance of speed and intelligence.

## Features & Usage

Tinc works everywhere. Browsers, terminals, text editors, IDEs. If you can type in it, Tinc works.

### AI Assistant Commands
Use the `[]` syntax followed by a trigger:

*   **`[]ai` (Interactive GUI)**: Type `[]ai` to summon the sleek, spotlight-style Mac-like chat window in the center of your screen. Ask your question, press Enter, and watch it smoothly expand to reveal the answer. Text is fully copyable. Press `Shift+Enter` to instantly paste the AI's response into whatever app you were using before!
*   **`[your prompt]ad` (Direct Paste)**: Need an answer right now? Type `[write a python loop]ad`. The text disappears instantly, and seconds later, the AI types the answer directly into your editor.
*   **`[your prompt]ac` (Command Only)**: Need a terminal command? Type `[update apt packages]ac` in your terminal. Tinc will fetch the raw bash command (stripping all conversational fluff and markdown) and paste it for you, ready to run.

### Translation Commands
Tinc uses a blazing-fast background daemon to provide instant, sub-50ms translations.

*   **`[apple]hi` (Grammatical Hindi)**: Translates the English text to proper Hindi (e.g. सेब). Works on full sentences.
*   **`[namaste]hd` (Transliteration)**: Converts Romanized words strictly to Devanagari script (e.g. नमस्ते).
*   **`[khaana]hu` (Hinglish)**: Translates Hinglish directly to Hindi.

## Configuration

### Editing the API Key or Model
Your sensitive API key and model choice are stored locally and securely in a standard JSON file:
```bash
nano ~/.config/tinc/config.json
```
```json
{
  "api_key": "gsk_your_api_key_here",
  "model": "llama-3.3-70b-versatile"
}
```

### Customizing Triggers
Want to change `[]ai` to `[]chat`? Or add your own custom prompts?
Edit the master trigger file:
```bash
nano ~/.config/espanso/match/tinc.yml
```
After editing, simply run `espanso restart` to apply the changes!
