#!/bin/bash
# Rhino Open AI Kit - start the local model server (macOS, Apple Silicon)
# Double-click in Finder, or run from Terminal. Close the window to stop.

KIT="$(cd "$(dirname "$0")" && pwd)"
cd "$KIT" || exit 1

# Load settings
while IFS='=' read -r key value; do
  case "$key" in ''|\#*) continue ;; esac
  export "$key"="$value"
done < "$KIT/kit.conf"

# Find llama-server anywhere under bin/mac (the release zip nests it in build/bin)
SERVER="$(find "$KIT/bin/mac" -type f -name llama-server 2>/dev/null | head -n 1)"
if [ -z "$SERVER" ]; then
  echo "llama-server not found. Run setup-mac.command first (or unzip the llama.cpp macos-arm64 release into bin/mac/)."
  read -r -p "Press Enter to close."; exit 1
fi

# Unsigned binaries: clear the macOS quarantine flag once
if xattr "$SERVER" 2>/dev/null | grep -q com.apple.quarantine; then
  echo "Clearing macOS quarantine flag on bin/mac ..."
  xattr -dr com.apple.quarantine "$KIT/bin/mac"
fi
chmod +x "$SERVER"

if [ ! -f "$KIT/models/$MODEL" ]; then
  echo "Model not found: models/$MODEL  (run setup-mac.command to download it)"
  read -r -p "Press Enter to close."; exit 1
fi

ARGS=(-m "$KIT/models/$MODEL" -c "$CTX" --port "$PORT" --host 127.0.0.1 -ngl "${NGL:-99}" --jinja)
if [ -n "$MMPROJ" ] && [ -f "$KIT/models/$MMPROJ" ]; then
  ARGS+=(--mmproj "$KIT/models/$MMPROJ")
fi

echo "Starting $MODEL on http://127.0.0.1:$PORT  (Ctrl+C or close window to stop)"
exec "$SERVER" "${ARGS[@]}"
