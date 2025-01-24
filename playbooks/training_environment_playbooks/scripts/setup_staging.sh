#!/bin/bash

# Variables
FILESERVER_DIR="/var/www/html/kali-packages" # Directory to store downloaded packages
APT_CACHE_DIR="/var/cache/apt/archives"
DESKTOP_ENV="kali-desktop-xfce"
DEFAULT_PACKAGES="kali-linux-default xorg xrdp"
EXTRA_PACKAGES="build-essential net-tools curl wget vim"
ALL_PACKAGES="$DEFAULT_PACKAGES $DESKTOP_ENV $EXTRA_PACKAGES"

# Ensure the script is run as root
if [[ $EUID -ne 0 ]]; then
    echo "This script must be run as root"
    exit 1
fi

# Step 1: Update Package Lists
echo "[i] Updating package lists..."
apt-get update -y

# Step 2: Download Required Packages
echo "[i] Downloading required packages for offline installation..."
mkdir -p "$FILESERVER_DIR"
apt-get install --download-only -y $ALL_PACKAGES

# Step 3: Copy All .deb Files to File Server Directory
echo "[i] Copying downloaded packages to $FILESERVER_DIR..."
cp $APT_CACHE_DIR/*.deb "$FILESERVER_DIR"

# Step 4: Generate a Package List
echo "[i] Generating a package list for offline installation..."
apt-get install -y dpkg-dev
dpkg-scanpackages "$FILESERVER_DIR" /dev/null | gzip -9c > "$FILESERVER_DIR/Packages.gz"

# Step 5: (Optional) Serve the Directory with HTTP
echo "[i] Setting up a simple HTTP server to serve the packages..."
if ! command -v python3 &>/dev/null; then
    apt-get install -y python3
fi
cd "$FILESERVER_DIR"
nohup python3 -m http.server 7000 --bind 172.16.1.10 > /dev/null 2>&1 &

SERVER_IP=$(hostname -I | awk '{print $1}')
echo "[i] All packages are downloaded and available at: http://$SERVER_IP:7000"
echo "[i] To install packages on a target system, use the following commands:"
echo "    1. Add the server as a repository:"
echo "       echo 'deb [trusted=yes] http://$SERVER_IP:7000/ ./' | sudo tee /etc/apt/sources.list.d/offline.list"
echo "    2. Run apt-get update and install the required packages:"
echo "       sudo apt-get update"
echo "       sudo apt-get install -y kali-linux-default kali-desktop-xfce xorg xrdp"
