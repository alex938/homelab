#!/bin/bash
set -euo pipefail
INVOKE_DIR="$(pwd)"
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$PATH"
LOGFILE="$INVOKE_DIR/execute-$(date +%Y%m%d-%H%M%S).log"
claude -p "read claude.md and follow its instructions to fix the server" --dangerously-skip-permissions 2>&1 | tee "$LOGFILE"
