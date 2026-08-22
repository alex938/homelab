#!/bin/bash
set -euo pipefail
INVOKE_DIR="$(pwd)"
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$PATH"
LOGFILE="$INVOKE_DIR/execute-$(date +%Y%m%d-%H%M%S).log"
claude -p "read CLAUDE.md and RUN-NOTES.md, then follow CLAUDE.md's instructions to clean servers and improve their efficiency. record what you learn in RUN-NOTES.md, not in CLAUDE.md" --dangerously-skip-permissions 2>&1 | tee "$LOGFILE"
