#!/bin/bash
# Rhino Open AI Kit - one-time setup for macOS
# Picks a preset for this Mac, downloads the llama.cpp runtime and the model,
# and checks every download against its SHA-256 checksum.
# Double-click in Finder, or run from Terminal:  ./setup-mac.command [preset]
# Needs internet once. Afterwards the kit runs fully offline.

set -u
KIT="$(cd "$(dirname "$0")" && pwd)"
cd "$KIT" || exit 1

# Pinned llama.cpp release (tested). Hashes from the GitHub release page.
LLAMA_BUILD="b12255"
LLAMA_BASE="https://github.com/ggml-org/llama.cpp/releases/download/$LLAMA_BUILD"
MAC_ARM64="llama-$LLAMA_BUILD-bin-macos-arm64.tar.gz"
MAC_ARM64_SHA="56074dd37cd369d4c73658d7ce3b1198ec359fb501ad8f2278b4f8fb36178a48"
MAC_X64="llama-$LLAMA_BUILD-bin-macos-x64.tar.gz"
MAC_X64_SHA="8cd76dd2c6d67d706dc06f9ef8a33629531b990263a53e1f2986deed4681ab6d"

die() { echo; echo "ERROR: $*"; read -r -p "Press Enter to close."; exit 1; }
sha() { shasum -a 256 "$1" | awk '{print $1}'; }

# ------------------------------------------------------------- 1. preset
RAM_GB=$(( $(sysctl -n hw.memsize) / 1073741824 ))
ARCH="$(uname -m)"
if   [ "$RAM_GB" -ge 96 ]; then REC="mac-128gb"
elif [ "$RAM_GB" -ge 48 ]; then REC="mac-64gb"
elif [ "$RAM_GB" -ge 24 ]; then REC="mac-32gb"
elif [ "$RAM_GB" -ge 16 ]; then REC="mac-16gb"
else REC="mac-8gb"; fi

PRESET="${1:-}"
if [ -z "$PRESET" ]; then
  echo "This Mac: $ARCH, $RAM_GB GB memory. Recommended preset: $REC"
  echo
  for f in presets/mac-*.conf; do
    n="$(basename "$f" .conf)"
    printf "  %-10s %s\n" "$n" "$(sed -n '1p' "$f" | sed 's/^# Preset: //')"
  done
  echo "  keep       keep the current kit.conf"
  echo
  read -r -p "Preset [$REC]: " PRESET
  PRESET="${PRESET:-$REC}"
fi

if [ "$PRESET" != "keep" ]; then
  [ -f "presets/$PRESET.conf" ] || die "No preset presets/$PRESET.conf"
  [ -f kit.conf ] && cp kit.conf kit.conf.bak
  cp "presets/$PRESET.conf" kit.conf
  [ "$ARCH" = "x86_64" ] && sed -i '' 's/^BACKEND=.*/BACKEND=mac-x64/; s/^NGL=.*/NGL=0/' kit.conf
  echo "kit.conf set to preset $PRESET (old one saved as kit.conf.bak)."
fi

while IFS='=' read -r key value; do
  case "$key" in ''|\#*) continue ;; esac
  export "$key"="$value"
done < kit.conf

# ------------------------------------------------------------- 2. runtime
if [ -z "$(find bin/mac -type f -name llama-server 2>/dev/null | head -n 1)" ]; then
  if [ "$ARCH" = "x86_64" ]; then FILE="$MAC_X64"; WANT="$MAC_X64_SHA"; else FILE="$MAC_ARM64"; WANT="$MAC_ARM64_SHA"; fi
  TMP="$(mktemp -d)"
  echo; echo "Downloading llama.cpp $LLAMA_BUILD ($FILE) ..."
  curl -fL --progress-bar -o "$TMP/$FILE" "$LLAMA_BASE/$FILE" || die "Download failed."
  [ "$(sha "$TMP/$FILE")" = "$WANT" ] || die "Checksum mismatch for $FILE. Deleted, nothing installed."
  tar -xzf "$TMP/$FILE" -C bin/mac || die "Could not unpack $FILE."
  rm -rf "$TMP"
  xattr -dr com.apple.quarantine bin/mac 2>/dev/null
  echo "Runtime installed in bin/mac (checksum OK)."
else
  echo "Runtime already in bin/mac."
fi

# ------------------------------------------------------------- 3. model
# Hugging Face sends each file's SHA-256 in the x-linked-etag header.
fetch_hf() {   # $1 = path inside the repo, $2 = name inside models/ (default: same)
  local rel="${2:-$1}" url="https://huggingface.co/$MODEL_REPO/resolve/main/$1"
  local dst="models/${2:-$1}"
  if [ -f "$dst" ]; then echo "Have models/$rel"; return 0; fi
  mkdir -p "$(dirname "$dst")"
  local want
  want="$(curl -sI "$url" | tr -d '\r' | awk -F'"' 'tolower($0) ~ /^x-linked-etag:/ {print $2}')"
  echo; echo "Downloading $1 from $MODEL_REPO ..."
  curl -fL -C - --progress-bar -o "$dst.part" "$url" || die "Download failed. Run setup again to resume."
  if [ -n "$want" ]; then
    [ "$(sha "$dst.part")" = "$want" ] || { rm -f "$dst.part"; die "Checksum mismatch for $rel. Deleted."; }
    echo "Checksum OK."
  else
    echo "Note: no checksum offered by the server for $rel, not verified."
  fi
  mv "$dst.part" "$dst"
}

if [ "${MODEL_PARTS:-1}" -gt 1 ]; then
  for i in $(seq 1 "$MODEL_PARTS"); do
    fetch_hf "$(echo "$MODEL" | sed "s/-00001-of-/-$(printf %05d "$i")-of-/")"
  done
else
  fetch_hf "$MODEL"
fi
[ -n "${MMPROJ:-}" ] && fetch_hf "${MMPROJ_FILE:-mmproj-F16.gguf}" "$MMPROJ"

echo
echo "Setup done. In Rhino 8 run _-RunPythonScript and pick rhino/rhino_ai.py"
read -r -p "Press Enter to close."
