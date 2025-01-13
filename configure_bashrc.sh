#!/bin/bash

ALIAS_URL="https://raw.githubusercontent.com/alex938/homelab/refs/heads/main/alias.txt"

BASHRC_FILE="$HOME/.bashrc"
ALIAS_MARKER="# Custom Aliases"
TEMP_FILE="/tmp/alias_list.txt"

if ! grep -q "$ALIAS_MARKER" "$BASHRC_FILE"; then
  echo -e "\n$ALIAS_MARKER" >> "$BASHRC_FILE"
fi

curl -s "$ALIAS_URL" -o "$TEMP_FILE"

if [ ! -s "$TEMP_FILE" ]; then
  echo "Failed to fetch alias file or file is empty."
  exit 1
fi

{ while IFS= read -r line || [ -n "$line" ]; do
  if [[ $line =~ ^alias ]]; then
    alias_name=$(echo "$line" | cut -d' ' -f2 | cut -d'=' -f1)
    sed -i "/alias $alias_name=/d" "$BASHRC_FILE"
    echo "$line" >> "$BASHRC_FILE"
    echo "Added or updated alias: $line"
  fi
done; } < "$TEMP_FILE"

echo "Aliases updated in ~/.bashrc. Please run 'source ~/.bashrc' to apply the changes."
