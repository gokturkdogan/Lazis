#!/bin/bash
# Explicit, owner-approved model download (never done by the app or the backend).
#   scripts/model-pull.sh <tag>      e.g. scripts/model-pull.sh qwen3.5:9b-q4_K_M
# Refuses tags that are not in scripts/approved-models.txt, cloud tags and registry-qualified
# names, checks free disk space, pulls through the local Ollama, and prints the digest.
set -euo pipefail
TAG="${1:-}"
DIR="$(cd "$(dirname "$0")" && pwd)"
LIST="$DIR/approved-models.txt"
[ -n "$TAG" ] || { echo "usage: $0 <tag>"; grep -v '^#' "$LIST"; exit 2; }
case "$TAG" in *cloud*|*/*) echo "refused: cloud or registry-qualified tag: $TAG" >&2; exit 2 ;; esac
SIZE="$(awk -v t="$TAG" '$1 == t {print $2}' "$LIST")"
[ -n "$SIZE" ] || { echo "refused: $TAG is not in $LIST (needs the owner's approval)" >&2; exit 2; }
FREE_GB="$(df -g "$HOME" | awk 'NR==2 {print $4}')"
awk -v f="$FREE_GB" -v s="$SIZE" 'BEGIN { exit !(f > s + 20) }' \
  || { echo "refused: only ${FREE_GB} GB free; need ${SIZE} GB + 20 GB headroom" >&2; exit 2; }
curl -s --max-time 2 http://127.0.0.1:11434/api/version >/dev/null \
  || { echo "Ollama is not running (scripts/ollama-agent.sh install)" >&2; exit 2; }
echo "pulling $TAG (~${SIZE} GB, ${FREE_GB} GB free) at $(date -u +%FT%TZ)"
ollama pull "$TAG"
curl -s http://127.0.0.1:11434/api/tags | /usr/bin/python3 -c "
import json, sys
for m in json.load(sys.stdin)['models']:
    if m['name'] == '$TAG':
        print('installed', m['name'], 'digest', m['digest'], 'bytes', m['size'])
"
