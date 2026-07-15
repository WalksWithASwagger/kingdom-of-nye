#!/usr/bin/env bash
# The Kingdom of Nye — one-command launcher.
# Starts ComfyUI (if needed) + the conductor, then opens the visualizer.
# Override with:  NYE_COMFYUI_DIR=/path/to/ComfyUI   NYE_BROWSER="Google Chrome"
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMFYUI_DIR="${NYE_COMFYUI_DIR:-$HOME/Code/ComfyUI}"
BROWSER="${NYE_BROWSER:-Brave Browser}"
URL="http://localhost:8765"

say()  { printf '\033[38;5;179m▸ %s\033[0m\n' "$1"; }
warn() { printf '\033[38;5;209m▸ %s\033[0m\n' "$1"; }
up()   { curl -s -o /dev/null -w "%{http_code}" "$1" 2>/dev/null; }

# 1) ComfyUI (the dream engine) — optional; the app still runs without it
if [ "$(up http://127.0.0.1:8188/)" = "200" ]; then
  say "ComfyUI already running on :8188"
elif [ -f "$COMFYUI_DIR/main.py" ]; then
  say "starting ComfyUI from $COMFYUI_DIR …"
  PY="$COMFYUI_DIR/.venv/bin/python"; [ -x "$PY" ] || PY="python3"
  ( cd "$COMFYUI_DIR" && PYTORCH_ENABLE_MPS_FALLBACK=1 nohup "$PY" main.py \
      --force-fp16 --use-pytorch-cross-attention --fp32-vae \
      >/tmp/nye-comfyui.log 2>&1 & )
  printf "  waiting for ComfyUI"
  for _ in $(seq 1 90); do [ "$(up http://127.0.0.1:8188/)" = "200" ] && break; printf "."; sleep 1; done; echo
  [ "$(up http://127.0.0.1:8188/)" = "200" ] && say "ComfyUI up" \
    || warn "ComfyUI didn't come up (see /tmp/nye-comfyui.log) — dreams will be offline"
else
  warn "ComfyUI not found at $COMFYUI_DIR (set NYE_COMFYUI_DIR) — dreams will be offline"
fi

# 2) The conductor (the brain) — required
if [ "$(up $URL/health)" = "200" ]; then
  say "conductor already running on :8765"
else
  say "starting the conductor …"
  ( cd "$HERE" && PYTHONUNBUFFERED=1 nohup python3 server.py >/tmp/nye-conductor.log 2>&1 & )
  printf "  waiting for the conductor"
  for _ in $(seq 1 60); do [ "$(up $URL/health)" = "200" ] && break; printf "."; sleep 1; done; echo
  [ "$(up $URL/health)" = "200" ] && say "conductor up" \
    || { warn "conductor failed to start — see /tmp/nye-conductor.log"; exit 1; }
fi

# 3) Open the show
say "opening $URL in $BROWSER"
open -a "$BROWSER" "$URL" 2>/dev/null || open "$URL"

echo
say "The Kingdom of Nye is on the air → $URL"
echo "  · click TUNE IN, allow the mic, press F for fullscreen"
echo "  · press ? for all controls · V pulls in the AutoLume substrate"
