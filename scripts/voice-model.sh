#!/bin/bash
# Explicit, owner-approved download of the speech-to-text model (Phase 13). Never done by the app,
# the backend or the speech server (which has no network access at all).
#   make voice-model APPROVED=yes [SHA256=<expected>]
# whisper.cpp's large-v3-turbo, 5-bit quantized (~574 MB), from the whisper.cpp model repository,
# into ~/Library/Application Support/LAZIS/models/whisper/ (shared by profiles; not user data).
set -euo pipefail
NAME="ggml-large-v3-turbo-q5_0.bin"
URL="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/$NAME"
DIR="$HOME/Library/Application Support/LAZIS/models/whisper"
[ "${APPROVED:-}" = "yes" ] || { echo "refused: needs the owner's approval (APPROVED=yes); ~574 MB download" >&2; exit 2; }
FREE_GB="$(df -g "$HOME" | awk 'NR==2 {print $4}')"
[ "$FREE_GB" -gt 5 ] || { echo "refused: only ${FREE_GB} GB free" >&2; exit 2; }
mkdir -p "$DIR" && chmod 700 "$DIR"
if [ -f "$DIR/$NAME" ]; then echo "already present: $DIR/$NAME"; else
  echo "downloading $NAME at $(date -u +%FT%TZ)"
  curl --fail --location --proto '=https' --tlsv1.2 --output "$DIR/$NAME.part" "$URL"
  mv "$DIR/$NAME.part" "$DIR/$NAME"
fi
GOT="$(shasum -a 256 "$DIR/$NAME" | awk '{print $1}')"
echo "sha256 $GOT bytes $(stat -f %z "$DIR/$NAME")"
if [ -n "${SHA256:-}" ] && [ "$GOT" != "$SHA256" ]; then
  echo "checksum mismatch: expected $SHA256; removing the file" >&2; rm -f "$DIR/$NAME"; exit 1
fi
command -v whisper-server >/dev/null || echo "note: whisper.cpp is not installed (brew install whisper-cpp)"
