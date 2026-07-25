#!/usr/bin/env bash
# SDR Radio — one-shot install. After this, the app is ready to run.
#   bash install.sh
#   python3 ~/SDR-Tools/sdr-control-ui.py
set -euo pipefail

REPO_URL="${SDR_REPO_URL:-https://github.com/nagesh147/sdr-radio.git}"
DIR="${SDR_DIR:-$HOME/SDR-Tools}"

echo "==> SDR Radio install → $DIR"

run_root() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    echo "Need root/sudo for: $*" >&2
    return 1
  fi
}

if command -v apt-get >/dev/null 2>&1; then
  echo "==> System packages (apt)"
  run_root apt-get update -y
  DEBIAN_FRONTEND=noninteractive run_root apt-get install -y \
    python3 \
    python3-pip \
    python3-pyqt5 \
    python3-pyqt5.qtsvg \
    git \
    curl \
    ca-certificates \
    sox \
    libsox-fmt-all \
    ffmpeg \
    pulseaudio-utils \
    rtl-sdr \
    libchromaprint-tools \
    fonts-dejavu-core
else
  echo "WARN: no apt-get — install PyQt5, sox, ffmpeg, rtl-sdr yourself."
fi

echo "==> Source tree"
mkdir -p "$DIR"
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" fetch origin 2>/dev/null || true
  git -C "$DIR" pull --ff-only origin main 2>/dev/null \
    || git -C "$DIR" pull --ff-only 2>/dev/null \
    || true
elif [ -f "$DIR/sdr-control-ui.py" ]; then
  echo "Using existing $DIR (no .git)"
else
  git clone "$REPO_URL" "$DIR"
fi

echo "==> Python venv + packages (UI + live CC speech-to-text)"
# venv with system-site-packages so apt python3-pyqt5 is still visible
if [ ! -x "$DIR/.venv/bin/python" ]; then
  python3 -m venv --system-site-packages "$DIR/.venv"
fi
"$DIR/.venv/bin/pip" install -U pip setuptools wheel >/dev/null 2>&1 || true
"$DIR/.venv/bin/pip" install -r "$DIR/requirements.txt" || true
"$DIR/.venv/bin/pip" install "numpy>=1.22" "faster-whisper>=1.0.0" || {
  echo "WARN: faster-whisper failed — installing vosk fallback"
  "$DIR/.venv/bin/pip" install vosk || true
}
"$DIR/.venv/bin/python" -c "from PyQt5.QtWidgets import QApplication; print('  PyQt5 OK')" 2>/dev/null \
  || echo "  WARN: PyQt5 not importable in venv (install python3-pyqt5)"
"$DIR/.venv/bin/python" -c "import faster_whisper; print('  faster-whisper OK')" 2>/dev/null \
  || "$DIR/.venv/bin/python" -c "import vosk; print('  vosk OK')" 2>/dev/null \
  || echo "  WARN: no STT engine — CC live captions will prompt to install"

echo "==> Launchers"
chmod +x "$DIR/install.sh" "$DIR/sdr-control" "$DIR/reset-dongle.sh" \
  "$DIR/aircraft.sh" "$DIR/ais.sh" "$DIR/flights.sh" "$DIR/weather.sh" \
  "$DIR/sdr-menu.sh" "$DIR/sdrpp.sh" 2>/dev/null || true

BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
mkdir -p "$BIN_DIR"
ln -sfn "$DIR/sdr-control" "$BIN_DIR/sdr-control"

APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$APP_DIR"
cat > "$APP_DIR/sdr-radio.desktop" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=SDR Radio
Comment=RTL-SDR + Internet radio player
Exec=python3 $DIR/sdr-control-ui.py
Icon=audio-headphones
Terminal=false
Categories=AudioVideo;Audio;Player;
StartupWMClass=sdr-control-ui
EOF
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APP_DIR" 2>/dev/null || true

echo "==> First-run seed (config, stations, default art, logos)"
if [ -x "$DIR/.venv/bin/python" ]; then
  "$DIR/.venv/bin/python" "$DIR/sdr-control-ui.py" --setup-only
else
  python3 "$DIR/sdr-control-ui.py" --setup-only
fi

echo
echo "========================================"
echo "  Ready."
echo "  Run:  $DIR/sdr-control"
echo "    or: $DIR/.venv/bin/python $DIR/sdr-control-ui.py"
echo "    or: python3 $DIR/sdr-control-ui.py   # GUI only; CC needs venv STT"
echo "  Reset dongle:  sudo $DIR/reset-dongle.sh"
echo "========================================"
