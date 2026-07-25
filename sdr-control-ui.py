#!/usr/bin/env python3
"""SDR Radio — Apple/Spotify-inspired responsive UI."""
from __future__ import annotations

import sys, os, subprocess, threading, time, json, asyncio, re
import urllib.parse, urllib.request
from datetime import datetime
from pathlib import Path
from difflib import SequenceMatcher

BASE = Path.home() / "SDR-Tools"
LOCK = Path("/tmp/sdr-control.lock")
CONFIG = BASE / "radio_config.json"
STATIONS_F = BASE / "stations.json"
HIST_F = BASE / "song_history.json"
FAV_F = BASE / "song_favorites.json"
AC_KEY = BASE / "acoustid_api_key.txt"
GN_KEY = BASE / "genius_api_key.txt"
SNIP = BASE / "snippets"
ART = BASE / "art"

def _alive(pid):
    try: os.kill(pid, 0); return True
    except OSError: return False

if LOCK.exists():
    try:
        o = int(LOCK.read_text().strip())
        if _alive(o): sys.exit(0)
        LOCK.unlink(missing_ok=True)
    except Exception:
        LOCK.unlink(missing_ok=True)
LOCK.write_text(str(os.getpid()))

from PyQt5.QtWidgets import (
    QMessageBox,
    QInputDialog,
    QMenu,
    QAbstractItemView,
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QTextEdit, QFrame, QGridLayout, QComboBox, QListWidget, QListWidgetItem,
    QDoubleSpinBox, QTabWidget, QSplitter, QSizePolicy, QAbstractSpinBox,
    QGraphicsDropShadowEffect, QToolTip,
)
from PyQt5.QtCore import Qt, pyqtSignal, QObject, QTimer, QUrl, QSize, QPoint, QPropertyAnimation, QEasingCurve
from PyQt5.QtGui import QTextCursor, QPainter, QColor, QPen, QFont, QPixmap, QDesktopServices, QCursor

DEFAULT_STATIONS = {
    "India FM": [
        {"name": "Big FM", "freq": 92.7, "mode": "wbfm"},
        {"name": "Red FM", "freq": 93.5, "mode": "wbfm"},
        {"name": "Radio Mirchi", "freq": 98.3, "mode": "wbfm"},
        {"name": "AIR FM Rainbow", "freq": 101.9, "mode": "wbfm"},
        {"name": "Magic FM", "freq": 106.4, "mode": "wbfm"},
        {"name": "Radio City", "freq": 91.1, "mode": "wbfm"},
        {"name": "Fever FM", "freq": 94.3, "mode": "wbfm"},
        {"name": "AIR FM Gold", "freq": 100.1, "mode": "wbfm"},
    ],
    "Airband": [
        {"name": "Tower", "freq": 118.6, "mode": "am"},
        {"name": "Approach", "freq": 119.55, "mode": "am"},
        {"name": "Emergency", "freq": 121.5, "mode": "am"},
    ],
    "Amateur": [
        {"name": "2m Calling", "freq": 145.5, "mode": "fm"},
        {"name": "70cm Calling", "freq": 433.5, "mode": "fm"},
    ],
    "Marine": [{"name": "Ch 16", "freq": 156.8, "mode": "fm"}],
    "Shortwave": [
        {"name": "WWV 10", "freq": 10.0, "mode": "am"},
        {"name": "BBC 9.41", "freq": 9.41, "mode": "am"},
    ],
}
BANDS = [
    ("LW", 0.15, 0.28, "am"), ("MW", 0.53, 1.71, "am"), ("SW", 2.3, 30.0, "am"),
    ("CB", 26.9, 27.4, "am"), ("FM", 88.0, 108.0, "wbfm"), ("Air", 118.0, 137.0, "am"),
    ("2m", 144.0, 148.0, "fm"), ("Marine", 156.0, 162.0, "fm"), ("70cm", 430.0, 440.0, "fm"),
]

def mode_for_freq(f):
    for _, a, b, m in BANDS:
        if a <= f <= b: return m
    return "wbfm" if 88 <= f <= 108 else ("am" if f < 30 else "fm")

def band_for_freq(f):
    for n, a, b, _ in BANDS:
        if a <= f <= b: return n
    return "All Bands"

def _norm(s):
    s = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", (s or "").lower())
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def song_match(a, b, th=0.82):
    if not a or not b: return False
    aa, at = _norm(a.get("artist")), _norm(a.get("title"))
    ba, bt = _norm(b.get("artist")), _norm(b.get("title"))
    if not at or not bt: return False
    if at == bt and (not aa or not ba or aa == ba or aa in ba or ba in aa): return True
    return SequenceMatcher(None, at, bt).ratio() >= th and (
        SequenceMatcher(None, aa, ba).ratio() if aa and ba else 0.9) >= 0.55

def load_json(path, default):
    if path.exists():
        try: return json.loads(path.read_text())
        except Exception: pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(default, indent=2))
    return json.loads(json.dumps(default))

def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


class Sig(QObject):
    log = pyqtSignal(str)
    result = pyqtSignal(dict)
    status = pyqtSignal(str)
    lyrics = pyqtSignal(str)
    art = pyqtSignal(str)  # path


