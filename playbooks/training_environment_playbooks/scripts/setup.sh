#!/bin/bash

# Variables
FILESERVER_URL="http://172.16.1.10:7000"
PACKAGES_DIR="/tmp/kali-packages"

# Ensure the script is run as root
if [[ $EUID -ne 0 ]]; then
   echo "This script must be run as root" 
   exit 1
fi

echo "Starting automated setup..."

echo "Preseeding language and keyboard layout (UK)..."
debconf-set-selections <<EOF
keyboard-configuration  keyboard-configuration/layoutcode select gb
keyboard-configuration  keyboard-configuration/xkb-keymap select gb
locales locales/default_environment_locale select en_GB.UTF-8
locales locales/locales_to_be_generated multiselect en_GB.UTF-8 UTF-8
EOF

echo "Generating locales..."
dpkg-reconfigure -f noninteractive locales
dpkg-reconfigure -f noninteractive keyboard-configuration

# Step 2: Download .deb Packages
echo "Downloading .deb packages from the fileserver at $FILESERVER_URL..."
mkdir -p "$PACKAGES_DIR"
cd "$PACKAGES_DIR"
wget -r -np -nH --cut-dirs=1 -A "*.deb" "$FILESERVER_URL"

# Step 3: Install Packages
echo "Installing downloaded packages..."
dpkg -i *.deb || echo "Fixing broken dependencies..."
apt-get install -f -y

# Step 4: Clean Up
echo "Cleaning up temporary files..."
rm -rf "$PACKAGES_DIR"
