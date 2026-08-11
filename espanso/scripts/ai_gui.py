#!/usr/bin/python3
"""
ai_gui.py — Perfect Spotlight-style upward-expanding chat window
==================================================================
- Real Gaussian blur background.
- Input bar is at the bottom, window smoothly expands UPWARD.
- Fully selectable and copyable text (no drag handles blocking it).
"""
import os
import os
import sys
import json
import subprocess
import threading
import time
import webview

import tinc_client

# Force X11 backend for WebKit2GTK rendering (XWayland)
os.environ["GDK_BACKEND"] = "x11"

# ─── HTML ────────────────────────────────────────────────────────────────────
HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>AI Assistant</title>
<style>
  @font-face {
      font-family: 'SF Pro';
      src: url('file:///home/heisenberg/Documents/Fonts/sf-pro-display/SFPRODISPLAYREGULAR.OTF');
  }

  @font-face {
      font-family: 'SF Pro';
      font-weight: 600;
      src: url('file:///home/heisenberg/Documents/Fonts/sf-pro-display/SFPRODISPLAYSEMIBOLDITALIC.OTF');
  }

  * { margin: 0; padding: 0; box-sizing: border-box; }

  :root {
    /* Spotlight Light Theme */
    --bg: rgba(245, 245, 247, 0.80);
    --border: rgba(0, 0, 0, 0.1);
    --user-color: #007aff;
    --ai-color: #1d1d1f;
    --muted: #86868b;
    --input-bg: transparent;
    --cursor: #007aff;
    --font: 'SF Pro', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
  }

  html, body {
    margin: 0; padding: 0;
    height: 100vh;
    background-color: transparent;
    font-family: var(--font);
    font-size: 16px;
    line-height: 1.6;
    user-select: text; 
    overflow: hidden;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  ::selection {
    background: rgba(0, 122, 255, 0.3);
    color: inherit;
  }

  /* The actual visible floating window */
  #wrapper {
    width: 100%;
    height: 72px; /* starts small */
    display: flex;
    flex-direction: column;
    justify-content: flex-end; /* keeps bar at bottom */

    
    background: var(--bg);
    -webkit-backdrop-filter: blur(25px);
    backdrop-filter: blur(25px);
    border-radius: 16px;
    border: 1px solid var(--border);
    box-shadow: 0 16px 40px rgba(0, 0, 0, 0.15), 0 0 1px rgba(0,0,0,0.3);
    overflow: hidden;
    
    /* Smooth upward expansion animation */
    transition: height 0.3s cubic-bezier(0.25, 1, 0.5, 1);
  }

  /* ── chat log (hidden until expanded) ── */
  #main-content {
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    opacity: 0;
    visibility: hidden;
    transition: opacity 0.2s ease 0.1s; /* fade in slightly after expand starts */
  }

  #main-content.visible {
    opacity: 1;
    visibility: visible;
  }

  #log {
    flex: 1;
    overflow-y: auto;
    padding: 24px 32px 16px;
    scroll-behavior: smooth;
  }

  #log::-webkit-scrollbar { width: 8px; }
  #log::-webkit-scrollbar-thumb { background: rgba(0,0,0,0.15); border-radius: 4px; }

  /* ── status bar ── */
  #status {
    padding: 10px 24px;
    font-size: 12px;
    color: var(--muted);
    background: rgba(0,0,0,0.03);
    border-bottom: 1px solid var(--border);
    display: flex;
    justify-content: space-between;
    font-weight: 500;
  }

  #status .keys {
    display: flex;
    gap: 16px;
  }

  /* ── message blocks ── */
  .turn { margin-bottom: 28px; }

  .label {
    font-size: 11px;
    letter-spacing: 0.5px;
    text-transform: uppercase;
    color: var(--muted);
    margin-bottom: 6px;
    font-weight: 600;
  }

  .user-label { color: var(--user-color); }
  .ai-label   { color: #d97706; }

  .user-text {
    color: var(--user-color);
    white-space: pre-wrap;
    word-break: break-word;
    font-size: 17px;
    font-weight: 500;
  }

  .ai-text {
    color: var(--ai-color);
    white-space: pre-wrap;
    word-break: break-word;
    font-size: 16px;
  }

  .cursor {
    display: inline-block;
    width: 8px;
    height: 16px;
    background: var(--cursor);
    vertical-align: middle;
    margin-left: 4px;
    animation: blink 0.9s step-end infinite;
  }
  @keyframes blink { 50% { opacity: 0; } }

  /* ── input bar (Bottom) ── */
  #bar {
    display: flex;
    align-items: center;
    padding: 16px 24px;
    height: 72px;
    min-height: 72px;
    flex-shrink: 0;
  }

  #prompt-icon {
    color: var(--user-color);
    font-size: 24px;
    padding-right: 16px;
    flex-shrink: 0;
    font-weight: 300;
  }

  #input {
    flex: 1;
    background: transparent;
    border: none;
    color: var(--ai-color);
    font-family: var(--font);
    font-size: 22px;
    line-height: 1.4;
    font-weight: 400;
    outline: none;
    resize: none;
    height: 32px;
  }

  #input::placeholder { color: rgba(0,0,0,0.3); font-weight: 300; }

  .flash-ok {
    animation: flashbg 0.3s ease;
  }
  @keyframes flashbg {
    0%   { background: rgba(0, 122, 255, 0.1); }
    100% { background: rgba(0,0,0,0.03); }
  }
