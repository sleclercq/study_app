#!/bin/bash
# Launcher for the revision app.
# Finds python3.13 with tkinter support on both Apple Silicon (/opt/homebrew)
# and Intel Macs (/usr/local). Install dependency with: brew install python-tk@3.13
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

for py in /opt/homebrew/bin/python3.13 /usr/local/bin/python3.13 python3.13 python3; do
  if command -v "$py" &>/dev/null && "$py" -c "import tkinter" &>/dev/null 2>&1; then
    exec "$py" "$SCRIPT_DIR/main.py" "$@"
  fi
done

echo "Python 3.13 with tkinter not found. Run: brew install python-tk@3.13"
exit 1
