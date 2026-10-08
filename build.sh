#!/usr/bin/env bash
# Builds the Linux version of Xenticorp Ripnamer into ./dist/xenticorp-ripnamer
# Usage:  chmod +x build.sh && ./build.sh
set -e
cd "$(dirname "$0")"
[ -f ripnamer_app/ui/app.py ] || { echo "The ripnamer_app folder is missing - keep it next to ripnamer.py."; exit 1; }

if ! python3 -c "import tkinter" 2>/dev/null || ! python3 -m venv --help >/dev/null 2>&1; then
  echo "Installing python3-tk and python3-venv (needs sudo)…"
  sudo apt-get update && sudo apt-get install -y python3-tk python3-venv
fi

python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip pyinstaller sv-ttk >/dev/null

echo
read -r -p "Paste TMDb API key to bake in (or just press Enter to skip): " KEY
rm -f ripnamer_key.py
if [ -n "$KEY" ]; then echo "KEY = \"$KEY\"" > ripnamer_key.py; echo "Key will be built in."; else echo "No key baked in."; fi
trap 'rm -f ripnamer_key.py' EXIT

EXTRA=()
[ -f ripnamer_key.py ] && EXTRA+=(--hidden-import ripnamer_key)
[ -f xenticorp.png ] && EXTRA+=(--add-data "xenticorp.png:.")
pyinstaller --noconfirm --clean --onefile --windowed --name xenticorp-ripnamer \
  --collect-data sv_ttk "${EXTRA[@]}" ripnamer.py

echo
echo "Done: $(pwd)/dist/xenticorp-ripnamer"
echo "Tip: run the tests any time with:  python3 -m unittest discover -s tests"
read -r -p "Add it to your app menu? [y/N] " yn
if [[ "$yn" =~ ^[Yy]$ ]]; then
  mkdir -p ~/.local/bin ~/.local/share/applications ~/.local/share/icons
  cp dist/xenticorp-ripnamer ~/.local/bin/
  [ -f xenticorp.png ] && cp xenticorp.png ~/.local/share/icons/xenticorp-ripnamer.png
  cat > ~/.local/share/applications/xenticorp-ripnamer.desktop <<DESK
[Desktop Entry]
Type=Application
Name=Xenticorp Ripnamer
Comment=Rename MakeMKV rips for Jellyfin
Exec=$HOME/.local/bin/xenticorp-ripnamer
Icon=$HOME/.local/share/icons/xenticorp-ripnamer.png
StartupWMClass=XenticorpRipnamer
Categories=AudioVideo;Utility;
Terminal=false
DESK
  echo "Added. Search 'Xenticorp Ripnamer' in Activities."
fi
