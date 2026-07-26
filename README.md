# SDR Radio

PyQt5 app for **RTL-SDR** (FM / air / amateur / SW) and **Internet radio**: tune, stream, song ID, lyrics, CC captions, station logos, tools.

Install path: **`~/SDR-Tools`** (required — the app loads config, icons, and art from there).

---

## One-shot install (recommended)

On Ubuntu / Debian / Pop!_OS / similar:

```bash
curl -fsSL https://raw.githubusercontent.com/nagesh147/sdr-radio/main/install.sh | bash
```

Or clone then install:

```bash
git clone https://github.com/nagesh147/sdr-radio.git ~/SDR-Tools
bash ~/SDR-Tools/install.sh
```

This installs system packages, Python deps, desktop launcher, seeds config/stations, and caches internet station logos.

### Run (use the launcher so the venv + live CC works)

```bash
~/SDR-Tools/sdr-control
```

Or if `~/.local/bin` is on your `PATH`:

```bash
sdr-control
```

Direct (system Python — GUI works; CC needs the venv):

```bash
~/SDR-Tools/.venv/bin/python ~/SDR-Tools/sdr-control-ui.py
```

### Setup only (no GUI)

```bash
~/SDR-Tools/.venv/bin/python ~/SDR-Tools/sdr-control-ui.py --setup-only
```
---

## What you get after install

| Feature | Needs |
|--------|--------|
| GUI | `python3-pyqt5` |
| Internet radio | `ffmpeg` (`ffplay`) or `mpv` |
| SDR live tune | `rtl-sdr` (`rtl_fm`) + `sox` (`play`) |
| Live **CC** captions (speech→text) | `faster-whisper` (pip) + `ffmpeg` — open source [SYSTRAN/faster-whisper](https://github.com/SYSTRAN/faster-whisper) |
| Song ID (optional) | `songrec` and/or `fpcalc` (AcoustID) |
| Genius lyrics (optional) | `lyricsgenius` + `genius_api_key.txt` |

### Live CC (subtitles)

Uses open-source **[faster-whisper](https://github.com/SYSTRAN/faster-whisper)** (Whisper `tiny.en`) to **transcribe live speech** from the stream (not station name).

1. Run via `~/SDR-Tools/sdr-control` (venv).
2. Play a station (e.g. **BBC World Service**).
3. Press **CC** next to play.
4. First time downloads the speech model (~75MB), then captions update every few seconds.

```bash
# Reinstall STT into the app venv if needed:
~/SDR-Tools/.venv/bin/pip install -U faster-whisper numpy
```

Keys (optional): put API keys in:

- `~/SDR-Tools/acoustid_api_key.txt`
- `~/SDR-Tools/genius_api_key.txt`

---

## Everyday use

- **SDR tab** — local stations / frequency tuner  
- **Internet tab** — radio-browser catalogs + streams  
  - **AIR-Net** — All India Radio (Akashvani) consolidated channels from the internet
    - National services: FM Gold, FM Rainbow, News 24x7, Raagam, Vividh Bharati
    - Regional languages: Tamil, Telugu, Kannada, Malayalam, Punjabi, Gujarati, Odia, Urdu, Assamese
    - City-specific: Delhi, Mumbai, Kolkata, Chennai, Bangalore, Kochi, Hyderabad, Jaipur, Lucknow, and more
    - Automatically fetches updates from radio-browser API
- **CC** — live stream titles / captions (ICY metadata + song ID)  
- **Lyrics** — right pane (lyrics icon or Lyrics nav)  
- **Ctrl+R / F5** — reload UI in-process  

If the dongle is stuck / busy:

```bash
sudo ~/SDR-Tools/reset-dongle.sh
```

---

## Manual package list (if not using install.sh)

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-pip python3-pyqt5 python3-pyqt5.qtsvg \
  git curl sox libsox-fmt-all ffmpeg pulseaudio-utils rtl-sdr libchromaprint-tools
python3 -m pip install --user -r ~/SDR-Tools/requirements.txt
python3 -m pip install --user lyricsgenius   # optional
python3 ~/SDR-Tools/sdr-control-ui.py --setup-only
```

---

## Config files (created on first run)

| File | Purpose |
|------|---------|
| `radio_config.json` | gain, theme, CC, last station |
| `stations.json` | station lists (seeded from defaults) |
| `song_history.json` / `song_favorites.json` | library |
| `art/stations/` | station logos / album art |
| `icons/` | UI icons (from repo) |

---

## License / repo

https://github.com/nagesh147/sdr-radio