</style>
</head>
<body>

<div id="wrapper">
  <div id="main-content">
    <div id="log"></div>
    <div id="status">
      <span id="status-text">Ready</span>
      <span class="keys">Enter · Send &nbsp;|&nbsp; ⇧Enter · Paste Last &nbsp;|&nbsp; Esc · Close</span>
    </div>
  </div>

  <div id="bar">
    <span id="prompt-icon">✧</span>
    <textarea id="input"
      rows="1"
      placeholder="Ask anything..."
      autofocus
      spellcheck="false"
    ></textarea>
  </div>
</div>

<script>
  const log    = document.getElementById('log');
  const input  = document.getElementById('input');
  const status = document.getElementById('status-text');
  const wrapper = document.getElementById('wrapper');
  const mainContent = document.getElementById('main-content');

  let lastAiText = '';
  let isStreaming = false;
  let currentAiEl = null;
  let cursorEl = null;
  let hasExpanded = false;

  // Called from Python after OS window resize is done
  function startExpandAnimation() {
    wrapper.style.height = '480px';
    mainContent.classList.add('visible');
  }

  function expandUI() {
    if (!hasExpanded) {
      hasExpanded = true;
      // Tell Python to resize the OS window instantly, then Python will call startExpandAnimation
      pywebview.api.request_expand();
    }
  }

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      pywebview.api.close_window();

    } else if (e.key === 'Enter' && e.shiftKey) {
      e.preventDefault();
      if (lastAiText) {
        status.textContent = 'Copying & Pasting...';
        pywebview.api.paste_response(lastAiText);
        status.classList.add('flash-ok');
        setTimeout(() => status.classList.remove('flash-ok'), 300);
        setTimeout(() => { status.textContent = 'Ready'; }, 1500);
      }

    } else if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      const text = input.value.trim();
      if (!text || isStreaming) return;
      sendMessage(text);
    }
  });

  function sendMessage(text) {
    expandUI();
    
    isStreaming = true;
    input.value = '';
    status.textContent = 'Thinking...';

    // Append user message
    const turn = document.createElement('div');
    turn.className = 'turn';
    turn.innerHTML = `
      <div class="label user-label">You</div>
      <div class="user-text">${escHtml(text)}</div>
    `;
    log.appendChild(turn);

    // Append AI placeholder
    const aiTurn = document.createElement('div');
    aiTurn.className = 'turn';
    const aiLabel = document.createElement('div');
    aiLabel.className = 'label ai-label';
    aiLabel.textContent = 'AI';
    currentAiEl = document.createElement('div');
    currentAiEl.className = 'ai-text';
    cursorEl = document.createElement('span');
    cursorEl.className = 'cursor';
    currentAiEl.appendChild(cursorEl);
    aiTurn.appendChild(aiLabel);
    aiTurn.appendChild(currentAiEl);
    log.appendChild(aiTurn);

    lastAiText = '';
    scrollDown();

    pywebview.api.send_message(text);
  }

  function appendChunk(chunk) {
    if (!currentAiEl) return;
    currentAiEl.insertBefore(document.createTextNode(chunk), cursorEl);
    lastAiText += chunk;
    scrollDown();
  }

  function streamDone() {
    isStreaming = false;
    status.textContent = 'Ready';
    if (cursorEl) { cursorEl.remove(); cursorEl = null; }
    scrollDown();
    input.focus();
  }

  function streamError(msg) {
    isStreaming = false;
    status.textContent = 'Error';
    if (cursorEl) { cursorEl.remove(); cursorEl = null; }
    if (currentAiEl) {
      currentAiEl.style.color = '#ef4444';
      currentAiEl.textContent = '⚠ ' + msg;
    }
    scrollDown();
    input.focus();
  }

  function scrollDown() {
    log.scrollTop = log.scrollHeight;
  }

  function escHtml(s) {
    return s.replace(/&/g,'&amp;')
            .replace(/</g,'&lt;')
            .replace(/>/g,'&gt;')
            .replace(/\n/g,'<br>');
  }

  window.addEventListener('load', () => input.focus());
</script>

