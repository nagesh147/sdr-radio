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

### Run

```bash
python3 ~/SDR-Tools/sdr-control-ui.py
```

Or if `~/.local/bin` is on your `PATH`:

```bash
sdr-control
```

### Setup only (no GUI)

```bash
python3 ~/SDR-Tools/sdr-control-ui.py --setup-only
```

---

## What you get after install

| Feature | Needs |
|--------|--------|
| GUI | `python3-pyqt5` |
| Internet radio | `ffmpeg` (`ffplay`) or `mpv` |
| SDR live tune | `rtl-sdr` (`rtl_fm`) + `sox` (`play`) |
| Song ID (optional) | `songrec` and/or `fpcalc` (AcoustID) |
| Genius lyrics (optional) | `lyricsgenius` + `genius_api_key.txt` |

Keys (optional): put API keys in:

- `~/SDR-Tools/acoustid_api_key.txt`
- `~/SDR-Tools/genius_api_key.txt`

---

## Everyday use

- **SDR tab** — local stations / frequency tuner  
- **Internet tab** — radio-browser catalogs + streams  
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
