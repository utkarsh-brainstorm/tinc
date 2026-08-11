#!/usr/bin/env bash
# ============================================================
#  tinc - This Is Not Copilot
#  Universal Installer for Linux (Wayland/X11)
# ============================================================
set -e

# ── Colors ───────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${CYAN}[INFO]${RESET}  $*"; }
success() { echo -e "${GREEN}[OK]${RESET}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
error()   { echo -e "${RED}[ERR]${RESET}   $*"; exit 1; }
section() { echo -e "\n${BOLD}══════════════════════════════════════${RESET}"; echo -e "${BOLD} $*${RESET}"; echo -e "${BOLD}══════════════════════════════════════${RESET}"; }

section "1 / 4  System Dependencies"

info "Updating package lists…"
sudo apt-get update -qq || warn "Apt update failed, continuing anyway..."

PACKAGES="wl-clipboard wtype xdotool wmctrl python3 python3-pip curl wget"
info "Installing: $PACKAGES"
sudo apt-get install -y -qq $PACKAGES || warn "Failed to install some packages. Ensure wl-clipboard/xdotool/python3 are installed."

# Python requests is required for tinc_client
info "Installing Python 'requests' module…"
pip3 install --quiet --user requests 2>/dev/null || true
success "System dependencies ready."

section "2 / 4  Installing Espanso"

ESPANSO_BIN="$HOME/.local/bin/espanso"
if [ -f "$ESPANSO_BIN" ]; then
    CURRENT_VER=$("$ESPANSO_BIN" --version 2>/dev/null || echo "unknown")
    success "Espanso already installed ($CURRENT_VER). Skipping download."
else
    # Automatically download Wayland version for broad compatibility on modern Linux
    ESPANSO_URL="https://github.com/espanso/espanso/releases/download/v2.4.0/espanso-debian-wayland-amd64.deb"
    DEB_PATH="/tmp/espanso_wayland.deb"
    info "Downloading Espanso Wayland v2.4.0…"
    wget -q --show-progress -O "$DEB_PATH" "$ESPANSO_URL"

    # Extract binary only (no system install needed)
    EXTRACT_DIR="/tmp/espanso_extracted"
    rm -rf "$EXTRACT_DIR"
    dpkg-deb -x "$DEB_PATH" "$EXTRACT_DIR"
    mkdir -p "$HOME/.local/bin"
    cp -v "$EXTRACT_DIR/usr/bin/espanso" "$ESPANSO_BIN"
    chmod +x "$ESPANSO_BIN"
    rm -rf "$EXTRACT_DIR" "$DEB_PATH"
    success "Espanso installed to $ESPANSO_BIN"
fi

# Ensure ~/.local/bin is in PATH
if ! echo "$PATH" | grep -q "$HOME/.local/bin"; then
    warn "~/.local/bin not in PATH. Adding to ~/.bashrc…"
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"
    export PATH="$HOME/.local/bin:$PATH"
fi

section "3 / 4  Tinc API Configuration"

TINC_CFG_DIR="$HOME/.config/tinc"
mkdir -p "$TINC_CFG_DIR"

echo -e "${YELLOW}Enter your Groq API key (get a free one at https://console.groq.com): ${RESET}\c"
read -r GROQ_API_KEY
if [ -z "$GROQ_API_KEY" ]; then
    warn "No key entered! AI features will not work until you configure it in ~/.config/tinc/config.json"
fi

echo -e "${YELLOW}Preferred Groq Model [default: llama-3.3-70b-versatile]: ${RESET}\c"
read -r PREF_MODEL
PREF_MODEL=${PREF_MODEL:-llama-3.3-70b-versatile}

cat > "$TINC_CFG_DIR/config.json" <<EOF
{
  "api_key": "$GROQ_API_KEY",
  "model": "$PREF_MODEL"
}
EOF
success "Configuration saved to ~/.config/tinc/config.json"

section "4 / 4  Deploying Tinc Core"

# This script assumes it's running from inside the cloned 'tinc' repo.
# If curl is used, we need to download the files.
# Let's handle both local install and remote curl install.

ESPANSO_CFG="$HOME/.config/espanso"
mkdir -p "$ESPANSO_CFG/config" "$ESPANSO_CFG/match" "$ESPANSO_CFG/scripts"

REPO_URL="https://raw.githubusercontent.com/utkarsh-brainstorm/tinc/main"

info "Downloading Tinc core files..."
wget -q -O "$ESPANSO_CFG/config/default.yml"          "$REPO_URL/espanso/config/default.yml"
wget -q -O "$ESPANSO_CFG/match/tinc.yml"              "$REPO_URL/espanso/match/tinc.yml"
wget -q -O "$ESPANSO_CFG/scripts/translate_daemon.py" "$REPO_URL/espanso/scripts/translate_daemon.py"
wget -q -O "$ESPANSO_CFG/scripts/translate_client.py" "$REPO_URL/espanso/scripts/translate_client.py"
wget -q -O "$ESPANSO_CFG/scripts/ai_gui.py"           "$REPO_URL/espanso/scripts/ai_gui.py"
wget -q -O "$ESPANSO_CFG/scripts/ai_router.py"        "$REPO_URL/espanso/scripts/ai_router.py"
wget -q -O "$ESPANSO_CFG/scripts/tinc_client.py"      "$REPO_URL/espanso/scripts/tinc_client.py"

# Neutralize Espanso's default base.yml which would otherwise conflict with tinc.yml.
# Espanso auto-generates this file with example triggers; keeping it causes every
# pattern to match twice, triggering a disambiguation popup on every keystroke.
cat > "$ESPANSO_CFG/match/base.yml" << 'BASEYML'
# Tinc: This file intentionally left with no matches.
# All triggers are defined in tinc.yml
matches: []
BASEYML
success "base.yml neutralized (tinc.yml is the sole trigger file)."

info "Setting up Translation Daemon as systemd user service…"
mkdir -p "$HOME/.config/systemd/user"
cat > "$HOME/.config/systemd/user/espanso-translate.service" << EOF
[Unit]
Description=Tinc Translation Daemon
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 $ESPANSO_CFG/scripts/translate_daemon.py
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable espanso-translate 2>/dev/null || true
systemctl --user start espanso-translate 2>/dev/null || true

info "Registering Espanso service…"
"$ESPANSO_BIN" service register 2>/dev/null || true
info "Starting Espanso…"
"$ESPANSO_BIN" start 2>/dev/null || "$ESPANSO_BIN" restart 2>/dev/null || true

echo ""
echo -e "${BOLD}${GREEN}════════════════════════════════════════${RESET}"
echo -e "${BOLD}${GREEN}  Tinc Installed Successfully! 🎉${RESET}"
echo -e "${BOLD}${GREEN}════════════════════════════════════════${RESET}"
echo ""
echo -e "${BOLD}AI Shortcuts:${RESET}"
echo -e "  ${CYAN}[]ai${RESET}        → Opens Spotlight AI chat window"
echo -e "  ${CYAN}[cmd]ac${RESET}     → Pastes terminal command"
echo -e "  ${CYAN}[prompt]ad${RESET}  → Pastes AI answer directly"
echo ""
echo -e "${BOLD}Translation Shortcuts:${RESET}"
echo -e "  ${CYAN}[apple]hi${RESET}   → सेब  (Hindi)"
echo -e "  ${CYAN}[namaste]hd${RESET} → नमस्ते  (Devanagari)"
echo -e ""
echo -e "Configuration: ${CYAN}~/.config/tinc/config.json${RESET}"
echo -e "Restart command: ${CYAN}espanso restart${RESET}"
