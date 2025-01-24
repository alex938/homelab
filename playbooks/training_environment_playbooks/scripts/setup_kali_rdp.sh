#!/bin/sh
echo "[i] Updating and upgrading Kali (this will take a while)"
apt-get update
apt-get full-upgrade -y

echo "[i] Installing Xfce4 & xrdp (this will take a while as well)"
apt-get install -y kali-desktop-xfce xorg xrdp

echo "[i] Starting and enabling the xrdp service"
systemctl start xrdp
systemctl enable xrdp

echo "[i] Checking the status of the xrdp service"
systemctl status xrdp --no-pager

