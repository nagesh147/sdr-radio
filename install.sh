#!/usr/bin/env bash
set -euo pipefail
DIR="${HOME}/SDR-Tools"
sudo apt-get update
sudo apt-get install -y python3-pyqt5 sox rtl-sdr git curl ffmpeg
mkdir -p "$DIR"
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" pull --ff-only || true
else
  git clone https://github.com/nagesh147/sdr-radio.git "$DIR"
fi
pip3 install --user -r "$DIR/requirements.txt" 2>/dev/null || true
mkdir -p "$HOME/.local/share/applications"
cat > "$HOME/.local/share/applications/sdr-radio.desktop" << DESK
[Desktop Entry]
Name=SDR Radio
Exec=python3 $DIR/sdr-control-ui.py
Icon=audio-headphones
Type=Application
Categories=AudioVideo;Audio;
Terminal=false
DESK
echo "Installed. Run: python3 $DIR/sdr-control-ui.py"
