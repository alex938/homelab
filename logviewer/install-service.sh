#!/usr/bin/env bash
# Install the log viewer as a systemd service so it keeps running after the
# terminal is closed and comes back after a reboot.
#
#   sudo ./install-service.sh
#
# Uninstall:
#   sudo systemctl disable --now logviewer
#   sudo rm /etc/systemd/system/logviewer.service && sudo systemctl daemon-reload
set -euo pipefail
cd "$(dirname "$0")"

if [[ $EUID -ne 0 ]]; then
  echo "Run with sudo: sudo $0" >&2
  exit 1
fi

install -m 0644 logviewer.service /etc/systemd/system/logviewer.service
systemctl daemon-reload
systemctl enable logviewer
systemctl restart logviewer

echo
systemctl --no-pager --lines=0 status logviewer || true
echo
echo "Logs:   journalctl -u logviewer -f"
echo "Stop:   sudo systemctl stop logviewer"
echo "Start:  sudo systemctl start logviewer"
