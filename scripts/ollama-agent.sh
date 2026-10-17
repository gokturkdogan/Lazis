#!/bin/bash
# Run Ollama as a per-user LaunchAgent with cloud features disabled and loopback-only binding.
#
#   scripts/ollama-agent.sh install    # write + load ~/Library/LaunchAgents/com.lazis.ollama.plist
#   scripts/ollama-agent.sh status     # show the agent and the server's OLLAMA_* environment
#   scripts/ollama-agent.sh uninstall  # unload + remove the agent (Ollama is then not running)
#
# Why: Ollama's cloud features (remote inference for "*-cloud" models, web search) would send
# prompts to ollama.com. LAZIS also refuses cloud models itself, but OLLAMA_NO_CLOUD=1 makes
# the server refuse them too. OLLAMA_HOST pins the API to 127.0.0.1:11434, the only port the
# backend's OS sandbox allows (apps/desktop/src-tauri/sandbox/backend.sb).
#
# LLAMA_ARG_CACHE_RAM caps llama.cpp's host-RAM prompt cache inside Ollama's runner (Ollama
# 0.40 does not set it, so llama.cpp's default of 8192 MiB applies). The runner saves earlier
# prompt states there and restores them, which makes switching back to a conversation fast,
# but on a 24 GB Mac it competes with everything else (measured: runner footprint peak 16 GB
# with the default). Override at install time: LAZIS_PROMPT_CACHE_MIB=<MiB> (0 disables it).
set -euo pipefail

LABEL="com.lazis.ollama"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$HOME/.ollama/logs"
OLLAMA_BIN="$(command -v ollama || true)"
PROMPT_CACHE_MIB="${LAZIS_PROMPT_CACHE_MIB:-2048}"

die() { echo "ollama-agent: $*" >&2; exit 1; }

install_agent() {
  [ -n "$OLLAMA_BIN" ] || die "ollama not found (brew install ollama)"
  [[ "$PROMPT_CACHE_MIB" =~ ^[0-9]+$ ]] || die "LAZIS_PROMPT_CACHE_MIB must be a number of MiB"
  OLLAMA_BIN="$(cd "$(dirname "$OLLAMA_BIN")" && pwd)/$(basename "$OLLAMA_BIN")"
  mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR"
  # Stop any manually started server so the agent can bind the port.
  if pgrep -x ollama >/dev/null && ! launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1; then
    echo "stopping the running 'ollama serve' (pid $(pgrep -x ollama | tr '\n' ' '))"
    pkill -x ollama || true
    for _ in $(seq 1 50); do pgrep -x ollama >/dev/null || break; sleep 0.1; done
  fi
  cat >"$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>$OLLAMA_BIN</string><string>serve</string></array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>OLLAMA_NO_CLOUD</key><string>1</string>
    <key>OLLAMA_HOST</key><string>127.0.0.1:11434</string>
    <key>LLAMA_ARG_CACHE_RAM</key><string>$PROMPT_CACHE_MIB</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ProcessType</key><string>Interactive</string>
  <key>StandardOutPath</key><string>$LOG_DIR/server.log</string>
  <key>StandardErrorPath</key><string>$LOG_DIR/server.log</string>
</dict>
</plist>
EOF
  chmod 600 "$PLIST"
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  # bootout returns before the old job is gone; bootstrapping too early fails with EIO.
  for _ in $(seq 1 50); do launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || break; sleep 0.1; done
  launchctl bootstrap "gui/$(id -u)" "$PLIST" || { sleep 2; launchctl bootstrap "gui/$(id -u)" "$PLIST"; }
  for _ in $(seq 1 100); do curl -s --max-time 1 http://127.0.0.1:11434/api/version >/dev/null && break; sleep 0.1; done
  status_agent
}

status_agent() {
  launchctl print "gui/$(id -u)/$LABEL" 2>/dev/null | grep -E "state =|pid =" || echo "agent not loaded"
  curl -s --max-time 2 http://127.0.0.1:11434/api/version && echo
  local pid; pid="$(pgrep -x ollama | head -1 || true)"
  [ -n "$pid" ] || { echo "ollama is not running"; return 0; }
  lsof -nP -a -p "$pid" -iTCP -sTCP:LISTEN | tail -n +2
  # The server's real environment, read from the kernel (only OLLAMA_* names/values).
  /usr/bin/python3 - "$pid" <<'PY'
import ctypes, sys
libc = ctypes.CDLL(None)
mib = (ctypes.c_int * 3)(1, 49, int(sys.argv[1]))  # CTL_KERN, KERN_PROCARGS2
size = ctypes.c_size_t(0)
libc.sysctl(mib, 3, None, ctypes.byref(size), None, 0)
buf = ctypes.create_string_buffer(size.value)
libc.sysctl(mib, 3, buf, ctypes.byref(size), None, 0)
names = (b"OLLAMA_", b"LLAMA_ARG_CACHE_RAM")
env = [p.decode() for p in buf.raw[4:size.value].split(b"\0") if p.startswith(names)]
print("server environment:", " ".join(env) or "(no OLLAMA_* variables)")
PY
}

uninstall_agent() {
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "removed $PLIST (start Ollama again with 'ollama serve' or 'brew services start ollama')"
}

case "${1:-}" in
  install) install_agent ;;
  status) status_agent ;;
  uninstall) uninstall_agent ;;
  *) die "usage: $0 install|status|uninstall" ;;
esac