</body>
</html>
"""

# ─── PASTE HELPER ────────────────────────────────────────────────────────────
def copy_to_clipboard(text: str) -> None:
    try:
        proc = subprocess.Popen(["wl-copy"], stdin=subprocess.PIPE)
        proc.communicate(input=text.encode("utf-8"))
        return
    except FileNotFoundError:
        pass
    try:
        proc = subprocess.Popen(["xclip", "-selection", "clipboard"],
                                stdin=subprocess.PIPE)
        proc.communicate(input=text.encode("utf-8"))
    except Exception:
        pass

def focus_prev_window_and_paste(prev_win_id: str) -> None:
    time.sleep(0.35)
    if prev_win_id:
        try:
            subprocess.run(["wmctrl", "-ia", prev_win_id], timeout=2)
            time.sleep(0.15)
        except Exception:
            pass

    sent = False
    try:
        res = subprocess.run(["wtype", "-M", "ctrl", "-k", "v", "-m", "ctrl"], timeout=2, capture_output=True)
        if res.returncode == 0:
            sent = True
    except Exception:
        pass

    if not sent:
        try:
            subprocess.run(["xdotool", "key", "--clearmodifiers", "ctrl+v"], timeout=2)
        except Exception:
            pass

# ─── PYWEBVIEW API ───────────────────────────────────────────────────────────
class Api:
    def __init__(self, initial_prompt: str, prev_win_id: str):
        self.window: webview.Window | None = None
        self.prev_win_id = prev_win_id
        self.conversation: list[dict] = []
        self.last_response = ""
        self._streaming = False
        self._initial_prompt = initial_prompt

    def request_expand(self) -> None:
        """Called by JS to instantly resize OS window, then triggers JS animation."""
        def task():
            if self.window:
                x, y = self.window.x, self.window.y
                # To expand symmetrically from 72 to 480, we move UP by (480-72)/2 = 204
                new_y = max(0, y - 204) if y is not None else 0
                self.window.move(x, new_y)
                self.window.resize(900, 480)
                time.sleep(0.05) # Tiny delay for OS to apply resize
                self.window.evaluate_js("startExpandAnimation()")
        threading.Thread(target=task, daemon=True).start()

    def send_message(self, text: str) -> None:
        if self._streaming:
            return
        self._streaming = True
        self.last_response = ""
        self.conversation.append({"role": "user", "content": text})
        threading.Thread(target=self._stream, daemon=True).start()

    def paste_response(self, text: str) -> None:
        copy_to_clipboard(text)
        threading.Thread(
            target=focus_prev_window_and_paste,
            args=(self.prev_win_id,),
            daemon=True
        ).start()

    def close_window(self) -> None:
        if self.window:
            self.window.destroy()

    def _stream(self) -> None:
        system = (
            "You are a concise, helpful AI assistant. "
            "Answer clearly without unnecessary preamble. "
            "Use plain text (no markdown). "
            "Maintain context from the conversation history below.\n\n"
        )
        history_text = ""
        for msg in self.conversation[:-1]:
            role = "User" if msg["role"] == "user" else "AI"
            history_text += f"{role}: {msg['content']}\n\n"

        current = self.conversation[-1]["content"]
        full_prompt = system + history_text + f"User: {current}\nAI:"

        try:
            for chunk in tinc_client.run_chat(self.conversation, stream=True):
                self.last_response += chunk
                safe = json.dumps(chunk)
                if self.window:
                    self.window.evaluate_js(f"appendChunk({safe})")

            self.conversation.append({
                "role": "assistant",
                "content": self.last_response.strip()
            })

            if self.window:
                self.window.evaluate_js("streamDone()")

        except Exception as e:
            safe = json.dumps(str(e))
            if self.window:
                self.window.evaluate_js(f"streamError({safe})")
        finally:
            self._streaming = False

    def _send_initial(self) -> None:
        time.sleep(0.2)
        if self.window and self._initial_prompt:
            safe = json.dumps(self._initial_prompt)
            self.window.evaluate_js(f"sendMessage({safe})")

# ─── MAIN ────────────────────────────────────────────────────────────────────
def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(1)

    initial_prompt = sys.argv[1]
    prev_win_id    = sys.argv[2] if len(sys.argv) > 2 else ""

    api = Api(initial_prompt, prev_win_id)

    window = webview.create_window(
        title="AI",
        html=HTML,
        width=900,
        height=72,        # Start small, just the search bar
        min_size=(400, 72), # Ensure the OS allows a 72px window so it doesn't underfit
        resizable=True,
        on_top=True,
        frameless=True,   # No OS window borders
        transparent=True, # Enable transparency for rounded corners & blur
        text_select=True, # Explicitly enable text selection which pywebview disables by default
        easy_drag=False,  # VERY IMPORTANT: disables full-window drag which was breaking text selection
    )
    api.window = window
    window.expose(api.request_expand, api.send_message, api.paste_response, api.close_window)

    def on_loaded():
        threading.Thread(target=api._send_initial, daemon=True).start()

    window.events.loaded += on_loaded
    webview.start(debug=False)

if __name__ == "__main__":
    main()