class Toast(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("toast")
        self.setWordWrap(True)
        self.hide()
        self._t = QTimer(self); self._t.setSingleShot(True); self._t.timeout.connect(self.hide)

    def show_msg(self, text, ms=3000):
        self.setText(text)
        self.adjustSize()
        self.setFixedWidth(min(320, max(180, (self.parent().width() if self.parent() else 360)//3)))
        self.adjustSize()
        if self.parent():
            r = self.parent().rect()
            self.move(r.width() - self.width() - 20, r.height() - self.height() - 20)
        self.show(); self.raise_(); self._t.start(ms)








class FreqScale(QWidget):
    """Center needle, sparse ticks, cached background for speed."""
    changed = pyqtSignal(float)
    released = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(76)
        self.setMinimumWidth(260)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self._min, self._max, self._val = 88.0, 108.0, 91.1
        self._drag = False
        self._lx = 0
        self.dark = False
        self._cache = None
        self._cache_key = None

    def setRange(self, a, b):
        a, b = float(a), float(b)
        if b <= a:
            b = a + 1.0
        self._min, self._max = a, b
        self._val = min(max(self._val, self._min), self._max)
        self._cache = None
        self.update()

    def setValue(self, v):
        nv = min(max(float(v), self._min), self._max)
        if abs(nv - self._val) < 1e-6:
            return
        self._val = nv
        self.update()

    def value(self):
        return self._val

    def _window(self):
        span = max(0.5, self._max - self._min)
        if span <= 5:
            return span
        if span <= 25:
            return min(span, 8.0)
        return min(span, 12.0)

    def _build_cache(self, w, h):
        """Static ticks for current range/value window — redraw only when key changes."""
        key = (w, h, round(self._min, 3), round(self._max, 3), round(self._val, 1), self.dark)
        if self._cache is not None and self._cache_key == key:
            return self._cache
        pm = QPixmap(w, h)
        pm.fill(QColor("#2c2c2e") if self.dark else QColor("#f2f2f7"))
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, False)  # ticks are axis-aligned
        pad = 16
        usable = max(1.0, w - 2 * pad)
        visible = self._window()
        mpp = visible / usable
        cx = w / 2.0
        major = 1.0 if visible <= 20 else 5.0
        half = visible / 2.0
        base = h - 24
        # majors only + mid markers every 0.5
        f = int((self._val - half) / 0.5) * 0.5
        end = self._val + half + 0.5
        while f <= end:
            if self._min - 1e-9 <= f <= self._max + 1e-9:
                x = cx + (f - self._val) / mpp
                if pad <= x <= w - pad:
                    maj = abs(round(f / major) * major - f) < 1e-4
                    p.setPen(QColor("#8e8e93") if maj else QColor("#c7c7cc"))
                    p.drawLine(int(x), base, int(x), 22 if maj else 30)
                    if maj:
                        p.setPen(QColor("#f5f5f7") if self.dark else QColor("#3a3a3c"))
                        p.setFont(QFont("Sans", 8))
                        lab = f"{f:.0f}" if abs(f - round(f)) < 1e-6 else f"{f:.1f}"
                        p.drawText(int(x) - 14, h - 16, 28, 12, Qt.AlignCenter, lab)
            f = round(f + 0.5, 5)
        p.end()
        self._cache = pm
        self._cache_key = key
        return pm

    def paintEvent(self, _ev):
        w, h = self.width(), self.height()
        if w < 40:
            return
        p = QPainter(self)
        p.drawPixmap(0, 0, self._build_cache(w, h))
        # needle + readout only (cheap)
        p.setRenderHint(QPainter.Antialiasing, True)
        cx = w / 2.0
        base = h - 24
        p.setPen(QPen(QColor("#30d158"), 2))
        p.drawLine(int(cx), 10, int(cx), base)
        p.setBrush(QColor("#30d158"))
        p.setPen(Qt.NoPen)
        p.drawEllipse(int(cx) - 5, 8, 10, 10)
        p.setPen(QColor("#30d158"))
        p.setFont(QFont("Sans", 10, QFont.Bold))
        p.drawText(16, 14, f"{self._val:.1f} MHz")

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = True
            self._lx = e.x()

    def mouseMoveEvent(self, e):
        if not self._drag:
            return
        dx = e.x() - self._lx
        self._lx = e.x()
        usable = max(1.0, self.width() - 32)
        mpp = self._window() / usable
        self._val = min(max(self._val - dx * mpp, self._min), self._max)
        self._val = round(self._val * 10) / 10.0
        self._cache = None
        self.update()
        self.changed.emit(self._val)

    def mouseReleaseEvent(self, _e):
        self._drag = False
        try:
            self.released.emit(self._val)
        except Exception:
            pass

    def wheelEvent(self, e):
        step = 0.1 if e.angleDelta().y() > 0 else -0.1
        self._val = min(max(round((self._val + step) * 10) / 10.0, self._min), self._max)
        self._cache = None
        self.update()
        self.changed.emit(self._val)

    def resizeEvent(self, e):
        self._cache = None
        super().resizeEvent(e)



class HoverIcon(QPushButton):
    """Fixed-size header icon. Fades in/out — never show()/hide() (avoids layout jump)."""
    def __init__(self, text, tip, parent=None):
        super().__init__(text, parent)
        self.setObjectName("icon")
        self.setFixedSize(28, 28)
        self.setToolTip(tip)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        from PyQt5.QtWidgets import QGraphicsOpacityEffect
        self._fx = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._fx)
        self._fx.setOpacity(0.0)  # invisible but still occupies space

    def fade(self, on: bool):
        self._fx.setOpacity(1.0 if on else 0.0)


class Collapse(QWidget):
    """When open, expands to fill remaining space; when closed, header only."""
    def __init__(self, title, start_open=True):
        super().__init__()
        self._open = start_open
        self._title = title
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.btn = QPushButton()
        self.btn.setObjectName("collapseBtn")
        self.btn.setCursor(Qt.PointingHandCursor)
        self.btn.setFixedHeight(30)
        self.btn.clicked.connect(self.toggle)
        root.addWidget(self.btn)
        self.body = QWidget()
        self.body_l = QVBoxLayout(self.body)
        self.body_l.setContentsMargins(0, 4, 0, 4)
        self.body_l.setSpacing(4)
        root.addWidget(self.body, 1)
        self._apply()

    def _apply(self):
        self.btn.setText(("▾  " if self._open else "▸  ") + self._title)
        self.body.setVisible(self._open)
        if self._open:
            self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
            self.setMinimumHeight(120)
            self.setMaximumHeight(16777215)
            self.body.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        else:
            self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
            self.setMinimumHeight(0)
            self.setMaximumHeight(30)
            self.body.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

    def toggle(self):
        self._open = not self._open
        self._apply()
        # notify parent to reflow
        p = self.parentWidget()
        if p and p.layout():
            p.layout().activate()

    def setOpen(self, v: bool):
        self._open = bool(v)
        self._apply()


class App(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SDR Radio")
        self.setWindowRole("sdr-control-ui")
        self.dark = False
        self.rtl = None
        self.playing = False
        self.song = None
        self.genius_url = None
        self.id_stop = threading.Event()
        self.id_thread = None
        self.id_busy = False
        self.aio_loop = None
        self.aio_thread = None
        self.lrc = []
        self.lrc_t0 = None
        self._band_lock = False

        self.sig = Sig()
        self.sig.log.connect(self._on_log)
        self.sig.result.connect(self.on_result)
        self.sig.status.connect(self.on_status)
        self.sig.lyrics.connect(self.on_lyrics)
        self.sig.art.connect(self.show_art)

        self.stations = self._clean_stations(load_json(STATIONS_F, DEFAULT_STATIONS))
        self.cfg = load_json(CONFIG, {"gain": 35, "song_id": True})
        self.history = load_json(HIST_F, [])
        self.favs = load_json(FAV_F, [])
        self.ac_key = AC_KEY.read_text().strip() if AC_KEY.exists() else ""
        self.gn_key = GN_KEY.read_text().strip() if GN_KEY.exists() else ""
        SNIP.mkdir(parents=True, exist_ok=True)
        ART.mkdir(parents=True, exist_ok=True)

        self.lrc_timer = QTimer(self)
        self.lrc_timer.timeout.connect(self._tick_lrc)

        self._ui()
        self._style()
        self.log("Ready")
        self.log("Bands: " + ", ".join(b[0] for b in BANDS))
        if self.cfg.get("song_id"):
            self.btn_auto.setChecked(True)

    def _clean_stations(self, data):
        out = {}
        for cat, items in (data or {}).items():
            clean = []
            for s in items or []:
                if not isinstance(s, dict): continue
                name = str(s.get("name", "")).strip()
                try: freq = float(s.get("freq", 0))
                except Exception: continue
                if not name or freq <= 0 or name.replace(".", "").isdigit(): continue
                clean.append({"name": name, "freq": freq, "mode": s.get("mode") or mode_for_freq(freq)})
            if clean: out[cat] = clean
        return out or DEFAULT_STATIONS

    def _ui(self):
        self.setMinimumSize(1020, 660)
        self.resize(1120, 720)
        c = QWidget(); self.setCentralWidget(c)
        root = QVBoxLayout(c)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(0)
        self.toast = Toast(c)

        self.split = QSplitter(Qt.Horizontal)
        self.split.setHandleWidth(6)
        self.split.setChildrenCollapsible(True)
        root.addWidget(self.split, 1)


        # --- Left: stations (resizable) ---
        left = QFrame(); left.setObjectName("card")
        left.setMinimumWidth(280)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(12, 12, 12, 12)
        ll.setSpacing(8)
        hdr = QHBoxLayout()
        hdr.setContentsMargins(0, 0, 0, 0)
        hdr.setSpacing(4)
        hl = QLabel("Stations"); hl.setObjectName("h")
        hdr.addWidget(hl)
        hdr.addStretch()
        self.btn_hide_left = HoverIcon("◂", "Hide stations")
        self.btn_hide_left.clicked.connect(lambda: self.toggle_left(False))
        hdr.addWidget(self.btn_hide_left)
        left.installEventFilter(self)
        ll.addLayout(hdr)
        row = QHBoxLayout()
        self.cats = QListWidget()
        self.cats.setObjectName("cats")
        self.cats.setFixedWidth(110)
        self.cats.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.cats.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        for k in self.stations: self.cats.addItem(k)
        self.cats.currentTextChanged.connect(self.load_cat)
        row.addWidget(self.cats)
        self.stations_list = QListWidget()
        self.stations_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.stations_list.setTextElideMode(Qt.ElideRight)
        self.stations_list.setMouseTracking(True)
        self.stations_list.itemClicked.connect(self.play_item)
        self.stations_list.setDragEnabled(True)
        self.stations_list.setAcceptDrops(True)
        self.stations_list.setDropIndicatorShown(True)
        self.stations_list.setDefaultDropAction(Qt.MoveAction)
        self.stations_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.stations_list.model().rowsMoved.connect(self._stations_reordered)
        self.stations_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.stations_list.customContextMenuRequested.connect(self.stations_menu)

        self.stations_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.stations_list.customContextMenuRequested.connect(self.stations_menu)
        self.stations_list.itemEntered.connect(lambda it: QToolTip.showText(
            QCursor.pos(), it.toolTip() or it.text(), self.stations_list))
        row.addWidget(self.stations_list, 1)
        # wrap row into splitter-like stretch
        ll.addLayout(row, 1)
        self.split.addWidget(left)

        # --- Center ---
        mid = QWidget()
        ml = QVBoxLayout(mid)
        ml.setContentsMargins(6, 0, 6, 0)
        ml.setSpacing(8)
        edge = QHBoxLayout()
        self.btn_show_left = QPushButton("☰")
        self.btn_show_left.setObjectName("icon")
        self.btn_show_left.setFixedSize(28, 28)
        self.btn_show_left.setToolTip("Show stations")
        self.btn_show_left.setVisible(False)
        self.btn_show_left.clicked.connect(lambda: self.toggle_left(True))
        edge.addWidget(self.btn_show_left)
        edge.addStretch()
        self.btn_show_right = QPushButton("☰")
        self.btn_show_right.setObjectName("icon")
        self.btn_show_right.setFixedSize(28, 28)
        self.btn_show_right.setToolTip("Show side panel")
        self.btn_show_right.setVisible(False)
        self.btn_show_right.clicked.connect(lambda: self.toggle_right(True))
        edge.addWidget(self.btn_show_right)
        ml.addLayout(edge)


        hero = QFrame(); hero.setObjectName("card")
        hl = QHBoxLayout(hero)
        hl.setContentsMargins(16, 16, 16, 16)
        hl.setSpacing(16)
        hl.setAlignment(Qt.AlignTop)

        self.art = QLabel("♪")
        self.art.setFixedSize(132, 132)
        self.art.setAlignment(Qt.AlignCenter)
        self.art.setObjectName("art")
        hl.addWidget(self.art)

        info = QVBoxLayout(); info.setSpacing(4)
        self.title = QLabel("Not playing"); self.title.setObjectName("title")
        self.sub = QLabel("Pick a station"); self.sub.setObjectName("sub")
        self.song_l = QLabel(""); self.song_l.setObjectName("song"); self.song_l.setWordWrap(True)
        info.addWidget(self.title); info.addWidget(self.sub); info.addWidget(self.song_l)
        info.addStretch()
        ctr = QHBoxLayout(); ctr.setSpacing(10)
        self.btn_play = QPushButton("▶")
        self.btn_play.setObjectName("play")
        self.btn_play.setFixedSize(48, 48)
        self.btn_play.setToolTip("Play / Stop")
        self.btn_play.clicked.connect(self.toggle)
        ctr.addWidget(self.btn_play)

        self.btn_id = QPushButton("🔎")
        self.btn_id.setObjectName("icon")
        self.btn_id.setFixedSize(40, 40)
        self.btn_id.setToolTip("Identify song now")
        self.btn_id.clicked.connect(self.id_now)
        ctr.addWidget(self.btn_id)

        self.btn_lrc = QPushButton("📝")
        self.btn_lrc.setObjectName("icon")
        self.btn_lrc.setFixedSize(40, 40)
        self.btn_lrc.setToolTip("Fetch lyrics now")
        self.btn_lrc.clicked.connect(self.lyrics_now)
        ctr.addWidget(self.btn_lrc)

        self.btn_fav = QPushButton("♡")
        self.btn_fav.setObjectName("icon")
        self.btn_fav.setFixedSize(40, 40)
        self.btn_fav.setEnabled(False)
        self.btn_fav.setToolTip("Bookmark / remove bookmark")
        self.btn_fav.clicked.connect(self.toggle_fav)
        ctr.addWidget(self.btn_fav)

        self.btn_yt = QPushButton("▶︎")
        self.btn_yt.setObjectName("icon")
        self.btn_yt.setFixedSize(40, 40)
        self.btn_yt.setEnabled(False)
        self.btn_yt.setToolTip("YouTube")
        self.btn_yt.clicked.connect(self.open_yt)
        ctr.addWidget(self.btn_yt)

        ctr.addStretch()
        info.addLayout(ctr)
        hl.addLayout(info, 1)
        ml.addWidget(hero)

        # Tuner
        tun = QFrame(); tun.setObjectName("card")
        tl = QVBoxLayout(tun)
        tl.setContentsMargins(14, 12, 14, 12)
        tl.setSpacing(8)
        tr = QHBoxLayout()
        tr.addWidget(QLabel("Band"))
        self.band = QComboBox()
        self.band.addItem("All Bands")
        for b in BANDS: self.band.addItem(b[0])
        tr.addWidget(self.band, 1)
        tr.addWidget(QLabel("Mode"))
        self.mode = QComboBox(); self.mode.addItems(["wbfm", "fm", "am"])
        tr.addWidget(self.mode)
        tr.addWidget(QLabel("Gain"))
        self.gain = QDoubleSpinBox()
        self.gain.setRange(0, 49); self.gain.setDecimals(0)
        self.gain.setValue(float(self.cfg.get("gain", 35)))
        self.gain.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.gain.setFixedWidth(44)
        tr.addWidget(self.gain)
        tl.addLayout(tr)
        self.scale = FreqScale()
        self.scale.changed.connect(self.on_scale)
        self.scale.released.connect(lambda _v: self.commit_tune())
        tl.addWidget(self.scale)
        self.freq = QDoubleSpinBox()
        self.freq.setDecimals(1); self.freq.setSingleStep(0.1)
        self.freq.setRange(0.1, 1700); self.freq.setValue(106.4)
        self.freq.setSuffix(" MHz")
        self.freq.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.freq.valueChanged.connect(self.on_freq)
        self.freq.editingFinished.connect(lambda: self.on_freq(self.freq.value()))
        tl.addWidget(self.freq)
        ml.addWidget(tun)

        # Lyrics under tuner
        lyr_row = QHBoxLayout()
        self.lyrics_toggle = QPushButton("▾  Lyrics")
        self.lyrics_toggle.setObjectName("collapseBtn")
        self.lyrics_toggle.setCheckable(True)
        self.lyrics_toggle.setChecked(False)
        self.lyrics_toggle.setToolTip("Show / hide lyrics")
        self.lyrics_toggle.clicked.connect(self._toggle_lyrics_panel)
        lyr_row.addWidget(self.lyrics_toggle)
        lyr_row.addStretch()
        ml.addLayout(lyr_row)
        self.lyrics_panel = QFrame()
        self.lyrics_panel.setObjectName("card")
        self.lyrics_panel.setVisible(False)
        lp = QVBoxLayout(self.lyrics_panel)
        lp.setContentsMargins(12, 10, 12, 10)
        self.lyrics = QTextEdit()
        self.lyrics.setReadOnly(True)
        self.lyrics.setPlaceholderText("Lyrics appear here after ID or Lyrics Now")
        self.lyrics.setFixedHeight(150)
        lp.addWidget(self.lyrics)
        ml.addWidget(self.lyrics_panel)
        ml.addStretch(1)

        ml.addStretch()
        self.split.addWidget(mid)

        # --- Right ---
        right = QWidget()
        right.setMinimumWidth(220)
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(6)
        rh = QHBoxLayout()
        rh.setContentsMargins(0, 0, 0, 0)
        rh.setSpacing(4)
        rh.addStretch()
        self.btn_hide_right = HoverIcon("▸", "Hide side panel")
        self.btn_hide_right.clicked.connect(lambda: self.toggle_right(False))
        self.btn_auto_side = HoverIcon("🎵", "Auto Song ID")
        self.btn_auto_side.setCheckable(True)
        self.btn_auto_side.clicked.connect(self._toggle_auto_side)
        rh.addWidget(self.btn_auto_side)
        self.btn_theme_side = HoverIcon("☾", "Light / Dark")
        self.btn_theme_side.clicked.connect(self.toggle_theme)
        rh.addWidget(self.btn_theme_side)
        rh.addWidget(self.btn_hide_right)
        right.installEventFilter(self)
        rl.addLayout(rh)


        self.col_lib = Collapse("Library", False)
        tabs = QTabWidget()
        self.hist = QListWidget()
        self.hist.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.hist.itemDoubleClicked.connect(self.open_hist)
        tabs.addTab(self.hist, "History")
        self.fav_list = QListWidget()
        self.fav_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.fav_list.itemDoubleClicked.connect(self.open_fav)
        self.fav_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.fav_list.customContextMenuRequested.connect(self.fav_menu)
        tabs.addTab(self.fav_list, "Bookmarks")
        self.col_lib.body_l.addWidget(tabs)
        rl.addWidget(self.col_lib, 1)

        self.col_tools = Collapse("Tools", False)
        g = QGridLayout(); g.setSpacing(8)
        for i, (txt, slot, tip) in enumerate([
            ("SDR++", self.start_sdr, "Open SDR++"),
            ("Flights", self.start_flights, "ADS-B map"),
            ("Weather", self.start_wx, "SatDump"),
            ("AIS", self.start_ais, "Marine AIS"),
            ("Test", self.test_dongle, "rtl_test"),
            ("Stop", self.free_all, "Stop all SDR apps"),
        ]):
            b = QPushButton(txt); b.setObjectName("pill")
            b.setToolTip(tip); b.clicked.connect(slot)
            g.addWidget(b, i // 2, i % 2)
        self.col_tools.body_l.addLayout(g)
        rl.addWidget(self.col_tools)
        self.col_log = Collapse("Log", False)
        self.logv = QTextEdit(); self.logv.setReadOnly(True); self.logv.setFixedHeight(90)
        self.col_log.body_l.addWidget(self.logv)
        rl.addWidget(self.col_log)

        rl.addStretch(1)
        self.split.addWidget(right)

        self.split.setStretchFactor(0, 3)
        self.split.setStretchFactor(1, 5)
        self.split.setStretchFactor(2, 3)
        self.split.setSizes([360, 480, 260])


        
        # Band combo: text change + activated (user selection)
        try:
            self.band.currentTextChanged.disconnect()
        except Exception:
            pass
        try:
            self.band.activated.disconnect()
        except Exception:
            pass
        self.band.activated.connect(self.on_band)
        try:
            self.freq.valueChanged.disconnect()
        except Exception:
            pass
        self.freq.valueChanged.connect(self.on_freq)
        try:
            self.scale.changed.disconnect()
        except Exception:
            pass
        self.scale.changed.connect(self.on_scale)


        # Band: use activated only (fires on user choice every time)
        try:
            self.band.currentTextChanged.disconnect()
        except Exception:
            pass
        try:
            self.band.activated[str].disconnect()
        except Exception:
            pass
        try:
            self.band.activated[int].disconnect()
        except Exception:
            pass
        try:
            self.band.activated.disconnect()
        except Exception:
            pass
        self.band.activated.connect(self.on_band)
        self.freq.valueChanged.connect(self.on_freq)
        self.scale.changed.connect(self.on_scale)


        # Startup station
        su = self.cfg.get("startup")
        if isinstance(su, dict) and su.get("freq"):
            try:
                if su.get("cat") and su["cat"] in self.stations:
                    # select category
                    for i in range(self.cats.count()):
                        if self.cats.item(i).text() == su["cat"]:
                            self.cats.setCurrentRow(i)
                            break
                self.freq.setValue(float(su["freq"]))
                if su.get("mode"):
                    self.mode.setCurrentText(su["mode"])
            except Exception:
                pass

        self._wire_band()
        self.statusBar().showMessage("Ready")
        QToolTip.setFont(QFont("Sans", 10))
        if self.cats.count(): self.cats.setCurrentRow(0)
        self.on_band("FM")
        self.refresh_hist(); self.refresh_favs()

    def _style(self):
        if self.dark:
            self.setStyleSheet("""
                QMainWindow, QWidget { background:#000; color:#f5f5f7; font-size:13px; }
                QFrame#card { background:#1c1c1e; border:none; border-radius:16px; }
                QLabel#art { background:#2c2c2e; border-radius:12px; color:#636366; font-size:42px; }
                QLabel#title { font-size:22px; font-weight:700; }
                QLabel#sub { color:#8e8e93; font-size:12px; }
                QLabel#song { color:#30d158; font-size:13px; }
                QLabel#h { background: transparent; }
                QLabel#toast { background:#f5f5f7; color:#1d1d1f; border-radius:14px; padding:12px 16px; }
                QPushButton#play { background:#30d158; color:#000; border:none; border-radius:24px; font-size:18px; }
                QPushButton#icon {
                    background:#2c2c2e; color:#f5f5f7; border:none; border-radius:20px; font-size:15px;
                }
                QPushButton#icon:checked { background:#30d158; color:#000; }
                QPushButton#icon:disabled { color:#636366; }
                QPushButton#pill {
                    background:#2c2c2e; color:#f5f5f7; border:none; border-radius:14px; padding:10px;
                }
                QPushButton#collapseBtn {
                    background:transparent; border:none; text-align:left; font-weight:600; color:#8e8e93; padding:4px 0;
                }
                QListWidget { background: transparent; border: none; outline: none; }
                QListWidget::item { padding:9px 10px; border-radius:10px; }
                QListWidget::item:selected { background: #1b4332; color: #f0fff4; border-radius: 8px; }
                QListWidget::item:hover { background: rgba(0,0,0,0.04); border-radius: 8px; }
                QComboBox, QDoubleSpinBox {
                    background:#2c2c2e; border:none; border-radius:10px; padding:7px 10px; color:#f5f5f7;
                }
                QTextEdit { background:#2c2c2e; border:none; border-radius:12px; color:#f5f5f7; }
                QSplitter::handle { background:#2c2c2e; width:4px; border-radius:2px; }
                QTabBar::tab { color:#8e8e93; padding:8px 12px; }
                QTabBar::tab:selected { color:#f5f5f7; }
                
                QFrame#card {
                    background: #1c1c1e;
                    border: none;
                    border-radius: 14px;
                }
                QComboBox {
                    background: #2c2c2e;
                    border: none;
                    border-radius: 10px;
                    padding: 7px 12px;
                    color: #f5f5f7;
                }
                QComboBox::drop-down { border: none; width: 24px; }
                QDoubleSpinBox {
                    background: #2c2c2e;
                    border: none;
                    border-radius: 10px;
                    padding: 7px 12px;
                    color: #f5f5f7;
                }

                QStatusBar { color:#8e8e93; background:#000; }
                QToolTip {
                    background-color: #2c2c2e; color: #f5f5f7;
                    border: 1px solid #3a3a3c; border-radius: 8px;
                    padding: 6px 10px; font-size: 11px;
                }
                QScrollBar:vertical { width:0px; }
                QScrollBar:horizontal { height:0px; }
            """)
        else:
            self.setStyleSheet("""
                QMainWindow, QWidget { background:#f5f5f7; color:#1d1d1f; font-size:13px; }
                QFrame#card { background:#ffffff; border:none; border-radius:16px; }
                QLabel#art { background:#f2f2f7; border-radius:12px; color:#aeaeb2; font-size:42px; }
                QLabel#title { font-size:22px; font-weight:700; }
                QLabel#sub { color:#6e6e73; font-size:12px; }
                QLabel#song { color:#248a3d; font-size:13px; }
                QLabel#h { background: transparent; }
                QLabel#toast { background:#1d1d1f; color:#f5f5f7; border-radius:14px; padding:12px 16px; }
                QPushButton#play { background:#30d158; color:#fff; border:none; border-radius:24px; font-size:18px; }
                QPushButton#icon {
                    background:#f2f2f7; color:#1d1d1f; border:none; border-radius:20px; font-size:15px;
                }
                QPushButton#icon:checked { background:#30d158; color:#fff; }
                QPushButton#icon:disabled { color:#aeaeb2; }
                QPushButton#pill {
                    background:#f2f2f7; color:#1d1d1f; border:none; border-radius:14px; padding:10px;
                }
                QPushButton#collapseBtn {
                    background:transparent; border:none; text-align:left; font-weight:600; color:#6e6e73; padding:4px 0;
                }
                QListWidget { background: transparent; border: none; outline: none; }
                QListWidget::item { padding:9px 10px; border-radius:10px; }
                QListWidget::item:selected { background: #b7dfc0; color: #0d1f0d; border-radius: 8px; }
                QListWidget::item:hover { background: rgba(0,0,0,0.04); border-radius: 8px; }
                QComboBox, QDoubleSpinBox {
                    background:#f2f2f7; border:none; border-radius:10px; padding:7px 10px;
                }
                QTextEdit { background:#f2f2f7; border:none; border-radius:12px; }
                QSplitter::handle { background:#e5e5ea; width:4px; border-radius:2px; }
                QTabBar::tab { color:#6e6e73; padding:8px 12px; }
                QTabBar::tab:selected { color:#1d1d1f; }
                
                QFrame#card {
                    background: #ffffff;
                    border: none;
                    border-radius: 14px;
                }
                QComboBox {
                    background: #f2f2f7;
                    border: none;
                    border-radius: 10px;
                    padding: 7px 12px;
                    min-height: 18px;
                }
                QComboBox::drop-down { border: none; width: 24px; }
                QDoubleSpinBox {
                    background: #f2f2f7;
                    border: none;
                    border-radius: 10px;
                    padding: 7px 12px;
                }

                QStatusBar { color:#6e6e73; background:#f5f5f7; }
                QToolTip {
                    background-color: #1d1d1f; color: #f5f5f7;
                    border: none; border-radius: 8px;
                    padding: 6px 10px; font-size: 11px;
                }
                QScrollBar:vertical { width:0px; }
                QScrollBar:horizontal { height:0px; }
            """)

    def toggle_theme(self):
        self.dark = not self.dark
        icon = "☀" if self.dark else "☾"
        if hasattr(self, "btn_theme"):
            self.btn_theme.setText(icon)
        if hasattr(self, "btn_theme_side"):
            self.btn_theme_side.setText(icon)
        self.scale.dark = self.dark
        self._style()
        self.scale.update()


    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.toast.isVisible():
            self.toast.show_msg(self.toast.text(), 1000)

    def log(self, m):
        line = f"{datetime.now().strftime('%H:%M:%S')}  {m}"
        print(line); self.sig.log.emit(line)

    def _on_log(self, line):
        self.logv.append(line); self.logv.moveCursor(QTextCursor.End)

    # band / freq







    def _sync_band(self, f):
        name = band_for_freq(float(f))
        self._band_lock = True
        try:
            idx = self.band.findText(name)
            if idx < 0: idx = self.band.findText('All Bands')
            if idx >= 0 and self.band.currentIndex() != idx:
                self.band.blockSignals(True)
                self.band.setCurrentIndex(idx)
                self.band.blockSignals(False)
        finally:
            self._band_lock = False

    def _wire_band(self):
        try:
            self.band.activated.disconnect()
        except Exception:
            pass
        try:
            self.band.currentTextChanged.disconnect()
        except Exception:
            pass
        self.band.activated.connect(self.on_band)
        print("[WIRE] band.activated -> on_band", flush=True)

    def on_band(self, *args):
        if getattr(self, '_band_lock', False):
            return
        name = None
        if args:
            a0 = args[0]
            try:
                name = self.band.itemText(int(a0)) if not isinstance(a0, str) else str(a0)
            except Exception:
                name = str(a0)
        if not name:
            name = self.band.currentText()
        name = (name or "").strip()
        print('[BAND]', repr(name), flush=True)
        try:
            self.toast.show_msg("Band: " + name)
        except Exception:
            pass
        if not name or name == "All Bands":
            self.freq.blockSignals(True)
            self.freq.setRange(0.1, 1700.0)
            self.freq.blockSignals(False)
            try: self.scale.setRange(0.1, 1700.0)
            except Exception: pass
            return
        hit = None
        for n, lo, hi, mode in BANDS:
            if n == name:
                hit = (n, float(lo), float(hi), mode)
                break
        if not hit:
            print('[BAND] unknown', name, flush=True)
            return
        n, lo, hi, mode = hit
        mid = round(((lo + hi) / 2.0) * 10) / 10.0
        self._band_lock = True
        try:
            try: self.scale.setRange(lo, hi)
            except Exception: pass
            self.freq.blockSignals(True)
            self.freq.setRange(lo, hi)
            self.freq.setValue(mid)
            self.freq.blockSignals(False)
            try: self.scale.setValue(mid)
            except Exception: pass
            self.mode.blockSignals(True)
            ix = self.mode.findText(mode)
            if ix >= 0: self.mode.setCurrentIndex(ix)
            else: self.mode.setCurrentText(mode)
            self.mode.blockSignals(False)
        finally:
            self._band_lock = False
        self.log("Band → %s: %s MHz %s" % (n, mid, mode))
        try:
            self.play(mid, mode, "%s %.1f" % (n, mid))
        except Exception as ex:
            self.log(str(ex))

    def on_freq(self, v):
        """Spinbox moved — update UI only (no RF restart)."""
        v = float(v)
        try:
            self.scale.blockSignals(True)
            self.scale.setValue(v)
            self.scale.blockSignals(False)
        except Exception:
            pass
        m = mode_for_freq(v)
        if self.mode.currentText() != m:
            self.mode.blockSignals(True)
            self.mode.setCurrentText(m)
            self.mode.blockSignals(False)
        self._sync_band(v)

    def commit_tune(self):
        v = float(self.freq.value())
        m = self.mode.currentText() or mode_for_freq(v)
        try:
            self.play(v, m, "%.1f MHz" % v)
        except Exception as ex:
            self.log(str(ex))

    def on_scale(self, v):
        """Scale dragged — needle/spinbox only; RF after drag ends."""
        v = round(float(v), 1)
        self.freq.blockSignals(True)
        self.freq.setValue(v)
        self.freq.blockSignals(False)
        m = mode_for_freq(v)
        if self.mode.currentText() != m:
            self.mode.blockSignals(True)
            self.mode.setCurrentText(m)
            self.mode.blockSignals(False)
        self._sync_band(v)
        # short debounce only as fallback if mouseRelease not wired
        if not hasattr(self, "_tune_timer"):
            from PyQt5.QtCore import QTimer
            self._tune_timer = QTimer(self)
            self._tune_timer.setSingleShot(True)
            self._tune_timer.timeout.connect(self.commit_tune)
        self._tune_timer.start(180)


    def _retune_from_ui(self):
        if not getattr(self, "playing", False):
            return
        pair = getattr(self, "_pending_tune", None)
        if not pair:
            return
        v, m = pair
        try:
            self.play(v, m, f"{v:.1f} MHz")
        except Exception as ex:
            self.log(str(ex))


    def load_cat(self, cat):
        self.stations_list.blockSignals(True)
        self.stations_list.clear()
        if not cat or cat not in self.stations:
            self.stations_list.blockSignals(False); return
        for s in self.stations[cat]:
            if not isinstance(s, dict): continue
            name, freq = str(s.get("name", "?")), s.get("freq", 0)
            it = QListWidgetItem(f"{name}  ·  {freq}")
            it.setToolTip(f"{name}  ·  {freq} MHz  ·  {str(s.get('mode','')).upper()}")
            it.setData(Qt.UserRole, s)
            self.stations_list.addItem(it)
        self.stations_list.blockSignals(False)




    def stations_menu(self, pos):
        from PyQt5.QtWidgets import QMenu, QInputDialog, QMessageBox
        item = self.stations_list.itemAt(pos)
        cat_item = self.cats.currentItem()
        if not cat_item: return
        cat = cat_item.text()
        menu = QMenu(self)
        act_add = menu.addAction("Add station…")
        act_ren = menu.addAction("Rename…")
        act_del = menu.addAction("Remove")
        menu.addSeparator()
        act_freq = menu.addAction("Edit frequency…")
        act_mode = menu.addAction("Set mode…")
        menu.addSeparator()
        act_def = menu.addAction("Set as default startup")
        act_top = menu.addAction("Move to top")
        act_bot = menu.addAction("Move to bottom")
        for a in (act_ren, act_del, act_freq, act_mode, act_def, act_top, act_bot):
            a.setEnabled(item is not None)
        chosen = menu.exec_(self.stations_list.mapToGlobal(pos))
        if chosen is None: return
        if chosen == act_add:
            name, ok = QInputDialog.getText(self, "Add station", "Name:")
            if not ok or not name.strip(): return
            freq, ok = QInputDialog.getDouble(self, "Frequency", "MHz:", float(self.freq.value()), 0.1, 1700.0, 1)
            if not ok: return
            self.stations.setdefault(cat, []).append({"name": name.strip(), "freq": float(freq), "mode": mode_for_freq(freq)})
            save_json(STATIONS_F, self.stations); self.load_cat(cat)
            try: self.toast.show_msg("Added " + name.strip())
            except Exception: pass
            return
        s = item.data(Qt.UserRole) if item else None
        if not isinstance(s, dict): return
        def _match(st):
            return st.get("name") == s.get("name") and float(st.get("freq", 0)) == float(s.get("freq", 0))
        if chosen == act_ren:
            name, ok = QInputDialog.getText(self, "Rename", "Name:", text=s.get("name", ""))
            if not ok or not name.strip(): return
            for st in self.stations.get(cat, []):
                if _match(st): st["name"] = name.strip(); break
            save_json(STATIONS_F, self.stations); self.load_cat(cat)
        elif chosen == act_del:
            if QMessageBox.question(self, "Remove", "Remove " + str(s.get("name")) + "?") != QMessageBox.Yes: return
            self.stations[cat] = [st for st in self.stations.get(cat, []) if not _match(st)]
            save_json(STATIONS_F, self.stations); self.load_cat(cat)
        elif chosen == act_freq:
            freq, ok = QInputDialog.getDouble(self, "Frequency", "MHz:", float(s.get("freq", 100)), 0.1, 1700.0, 1)
            if not ok: return
            for st in self.stations.get(cat, []):
                if _match(st): st["freq"] = float(freq); st["mode"] = mode_for_freq(freq); break
            save_json(STATIONS_F, self.stations); self.load_cat(cat)
        elif chosen == act_mode:
            modes = ["wbfm", "fm", "am"]; cur = s.get("mode", "wbfm")
            mode, ok = QInputDialog.getItem(self, "Mode", "Mode:", modes, modes.index(cur) if cur in modes else 0, False)
            if not ok: return
            for st in self.stations.get(cat, []):
                if _match(st): st["mode"] = mode; break
            save_json(STATIONS_F, self.stations); self.load_cat(cat)
        elif chosen == act_def:
            self.cfg["startup"] = {"cat": cat, "name": s.get("name"), "freq": s.get("freq"), "mode": s.get("mode")}
            save_json(CONFIG, self.cfg)
            try: self.toast.show_msg("Default: " + str(s.get("name")))
            except Exception: pass
        elif chosen == act_top:
            lst = self.stations.get(cat, [])
            self.stations[cat] = [s] + [st for st in lst if not _match(st)]
            save_json(STATIONS_F, self.stations); self.load_cat(cat)
        elif chosen == act_bot:
            lst = self.stations.get(cat, [])
            self.stations[cat] = [st for st in lst if not _match(st)] + [s]
            save_json(STATIONS_F, self.stations); self.load_cat(cat)

    def _stations_reordered(self, *args):
        cat_item = self.cats.currentItem()
        if not cat_item: return
        cat = cat_item.text()
        if cat not in self.stations: return
        ordered = []
        for i in range(self.stations_list.count()):
            data = self.stations_list.item(i).data(Qt.UserRole)
            if isinstance(data, dict): ordered.append(data)
        if ordered:
            self.stations[cat] = ordered
            save_json(STATIONS_F, self.stations)

    def _finish_ui_hooks(self):
        self._wire_band()
        try: self.band.activated.disconnect()
        except Exception: pass
        try: self.band.currentTextChanged.disconnect()
        except Exception: pass
        self.band.activated.connect(self.on_band)
        try: self.freq.valueChanged.disconnect()
        except Exception: pass
        self.freq.valueChanged.connect(self.on_freq)
        try: self.scale.changed.disconnect()
        except Exception: pass
        self.scale.changed.connect(self.on_scale)
        self.log("Band items: " + ", ".join(self.band.itemText(i) for i in range(self.band.count())))
        su = self.cfg.get("startup") if isinstance(getattr(self, "cfg", None), dict) else None
        if isinstance(su, dict) and su.get("freq") is not None:
            cat = su.get("cat")
            if cat and cat in self.stations:
                for i in range(self.cats.count()):
                    if self.cats.item(i).text() == cat:
                        self.cats.setCurrentRow(i); break
            try:
                freq = float(su["freq"])
                mode = su.get("mode") or mode_for_freq(freq)
                self.freq.blockSignals(True); self.freq.setValue(freq); self.freq.blockSignals(False)
                self.scale.setValue(freq)
                self.mode.blockSignals(True)
                mi = self.mode.findText(mode)
                if mi >= 0: self.mode.setCurrentIndex(mi)
                self.mode.blockSignals(False)
                for i in range(self.stations_list.count()):
                    data = self.stations_list.item(i).data(Qt.UserRole)
                    if isinstance(data, dict) and data.get("name") == su.get("name"):
                        self.stations_list.setCurrentRow(i); break
                self.log("Startup: " + str(su.get("name")) + f" {freq} MHz")
            except Exception as ex:
                self.log("Startup: " + str(ex))

    def play_item(self, item):
        s = item.data(Qt.UserRole)
        if not s:
            return
        freq = float(s.get("freq", 0))
        mode = s.get("mode") or mode_for_freq(freq)
        name = s.get("name") or ("%.1f" % freq)
        self.freq.blockSignals(True)
        self.freq.setValue(freq)
        self.freq.blockSignals(False)
        try:
            self.scale.setValue(freq)
        except Exception:
            pass
        self.mode.blockSignals(True)
        self.mode.setCurrentText(mode)
        self.mode.blockSignals(False)
        try:
            self._sync_band(freq)
        except Exception:
            pass
        self.play(freq, mode, name)

    def clear_song(self):
        self.song = None; self.genius_url = None
        self.song_l.setText("")
        self.btn_fav.setEnabled(False); self.btn_fav.setText("♡")
        self.btn_yt.setEnabled(False); pass  # genius removed
        self.art.setPixmap(QPixmap()); self.art.setText("♪")
        self.lyrics.setPlainText(""); self.lrc = []; self.lrc_timer.stop()

    def set_playing(self, on, name="", detail=""):
        self.playing = on
        if on:
            self.btn_play.setText("⏹"); self.title.setText(name or "Playing"); self.sub.setText(detail)
        else:
            self.btn_play.setText("▶"); self.title.setText("Not playing"); self.sub.setText("Pick a station")
            self.clear_song()


    def _kill_audio(self):
        import subprocess, os, signal
        proc = getattr(self, "rtl", None)
        if proc is not None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            try:
                proc.wait(timeout=0.5)
            except Exception:
                pass
            self.rtl = None
        subprocess.run(
            ["killall", "-9", "rtl_fm", "play"],
            stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        )

    def stop(self):
        try:
            self.stop_id()
        except Exception:
            pass
        self._kill_audio()
        try:
            self.set_playing(False)
        except Exception:
            self.playing = False


    def toggle(self):
        if self.playing: self.stop()
        else: self.play(self.freq.value(), self.mode.currentText(), f"{self.freq.value():.1f} MHz")

    def play(self, freq, mode, name=""):
        import subprocess, time
        self._kill_audio()
        time.sleep(0.25)
        try:
            self.stop_id()
        except Exception:
            pass
        try:
            self.clear_song()
        except Exception:
            pass
        gain = int(self.gain.value()) if hasattr(self, "gain") else 35
        try:
            self.cfg["gain"] = gain
            save_json(CONFIG, self.cfg)
        except Exception:
            pass
        hz = int(round(float(freq) * 1e6))
        mode = (mode or "wbfm").lower().strip()
        detail = "%.3f MHz · %s · gain %s" % (float(freq), mode.upper(), gain)
        self.playing = True
        try:
            self.set_playing(True, name or ("%.1f MHz" % float(freq)), detail)
        except Exception:
            pass
        self.log("▶ %s · %s" % (name, detail))
        if mode == "wbfm":
            cmd = "rtl_fm -f %d -M wbfm -g %d -s 170k -A fast -r 32000 -l 0 -E deemp - | play -r 32000 -t raw -e signed -b 16 -c 1 -" % (hz, gain)
        elif mode == "am":
            cmd = "rtl_fm -f %d -M am -g %d -s 12000 -r 12000 -l 0 - | play -r 12000 -t raw -e signed -b 16 -c 1 -" % (hz, gain)
        else:
            cmd = "rtl_fm -f %d -M fm -g %d -s 22050 -r 22050 -l 0 - | play -r 22050 -t raw -e signed -b 16 -c 1 -" % (hz, gain)
        self.log("CMD: " + cmd[:100])
        try:
            self.rtl = subprocess.Popen(cmd, shell=True, start_new_session=True)
            self.log("rtl pid %s" % self.rtl.pid)
        except Exception as e:
            self.log("play error: " + str(e))
            self.playing = False
            return
        if bool(getattr(self, "cfg", {}).get("song_id", True)):
            try:
                self.start_id()
            except Exception:
                pass

    def _toggle_auto_side(self):
        on = not bool(self.cfg.get("song_id", True))
        self.cfg["song_id"] = on
        save_json(CONFIG, self.cfg)
        if hasattr(self, "btn_auto_side"):
            self.btn_auto_side.setChecked(on)
        if hasattr(self, "btn_auto"):
            self.btn_auto.blockSignals(True)
            self.btn_auto.setChecked(on)
            self.btn_auto.blockSignals(False)
        self.on_auto(on)
        self.toast.show_msg("Auto Song ID " + ("on" if on else "off"))

    def on_auto(self, on):
        self.cfg["song_id"] = on; save_json(CONFIG, self.cfg)
        if on and self.playing: self.start_id()
        else: self.stop_id()

    def _ensure_aio(self):
        if self.aio_loop and self.aio_thread and self.aio_thread.is_alive(): return
        self.aio_loop = asyncio.new_event_loop()
        def run(loop):
            asyncio.set_event_loop(loop); loop.run_forever()
        self.aio_thread = threading.Thread(target=run, args=(self.aio_loop,), daemon=True)
        self.aio_thread.start()

    def _submit(self, coro):
        self._ensure_aio()
        return asyncio.run_coroutine_threadsafe(coro, self.aio_loop)

    def start_id(self):
        if not self.playing: return
        if self.id_thread and self.id_thread.is_alive(): return
        self.id_stop.clear()
        self.id_thread = threading.Thread(target=self._id_loop, daemon=True)
        self.id_thread.start()

    def stop_id(self):
        self.id_stop.set(); self.id_thread = None

    def _id_loop(self):
        for _ in range(12):
            if self.id_stop.is_set() or not self.playing: return
            time.sleep(1)
        while not self.id_stop.is_set() and self.playing:
            if not self.id_busy:
                try: self._submit(self._identify())
                except Exception: pass
            for _ in range(45):
                if self.id_stop.is_set() or not self.playing: return
                time.sleep(1)

    def id_now(self):
        if not self.playing: self.toast.show_msg("Play a station first"); return
        if self.id_busy: self.toast.show_msg("Already identifying…"); return
        try: self._submit(self._identify())
        except Exception as e: self.log(str(e))

    async def _identify(self):
        if self.id_busy: return
        self.id_busy = True
        try:
            self.sig.status.emit("Listening…")
            wav = str(SNIP / "sdr_song_id.wav")
            ok = await asyncio.to_thread(self.capture, wav, 12)
            if not ok: self.sig.status.emit("Capture failed"); return
            song = await asyncio.to_thread(self.songrec, wav)
            if not song and self.ac_key:
                song = await asyncio.to_thread(self.acoustid, wav)
            if song: self.sig.result.emit(song)
            else: self.sig.status.emit("No match")
        except Exception as e:
            self.sig.status.emit(str(e))
        finally:
            self.id_busy = False

    def capture(self, path, sec=12):
        try: Path(path).unlink(missing_ok=True)
        except Exception: pass
        tries = []
        try:
            r = subprocess.run(["pactl", "get-default-sink"], capture_output=True, text=True, timeout=2)
            sink = (r.stdout or "").strip()
            if sink:
                tries.append(["ffmpeg","-y","-f","pulse","-i",f"{sink}.monitor","-t",str(sec),"-ac","1","-ar","44100",path])
        except Exception: pass
        tries.append(["ffmpeg","-y","-f","pulse","-i","default","-t",str(sec),"-ac","1","-ar","44100",path])
        for cmd in tries:
            try:
                r = subprocess.run(cmd, capture_output=True, timeout=sec+6)
                if r.returncode == 0 and Path(path).exists() and Path(path).stat().st_size > 2000:
                    return True
            except Exception: continue
        return False

    def songrec(self, wav):
        for b in ("/snap/bin/songrec", "songrec"):
            if b == "songrec" or Path(b).exists():
                bin_ = b; break
        else: return None
        try:
            r = subprocess.run([bin_, "recognize", wav], capture_output=True, text=True, timeout=30)
            out = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()
            for line in out.splitlines():
                if " - " in line and "error" not in line.lower() and len(line) < 160:
                    a, t = line.split(" - ", 1)
                    return {"title": t.strip(), "artist": a.strip(), "album": "",
                            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        except Exception: return None
        return None

    def acoustid(self, wav):
        try:
            r = subprocess.run(["fpcalc", "-json", wav], capture_output=True, text=True, timeout=15)
            if r.returncode != 0: return None
            data = json.loads(r.stdout)
            fp, dur = data.get("fingerprint"), data.get("duration")
            if not fp: return None
            post = urllib.parse.urlencode({
                "client": self.ac_key.strip(), "meta": "recordings releasegroups compress",
                "duration": int(float(dur)), "fingerprint": fp,
            }).encode()
            req = urllib.request.Request("https://api.acoustid.org/v2/lookup", data=post,
                headers={"User-Agent": "SDR-Radio/1.0", "Content-Type": "application/x-www-form-urlencoded"}, method="POST")
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read().decode())
            if result.get("status") != "ok" or not result.get("results"): return None
            best = result["results"][0]
            if best.get("score", 0) < 0.25: return None
            recs = best.get("recordings") or []
            if not recs: return None
            rec = recs[0]
            title = rec.get("title") or "?"
            artists = ", ".join(a.get("name","") for a in rec.get("artists", [])) or "?"
            album = (rec.get("releasegroups") or [{}])[0].get("title", "") if rec.get("releasegroups") else ""
            return {"title": title, "artist": artists, "album": album,
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        except Exception: return None

    def on_status(self, msg):
        if not self.song: self.song_l.setText(msg)
        self.log(f"🎵 {msg}")

    def on_result(self, song):
        if song_match(song, self.song):
            self.log("♪ Same song — refreshing lyrics")
            threading.Thread(target=self._post, args=(song,), daemon=True).start()
            return
        self.song = song
        text = f"{song.get('artist','')} — {song.get('title','')}"
        self.song_l.setText(text)
        self.btn_fav.setEnabled(True)
        self.btn_yt.setEnabled(True)
        pass  # genius removed
        self.btn_fav.setText("♥" if self._is_fav(song) else "♡")
        self.log(f"♪ {text}"); self.toast.show_msg(f"♪  {text}")
        self.history.insert(0, song); self.history = self.history[:100]
        save_json(HIST_F, self.history); self.refresh_hist()
        threading.Thread(target=self._post, args=(song,), daemon=True).start()


    def _post(self, song):
        """Album art + lyrics always after any successful ID."""
        try:
            path = self.fetch_art(song.get("artist", ""), song.get("title", ""))
            if path:
                self.sig.art.emit(path)
        except Exception as e:
            self.log(f"Art: {e}")
        try:
            text = self.fetch_lrc(song.get("artist", ""), song.get("title", ""))
            if not text and getattr(self, "gn_key", ""):
                try:
                    import lyricsgenius
                    g = lyricsgenius.Genius(self.gn_key, verbose=False, remove_section_headers=True, timeout=12)
                    s = g.search_song(song.get("title", ""), song.get("artist", ""))
                    if s and s.lyrics:
                        lines = s.lyrics.splitlines()
                        text = "\n".join(lines[1:]).strip() if lines and "lyrics" in lines[0].lower() else s.lyrics.strip()
                except Exception:
                    pass
            self.sig.lyrics.emit(text or "No lyrics found.")
        except Exception as e:
            self.sig.lyrics.emit("No lyrics found.")
            self.log(f"Lyrics: {e}")
        try:
            meta = self.fetch_gn_meta(song.get("artist", ""), song.get("title", ""))
            if meta and meta.get("url"):
                self.genius_url = meta["url"]
        except Exception:
            pass



    def on_lyrics(self, text):
        self.lyrics.setPlainText(text or "")
        if text and not text.startswith("No lyrics") and not text.startswith("Loading"):
            if hasattr(self, "lyrics_toggle"):
                self.lyrics_toggle.setChecked(True)
                self._toggle_lyrics_panel()
            if getattr(self, "lrc", None):
                self.lrc_t0 = time.time()
                self.lrc_timer.start(400)


    def _tick_lrc(self):
        if not self.lrc or self.lrc_t0 is None: return
        el = time.time() - self.lrc_t0
        idx = 0
        for i, (ts, _) in enumerate(self.lrc):
            if ts <= el: idx = i
        new = "\n".join(f"{'▶ ' if i==idx else '  '}{ln}" for i, (_, ln) in enumerate(self.lrc))
        if self.lyrics.toPlainText() != new: self.lyrics.setPlainText(new)

    def fetch_art(self, artist, title):
        ART.mkdir(parents=True, exist_ok=True)
        dest = ART / "current.jpg"
        urls = []
        for url_build in [
            lambda: self._itunes(artist, title),
            lambda: self._deezer(artist, title),
        ]:
            try:
                u = url_build()
                if u: urls.append(u)
            except Exception: pass
        for u in urls:
            try:
                req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0 SDR-Radio/1.0"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    dest.write_bytes(resp.read())
                if dest.exists() and dest.stat().st_size > 800:
                    self.log(f"🖼 Art OK ({dest.stat().st_size} B)")
                    return str(dest)
            except Exception as e:
                self.log(f"Art fail: {e}")
        self.log("🖼 No album art")
        return None

    def _itunes(self, artist, title):
        q = urllib.parse.quote(f"{artist} {title}")
        req = urllib.request.Request(f"https://itunes.apple.com/search?term={q}&entity=song&limit=1",
                                     headers={"User-Agent": "SDR-Radio/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
        if data.get("results"):
            u = data["results"][0].get("artworkUrl100") or ""
            return u.replace("100x100bb", "600x600bb") if u else None
        return None

    def _deezer(self, artist, title):
        q = urllib.parse.quote(f"{artist} {title}")
        req = urllib.request.Request(f"https://api.deezer.com/search?q={q}&limit=1",
                                     headers={"User-Agent": "SDR-Radio/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
        if data.get("data"):
            alb = data["data"][0].get("album") or {}
            return alb.get("cover_xl") or alb.get("cover_big")
        return None

    def show_art(self, path):
        try:
            pix = QPixmap(path)
            if pix.isNull():
                self.art.setText("♪"); return
            pix = pix.scaled(132, 132, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            if pix.width() >= 132 and pix.height() >= 132:
                pix = pix.copy((pix.width()-132)//2, (pix.height()-132)//2, 132, 132)
            self.art.setPixmap(pix)
        except Exception:
            self.art.setText("♪")

    def fetch_lrc(self, artist, title):
        try:
            q = urllib.parse.urlencode({"track_name": title, "artist_name": artist})
            req = urllib.request.Request(f"https://lrclib.net/api/search?{q}",
                                         headers={"User-Agent": "SDR-Radio/1.0"})
            with urllib.request.urlopen(req, timeout=12) as resp:
                results = json.loads(resp.read().decode())
            if not results:
                q2 = urllib.parse.urlencode({"q": f"{artist} {title}"})
                req2 = urllib.request.Request(f"https://lrclib.net/api/search?{q2}",
                                             headers={"User-Agent": "SDR-Radio/1.0"})
                with urllib.request.urlopen(req2, timeout=12) as resp2:
                    results = json.loads(resp2.read().decode())
            if not results:
                self.log("LRCLIB: no results")
                return ""
            best = results[0]
            plain = (best.get("plainLyrics") or "").strip()
            synced = (best.get("syncedLyrics") or "").strip()
            self.log(f"LRCLIB: hit {best.get('trackName','?')} / {best.get('artistName','?')}")
            if synced:
                parsed = []
                for ln in synced.splitlines():
                    m = re.match(r"\[(\d{1,2}):(\d{2})(?:\.(\d+))?\]\s*(.*)", ln.strip())
                    if m and m.group(4).strip():
                        ts = int(m.group(1))*60 + int(m.group(2)) + float("0."+(m.group(3) or "0"))
                        parsed.append((ts, m.group(4).strip()))
                self.lrc = parsed
                return "\n".join(x[1] for x in parsed) or plain
            self.lrc = []; return plain
        except Exception:
            self.lrc = []; return ""

    def fetch_gn_meta(self, artist, title):
        if not self.gn_key: return None
        try:
            q = urllib.parse.quote(f"{artist} {title}")
            req = urllib.request.Request(f"https://api.genius.com/search?q={q}",
                headers={"Authorization": f"Bearer {self.gn_key}", "User-Agent": "SDR-Radio/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
            hits = (data.get("response") or {}).get("hits") or []
            if hits: return {"url": hits[0]["result"].get("url", "")}
        except Exception: return None
        return None

    def open_yt(self):
        if not self.song: return
        q = f"{self.song.get('artist','')} {self.song.get('title','')}"
        QDesktopServices.openUrl(QUrl("https://www.youtube.com/results?search_query=" + urllib.parse.quote(q)))

    def open_gn(self):
        url = self.genius_url
        if not url and self.song:
            meta = self.fetch_gn_meta(self.song.get("artist",""), self.song.get("title",""))
            url = (meta or {}).get("url")
        if url: QDesktopServices.openUrl(QUrl(url))

    def _is_fav(self, song):
        k = (_norm(song.get("title")), _norm(song.get("artist")))
        return any((_norm(s.get("title")), _norm(s.get("artist"))) == k for s in self.favs)

    def toggle_fav(self):
        if not self.song: return
        k = (_norm(self.song.get("title")), _norm(self.song.get("artist")))
        if self._is_fav(self.song):
            self.favs = [s for s in self.favs if (_norm(s.get("title")), _norm(s.get("artist"))) != k]
            self.btn_fav.setText("♡")
            self.toast.show_msg("Removed bookmark")
        else:
            self.favs.insert(0, self.song)
            self.favs = self.favs[:50]
            self.btn_fav.setText("♥")
            self.toast.show_msg("Bookmarked")
        save_json(FAV_F, self.favs)
        self.refresh_favs()
        self._finish_ui_hooks()

    def fav_menu(self, pos):
        from PyQt5.QtWidgets import QMenu
        item = self.fav_list.itemAt(pos)
        if not item: return
        m = QMenu(self)
        m.addAction("Remove", lambda: self._remove_fav_item(item))
        m.exec_(self.fav_list.mapToGlobal(pos))

    def _remove_fav_item(self, item):
        s = item.data(Qt.UserRole)
        if not s: return
        k = (_norm(s.get("title")), _norm(s.get("artist")))
        self.favs = [x for x in self.favs if (_norm(x.get("title")), _norm(x.get("artist"))) != k]
        save_json(FAV_F, self.favs)
        self.refresh_favs()
        if self.song and song_match(self.song, s):
            self.btn_fav.setText("♡")
        self.toast.show_msg("Removed bookmark")


    def refresh_hist(self):
        self.hist.clear()
        self.hist.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.hist.setTextElideMode(Qt.ElideRight)
        self.hist.setSpacing(2)
        for s in self.history:
            artist = s.get("artist") or "?"
            title = s.get("title") or "?"
            it = QListWidgetItem(f"{title}  ·  {artist}")
            it.setToolTip(f"{artist} — {title}")
            it.setData(Qt.UserRole, s)
            self.hist.addItem(it)

    def refresh_favs(self):
        self.fav_list.clear()
        self.fav_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.fav_list.setTextElideMode(Qt.ElideRight)
        self.fav_list.setSpacing(2)
        for s in self.favs:
            artist = s.get("artist") or "?"
            title = s.get("title") or "?"
            it = QListWidgetItem(f"{title}  ·  {artist}")
            it.setToolTip(f"{artist} — {title}\nRight-click to remove")
            it.setData(Qt.UserRole, s)
            self.fav_list.addItem(it)


    def open_hist(self, item):
        s = item.data(Qt.UserRole)
        if not s:
            idx = self.hist.row(item)
            if 0 <= idx < len(self.history):
                s = self.history[idx]
        if not s:
            return
        self.song = s
        self.song_l.setText(f"{s.get('artist')} — {s.get('title')}")
        self.btn_fav.setEnabled(True)
        self.btn_yt.setEnabled(True)
        self.btn_fav.setText("♥" if self._is_fav(s) else "♡")


    def open_fav(self, item):
        s = item.data(Qt.UserRole)
        if s:
            self.song = s
            self.song_l.setText(f"{s.get('artist')} — {s.get('title')}")
            self.btn_fav.setEnabled(True); self.btn_yt.setEnabled(True); pass  # genius removed
            self.btn_fav.setText("♥")


    def _toggle_lyrics_panel(self):
        """Open/close lyrics in a fixed-height slot so the player card does not move."""
        show = self.lyrics_toggle.isChecked()
        self.lyrics_toggle.setText(("▾  Lyrics" if show else "▸  Lyrics"))
        # Fixed slot: always reserves 0 or LYRICS_H — stretch below absorbs the delta
        LYRICS_H = 168
        if show:
            self.lyrics_panel.setVisible(True)
            self.lyrics_panel.setMinimumHeight(LYRICS_H)
            self.lyrics_panel.setMaximumHeight(LYRICS_H)
        else:
            self.lyrics_panel.setVisible(False)
            self.lyrics_panel.setMinimumHeight(0)
            self.lyrics_panel.setMaximumHeight(0)

    def lyrics_now(self):

        """Force-fetch lyrics for current song (or last identified)."""
        if not self.song:
            self.toast.show_msg("Identify a song first")
            return
        self.toast.show_msg("Fetching lyrics…")
        self.lyrics.setPlainText("Loading lyrics…")
        self.lyrics_toggle.setChecked(True)
        self._toggle_lyrics_panel()
        def task():
            artist = self.song.get("artist", "")
            title = self.song.get("title", "")
            text = self.fetch_lrc(artist, title)
            if not text and self.gn_key:
                try:
                    import lyricsgenius
                    g = lyricsgenius.Genius(self.gn_key, verbose=False, remove_section_headers=True, timeout=15)
                    song = g.search_song(title, artist)
                    if song and song.lyrics:
                        lines = song.lyrics.splitlines()
                        text = "\n".join(lines[1:]).strip() if lines and "lyrics" in lines[0].lower() else song.lyrics.strip()
                        if text:
                            text += "\n\n— Genius"
                except Exception as e:
                    self.log(f"Genius lyrics: {e}")
            if not text:
                # broader LRCLIB search
                try:
                    q = urllib.parse.urlencode({"q": f"{artist} {title}"})
                    req = urllib.request.Request(
                        f"https://lrclib.net/api/search?{q}",
                        headers={"User-Agent": "SDR-Radio/1.0"},
                    )
                    with urllib.request.urlopen(req, timeout=12) as resp:
                        results = json.loads(resp.read().decode())
                    if results:
                        best = results[0]
                        text = (best.get("plainLyrics") or best.get("syncedLyrics") or "").strip()
                        if text and "[" in text[:20]:
                            # strip LRC tags
                            text = re.sub(r"\[\d{1,2}:\d{2}(?:\.\d+)?\]", "", text)
                            text = "\n".join(ln.strip() for ln in text.splitlines() if ln.strip())
                except Exception as e:
                    self.log(f"LRCLIB q-search: {e}")
            self.sig.lyrics.emit(text or "No lyrics found.")
            if text:
                QTimer.singleShot(0, lambda: self.toast.show_msg("Lyrics loaded"))
            else:
                QTimer.singleShot(0, lambda: self.toast.show_msg("No lyrics found"))
        threading.Thread(target=task, daemon=True).start()





    def eventFilter(self, obj, ev):
        from PyQt5.QtCore import QEvent
        left = self.split.widget(0) if hasattr(self, "split") else None
        right = self.split.widget(2) if hasattr(self, "split") else None
        if left is not None and obj is left:
            if ev.type() == QEvent.Enter:
                if hasattr(self, "btn_hide_left"):
                    self.btn_hide_left.fade(True)
            elif ev.type() == QEvent.Leave:
                if hasattr(self, "btn_hide_left"):
                    self.btn_hide_left.fade(False)
        if right is not None and obj is right:
            icons = ("btn_hide_right", "btn_auto_side", "btn_theme_side")
            if ev.type() == QEvent.Enter:
                for b in icons:
                    if hasattr(self, b):
                        getattr(self, b).fade(True)
            elif ev.type() == QEvent.Leave:
                for b in icons:
                    if hasattr(self, b):
                        getattr(self, b).fade(False)
        return super().eventFilter(obj, ev)


    def toggle_left(self, on=None):
        left = self.split.widget(0)
        if left is None:
            return
        if on is None:
            on = not left.isVisible()
        left.setVisible(bool(on))
        if hasattr(self, "btn_show_left"):
            self.btn_show_left.setVisible(not on)
        if hasattr(self, "btn_hide_left"):
            self.btn_hide_left.setVisible(bool(on))
        self._redistribute()

    def toggle_right(self, on=None):
        right = self.split.widget(2)
        if right is None:
            return
        if on is None:
            on = not right.isVisible()
        right.setVisible(bool(on))
        if hasattr(self, "btn_show_right"):
            self.btn_show_right.setVisible(not on)
        if hasattr(self, "btn_hide_right"):
            self.btn_hide_right.setVisible(bool(on))
        self._redistribute()

    def _redistribute(self):
        try:
            total = max(400, self.split.width())
            left = self.split.widget(0)
            right = self.split.widget(2)
            left_on = left is not None and left.isVisible()
            right_on = right is not None and right.isVisible()
            if left_on and right_on:
                self.split.setSizes([int(total * 0.32), int(total * 0.46), int(total * 0.22)])
            elif left_on:
                self.split.setSizes([int(total * 0.36), int(total * 0.64), 0])
            elif right_on:
                self.split.setSizes([0, int(total * 0.70), int(total * 0.30)])
            else:
                self.split.setSizes([0, total, 0])
        except Exception as e:
            self.log(f"split: {e}")


    def start_sdr(self):
        self.stop()
        subprocess.Popen(["sdrpp"])
        self.toast.show_msg("SDR++ launched")
    def start_flights(self):
        self.stop()
        subprocess.run(["sudo","mkdir","-p","/run/readsb"])
        subprocess.run(["sudo","chmod","777","/run/readsb"])
        subprocess.run(["sudo","systemctl","restart","readsb"]); time.sleep(1.2)
        subprocess.Popen(["xdg-open","http://localhost/tar1090/"])
        self.toast.show_msg("Flights opened in browser")
    def start_wx(self):
        self.stop()
        subprocess.Popen(["satdump-ui"])
        self.toast.show_msg("Weather (SatDump) launched")
    def start_ais(self):
        self.stop()
        threading.Thread(target=lambda: subprocess.Popen(
            ["AIS-catcher","-d","00000001","-s","1536k","-a","33","-N","8100"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL), daemon=True).start()
        threading.Thread(target=lambda: (time.sleep(2), subprocess.Popen(
            ["xdg-open","http://localhost:8100/?lat=17.385&lon=78.4867&zoom=7&tab=map"])), daemon=True).start()
        self.toast.show_msg("AIS map opening in browser")
    def test_dongle(self):
        def task():
            proc = subprocess.Popen(["timeout","4","rtl_test","-t"],
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for line in proc.stdout:
                if line.strip(): self.log(line.rstrip())
        threading.Thread(target=task, daemon=True).start()
    def free_all(self):
        self.stop()
        subprocess.run(["sudo","systemctl","stop","readsb"], stderr=subprocess.DEVNULL)
        subprocess.run(["killall","-9","sdrpp","satdump","satdump-ui","AIS-catcher"], stderr=subprocess.DEVNULL)
        self.toast.show_msg("All SDR processes stopped")

    def closeEvent(self, e):
        try:
            self.stop_id()
        except Exception:
            pass
        self._kill_audio()
        try:
            if getattr(self, "aio_loop", None):
                self.aio_loop.call_soon_threadsafe(self.aio_loop.stop)
        except Exception:
            pass
        e.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("SDR Radio")
    app.setDesktopFileName("sdr-control")
    app.setStyle("Fusion")
    w = App(); w.show()
    def cleanup():
        subprocess.run(["killall", "-9", "rtl_fm", "play", "aplay", "paplay"],
                       stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
        LOCK.unlink(missing_ok=True)
    app.aboutToQuit.connect(cleanup)
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
