#!/bin/bash
set -euo pipefail
INVOKE_DIR="$(pwd)"
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$PATH"
LOGFILE="$INVOKE_DIR/execute-$(date +%Y%m%d-%H%M%S).log"
claude -p "read claude.md and follow its instructions to check the health and performance of the apt cacher. do nothing that would cause the server to catastrophically fail" --dangerously-skip-permissions 2>&1 | tee "$LOGFILE"