#!/usr/bin/env bash
# Set up the on-prem handwriting model on a Mac Studio. Installs Ollama (if needed), starts it, and
# pulls a vision model sized to this machine's memory. Everything runs locally — no data leaves.
#
#   bash scripts/setup_mac_ai.sh                 # auto-pick a model from installed RAM
#   bash scripts/setup_mac_ai.sh qwen2.5vl:32b   # or name one explicitly
set -e

MODEL="${1:-}"

# --- pick a model from unified memory if not given ---
if [ -z "$MODEL" ]; then
  GB=$(( $(sysctl -n hw.memsize 2>/dev/null || echo 0) / 1073741824 ))
  if   [ "$GB" -ge 120 ]; then MODEL="qwen2.5vl:72b"
  elif [ "$GB" -ge 60 ];  then MODEL="qwen2.5vl:32b"
  else                          MODEL="qwen2.5vl:7b"
  fi
  echo "Detected ${GB} GB memory -> choosing $MODEL"
fi

# --- install Ollama if missing ---
if ! command -v ollama >/dev/null 2>&1; then
  echo "Installing Ollama…"
  if command -v brew >/dev/null 2>&1; then
    brew install ollama
  else
    curl -fsSL https://ollama.com/install.sh | sh
  fi
fi

# --- start the local server (idempotent) ---
if ! curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  echo "Starting Ollama service…"
  (ollama serve >/tmp/ollama.log 2>&1 &) || true
  for i in $(seq 1 20); do
    curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1 && break
    sleep 1
  done
fi

echo "Pulling vision model: $MODEL  (downloads once, then runs offline)…"
ollama pull "$MODEL"

echo
echo "Done. Add this to settings.json next to the app:"
echo "    { \"vlm_model\": \"$MODEL\" }"
echo "Then open the app — the header should show “Handwriting model ✓”."
