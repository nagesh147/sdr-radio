#!/usr/bin/env python3
"""SDR Radio — clean modern UI with Lucide icons."""
from __future__ import annotations

import sys, os, subprocess, threading, time, json, asyncio, re
import urllib.parse, urllib.request
from datetime import datetime
from pathlib import Path
from difflib import SequenceMatcher

BASE = Path.home() / "SDR-Tools"
ICONS = BASE / "icons"
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
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def acquire_single_instance_lock():
    """Only used at process start (main). Safe to re-import the file for in-process reload."""
    force = os.environ.pop("SDR_FORCE_START", "") == "1"
    if force:
        try:
            LOCK.unlink(missing_ok=True)
        except Exception:
            pass
    elif LOCK.exists():
        try:
            o = int(LOCK.read_text().strip())
            # Same PID is fine (e.g. re-exec); only block a different live process
            if o != os.getpid() and _alive(o):
                sys.exit(0)
            LOCK.unlink(missing_ok=True)
        except Exception:
            try:
                LOCK.unlink(missing_ok=True)
            except Exception:
                pass
    try:
        LOCK.write_text(str(os.getpid()))
    except Exception:
        pass


from PyQt5.QtWidgets import (
    QMessageBox, QInputDialog, QMenu, QAbstractItemView,
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QTextEdit, QFrame, QGridLayout, QComboBox, QListWidget, QListWidgetItem,
    QDoubleSpinBox, QTabWidget, QSplitter, QSizePolicy, QAbstractSpinBox, QToolTip,
    QShortcut, QAction,
)
from PyQt5.QtCore import Qt, pyqtSignal, QObject, QTimer, QUrl, QSize
from PyQt5.QtGui import QTextCursor, QPainter, QColor, QPen, QFont, QPixmap, QDesktopServices, QCursor, QIcon, QKeySequence

def load_icon(name: str) -> QIcon:
    p = ICONS / f"{name}.png"
    if p.exists():
        return QIcon(str(p))
    return QIcon()

DEFAULT_STATIONS = {
    "Internet": [
        {"name": "Radio Mirchi Online", "url": "https://playerservices.streamtheworld.com/api/livestream-redirect/MIR_HIN_BACCYC.mp3", "mode": "net"},
        {"name": "BBC World Service", "url": "https://stream.live.vc.bbcmedia.co.uk/bbc_world_service", "mode": "net"},
        {"name": "NPR News", "url": "https://npr-ice.streamguys1.com/live.mp3", "mode": "net"},
        {"name": "Lofi Hip Hop", "url": "https://streams.ilovemusic.de/iloveradio17.mp3", "mode": "net"},
        {"name": "SomaFM Groove Salad", "url": "https://ice2.somafm.com/groovesalad-128-mp3", "mode": "net"},
    ],

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
        if a <= f <= b:
            return m
    return "wbfm" if 88 <= f <= 108 else ("am" if f < 30 else "fm")

def band_for_freq(f):
    for n, a, b, _ in BANDS:
        if a <= f <= b:
            return n
    return "All Bands"

def _norm(s):
    s = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", (s or "").lower())
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def song_match(a, b, th=0.82):
    if not a or not b:
        return False
    aa, at = _norm(a.get("artist")), _norm(a.get("title"))
    ba, bt = _norm(b.get("artist")), _norm(b.get("title"))
    if not at or not bt:
        return False
    if at == bt and (not aa or not ba or aa == ba or aa in ba or ba in aa):
        return True
    return SequenceMatcher(None, at, bt).ratio() >= th and (
        SequenceMatcher(None, aa, ba).ratio() if aa and ba else 0.9) >= 0.55

def load_json(path, default):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
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
    art = pyqtSignal(str)
    net_list = pyqtSignal(list, str)  # stations, category_or_msg


class Toast(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("toast")
        self.setWordWrap(True)
        self.hide()
        self._t = QTimer(self)
        self._t.setSingleShot(True)
        self._t.timeout.connect(self.hide)

    def show_msg(self, text, ms=3000):
        self.setText(text)
        self.adjustSize()
        self.setFixedWidth(min(320, max(180, (self.parent().width() if self.parent() else 360) // 3)))
        self.adjustSize()
        if self.parent():
            r = self.parent().rect()
            self.move(20, r.height() - self.height() - 20)
        self.show()
        self.raise_()
        self._t.start(ms)


class FreqScale(QWidget):
    changed = pyqtSignal(float)
    released = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(72)
        self.setMinimumWidth(240)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self._min, self._max, self._val = 88.0, 108.0, 106.4
        self._drag = False
        self._lx = 0
        self.dark = False

    def setRange(self, a, b):
        a, b = float(a), float(b)
        if b <= a:
            b = a + 1.0
        self._min, self._max = a, b
        self._val = min(max(self._val, a), b)
        self.update()

    def setValue(self, v):
        v = min(max(float(v), self._min), self._max)
        if abs(v - self._val) < 1e-6:
            return
        self._val = v
        self.update()

    def value(self):
        return self._val

    def _vis(self):
        span = max(0.5, self._max - self._min)
        if span <= 5:
            return span
        if span <= 25:
            return min(span, 8.0)
        return min(span, 12.0)

    def paintEvent(self, _e):
        w, h = self.width(), self.height()
        if w < 40:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        bg = QColor("#2c2c2e") if self.dark else QColor("#f2f2f7")
        p.fillRect(0, 0, w, h, bg)
        pad, base = 16, h - 22
        usable = max(1.0, w - 2 * pad)
        vis = self._vis()
        mpp = vis / usable
        cx = w * 0.5
        half = vis * 0.5
        major = 1.0 if vis <= 20 else 5.0
        f0 = int((self._val - half) * 2) / 2.0
        f1 = self._val + half + 0.5
        f = f0
        pen_maj = QColor("#8e8e93")
        pen_min = QColor("#c7c7cc")
        pen_txt = QColor("#f5f5f7") if self.dark else QColor("#3a3a3c")
        p.setFont(QFont("Sans", 8))
        while f <= f1:
            if self._min - 1e-9 <= f <= self._max + 1e-9:
                x = cx + (f - self._val) / mpp
                if pad <= x <= w - pad:
                    maj = abs(round(f / major) * major - f) < 1e-4
                    p.setPen(pen_maj if maj else pen_min)
                    p.drawLine(int(x), base, int(x), 20 if maj else 28)
                    if maj:
                        p.setPen(pen_txt)
                        lab = f"{f:.0f}" if abs(f - round(f)) < 1e-6 else f"{f:.1f}"
                        p.drawText(int(x) - 14, h - 14, 28, 12, Qt.AlignCenter, lab)
            f = round(f + 0.5, 5)
        p.setPen(QPen(QColor("#30d158"), 2))
        p.drawLine(int(cx), 8, int(cx), base)
        p.setBrush(QColor("#30d158"))
        p.setPen(Qt.NoPen)
        p.drawEllipse(int(cx) - 4, 6, 8, 8)
        p.setPen(QColor("#30d158"))
        p.setFont(QFont("Sans", 10, QFont.Bold))
        p.drawText(14, 14, f"{self._val:.1f} MHz")

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        self._drag = True
        self._lx = e.pos().x()
        self.grabMouse()

    def mouseMoveEvent(self, e):
        if not self._drag:
            return
        x = e.pos().x()
        dx = x - self._lx
        self._lx = x
        usable = max(1.0, self.width() - 32)
        mpp = self._vis() / usable
        nv = min(max(self._val - dx * mpp, self._min), self._max)
        nv = round(nv * 10) / 10.0
        if abs(nv - self._val) < 1e-9:
            return
        self._val = nv
        self.update()
        self.changed.emit(self._val)

    def mouseReleaseEvent(self, e):
        if not self._drag:
            return
        self._drag = False
        try:
            self.releaseMouse()
        except Exception:
            pass
        self.released.emit(float(self._val))

    def wheelEvent(self, e):
        step = 0.1 if e.angleDelta().y() > 0 else -0.1
        nv = min(max(round((self._val + step) * 10) / 10.0, self._min), self._max)
        if abs(nv - self._val) < 1e-9:
            return
        self._val = nv
        self.update()
        self.changed.emit(self._val)
        self.released.emit(float(self._val))


class HoverIcon(QPushButton):
    def __init__(self, icon_name, tip, parent=None):
        super().__init__(parent)
        self.setObjectName("icon")
        self.setFixedSize(28, 28)
        self.setIcon(load_icon(icon_name))
        self.setIconSize(QSize(15, 15))
        self.setToolTip(tip)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        from PyQt5.QtWidgets import QGraphicsOpacityEffect
        self._fx = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._fx)
        self._fx.setOpacity(0.0)

    def fade(self, on: bool):
        self._fx.setOpacity(1.0 if on else 0.0)


class Collapse(QWidget):
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
        self.btn.setFixedHeight(26)
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
        self.sig.net_list.connect(self._on_net_list)

        self.stations = self._clean_stations(load_json(STATIONS_F, DEFAULT_STATIONS))
        self.cfg = load_json(CONFIG, {"gain": 35, "song_id": True})
        self.history = load_json(HIST_F, [])
        self.favs = load_json(FAV_F, [])
        self.ac_key = AC_KEY.read_text().strip() if AC_KEY.exists() else ""
        self.gn_key = GN_KEY.read_text().strip() if GN_KEY.exists() else ""
        SNIP.mkdir(parents=True, exist_ok=True)
        ART.mkdir(parents=True, exist_ok=True)

        # Always kill leftover audio on every launch
        try:
            subprocess.run(["killall", "-9", "rtl_fm", "play", "ffplay", "mpv"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(0.25)
        except Exception:
            pass


        self.lrc_timer = QTimer(self)
        self.lrc_timer.timeout.connect(self._tick_lrc)

        self._ui()
        self._style()
        self._bind_shortcuts()
        self.log("Ready")
        try:
            self._sync_auto_id_tooltip()
        except Exception:
            pass

    def _bind_shortcuts(self):
        """Global keyboard shortcuts for reload (Ctrl+R / F5)."""
        # Menu actions (ApplicationShortcut)
        self.act_reload = QAction("Reload", self)
        self.act_reload.setShortcuts([
            QKeySequence("Ctrl+R"),
            QKeySequence("Ctrl+Shift+R"),
            QKeySequence(Qt.Key_F5),
        ])
        self.act_reload.setShortcutContext(Qt.ApplicationShortcut)
        self.act_reload.triggered.connect(self.reload_app)
        self.addAction(self.act_reload)

        # Explicit shortcuts on the window + central widget
        targets = [self]
        try:
            if self.centralWidget() is not None:
                targets.append(self.centralWidget())
        except Exception:
            pass
        self._reload_shortcuts = []
        for seq in ("Ctrl+R", "Ctrl+Shift+R", "F5"):
            for parent in targets:
                sc = QShortcut(QKeySequence(seq), parent)
                sc.setContext(Qt.ApplicationShortcut)
                sc.setAutoRepeat(False)
                sc.activated.connect(self.reload_app)
                self._reload_shortcuts.append(sc)

        # App-wide filter (handles ShortcutOverride + KeyPress)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
            # Also intercept at QApplication.notify level via filter on app object
            try:
                app.installEventFilter(self)
            except Exception:
                pass

    def _is_reload_key(self, ev) -> bool:
        try:
            key = ev.key()
            mods = ev.modifiers()
            if key == Qt.Key_F5:
                return True
            if key == Qt.Key_R and (mods & Qt.ControlModifier):
                return True
        except Exception:
            pass
        return False

    def keyPressEvent(self, e):
        if self._is_reload_key(e):
            e.accept()
            self.reload_app()
            return
        super().keyPressEvent(e)

    def reload_app(self):
        """Ctrl+R / F5 — reload UI code in-process (app stays open)."""
        if getattr(self, "_reloading", False):
            return
        self._reloading = True
        self._closing_for_reload = True

        try:
            self.statusBar().showMessage("Reloading…", 3000)
            self.log("Reloading UI…")
            self.toast.show_msg("Reloading…")
            QApplication.processEvents()
        except Exception:
            pass

        try:
            self._save_prefs()
        except Exception:
            pass
        try:
            self.stop()
        except Exception:
            pass

        # Remember window placement
        geo = None
        try:
            geo = self.saveGeometry()
        except Exception:
            pass

        script = str(BASE / "sdr-control-ui.py")
        try:
            if getattr(sys, "argv", None) and sys.argv[0] and os.path.isfile(os.path.abspath(sys.argv[0])):
                script = os.path.abspath(sys.argv[0])
            elif os.path.isfile(str(Path(__file__).resolve())):
                script = str(Path(__file__).resolve())
        except Exception:
            pass

        app = QApplication.instance()
        try:
            # Drop our app-wide key filter so the new window owns shortcuts
            if app is not None:
                try:
                    app.removeEventFilter(self)
                except Exception:
                    pass

            import importlib.util
            # Unique module name so Python re-reads the file from disk
            for k in list(sys.modules):
                if k.startswith("sdr_control_ui_reload_"):
                    try:
                        del sys.modules[k]
                    except Exception:
                        pass
            mod_name = f"sdr_control_ui_reload_{int(time.time() * 1000)}"
            spec = importlib.util.spec_from_file_location(mod_name, script)
            if spec is None or spec.loader is None:
                raise RuntimeError(f"Cannot load {script}")
            mod = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = mod
            spec.loader.exec_module(mod)

            new = mod.App()
            if geo is not None:
                try:
                    new.restoreGeometry(geo)
                except Exception:
                    pass
            new.show()
            new.raise_()
            new.activateWindow()

            # Keep a hard ref so GC doesn't drop the new window
            if app is not None:
                app._sdr_main = new

            try:
                new.toast.show_msg("Reloaded")
                new.statusBar().showMessage("Reloaded", 2500)
                new.log("UI reloaded (in-process)")
            except Exception:
                pass

            # Tear down old window without process exit / lock cleanup
            try:
                self.hide()
            except Exception:
                pass
            self.deleteLater()
            return
        except Exception as e:
            self._reloading = False
            self._closing_for_reload = False
            try:
                if app is not None:
                    app.installEventFilter(self)
            except Exception:
                pass
            try:
                self.log(f"In-process reload failed: {e}")
                self.toast.show_msg("Reload failed")
                self.statusBar().showMessage(f"Reload failed: {e}", 5000)
            except Exception:
                pass
            # Last resort: full process restart
            try:
                env = os.environ.copy()
                env["SDR_FORCE_START"] = "1"
                subprocess.Popen(
                    [sys.executable, script, *list(sys.argv[1:])],
                    cwd=str(Path(script).parent),
                    env=env,
                    start_new_session=True,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    close_fds=True,
                )
                try:
                    LOCK.unlink(missing_ok=True)
                except Exception:
                    pass
                os._exit(0)
            except Exception:
                pass

    def _clean_stations(self, data):
        out = {}
        for cat, items in (data or {}).items():
            clean = []
            for s in items or []:
                if not isinstance(s, dict):
                    continue
                name = str(s.get("name", "")).strip()
                if not name:
                    continue
                # Internet / stream stations
                if s.get("url"):
                    clean.append({
                        "name": name,
                        "url": str(s.get("url")).strip(),
                        "mode": s.get("mode") or "net",
                    })
                    continue
                try:
                    freq = float(s.get("freq", 0))
                except Exception:
                    continue
                if freq <= 0 or name.replace(".", "").isdigit():
                    continue
                clean.append({"name": name, "freq": freq, "mode": s.get("mode") or mode_for_freq(freq)})
            if clean:
                out[cat] = clean
        return out or DEFAULT_STATIONS

    def _ui(self):
        self.setMinimumSize(1020, 660)
        self.resize(1120, 720)
        c = QWidget()
        self.setCentralWidget(c)
        root = QVBoxLayout(c)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(0)
        self.toast = Toast(c)

        self.split = QSplitter(Qt.Horizontal)
        self.split.setHandleWidth(6)
        self.split.setChildrenCollapsible(True)
        root.addWidget(self.split, 1)

        # Left
        left = QFrame()
        left.setObjectName("card")
        left.setMinimumWidth(280)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(12, 12, 12, 12)
        ll.setSpacing(8)
        hdr = QHBoxLayout()
        hdr.setContentsMargins(0, 0, 0, 0)
        hdr.setSpacing(4)
        self.left_mode = QTabWidget()
        self.left_mode.setDocumentMode(True)
        self.left_mode.setFixedHeight(32)
        self.left_mode.addTab(QWidget(), "SDR")
        self.left_mode.addTab(QWidget(), "Internet")
        self.left_mode.currentChanged.connect(self._on_left_mode)
        hdr.addWidget(self.left_mode, 1)
        self.btn_scan = QPushButton()
        self.btn_scan.setObjectName("icon")
        self.btn_scan.setFixedSize(28, 28)
        self.btn_scan.setIcon(load_icon("radio"))
        self.btn_scan.setIconSize(QSize(15, 15))
        self.btn_scan.setToolTip("Auto-scan all bands (SDR)")
        self.btn_scan.setCursor(Qt.PointingHandCursor)
        self.btn_scan.clicked.connect(self.start_auto_scan)
        hdr.addWidget(self.btn_scan)
        self.btn_hide_left = QPushButton()
        self.btn_hide_left.setObjectName("icon")
        self.btn_hide_left.setFixedSize(28, 28)
        self.btn_hide_left.setIcon(load_icon("panel-left"))
        self.btn_hide_left.setIconSize(QSize(15, 15))
        self.btn_hide_left.setToolTip("Hide stations")
        self.btn_hide_left.setCursor(Qt.PointingHandCursor)
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
        for k in self.stations:
            self.cats.addItem(k)
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
        row.addWidget(self.stations_list, 1)
        ll.addLayout(row, 1)
        self.split.addWidget(left)

        # Center
        mid = QWidget()
        self.mid_panel = mid
        ml = QVBoxLayout(mid)
        self._mid_layout = ml
        ml.setContentsMargins(6, 0, 6, 0)
        ml.setSpacing(8)
        edge = QHBoxLayout()
        self.btn_show_left = QPushButton()
        self.btn_show_left.setObjectName("icon")
        self.btn_show_left.setFixedSize(32, 32)
        self.btn_show_left.setIcon(load_icon("menu"))
        self.btn_show_left.setIconSize(QSize(18, 18))
        self.btn_show_left.setToolTip("Show stations")
        self.btn_show_left.setVisible(False)
        self.btn_show_left.clicked.connect(lambda: self.toggle_left(True))
        edge.addWidget(self.btn_show_left)
        edge.addStretch()
        self.btn_show_right = QPushButton()
        self.btn_show_right.setObjectName("icon")
        self.btn_show_right.setFixedSize(32, 32)
        self.btn_show_right.setIcon(load_icon("panel-right"))
        self.btn_show_right.setIconSize(QSize(16, 16))
        self.btn_show_right.setToolTip("Show side panel")
        self.btn_show_right.setVisible(False)
        self.btn_show_right.setCursor(Qt.PointingHandCursor)
        self.btn_show_right.clicked.connect(self._toggle_right_sidebar)
        edge.addWidget(self.btn_show_right)
        ml.addLayout(edge)

        # Shared player (same layout for SDR + Internet)
        # Internet layout is the reference: centered art, title, sub, song, lyrics·play·like
        self.spotify_panel = QFrame()
        self.spotify_panel.setObjectName("card")
        self.spotify_panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        sp = QVBoxLayout(self.spotify_panel)
        self._spotify_layout = sp
        sp.setContentsMargins(32, 28, 32, 20)
        sp.setSpacing(8)
        sp.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        sp.addStretch(1)

        self.sp_art = QLabel("♪")
        self.sp_art.setFixedSize(280, 280)
        self.sp_art.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.sp_art.setAlignment(Qt.AlignCenter)
        self.sp_art.setObjectName("art")
        self.sp_art.setScaledContents(False)
        sp.addWidget(self.sp_art, 0, Qt.AlignHCenter)
        sp.addSpacing(12)

        self.sp_title = QLabel("Not playing")
        self.sp_title.setObjectName("title")
        self.sp_title.setAlignment(Qt.AlignHCenter)
        self.sp_title.setWordWrap(True)
        sp.addWidget(self.sp_title)
        self.sp_sub = QLabel("Pick a station")
        self.sp_sub.setObjectName("sub")
        self.sp_sub.setAlignment(Qt.AlignHCenter)
        self.sp_sub.setWordWrap(True)
        sp.addWidget(self.sp_sub)
        self.sp_song = QLabel("")
        self.sp_song.setObjectName("song")
        self.sp_song.setAlignment(Qt.AlignHCenter)
        self.sp_song.setWordWrap(True)
        sp.addWidget(self.sp_song)
        sp.addSpacing(16)

        rowsp = QHBoxLayout()
        rowsp.setSpacing(14)
        rowsp.addStretch()
        self.sp_lrc = QPushButton()
        self.sp_lrc.setObjectName("icon")
        self.sp_lrc.setFixedSize(42, 42)
        self.sp_lrc.setIcon(load_icon("lyrics"))
        self.sp_lrc.setIconSize(QSize(18, 18))
        self.sp_lrc.setCheckable(True)
        self.sp_lrc.setToolTip("Show / hide lyrics (right pane)")
        self.sp_lrc.clicked.connect(self._toggle_lyrics_from_icon)
        self.sp_play = QPushButton()
        self.sp_play.setObjectName("play")
        self.sp_play.setFixedSize(56, 56)
        self.sp_play.setIcon(load_icon("play"))
        self.sp_play.setIconSize(QSize(26, 26))
        self.sp_play.setToolTip("Play / Stop")
        self.sp_play.clicked.connect(self.toggle)
        self.sp_fav = QPushButton()
        self.sp_fav.setObjectName("icon")
        self.sp_fav.setFixedSize(42, 42)
        self.sp_fav.setIcon(load_icon("heart"))
        self.sp_fav.setIconSize(QSize(18, 18))
        self.sp_fav.setCheckable(True)
        self.sp_fav.setEnabled(False)
        self.sp_fav.setToolTip("Like / unlike")
        self.sp_fav.clicked.connect(self.toggle_fav)
        self.sp_id = QPushButton()
        self.sp_id.setVisible(False)
        self.sp_yt = QPushButton()
        self.sp_yt.setVisible(False)
        rowsp.addWidget(self.sp_lrc)
        rowsp.addWidget(self.sp_play)
        rowsp.addWidget(self.sp_fav)
        rowsp.addStretch()
        sp.addLayout(rowsp)
        sp.addStretch(1)
        self.spotify_panel.setVisible(True)
        ml.addWidget(self.spotify_panel, 1)

        # Aliases so existing SDR code (title/art/btn_*) drives the same widgets
        self.hero_frame = self.spotify_panel
        self._hero_layout = sp
        self.art = self.sp_art
        self.title = self.sp_title
        self.sub = self.sp_sub
        self.song_l = self.sp_song
        self.btn_lrc = self.sp_lrc
        self.btn_play = self.sp_play
        self.btn_fav = self.sp_fav

        # Identify / YouTube live on the right sidebar (logic hooks)
        self.btn_id = QPushButton()
        self.btn_id.setObjectName("icon")
        self.btn_id.setFixedSize(36, 36)
        self.btn_id.setIcon(load_icon("search"))
        self.btn_id.setIconSize(QSize(16, 16))
        self.btn_id.setToolTip("Identify song now")
        self.btn_id.clicked.connect(self.id_now)
        self.btn_id.setVisible(False)

        self.btn_yt = QPushButton()
        self.btn_yt.setObjectName("icon")
        self.btn_yt.setFixedSize(36, 36)
        self.btn_yt.setIcon(load_icon("youtube"))
        self.btn_yt.setIconSize(QSize(16, 16))
        self.btn_yt.setEnabled(False)
        self.btn_yt.setToolTip("YouTube")
        self.btn_yt.clicked.connect(self.open_yt)
        self.btn_yt.setVisible(False)

        # Tuner (SDR only)
        self.tuner_frame = QFrame()
        self.tuner_frame.setObjectName("card")
        self.tuner_frame.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        tl = QVBoxLayout(self.tuner_frame)
        tl.setContentsMargins(14, 12, 14, 12)
        tl.setSpacing(8)
        tr = QHBoxLayout()
        tr.addWidget(QLabel("Band"))
        self.band = QComboBox()
        self.band.addItem("All Bands")
        for b in BANDS:
            self.band.addItem(b[0])
        tr.addWidget(self.band, 1)
        tr.addWidget(QLabel("Mode"))
        self.mode = QComboBox()
        self.mode.addItems(["wbfm", "fm", "am"])
        tr.addWidget(self.mode)
        tr.addWidget(QLabel("Gain"))
        self.gain = QDoubleSpinBox()
        self.gain.setRange(0, 49)
        self.gain.setDecimals(0)
        self.gain.setValue(float(self.cfg.get("gain", 35)))
        self.gain.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.gain.setFixedWidth(44)
        tr.addWidget(self.gain)
        tl.addLayout(tr)
        self.scale = FreqScale()
        self.scale.changed.connect(self.on_scale)
        self.scale.released.connect(self.on_scale_release)
        tl.addWidget(self.scale)
        self.freq = QDoubleSpinBox()
        self.freq.setDecimals(1)
        self.freq.setSingleStep(0.1)
        self.freq.setRange(0.1, 1700)
        self.freq.setValue(106.4)
        self.freq.setSuffix(" MHz")
        self.freq.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.freq.valueChanged.connect(self.on_freq)
        self.freq.editingFinished.connect(self.commit_tune)
        tl.addWidget(self.freq)
        ml.addWidget(self.tuner_frame)
        self._tuner_open = True  # user preference; stream mode can force-hide

        # Hidden lyrics toggle (state only; UI lives in right pane)
        self.lyrics_toggle = QPushButton("Lyrics")
        self.lyrics_toggle.setVisible(False)
        self.lyrics_toggle.setCheckable(True)
        self.lyrics_toggle.setChecked(False)

        self.split.addWidget(mid)
        self._art_path = None
        self._lyrics_open = False
        self._right_tab_before_lyrics = 0
        QTimer.singleShot(0, lambda: self._layout_player_for_lyrics(False))

        
        
        
        # Right – collapsible sidebar
        right = QWidget()
        right.setMinimumWidth(200)
        right.setMaximumWidth(280)
        self.right_panel = right
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 10, 8, 10)
        rl.setSpacing(2)

        # Top row: Collapse + Auto ID + Theme
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)
        self.btn_collapse_right = QPushButton()
        self.btn_collapse_right.setObjectName("icon")
        self.btn_collapse_right.setFixedSize(34, 34)
        self.btn_collapse_right.setIcon(load_icon("panel-right"))
        self.btn_collapse_right.setIconSize(QSize(16, 16))
        self.btn_collapse_right.setToolTip("Collapse sidebar")
        self.btn_collapse_right.setCursor(Qt.PointingHandCursor)
        self.btn_collapse_right.clicked.connect(self._toggle_right_sidebar)
        top.addWidget(self.btn_collapse_right)

        top.addStretch()

        self.btn_theme_side = QPushButton()
        self.btn_theme_side.setObjectName("icon")
        self.btn_theme_side.setFixedSize(34, 34)
        self.btn_theme_side.setIcon(load_icon("moon"))
        self.btn_theme_side.setIconSize(QSize(16, 16))
        self.btn_theme_side.setToolTip("Light / Dark")
        self.btn_theme_side.setCursor(Qt.PointingHandCursor)
        self.btn_theme_side.clicked.connect(self.toggle_theme)
        top.addWidget(self.btn_theme_side)
        rl.addLayout(top)
        rl.addSpacing(8)

        # Navigation list (Library / Lyrics / Tools / Log)
        self.nav_btns = []
        self._nav_labels = ["  Library", "  Lyrics", "  Tools", "  Log"]
        nav_items = [
            ("Library", "bookmark", 0),
            ("Lyrics",  "lyrics",   1),
            ("Tools",   "settings", 2),
            ("Log",     "history",  3),
        ]
        for label, icon_name, idx in nav_items:
            btn = QPushButton(f"  {label}")
            btn.setObjectName("navBtn")
            btn.setIcon(load_icon(icon_name))
            btn.setIconSize(QSize(16, 16))
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(38)
            btn.clicked.connect(lambda checked, i=idx: self._switch_right_tab(i))
            rl.addWidget(btn)
            self.nav_btns.append(btn)

        if self.nav_btns:
            self.nav_btns[0].setChecked(True)

        rl.addSpacing(6)

        # Content stack
        from PyQt5.QtWidgets import QStackedWidget
        self.right_stack = QStackedWidget()

        # 0 – Library
        lib_w = QWidget()
        lib_l = QVBoxLayout(lib_w)
        lib_l.setContentsMargins(0, 4, 0, 0)
        lib_tabs = QTabWidget()
        self.hist = QListWidget()
        self.hist.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.hist.itemDoubleClicked.connect(self.open_hist)
        lib_tabs.addTab(self.hist, "History")
        self.fav_list = QListWidget()
        self.fav_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.fav_list.itemDoubleClicked.connect(self.open_fav)
        self.fav_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.fav_list.customContextMenuRequested.connect(self.fav_menu)
        lib_tabs.addTab(self.fav_list, "Likes")
        lib_l.addWidget(lib_tabs)
        self.right_stack.addWidget(lib_w)

        # 1 – Lyrics (right pane — not below the player)
        self.lyrics_panel = QFrame()
        self.lyrics_panel.setObjectName("card")
        self.lyrics_panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        lp = QVBoxLayout(self.lyrics_panel)
        lp.setContentsMargins(8, 6, 8, 6)
        lp.setSpacing(6)
        lyr_hdr = QLabel("Lyrics")
        lyr_hdr.setObjectName("h")
        lyr_hdr.setStyleSheet("font-weight:600; font-size:13px;")
        lp.addWidget(lyr_hdr)
        self.lyrics = QTextEdit()
        self.lyrics.setReadOnly(True)
        self.lyrics.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.lyrics.setPlaceholderText("")
        lp.addWidget(self.lyrics, 1)
        self.right_stack.addWidget(self.lyrics_panel)

        # 2 – Tools
        tools_w = QWidget()
        tools_l = QVBoxLayout(tools_w)
        tools_l.setContentsMargins(4, 8, 4, 4)
        g = QGridLayout()
        g.setSpacing(8)
        for i, (txt, slot, tip) in enumerate([
            ("SDR++", self.start_sdr, "Open SDR++"),
            ("Flights", self.start_flights, "ADS-B map"),
            ("Weather", self.start_wx, "SatDump"),
            ("AIS", self.start_ais, "Marine AIS"),
            ("Test", self.test_dongle, "rtl_test"),
            ("Stop All", self.free_all, "Stop all SDR apps"),
        ]):
            b = QPushButton(txt)
            b.setObjectName("pill")
            b.setToolTip(tip)
            b.clicked.connect(slot)
            g.addWidget(b, i // 2, i % 2)
        tools_l.addLayout(g)
        tools_l.addStretch(1)
        self.right_stack.addWidget(tools_w)

        # 3 – Log
        log_w = QWidget()
        log_l = QVBoxLayout(log_w)
        log_l.setContentsMargins(0, 4, 0, 0)
        self.logv = QTextEdit()
        self.logv.setReadOnly(True)
        log_l.addWidget(self.logv)
        self.right_stack.addWidget(log_w)

        rl.addWidget(self.right_stack, 1)

        # Bottom-right actions: Tuner · Identify · Fetch lyrics · YouTube · Auto Song ID
        rl.addSpacing(6)
        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 4, 0, 0)
        bottom.setSpacing(8)
        bottom.addStretch(1)

        # Show / hide SDR tuner (band, mode, gain, frequency scale)
        self.btn_toggle_tuner = QPushButton()
        self.btn_toggle_tuner.setObjectName("icon")
        self.btn_toggle_tuner.setFixedSize(38, 38)
        self.btn_toggle_tuner.setIcon(load_icon("radio"))
        self.btn_toggle_tuner.setIconSize(QSize(18, 18))
        self.btn_toggle_tuner.setCheckable(True)
        self.btn_toggle_tuner.setChecked(True)
        self.btn_toggle_tuner.setToolTip("Show / hide tuner (band · mode · gain · frequency)")
        self.btn_toggle_tuner.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_tuner.setVisible(True)
        self.btn_toggle_tuner.clicked.connect(self._on_toggle_tuner)
        bottom.addWidget(self.btn_toggle_tuner)

        self.btn_id_side = QPushButton()
        self.btn_id_side.setObjectName("icon")
        self.btn_id_side.setFixedSize(38, 38)
        self.btn_id_side.setIcon(load_icon("search"))
        self.btn_id_side.setIconSize(QSize(18, 18))
        self.btn_id_side.setToolTip("Identify song now")
        self.btn_id_side.setCursor(Qt.PointingHandCursor)
        self.btn_id_side.clicked.connect(self.id_now)
        bottom.addWidget(self.btn_id_side)

        self.btn_lrc_side = QPushButton()
        self.btn_lrc_side.setObjectName("icon")
        self.btn_lrc_side.setFixedSize(38, 38)
        self.btn_lrc_side.setIcon(load_icon("lyrics"))
        self.btn_lrc_side.setIconSize(QSize(18, 18))
        self.btn_lrc_side.setToolTip("Fetch lyrics now")
        self.btn_lrc_side.setCursor(Qt.PointingHandCursor)
        self.btn_lrc_side.clicked.connect(self.lyrics_now)
        bottom.addWidget(self.btn_lrc_side)

        self.btn_yt_side = QPushButton()
        self.btn_yt_side.setObjectName("icon")
        self.btn_yt_side.setFixedSize(38, 38)
        self.btn_yt_side.setIcon(load_icon("youtube"))
        self.btn_yt_side.setIconSize(QSize(18, 18))
        self.btn_yt_side.setToolTip("YouTube")
        self.btn_yt_side.setCursor(Qt.PointingHandCursor)
        self.btn_yt_side.clicked.connect(self.open_yt)
        bottom.addWidget(self.btn_yt_side)

        # Auto Song ID — no checked highlight; status via hover tooltip only
        self.btn_auto_side = QPushButton()
        self.btn_auto_side.setObjectName("icon")
        self.btn_auto_side.setFixedSize(38, 38)
        self.btn_auto_side.setIcon(load_icon("music"))
        self.btn_auto_side.setIconSize(QSize(18, 18))
        self.btn_auto_side.setCheckable(False)  # no green highlight
        self.btn_auto_side.setCursor(Qt.PointingHandCursor)
        self.btn_auto_side.clicked.connect(self._toggle_auto_side)
        bottom.addWidget(self.btn_auto_side)
        self._sync_auto_id_tooltip()

        rl.addLayout(bottom)

        self._right_expanded = True
        # Start collapsed — reopen control is center-edge btn_show_right
        self.right_panel.setMinimumWidth(52)
        self.right_panel.setMaximumWidth(56)
        for b in self.nav_btns:
            b.setText("")
        self.right_stack.setVisible(False)
        self.split.addWidget(right)




        self.split.setStretchFactor(0, 3)
        self.split.setStretchFactor(1, 5)
        self.split.setStretchFactor(2, 3)
        self.split.setSizes([360, 480, 260])

        try:
            self.band.currentTextChanged.disconnect()
        except Exception:
            pass
        try:
            self.band.activated.disconnect()
        except Exception:
            pass
        self.band.activated.connect(self.on_band)
        self.freq.valueChanged.connect(self.on_freq)

        su = self.cfg.get("startup")
        if isinstance(su, dict) and su.get("freq"):
            try:
                if su.get("cat") and su["cat"] in self.stations:
                    for i in range(self.cats.count()):
                        if self.cats.item(i).text() == su["cat"]:
                            self.cats.setCurrentRow(i)
                            break
                self.freq.setValue(float(su["freq"]))
                if su.get("mode"):
                    self.mode.setCurrentText(su["mode"])
            except Exception:
                pass

        self.statusBar().showMessage("Ready")
        QTimer.singleShot(400, self._apply_startup)
        QTimer.singleShot(500, self._restore_right_panel)
        QToolTip.setFont(QFont("Sans", 10))
        if self.cats.count():
            self.cats.setCurrentRow(0)
        self.on_band("FM")
        self.refresh_hist()
        self.refresh_favs()

    def _style(self):
        if self.dark:
            self.setStyleSheet("""
                QMainWindow, QWidget { background:#000; color:#f5f5f7; font-size:13px; }
                QFrame#card { background:transparent; border:none; border-radius:16px; }
                QLabel#art { background:#2c2c2e; border-radius:12px; color:#636366; font-size:42px; }
                QLabel#title { font-size:22px; font-weight:700; }
                QLabel#sub { color:#8e8e93; font-size:12px; }
                QLabel#song { color:#30d158; font-size:13px; }
                QLabel#h { background: transparent; }
                QLabel#toast { background:#f5f5f7; color:#1d1d1f; border-radius:14px; padding:12px 16px; }
                QPushButton#play { background:#30d158; color:#000; border:none; border-radius:22px; }
                QPushButton#icon { background:#2c2c2e; color:#f5f5f7; border:none; border-radius:21px; }
                QPushButton#icon:checked { background:#30d158; color:#000; }
                QPushButton#icon:disabled { color:#636366; }
                QPushButton#pill { background:#2c2c2e; color:#f5f5f7; border:none; border-radius:14px; padding:10px; }
                QPushButton#navBtn {
                    background: transparent;
                    border: none;
                    border-radius: 8px;
                    text-align: left;
                    padding: 8px 10px;
                    color: #f5f5f7;
                }
                QPushButton#navBtn:checked {
                    background: rgba(48, 209, 88, 0.25);
                    color: #30d158;
                    font-weight: 600;
                }
                QPushButton#navBtn:hover {
                    background: rgba(255,255,255,0.06);
                }

                QPushButton#collapseBtn { background:transparent; border:none; text-align:left; font-weight:600; color:#8e8e93; padding:4px 0; }
                QListWidget { background: transparent; border: none; outline: none; }
                QListWidget::item { padding:9px 10px; border-radius:10px; }
                QListWidget::item:selected { background: rgba(48, 209, 88, 0.35); color: #0b3d0b; border-radius: 8px; }
                QListWidget::item:hover { background: rgba(255,255,255,0.06); border-radius: 8px; }
                QComboBox, QDoubleSpinBox { background:transparent; border:none; border-radius:10px; padding:7px 10px; color:#f5f5f7; }
                QTextEdit { background:#2c2c2e; border:none; border-radius:12px; color:#f5f5f7; }
                QSplitter::handle { background:#2c2c2e; width:4px; border-radius:2px; }
                QTabBar::tab { color:#8e8e93; padding:8px 12px; }
                QTabBar::tab:selected { color:#f5f5f7; }
                QStatusBar { color:#8e8e93; background:#000; }
                QToolTip { background-color: #2c2c2e; color: #f5f5f7; border: 1px solid #3a3a3c; border-radius: 8px; padding: 6px 10px; font-size: 11px; }
                QScrollBar:vertical { width:0px; }
                QScrollBar:horizontal { height:0px; }
            """)
        else:
            self.setStyleSheet("""
                QMainWindow, QWidget { background:#f5f5f7; color:#1d1d1f; font-size:13px; }
                QFrame#card { background:transparent; border:none; border-radius:16px; }
                QLabel#art { background:#f2f2f7; border-radius:12px; color:#aeaeb2; font-size:42px; }
                QLabel#title { font-size:22px; font-weight:700; }
                QLabel#sub { color:#6e6e73; font-size:12px; }
                QLabel#song { color:#248a3d; font-size:13px; }
                QLabel#h { background: transparent; }
                QLabel#toast { background:#1d1d1f; color:#f5f5f7; border-radius:14px; padding:12px 16px; }
                QPushButton#play { background:#30d158; color:#fff; border:none; border-radius:22px; }
                QPushButton#icon { background:#f2f2f7; color:#1d1d1f; border:none; border-radius:21px; }
                QPushButton#icon:checked { background:#30d158; color:#fff; }
                QPushButton#icon:disabled { color:#aeaeb2; }
                QPushButton#pill { background:#f2f2f7; color:#1d1d1f; border:none; border-radius:14px; padding:10px; }
                QPushButton#navBtn {
                    background: transparent;
                    border: none;
                    border-radius: 8px;
                    text-align: left;
                    padding: 8px 10px;
                    color: #1d1d1f;
                }
                QPushButton#navBtn:checked {
                    background: rgba(48, 209, 88, 0.18);
                    color: #0b3d0b;
                    font-weight: 600;
                }
                QPushButton#navBtn:hover {
                    background: rgba(0,0,0,0.04);
                }

                QPushButton#collapseBtn { background:transparent; border:none; text-align:left; font-weight:600; color:#6e6e73; padding:4px 0; }
                QListWidget { background: transparent; border: none; outline: none; }
                QListWidget::item { padding:9px 10px; border-radius:10px; }
                QListWidget::item:selected { background: rgba(48, 209, 88, 0.35); color: #0b3d0b; border-radius: 8px; }
                QListWidget::item:hover { background: rgba(0,0,0,0.04); border-radius: 8px; }
                QComboBox, QDoubleSpinBox { background:transparent; border:none; border-radius:10px; padding:7px 10px; }
                QTextEdit { background:#f2f2f7; border:none; border-radius:12px; }
                QSplitter::handle { background:#e5e5ea; width:4px; border-radius:2px; }
                QTabBar::tab { color:#6e6e73; padding:8px 12px; }
                QTabBar::tab:selected { color:#1d1d1f; }
                QStatusBar { color:#6e6e73; background:#f5f5f7; }
                QToolTip { background-color: #1d1d1f; color: #f5f5f7; border: none; border-radius: 8px; padding: 6px 10px; font-size: 11px; }
                QScrollBar:vertical { width:0px; }
                QScrollBar:horizontal { height:0px; }
            """)

    def toggle_theme(self):
        self.dark = not self.dark
        if hasattr(self, "btn_theme_side"):
            self.btn_theme_side.setIcon(load_icon("sun" if self.dark else "moon"))
        self.scale.dark = self.dark
        self._style()
        self.scale.update()
        self._save_prefs()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.toast.isVisible():
            self.toast.show_msg(self.toast.text(), 1000)

    def log(self, m):
        line = f"{datetime.now().strftime('%H:%M:%S')}  {m}"
        print(line)
        self.sig.log.emit(line)

    def _on_log(self, line):
        self.logv.append(line)
        self.logv.moveCursor(QTextCursor.End)

    def _sync_band(self, f):
        name = band_for_freq(float(f))
        self._band_lock = True
        try:
            idx = self.band.findText(name)
            if idx < 0:
                idx = self.band.findText("All Bands")
            if idx >= 0 and self.band.currentIndex() != idx:
                self.band.blockSignals(True)
                self.band.setCurrentIndex(idx)
                self.band.blockSignals(False)
        finally:
            self._band_lock = False

    def _highlight_station_for_freq(self, freq):
        try:
            freq = round(float(freq), 1)
        except Exception:
            return
        matched = False
        for i in range(self.stations_list.count()):
            it = self.stations_list.item(i)
            s = it.data(Qt.UserRole)
            if isinstance(s, dict):
                try:
                    sf = round(float(s.get("freq", 0)), 1)
                except Exception:
                    continue
                if abs(sf - freq) < 0.05:
                    self.stations_list.blockSignals(True)
                    self.stations_list.setCurrentRow(i)
                    self.stations_list.scrollToItem(it)
                    self.stations_list.blockSignals(False)
                    matched = True
                    break
        if not matched:
            self.stations_list.clearSelection()

    def on_band(self, *args):
        if getattr(self, "_band_lock", False):
            return
        name = None
        if args:
            a0 = args[0]
            name = self.band.itemText(a0) if isinstance(a0, int) else str(a0)
        if not name:
            name = self.band.currentText()
        name = (name or "").strip()
        try:
            self.toast.show_msg("Band: " + name)
        except Exception:
            pass
        if not name or name == "All Bands":
            self.freq.blockSignals(True)
            self.freq.setRange(0.1, 1700.0)
            self.freq.blockSignals(False)
            self.scale.setRange(0.1, 1700.0)
            return
        hit = None
        for n, a, b, m in BANDS:
            if n == name:
                hit = (n, float(a), float(b), m)
                break
        if not hit:
            self.log("Band unknown: " + repr(name))
            return
        n, a, b, m = hit
        mid = round(((a + b) / 2.0) * 10) / 10.0
        self._band_lock = True
        try:
            self.scale.setRange(a, b)
            self.freq.blockSignals(True)
            self.freq.setRange(a, b)
            self.freq.setValue(mid)
            self.freq.blockSignals(False)
            self.scale.setValue(mid)
            self.mode.blockSignals(True)
            i = self.mode.findText(m)
            if i >= 0:
                self.mode.setCurrentIndex(i)
            self.mode.blockSignals(False)
        finally:
            self._band_lock = False
        self.log(f"Band → {n}: {mid} MHz [{a}-{b}] {m}")
        try:
            self.play(mid, m, f"{n} {mid}")
        except Exception as ex:
            self.log(str(ex))

    def on_scale(self, v):
        v = round(float(v), 1)
        self.freq.blockSignals(True)
        self.freq.setValue(v)
        self.freq.blockSignals(False)
        m = mode_for_freq(v)
        if self.mode.currentText() != m:
            self.mode.blockSignals(True)
            self.mode.setCurrentText(m)
            self.mode.blockSignals(False)
        try:
            self._sync_band(v)
        except Exception:
            pass
        self._highlight_station_for_freq(v)

    def on_scale_release(self, v=None):
        try:
            v = float(self.freq.value() if v is None else v)
        except Exception:
            return
        m = mode_for_freq(v)
        if self.mode.currentText() != m:
            self.mode.blockSignals(True)
            self.mode.setCurrentText(m)
            self.mode.blockSignals(False)
        try:
            self._sync_band(v)
        except Exception:
            pass
        self._highlight_station_for_freq(v)
        if not getattr(self, "playing", False):
            return
        self.play(v, m, "%.1f MHz" % v, quick=True)

    def commit_tune(self):
        v = float(self.freq.value())
        m = self.mode.currentText() or mode_for_freq(v)
        self._highlight_station_for_freq(v)
        if not getattr(self, "playing", False):
            return
        try:
            self.play(v, m, "%.1f MHz" % v)
        except Exception as ex:
            self.log(str(ex))

    def on_freq(self, v):
        v = float(v)
        try:
            self.scale.blockSignals(True)
            self.scale.setValue(v)
            self.scale.blockSignals(False)
        except Exception:
            pass
        self._highlight_station_for_freq(v)

    def load_cat(self, cat):
        # Top-level Internet mode tab → radio-browser categories
        if getattr(self, "left_mode", None) is not None and self.left_mode.currentIndex() == 1:
            if cat:
                self._load_internet_cat(cat)
            self._apply_stream_mode(True)
            return
        self.stations_list.blockSignals(True)
        self.stations_list.clear()
        if not cat or cat not in self.stations:
            self.stations_list.blockSignals(False)
            return
        for s in self.stations[cat]:
            if not isinstance(s, dict):
                continue
            name = str(s.get("name", "?"))
            if s.get("url"):
                it = QListWidgetItem(f"{name}  ·  net")
                it.setToolTip(f"{name}\n{s.get('url')}")
            else:
                freq = s.get("freq", 0)
                it = QListWidgetItem(f"{name}  ·  {freq}")
                it.setToolTip(f"{name}  ·  {freq} MHz  ·  {str(s.get('mode','')).upper()}")
            it.setData(Qt.UserRole, s)
            self.stations_list.addItem(it)
        self.stations_list.blockSignals(False)
        # SDR-side "Internet" (or any stream) category → same UI as Internet radio
        self._apply_stream_mode(self._cat_is_internet(cat))
        try:
            if not self._cat_is_internet(cat):
                self._highlight_station_for_freq(self.freq.value())
        except Exception:
            pass

    def _cat_is_internet(self, cat) -> bool:
        """True if category is stream/internet radio (not SDR frequencies)."""
        if not cat:
            return False
        name = str(cat).strip().lower()
        if name in ("internet", "stream", "online", "web radio", "webradio"):
            return True
        items = (self.stations or {}).get(cat) or []
        if not items:
            return False
        urls = 0
        total = 0
        for s in items:
            if not isinstance(s, dict):
                continue
            total += 1
            if s.get("url"):
                urls += 1
        if total == 0:
            return False
        # Majority (or all) stream URLs → treat as internet radio
        return urls > 0 and urls * 2 >= total

    def _apply_stream_mode(self, is_net: bool):
        """Apply Internet-radio layout (spotify player, hide tuner) or SDR layout."""
        is_net = bool(is_net)
        self._stream_mode = is_net
        try:
            if hasattr(self, "btn_scan") and getattr(self, "left_mode", None) is not None:
                # Scan only makes sense for real SDR categories
                if self.left_mode.currentIndex() == 0:
                    self.btn_scan.setVisible(not is_net)
                else:
                    self.btn_scan.setVisible(False)
            self._set_player_layout(spotify=is_net)
            # Tuner icon + body only for SDR RF stations (hidden on Internet radio)
            want_tuner = (not is_net) and bool(getattr(self, "_tuner_open", True))
            self._set_tuner_visible(want_tuner)
            if hasattr(self, "btn_toggle_tuner"):
                self.btn_toggle_tuner.setVisible(not is_net)
                self.btn_toggle_tuner.setEnabled(not is_net)
                self.btn_toggle_tuner.blockSignals(True)
                self.btn_toggle_tuner.setChecked(bool(getattr(self, "_tuner_open", True)))
                self.btn_toggle_tuner.blockSignals(False)
                self.btn_toggle_tuner.setToolTip(
                    "Show / hide tuner (band · mode · gain · frequency)"
                )
            self._layout_player_for_lyrics(getattr(self, "_lyrics_open", False))
            if hasattr(self, "mid_panel"):
                self.mid_panel.updateGeometry()
            if hasattr(self, "_mid_layout"):
                self._mid_layout.activate()
        except Exception as e:
            try:
                self.log(f"stream mode: {e}")
            except Exception:
                pass

    def _on_toggle_tuner(self):
        """Small radio icon — show/hide band · mode · gain · frequency tuner."""
        on = True
        if hasattr(self, "btn_toggle_tuner"):
            on = bool(self.btn_toggle_tuner.isChecked())
        self._tuner_open = on
        # Never show tuner while in internet/stream layout
        if getattr(self, "_stream_mode", False):
            self._set_tuner_visible(False)
        else:
            self._set_tuner_visible(on)
            try:
                self._layout_player_for_lyrics(getattr(self, "_lyrics_open", False))
            except Exception:
                pass
        try:
            self._save_prefs()
        except Exception:
            pass

    def stations_menu(self, pos):
        item = self.stations_list.itemAt(pos)
        cat_item = self.cats.currentItem()
        if not cat_item:
            return
        cat = cat_item.text()
        menu = QMenu(self)
        act_add = menu.addAction("Add station…")
        act_add_net = menu.addAction("Add internet station…")
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
        if chosen is None:
            return
        if chosen == act_add_net:
            name, ok = QInputDialog.getText(self, "Internet station", "Name:")
            if not ok or not name.strip():
                return
            url, ok = QInputDialog.getText(self, "Stream URL", "URL (http/https):")
            if not ok or not url.strip():
                return
            self.stations.setdefault(cat, []).append({
                "name": name.strip(), "url": url.strip(), "mode": "net"
            })
            save_json(STATIONS_F, self.stations)
            self.load_cat(cat)
            self.toast.show_msg("Added stream " + name.strip())
            return
        if chosen == act_add:
            name, ok = QInputDialog.getText(self, "Add station", "Name:")
            if not ok or not name.strip():
                return
            freq, ok = QInputDialog.getDouble(self, "Frequency", "MHz:", float(self.freq.value()), 0.1, 1700.0, 1)
            if not ok:
                return
            self.stations.setdefault(cat, []).append({"name": name.strip(), "freq": float(freq), "mode": mode_for_freq(freq)})
            save_json(STATIONS_F, self.stations)
            self.load_cat(cat)
            return
        s = item.data(Qt.UserRole) if item else None
        if not isinstance(s, dict):
            return
        def _match(st):
            return st.get("name") == s.get("name") and float(st.get("freq", 0)) == float(s.get("freq", 0))
        if chosen == act_ren:
            name, ok = QInputDialog.getText(self, "Rename", "Name:", text=s.get("name", ""))
            if not ok or not name.strip():
                return
            for st in self.stations.get(cat, []):
                if _match(st):
                    st["name"] = name.strip()
                    break
            save_json(STATIONS_F, self.stations)
            self.load_cat(cat)
        elif chosen == act_del:
            if QMessageBox.question(self, "Remove", "Remove " + str(s.get("name")) + "?") != QMessageBox.Yes:
                return
            self.stations[cat] = [st for st in self.stations.get(cat, []) if not _match(st)]
            save_json(STATIONS_F, self.stations)
            self.load_cat(cat)
        elif chosen == act_freq:
            freq, ok = QInputDialog.getDouble(self, "Frequency", "MHz:", float(s.get("freq", 100)), 0.1, 1700.0, 1)
            if not ok:
                return
            for st in self.stations.get(cat, []):
                if _match(st):
                    st["freq"] = float(freq)
                    st["mode"] = mode_for_freq(freq)
                    break
            save_json(STATIONS_F, self.stations)
            self.load_cat(cat)
        elif chosen == act_mode:
            modes = ["wbfm", "fm", "am"]
            cur = s.get("mode", "wbfm")
            mode, ok = QInputDialog.getItem(self, "Mode", "Mode:", modes, modes.index(cur) if cur in modes else 0, False)
            if not ok:
                return
            for st in self.stations.get(cat, []):
                if _match(st):
                    st["mode"] = mode
                    break
            save_json(STATIONS_F, self.stations)
            self.load_cat(cat)
        elif chosen == act_def:
            self.cfg["startup"] = {"cat": cat, "name": s.get("name"), "freq": s.get("freq"), "mode": s.get("mode")}
            save_json(CONFIG, self.cfg)
            try:
                self.toast.show_msg("Default: " + str(s.get("name")))
            except Exception:
                pass
        elif chosen == act_top:
            lst = self.stations.get(cat, [])
            self.stations[cat] = [s] + [st for st in lst if not _match(st)]
            save_json(STATIONS_F, self.stations)
            self.load_cat(cat)
        elif chosen == act_bot:
            lst = self.stations.get(cat, [])
            self.stations[cat] = [st for st in lst if not _match(st)] + [s]
            save_json(STATIONS_F, self.stations)
            self.load_cat(cat)

    def _stations_reordered(self, *args):
        cat_item = self.cats.currentItem()
        if not cat_item:
            return
        cat = cat_item.text()
        if cat not in self.stations:
            return
        ordered = []
        for i in range(self.stations_list.count()):
            data = self.stations_list.item(i).data(Qt.UserRole)
            if isinstance(data, dict):
                ordered.append(data)
        if ordered:
            self.stations[cat] = ordered
            save_json(STATIONS_F, self.stations)

    def play_item(self, item):
        s = item.data(Qt.UserRole)
        if not s:
            return
        # Internet stream
        if s.get("url"):
            self._apply_stream_mode(True)
            self.play_stream(s.get("url"), s.get("name", "Stream"))
            return
        # RF station — restore SDR player/tuner if we were in stream UI
        if getattr(self, "left_mode", None) is not None and self.left_mode.currentIndex() == 0:
            self._apply_stream_mode(False)
        freq = float(s.get("freq", 0) or 0)
        if freq <= 0:
            return
        self.freq.setValue(freq)
        self.scale.setValue(freq)
        self.mode.setCurrentText(s.get("mode") or mode_for_freq(freq))
        self._sync_band(freq)
        self.play(freq, s.get("mode") or mode_for_freq(freq), s.get("name", ""))


    def _station_art_path(self, name):
        """Return path to station default art if it exists."""
        if not name:
            return None
        base = ART / "stations"
        candidates = [
            base / f"{name.replace(' ', '_')}.png",
            base / f"{name.replace(' ', '_')}.jpg",
            base / "default.png",
        ]
        for p in candidates:
            if p.exists() and p.stat().st_size > 200:
                return str(p)
        return None

    def _show_station_art(self, name=""):
        path = self._station_art_path(name)
        if path:
            self.show_art(path)
        else:
            self.art.setPixmap(QPixmap())
            self.art.setText("♪")

    def clear_song(self):
        self.song = None
        self.genius_url = None
        self.song_l.setText("")
        self.btn_fav.setCheckable(True)
        self.btn_fav.setEnabled(False)
        self.btn_fav.setChecked(False)
        self.btn_fav.setIcon(load_icon("heart"))
        self.btn_yt.setEnabled(False)
        self.art.setPixmap(QPixmap())
        self.art.setText("♪")
        if hasattr(self, "sp_art"):
            self.sp_art.setPixmap(QPixmap())
            self.sp_art.setText("♪")
        if hasattr(self, "sp_song"):
            self.sp_song.setText("")
        if hasattr(self, "sp_fav"):
            self.sp_fav.setEnabled(False)
            self.sp_fav.setChecked(False)
            self.sp_fav.setIcon(load_icon("heart"))
        self._art_path = None
        self.lyrics.setPlainText("")
        self.lrc = []
        self.lrc_timer.stop()

    def set_playing(self, on, name="", detail=""):
        self.playing = on
        if on:
            self.btn_play.setIcon(load_icon("stop"))
            if hasattr(self, "btn_id"):
                self.btn_id.setVisible(False)
            if hasattr(self, "btn_yt"):
                self.btn_yt.setVisible(False)
            if hasattr(self, "sp_play"):
                self.sp_play.setIcon(load_icon("stop"))
            self.title.setText(name or "Playing")
            self.sub.setText(detail)
            if hasattr(self, "sp_title"):
                self.sp_title.setText(name or "Playing")
                self.sp_sub.setText(detail)
        else:
            self.btn_play.setIcon(load_icon("play"))
            if hasattr(self, "sp_play"):
                self.sp_play.setIcon(load_icon("play"))
            self.title.setText("Not playing")
            self.sub.setText("Pick a station")
            if hasattr(self, "sp_title"):
                self.sp_title.setText("Not playing")
                self.sp_sub.setText("Pick a station")
                self.sp_song.setText("")
            self.clear_song()

    def stop(self):
        try:
            self.stop_id()
        except Exception:
            pass
        try:
            if getattr(self, "rtl", None) is not None and self.rtl.poll() is None:
                self.rtl.terminate()
                try:
                    self.rtl.wait(timeout=0.4)
                except Exception:
                    try:
                        self.rtl.kill()
                    except Exception:
                        pass
        except Exception:
            pass
        self.rtl = None
        subprocess.run(["killall", "-9", "rtl_fm", "play", "ffplay", "mpv"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            self.set_playing(False)
        except Exception:
            self.playing = False


    def toggle(self):
        if self.playing:
            self.stop()
        else:
            self.play(self.freq.value(), self.mode.currentText(), f"{self.freq.value():.1f} MHz")


    def _soft_reset_dongle(self):
        """Release a stuck RTL-SDR. Tries helper script first, then sysfs."""
        self.log("Soft-resetting dongle…")
        subprocess.run(["killall", "-9", "rtl_fm", "play", "ffplay", "mpv"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.2)

        # Prefer the passwordless helper script if present
        helper = BASE / "reset-dongle.sh"
        if helper.exists():
            try:
                r = subprocess.run(["sudo", str(helper)],
                                   capture_output=True, text=True, timeout=8)
                if r.returncode == 0:
                    self.log("Dongle reset via helper script")
                    time.sleep(0.5)
                    return True
            except Exception as e:
                self.log(f"helper reset: {e}")

        # Fallback: sysfs re-authorize (needs permissions)
        try:
            for d in Path("/sys/bus/usb/devices").glob("*/idVendor"):
                try:
                    if d.read_text().strip().lower() == "0bda":
                        dev = d.parent
                        auth = dev / "authorized"
                        if auth.exists():
                            auth.write_text("0")
                            time.sleep(0.4)
                            auth.write_text("1")
                            self.log(f"Reset {dev.name}")
                            time.sleep(0.6)
                            return True
                except Exception:
                    continue
        except Exception as e:
            self.log(f"sysfs reset: {e}")

        # Last resort: reload drivers
        try:
            subprocess.run(["sudo", "modprobe", "-r", "dvb_usb_rtl28xxu", "rtl2832", "rtl2830"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            time.sleep(0.3)
            subprocess.run(["sudo", "modprobe", "dvb_usb_rtl28xxu"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            self.log("Drivers reloaded")
            time.sleep(0.5)
            return True
        except Exception as e:
            self.log(f"modprobe reset: {e}")
        return False

    def _dongle_ok(self):
        """Non-invasive check: rtl_test -t with short timeout."""
        try:
            r = subprocess.run(
                ["timeout", "2", "rtl_test", "-t"],
                capture_output=True, text=True, timeout=4
            )
            out = (r.stdout or "") + (r.stderr or "")
            # Success if we see device info and no "Failed to open"
            if "Failed to open" in out or "usb_open error" in out:
                return False
            if "Found" in out or "Using device" in out or r.returncode == 0:
                return True
            return False
        except Exception:
            return False



    def play_stream(self, url, name="Internet Radio"):
        """Play an internet radio URL via ffplay (fallback mpv)."""
        try:
            self.stop()
        except Exception:
            pass
        self.stop_id()
        self.clear_song()
        detail = "Internet stream"
        self.set_playing(True, name, detail)
        self.log(f"▶ {name} · {url}")
        self._current_station = name

        cmd = None
        # Prefer ffplay (ffmpeg), quiet, no window
        try:
            if subprocess.run(["which", "ffplay"], capture_output=True).returncode == 0:
                cmd = [
                    "ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet",
                    "-i", url,
                ]
        except Exception:
            pass
        if cmd is None:
            try:
                if subprocess.run(["which", "mpv"], capture_output=True).returncode == 0:
                    cmd = ["mpv", "--no-video", "--really-quiet", url]
            except Exception:
                pass
        if cmd is None:
            self.log("No ffplay or mpv found – install ffmpeg or mpv")
            self.toast.show_msg("Install ffmpeg (ffplay) for internet radio")
            self.set_playing(False)
            return

        try:
            self.rtl = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            self.log(f"stream: {e}")
            self.set_playing(False)
            return

        time.sleep(0.4)
        if self.rtl.poll() is not None:
            self.log("stream process exited – bad URL or network?")
            self.set_playing(False)
            self.rtl = None
            return

        self.log("stream: started OK")
        if bool(self.cfg.get("song_id", True)):
            self.start_id()


    def play(self, freq, mode, name="", quick=False):
        """Start or retune. Auto soft-resets the dongle if it is locked."""
        # Stop previous cleanly
        if self.rtl is not None:
            try:
                if self.rtl.poll() is None:
                    self.rtl.terminate()
                    try:
                        self.rtl.wait(timeout=0.5)
                    except Exception:
                        self.rtl.kill()
            except Exception:
                pass
            self.rtl = None

        subprocess.run(["killall", "-9", "rtl_fm", "play", "ffplay", "mpv"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.2 if quick else 0.3)

        self.stop_id()
        self.clear_song()

        try:
            gain = int(self.gain.value())
            self.cfg["gain"] = gain
            save_json(CONFIG, self.cfg)
            hz = int(round(float(freq) * 1e6))
        except Exception as e:
            self.log(f"play: bad parameters: {e}")
            self.set_playing(False)
            return

        detail = f"{freq:.3f} MHz · {mode.upper()} · gain {gain}"
        self.set_playing(True, name or f"{freq:.1f} MHz", detail)
        self.log(f"▶ {name} · {detail}")

        if mode == "wbfm":
            cmd = (f"rtl_fm -f {hz} -M wbfm -g {gain} -s 170k -A fast "
                   f"-r 32000 -l 0 -E deemp - | "
                   f"play -r 32000 -t raw -e signed -b 16 -c 1 -q -")
        elif mode == "am":
            cmd = (f"rtl_fm -f {hz} -M am -g {gain} -s 12000 -r 12000 -l 0 - | "
                   f"play -r 12000 -t raw -e signed -b 16 -c 1 -q -")
        else:
            cmd = (f"rtl_fm -f {hz} -M fm -g {gain} -s 22050 -r 22050 -l 0 - | "
                   f"play -r 22050 -t raw -e signed -b 16 -c 1 -q -")

        # Try up to 3 times, with a soft reset in the middle
        for attempt in range(3):
            try:
                self.rtl = subprocess.Popen(cmd, shell=True)
            except Exception as e:
                self.log(f"play: Popen failed: {e}")
                self.set_playing(False)
                return

            time.sleep(0.4)
            if self.rtl.poll() is None:
                self.log("play: started OK")
                self._highlight_station_for_freq(freq)
                if bool(self.cfg.get("song_id", True)):
                    self.start_id()
                return

            self.log(f"play: attempt {attempt+1} failed (device busy)")
            subprocess.run(["killall", "-9", "rtl_fm", "play", "ffplay", "mpv"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if attempt == 0:
                # After first failure, soft-reset the dongle
                self._soft_reset_dongle()
            else:
                time.sleep(0.5)

        self.log("play: still locked — please unplug/replug once")
        self.set_playing(False)
        self.rtl = None


    def _sync_auto_id_tooltip(self):
        """Hover shows On/Off — no checked highlight on the icon."""
        if not hasattr(self, "btn_auto_side"):
            return
        on = bool(self.cfg.get("song_id", True))
        self.btn_auto_side.setToolTip(
            "Auto Song ID: On" if on else "Auto Song ID: Off"
        )

    def _toggle_auto_side(self):
        on = not bool(self.cfg.get("song_id", True))
        self.cfg["song_id"] = on
        save_json(CONFIG, self.cfg)
        self._sync_auto_id_tooltip()
        self.on_auto(on)
        self.toast.show_msg("Auto Song ID " + ("on" if on else "off"))
        self._save_prefs()

    def on_auto(self, on):
        self.cfg["song_id"] = on
        save_json(CONFIG, self.cfg)
        self._sync_auto_id_tooltip()
        if on and self.playing:
            self.start_id()
        else:
            self.stop_id()

    def _ensure_aio(self):
        if self.aio_loop and self.aio_thread and self.aio_thread.is_alive():
            return
        self.aio_loop = asyncio.new_event_loop()
        def run(loop):
            asyncio.set_event_loop(loop)
            loop.run_forever()
        self.aio_thread = threading.Thread(target=run, args=(self.aio_loop,), daemon=True)
        self.aio_thread.start()

    def _submit(self, coro):
        self._ensure_aio()
        return asyncio.run_coroutine_threadsafe(coro, self.aio_loop)

    def start_id(self):
        if not self.playing:
            return
        if self.id_thread and self.id_thread.is_alive():
            return
        self.id_stop.clear()
        self.id_thread = threading.Thread(target=self._id_loop, daemon=True)
        self.id_thread.start()

    def stop_id(self):
        self.id_stop.set()
        self.id_thread = None

    def _id_loop(self):
        # Short initial delay so we start identifying quickly
        for _ in range(4):
            if self.id_stop.is_set() or not self.playing:
                return
            time.sleep(1)
        while not self.id_stop.is_set() and self.playing:
            if not self.id_busy:
                try:
                    self._submit(self._identify())
                except Exception:
                    pass
            # Re-check every 30s instead of 45s
            for _ in range(30):
                if self.id_stop.is_set() or not self.playing:
                    return
                time.sleep(1)

    def id_now(self):
        if not self.playing:
            self.toast.show_msg("Play a station first")
            return
        if self.id_busy:
            self.toast.show_msg("Already identifying…")
            return
        self.song_l.setText("Listening…")
        self.toast.show_msg("Identifying…")
        try:
            self._submit(self._identify())
        except Exception as e:
            self.log(str(e))

    async def _identify(self):
        if self.id_busy:
            return
        self.id_busy = True
        try:
            self.sig.status.emit("Listening…")
            wav = str(SNIP / "sdr_song_id.wav")
            ok = await asyncio.to_thread(self.capture, wav, 7)
            if not ok:
                self.sig.status.emit("Capture failed")
                return
            song = await asyncio.to_thread(self.songrec, wav)
            if not song and self.ac_key:
                song = await asyncio.to_thread(self.acoustid, wav)
            if song:
                self.sig.result.emit(song)
            else:
                self.sig.status.emit("No match")
        except Exception as e:
            self.sig.status.emit(str(e))
        finally:
            self.id_busy = False

    def capture(self, path, sec=7):
        try:
            Path(path).unlink(missing_ok=True)
        except Exception:
            pass
        tries = []
        try:
            r = subprocess.run(["pactl", "get-default-sink"], capture_output=True, text=True, timeout=2)
            sink = (r.stdout or "").strip()
            if sink:
                tries.append(["ffmpeg", "-y", "-f", "pulse", "-i", f"{sink}.monitor",
                              "-t", str(sec), "-ac", "1", "-ar", "44100", path])
        except Exception:
            pass
        tries.append(["ffmpeg", "-y", "-f", "pulse", "-i", "default",
                      "-t", str(sec), "-ac", "1", "-ar", "44100", path])
        for cmd in tries:
            try:
                r = subprocess.run(cmd, capture_output=True, timeout=sec + 6)
                if r.returncode == 0 and Path(path).exists() and Path(path).stat().st_size > 2000:
                    return True
            except Exception:
                continue
        return False

    def songrec(self, wav):
        for b in ("/snap/bin/songrec", "songrec"):
            if b == "songrec" or Path(b).exists():
                bin_ = b
                break
        else:
            return None
        try:
            r = subprocess.run([bin_, "recognize", wav], capture_output=True, text=True, timeout=30)
            out = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()
            for line in out.splitlines():
                if " - " in line and "error" not in line.lower() and len(line) < 160:
                    a, t = line.split(" - ", 1)
                    return {"title": t.strip(), "artist": a.strip(), "album": "",
                            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        except Exception:
            return None
        return None

    def acoustid(self, wav):
        try:
            r = subprocess.run(["fpcalc", "-json", wav], capture_output=True, text=True, timeout=15)
            if r.returncode != 0:
                return None
            data = json.loads(r.stdout)
            fp, dur = data.get("fingerprint"), data.get("duration")
            if not fp:
                return None
            post = urllib.parse.urlencode({
                "client": self.ac_key.strip(), "meta": "recordings releasegroups compress",
                "duration": int(float(dur)), "fingerprint": fp,
            }).encode()
            req = urllib.request.Request("https://api.acoustid.org/v2/lookup", data=post,
                headers={"User-Agent": "SDR-Radio/1.0", "Content-Type": "application/x-www-form-urlencoded"}, method="POST")
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read().decode())
            if result.get("status") != "ok" or not result.get("results"):
                return None
            best = result["results"][0]
            if best.get("score", 0) < 0.25:
                return None
            recs = best.get("recordings") or []
            if not recs:
                return None
            rec = recs[0]
            title = rec.get("title") or "?"
            artists = ", ".join(a.get("name", "") for a in rec.get("artists", [])) or "?"
            album = (rec.get("releasegroups") or [{}])[0].get("title", "") if rec.get("releasegroups") else ""
            return {"title": title, "artist": artists, "album": album,
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        except Exception:
            return None

    def on_status(self, msg):
        if not self.song:
            self.song_l.setText(msg)
        self.log(f"🎵 {msg}")
        try:
            if getattr(self, "_scan_busy", False) or str(msg).lower().startswith("scanning"):
                self.statusBar().showMessage(str(msg))
        except Exception:
            pass

    def on_result(self, song):
        if song_match(song, self.song):
            self.log("♪ Same song — refreshing lyrics")
            threading.Thread(target=self._post, args=(song,), daemon=True).start()
            return
        self.song = song
        text = f"{song.get('artist','')} — {song.get('title','')}"
        self.song_l.setText(text)
        if hasattr(self, "song_l2"):
            self.song_l2.setText(text)
        if hasattr(self, "sp_song"):
            self.sp_song.setText(text)
        self.btn_fav.setEnabled(True)
        self.btn_yt.setEnabled(True)
        liked = self._is_fav(song)
        self.btn_fav.setChecked(liked)
        self.btn_fav.setIcon(load_icon("heart"))
        if hasattr(self, "sp_fav"):
            self.sp_fav.setEnabled(True)
            self.sp_fav.setChecked(liked)
            self.sp_fav.setIcon(load_icon("heart"))
        self.log(f"♪ {text}")
        self.toast.show_msg(f"♪  {text}")
        self.history.insert(0, song)
        self.history = self.history[:100]
        save_json(HIST_F, self.history)
        self.refresh_hist()
        threading.Thread(target=self._post, args=(song,), daemon=True).start()

    def _post(self, song):
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
                    g = lyricsgenius.Genius(self.gn_key, verbose=False, remove_section_headers=True, timeout=8)
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
        if not self.lrc or self.lrc_t0 is None:
            return
        el = time.time() - self.lrc_t0
        idx = 0
        for i, (ts, _) in enumerate(self.lrc):
            if ts <= el:
                idx = i
        new = "\n".join(ln for _, ln in self.lrc)
        if self.lyrics.toPlainText() != new:
            self.lyrics.setPlainText(new)

    def fetch_art(self, artist, title):
        ART.mkdir(parents=True, exist_ok=True)
        dest = ART / "current.jpg"
        urls = []
        for url_build in [lambda: self._itunes(artist, title), lambda: self._deezer(artist, title)]:
            try:
                u = url_build()
                if u:
                    urls.append(u)
            except Exception:
                pass
        for u in urls:
            try:
                req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0 SDR-Radio/1.0"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    dest.write_bytes(resp.read())
                if dest.exists() and dest.stat().st_size > 800:
                    return str(dest)
            except Exception:
                pass
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
            self._art_path = path
            pix = QPixmap(path)
            art = getattr(self, "sp_art", None) or getattr(self, "art", None)
            if art is None:
                return
            if pix.isNull():
                art.setText("♪")
                return
            side = max(1, art.width() or 280)
            scaled = pix.scaled(side, side, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            if scaled.width() >= side and scaled.height() >= side:
                scaled = scaled.copy((scaled.width()-side)//2, (scaled.height()-side)//2, side, side)
            art.setPixmap(scaled)
        except Exception:
            art = getattr(self, "sp_art", None) or getattr(self, "art", None)
            if art is not None:
                art.setText("♪")

    def fetch_lrc(self, artist, title):
        headers = {"User-Agent": "SDR-Radio/1.0[](https://github.com/nagesh147/sdr-radio)"}
        queries = [
            ("track+artist", {"track_name": title, "artist_name": artist}),
            ("q=artist+title", {"q": f"{artist} {title}".strip()}),
            ("q=title", {"q": title}),
        ]
        try:
            for label, params in queries:
                if not any(v for v in params.values() if v):
                    continue
                try:
                    q = urllib.parse.urlencode({k: v for k, v in params.items() if v})
                    req = urllib.request.Request(f"https://lrclib.net/api/search?{q}", headers=headers)
                    with urllib.request.urlopen(req, timeout=12) as resp:
                        results = json.loads(resp.read().decode())
                    if not results:
                        continue
                    best = None
                    for r in results:
                        if r.get("syncedLyrics"):
                            best = r
                            break
                    if not best:
                        best = results[0]
                    plain = (best.get("plainLyrics") or "").strip()
                    synced = (best.get("syncedLyrics") or "").strip()
                    self.log(f"LRCLIB ({label}): {best.get('trackName','?')} / {best.get('artistName','?')}")
                    if synced:
                        parsed = []
                        for ln in synced.splitlines():
                            m = re.match(r"\[(\d{1,2}):(\d{2})(?:\.(\d+))?\]\s*(.*)", ln.strip())
                            if m and m.group(4).strip():
                                ts = int(m.group(1))*60 + int(m.group(2)) + float("0."+(m.group(3) or "0"))
                                parsed.append((ts, m.group(4).strip()))
                        self.lrc = parsed
                        return "\n".join(x[1] for x in parsed) or plain
                    self.lrc = []
                    return plain
                except Exception as e:
                    self.log(f"LRCLIB {label}: {e}")
                    continue
            return ""
        except Exception as e:
            self.lrc = []
            self.log(f"LRCLIB error: {e}")
            return ""

    def open_yt(self):
        if not self.song:
            return
        q = f"{self.song.get('artist','')} {self.song.get('title','')}"
        QDesktopServices.openUrl(QUrl("https://www.youtube.com/results?search_query=" + urllib.parse.quote(q)))

    def _is_fav(self, song):
        k = (_norm(song.get("title")), _norm(song.get("artist")))
        return any((_norm(s.get("title")), _norm(s.get("artist"))) == k for s in self.favs)

    def toggle_fav(self):
        if not self.song:
            return
        k = (_norm(self.song.get("title")), _norm(self.song.get("artist")))
        if self._is_fav(self.song):
            self.favs = [s for s in self.favs if (_norm(s.get("title")), _norm(s.get("artist"))) != k]
            self.btn_fav.setChecked(False)
            if hasattr(self, "sp_fav"):
                self.sp_fav.setChecked(False)
            self.toast.show_msg("Removed like")
        else:
            self.favs.insert(0, self.song)
            self.favs = self.favs[:50]
            self.btn_fav.setChecked(True)
            if hasattr(self, "sp_fav"):
                self.sp_fav.setChecked(True)
            self.toast.show_msg("Liked")
        save_json(FAV_F, self.favs)
        self.refresh_favs()

    def fav_menu(self, pos):
        item = self.fav_list.itemAt(pos)
        if not item:
            return
        m = QMenu(self)
        m.addAction("Remove", lambda: self._remove_fav_item(item))
        m.exec_(self.fav_list.mapToGlobal(pos))

    def _remove_fav_item(self, item):
        s = item.data(Qt.UserRole)
        if not s:
            return
        k = (_norm(s.get("title")), _norm(s.get("artist")))
        self.favs = [x for x in self.favs if (_norm(x.get("title")), _norm(x.get("artist"))) != k]
        save_json(FAV_F, self.favs)
        self.refresh_favs()
        if self.song and song_match(self.song, s):
            self.btn_fav.setIcon(load_icon("heart"))
        self.toast.show_msg("Removed like")

    def refresh_hist(self):
        self.hist.clear()
        for s in self.history:
            artist = s.get("artist") or "?"
            title = s.get("title") or "?"
            it = QListWidgetItem(f"{title}  ·  {artist}")
            it.setToolTip(f"{artist} — {title}")
            it.setData(Qt.UserRole, s)
            self.hist.addItem(it)

    def refresh_favs(self):
        self.fav_list.clear()
        for s in self.favs:
            artist = s.get("artist") or "?"
            title = s.get("title") or "?"
            it = QListWidgetItem(f"{title}  ·  {artist}")
            it.setToolTip(f"{artist} — {title}")
            it.setData(Qt.UserRole, s)
            self.fav_list.addItem(it)

    def open_hist(self, item):
        s = item.data(Qt.UserRole)
        if not s:
            return
        self.song = s
        self.song_l.setText(f"{s.get('artist')} — {s.get('title')}")
        self.btn_fav.setEnabled(True)
        self.btn_yt.setEnabled(True)

    def open_fav(self, item):
        s = item.data(Qt.UserRole)
        if s:
            self.song = s
            self.song_l.setText(f"{s.get('artist')} — {s.get('title')}")
            self.btn_fav.setEnabled(True)
            self.btn_yt.setEnabled(True)



    def _toggle_lyrics_from_icon(self):
        """Icon next to play: show/hide lyrics in the right pane; fetch if empty."""
        show = not getattr(self, "_lyrics_open", False)
        if hasattr(self, "lyrics_toggle"):
            self.lyrics_toggle.setChecked(show)
        self._toggle_lyrics_panel()
        if show:
            txt = (self.lyrics.toPlainText() or "").strip()
            if self.song and (not txt or txt.startswith("No lyrics") or txt.startswith("Loading")):
                if not txt.startswith("Loading"):
                    self.lyrics_now()

    def _toggle_lyrics_panel(self):
        """Show/hide lyrics in the right sidebar (not under the player)."""
        show = bool(self.lyrics_toggle.isChecked())
        self._lyrics_open = show

        # Sync checkable lyric icons
        for bname in ("btn_lrc", "sp_lrc"):
            b = getattr(self, bname, None)
            if b is not None:
                b.blockSignals(True)
                b.setChecked(show)
                b.blockSignals(False)

        if show:
            # Remember previous right tab (if not already on lyrics)
            try:
                cur = self.right_stack.currentIndex() if hasattr(self, "right_stack") else 0
                if cur != 1:
                    self._right_tab_before_lyrics = cur
            except Exception:
                self._right_tab_before_lyrics = 0
            self._ensure_right_open_for_lyrics()
            self._switch_right_tab(1)  # Lyrics page
        else:
            # Restore previous tab if still on lyrics
            try:
                if hasattr(self, "right_stack") and self.right_stack.currentIndex() == 1:
                    prev = int(getattr(self, "_right_tab_before_lyrics", 0) or 0)
                    if prev == 1:
                        prev = 0
                    self._switch_right_tab(prev)
            except Exception:
                pass

        # Center player stays expanded (lyrics no longer steal vertical space)
        self._layout_player_for_lyrics(show)
        try:
            self._save_prefs()
        except Exception:
            pass

    def _ensure_right_open_for_lyrics(self):
        """Expand the right sidebar so lyrics are readable."""
        rp = getattr(self, "right_panel", None)
        if rp is None:
            return
        try:
            need_open = (
                not rp.isVisible()
                or rp.maximumWidth() == 0
                or rp.maximumWidth() <= 60
                or not getattr(self, "right_stack", None)
                or not self.right_stack.isVisible()
            )
        except Exception:
            need_open = True
        if need_open:
            rp.setVisible(True)
            rp.setMinimumWidth(240)
            rp.setMaximumWidth(360)
            try:
                self.split.widget(2).setVisible(True)
            except Exception:
                pass
            self._right_expanded = True
            labels = getattr(self, "_nav_labels", ["  Library", "  Lyrics", "  Tools", "  Log"])
            for b, lab in zip(getattr(self, "nav_btns", []), labels):
                b.setText(lab)
            if hasattr(self, "right_stack"):
                self.right_stack.setVisible(True)
            if hasattr(self, "split"):
                total = max(900, self.split.width())
                self.split.setSizes([int(total * 0.26), int(total * 0.48), int(total * 0.26)])
        else:
            # Already open — widen a bit for lyrics
            try:
                if rp.maximumWidth() < 300:
                    rp.setMinimumWidth(240)
                    rp.setMaximumWidth(360)
            except Exception:
                pass

    def _layout_player_for_lyrics(self, lyrics_open: bool = False):
        """Shared player sizing (identical for SDR + Internet)."""
        self._lyrics_open = bool(lyrics_open)

        try:
            mid_h = max(300, self.mid_panel.height() if hasattr(self, "mid_panel") else 600)
        except Exception:
            mid_h = 600
        tuner_h = 0
        try:
            if hasattr(self, "tuner_frame") and self.tuner_frame.isVisible():
                tuner_h = max(120, self.tuner_frame.sizeHint().height())
        except Exception:
            tuner_h = 140
        avail = max(200, mid_h - tuner_h - 40)

        # One art size for both modes (Internet layout is the reference)
        art_side = min(360, max(240, int(avail * 0.60)))
        title_px, sub_px, song_px = 28, 13, 14
        play_sz, icon_sz = 60, 44
        play_icon, icon_icon = 28, 18
        sp_margins = (32, 28, 32, 20)

        song_color = "#30d158" if getattr(self, "dark", True) else "#248a3d"
        sub_color = "#8e8e93" if getattr(self, "dark", True) else "#6e6e73"
        art_bg = "#2c2c2e" if getattr(self, "dark", True) else "#f2f2f7"
        art_fg = "#636366" if getattr(self, "dark", True) else "#aeaeb2"
        art_radius = max(12, art_side // 12)
        art_font = max(32, art_side // 4)

        if hasattr(self, "spotify_panel"):
            self.spotify_panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
            self.spotify_panel.setVisible(True)
            if hasattr(self, "_spotify_layout"):
                self._spotify_layout.setContentsMargins(*sp_margins)
            self.sp_art.setFixedSize(art_side, art_side)
            self.sp_art.setStyleSheet(
                f"QLabel#art {{ background:{art_bg}; border-radius:{art_radius}px; "
                f"color:{art_fg}; font-size:{art_font}px; }}"
            )
            self.sp_title.setStyleSheet(f"font-size:{title_px}px; font-weight:700;")
            self.sp_sub.setStyleSheet(f"font-size:{sub_px}px; color:{sub_color};")
            self.sp_song.setStyleSheet(f"font-size:{song_px}px; color:{song_color};")
            self.sp_play.setFixedSize(play_sz, play_sz)
            self.sp_play.setIconSize(QSize(play_icon, play_icon))
            for b in (self.sp_lrc, self.sp_fav):
                b.setFixedSize(icon_sz, icon_sz)
                b.setIconSize(QSize(icon_icon, icon_icon))

        ml = getattr(self, "_mid_layout", None)
        if ml is not None:
            try:
                if hasattr(self, "spotify_panel"):
                    ml.setStretch(ml.indexOf(self.spotify_panel), 1)
            except Exception:
                pass

        path = getattr(self, "_art_path", None)
        if path:
            self.show_art(path)

        try:
            if hasattr(self, "mid_panel"):
                self.mid_panel.updateGeometry()
            if hasattr(self, "spotify_panel"):
                self.spotify_panel.updateGeometry()
        except Exception:
            pass


    def lyrics_now(self):
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
                    g = lyricsgenius.Genius(self.gn_key, verbose=False, remove_section_headers=True, timeout=8)
                    song = g.search_song(title, artist)
                    if song and song.lyrics:
                        lines = song.lyrics.splitlines()
                        text = "\n".join(lines[1:]).strip() if lines and "lyrics" in lines[0].lower() else song.lyrics.strip()
                        if text:
                            text += "\n\n— Genius"
                except Exception as e:
                    self.log(f"Genius: {e}")
            self.sig.lyrics.emit(text or "No lyrics found.")
        threading.Thread(target=task, daemon=True).start()

    def eventFilter(self, obj, ev):
        from PyQt5.QtCore import QEvent
        # Global reload: accept ShortcutOverride so children don't eat Ctrl+R / F5
        try:
            et = ev.type()
            if et in (QEvent.KeyPress, QEvent.ShortcutOverride):
                if self._is_reload_key(ev):
                    if et == QEvent.ShortcutOverride:
                        ev.accept()
                        return True
                    # KeyPress → do the reload
                    self.reload_app()
                    return True
        except Exception:
            pass
        left = self.split.widget(0) if hasattr(self, "split") else None
        right = self.split.widget(2) if hasattr(self, "split") else None
        if left is not None and obj is left:
            if ev.type() == QEvent.Enter:
                if hasattr(self, "btn_hide_left"):
                    try: hasattr(self.btn_hide_left, "fade") and self.btn_hide_left.fade(True)
                    except Exception: pass
            elif ev.type() == QEvent.Leave:
                if hasattr(self, "btn_hide_left"):
                    hasattr(self.btn_hide_left, "fade") and self.btn_hide_left.fade(False)
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
        subprocess.run(["sudo", "mkdir", "-p", "/run/readsb"])
        subprocess.run(["sudo", "chmod", "777", "/run/readsb"])
        subprocess.run(["sudo", "systemctl", "restart", "readsb"])
        time.sleep(1.2)
        subprocess.Popen(["xdg-open", "http://localhost/tar1090/"])
        self.toast.show_msg("Flights opened")

    def start_wx(self):
        self.stop()
        subprocess.Popen(["satdump-ui"])
        self.toast.show_msg("Weather launched")

    def start_ais(self):
        self.stop()
        threading.Thread(target=lambda: subprocess.Popen(
            ["AIS-catcher", "-d", "00000001", "-s", "1536k", "-a", "33", "-N", "8100"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL), daemon=True).start()
        threading.Thread(target=lambda: (time.sleep(2), subprocess.Popen(
            ["xdg-open", "http://localhost:8100/?lat=17.385&lon=78.4867&zoom=7&tab=map"])), daemon=True).start()
        self.toast.show_msg("AIS map opening")

    def test_dongle(self):
        def task():
            proc = subprocess.Popen(["timeout", "4", "rtl_test", "-t"],
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for line in proc.stdout:
                if line.strip():
                    self.log(line.rstrip())
        threading.Thread(target=task, daemon=True).start()


    def start_auto_scan(self):
        """Scan all defined bands and add stations to the list."""
        if getattr(self, "_scan_busy", False):
            self.toast.show_msg("Scan already running")
            return
        self._scan_busy = True
        self.toast.show_msg("Scanning all bands…")
        self.log("Auto-scan started (all bands)")
        try:
            self.statusBar().showMessage("Scanning…")
        except Exception:
            pass
        try:
            self.stop()
        except Exception:
            pass
        threading.Thread(target=self._auto_scan_worker, daemon=True).start()

    def _auto_scan_worker(self):
        import csv, tempfile, os
        found = []  # list of (freq_mhz, mode, band_name, db)
        try:
            has_power = False
            try:
                r = subprocess.run(["which", "rtl_power"], capture_output=True, text=True, timeout=2)
                has_power = r.returncode == 0 and bool(r.stdout.strip())
            except Exception:
                pass

            if not has_power:
                self.sig.log.emit("rtl_power not found – install rtl-sdr")
                self._scan_busy = False
                QTimer.singleShot(0, lambda: self.toast.show_msg("Install rtl_power first"))
                return

            # Scan each band from BANDS
            for bname, lo, hi, mode in BANDS:
                if not getattr(self, "_scan_busy", True):
                    break
                # Skip very wide or awkward ranges for speed; still cover main ones
                span = float(hi) - float(lo)
                if span <= 0:
                    continue
                # Bin size: finer for narrow bands, coarser for wide
                if span <= 2:
                    bin_hz = "5k"
                elif span <= 30:
                    bin_hz = "25k"
                else:
                    bin_hz = "100k"
                # Integration time scales with band width (cap total time)
                dwell = "2"
                end_s = "12s" if span > 50 else "8s"
                tmp = tempfile.mktemp(suffix=".csv")
                cmd = [
                    "rtl_power",
                    "-f", f"{lo}M:{hi}M:{bin_hz}",
                    "-i", dwell,
                    "-e", end_s,
                    tmp,
                ]
                self.sig.log.emit(f"Scan {bname}: {' '.join(cmd)}")
                try:
                    self.sig.status.emit(f"Scanning {bname} ({lo}–{hi} MHz)…")
                except Exception:
                    pass
                try:
                    subprocess.run(cmd, capture_output=True, timeout=30)
                except subprocess.TimeoutExpired:
                    pass
                except Exception as e:
                    self.sig.log.emit(f"Scan {bname} error: {e}")
                    continue

                rows = []
                try:
                    with open(tmp, newline="") as f:
                        for row in csv.reader(f):
                            if len(row) < 7:
                                continue
                            try:
                                hz_low = float(row[2])
                                step = float(row[4])
                                vals = [float(x) for x in row[6:] if x.strip()]
                                for i, db in enumerate(vals):
                                    freq_mhz = (hz_low + i * step) / 1e6
                                    rows.append((freq_mhz, db))
                            except Exception:
                                continue
                finally:
                    try:
                        os.unlink(tmp)
                    except Exception:
                        pass

                if not rows:
                    continue
                dbs = [r[1] for r in rows]
                noise = sorted(dbs)[max(0, len(dbs) // 5)]
                # Higher threshold for noisy wide bands
                thresh = noise + (10.0 if span > 20 else 7.0)
                peaks = []
                rows.sort(key=lambda x: x[0])
                for i in range(1, len(rows) - 1):
                    f, db = rows[i]
                    if db >= thresh and db >= rows[i - 1][1] and db >= rows[i + 1][1]:
                        peaks.append((f, db))
                peaks.sort(key=lambda x: -x[1])
                used = []
                for f, db in peaks:
                    fr = round(f, 2) if mode == "am" and f < 30 else round(f, 1)
                    if any(abs(fr - u) < (0.05 if f < 30 else 0.15) for u in used):
                        continue
                    used.append(fr)
                    found.append((fr, mode, bname, db))

        except Exception as e:
            self.sig.log.emit(f"Scan error: {e}")
        finally:
            self._scan_busy = False

        def apply():
            if not found:
                self.toast.show_msg("No stations found")
                self.log("Auto-scan: no peaks")
                try:
                    self.statusBar().showMessage("Scan done: nothing found")
                except Exception:
                    pass
                return
            cat = "Scanned"
            existing = set()
            for items in self.stations.values():
                for s in items or []:
                    if isinstance(s, dict):
                        try:
                            existing.add(round(float(s.get("freq", 0)), 2))
                        except Exception:
                            pass
            self.stations.setdefault(cat, [])
            added = 0
            for fr, mode, bname, db in sorted(found, key=lambda x: x[0]):
                key = round(float(fr), 2)
                if key in existing:
                    continue
                name = f"{bname} {fr}"
                self.stations[cat].append({
                    "name": name,
                    "freq": float(fr),
                    "mode": mode,
                })
                existing.add(key)
                added += 1
            save_json(STATIONS_F, self.stations)
            cats = [self.cats.item(i).text() for i in range(self.cats.count())]
            if cat not in cats:
                self.cats.addItem(cat)
            for i in range(self.cats.count()):
                if self.cats.item(i).text() == cat:
                    self.cats.setCurrentRow(i)
                    break
            self.load_cat(cat)
            self.toast.show_msg(f"Scan done: +{added} stations")
            self.log(f"Auto-scan: +{added} across all bands")
            try:
                self.statusBar().showMessage(f"Scan done: +{added} stations")
            except Exception:
                pass

        QTimer.singleShot(0, apply)



    def _set_tuner_visible(self, on: bool):
        """Show/hide SDR tuner (band, mode, gain, freq scale) as a whole card."""
        on = bool(on)
        if hasattr(self, "tuner_frame"):
            self.tuner_frame.setVisible(on)
            # Collapse height so center player can expand on Internet mode
            if on:
                self.tuner_frame.setMinimumHeight(0)
                self.tuner_frame.setMaximumHeight(16777215)
            else:
                self.tuner_frame.setMinimumHeight(0)
                self.tuner_frame.setMaximumHeight(0)
        for wname in ("scale", "freq", "band", "mode", "gain"):
            w = getattr(self, wname, None)
            if w is not None:
                w.setVisible(on)
        # Anonymous Band / Mode / Gain labels live in the same card — hide with frame

    def _set_player_layout(self, spotify=False):
        """Player chrome is shared (Internet layout). Only tuner differs for SDR."""
        try:
            # Always use the same centered player for SDR + Internet
            if hasattr(self, "spotify_panel"):
                self.spotify_panel.setVisible(True)
            if hasattr(self, "player_stack"):
                self.player_stack.setVisible(False)
            if hasattr(self, "_shared_controls"):
                self._shared_controls.setVisible(False)
            # Tuner icon + body: SDR only
            if hasattr(self, "btn_toggle_tuner"):
                self.btn_toggle_tuner.setVisible(not spotify)
                self.btn_toggle_tuner.setEnabled(not spotify)
            want = (not spotify) and bool(getattr(self, "_tuner_open", True))
            self._set_tuner_visible(want)
        except Exception as e:
            try:
                self.log(f"layout: {e}")
            except Exception:
                pass


    def _on_left_mode(self, idx):
        is_net = idx == 1
        if is_net:
            self._show_internet_ui(True)
            self._apply_stream_mode(True)
        else:
            self._show_internet_ui(False)
            # After restoring SDR cats, load_cat applies stream mode if cat is Internet
            cat = None
            try:
                it = self.cats.currentItem()
                cat = it.text() if it else None
            except Exception:
                cat = None
            self._apply_stream_mode(self._cat_is_internet(cat) if cat else False)

    def _show_internet_ui(self, on):
        """Switch left lists between local SDR stations and internet radio."""
        if on:
            # Load internet categories once
            if not getattr(self, "_net_ready", False):
                self._init_internet_categories()
                self._net_ready = True
            # Populate cats with net categories
            self.cats.blockSignals(True)
            self.cats.clear()
            for c in getattr(self, "_net_categories", []):
                self.cats.addItem(c)
            self.cats.blockSignals(False)
            if self.cats.count():
                self.cats.setCurrentRow(0)
                self._load_internet_cat(self.cats.currentItem().text())
        else:
            # Restore SDR categories
            self.cats.blockSignals(True)
            self.cats.clear()
            for k in self.stations:
                self.cats.addItem(k)
            self.cats.blockSignals(False)
            if self.cats.count():
                self.cats.setCurrentRow(0)
                self.load_cat(self.cats.currentItem().text())

    def _init_internet_categories(self):
        """Popular genres + India focus – stations loaded on demand from radio-browser."""
        self._net_categories = [
            "Top voted",
            "India",
            "Bollywood",
            "Tamil",
            "Telugu",
            "Hindi",
            "News",
            "Talk",
            "Pop",
            "Rock",
            "Jazz",
            "Classical",
            "Electronic",
            "Dance",
            "Hip-Hop",
            "Country",
            "Reggae",
            "Metal",
            "Blues",
            "Folk",
            "Ambient",
            "Lounge",
            "Sports",
            "Christian",
            "World",
            "UK",
            "USA",
            "Germany",
            "France",
            "Search…",
        ]
        self._net_cache = {}



    def _on_net_list(self, stations, label):
        self.stations_list.clear()
        if not stations:
            self.stations_list.addItem(label or "No stations")
            self.statusBar().showMessage(label or "No stations")
            return
        for s in stations:
            if not isinstance(s, dict):
                continue
            name = (s.get("name") or "Station").strip()
            url = (s.get("url_resolved") or s.get("url") or "").strip()
            if not url:
                continue
            country = s.get("countrycode") or s.get("country") or ""
            text = f"{name}  ·  {country}" if country else name
            it = QListWidgetItem(text)
            it.setToolTip(f"{name}\n{url}")
            it.setData(Qt.UserRole, {"name": name, "url": url, "mode": "net"})
            self.stations_list.addItem(it)
        self.statusBar().showMessage(f"Internet: {self.stations_list.count()} – {label}")

    def _load_internet_cat(self, cat):
        self.stations_list.clear()
        self.stations_list.addItem("Loading…")
        self.statusBar().showMessage(f"Loading {cat}…")

        def work():
            try:
                if cat in getattr(self, "_net_cache", {}):
                    self.sig.net_list.emit(self._net_cache[cat], cat)
                    return
                if cat == "Search…":
                    self.sig.net_list.emit([], "Search…")
                    return
                if cat == "Top voted":
                    stations = self._radio_browser_get("/json/stations/topvote/80")
                elif cat in ("India", "UK", "USA", "Germany", "France"):
                    cmap = {
                        "India": "India",
                        "UK": "The United Kingdom Of Great Britain And Northern Ireland",
                        "USA": "The United States Of America",
                        "Germany": "Germany",
                        "France": "France",
                    }
                    q = urllib.parse.quote(cmap.get(cat, cat))
                    stations = self._radio_browser_get(
                        f"/json/stations/search?country={q}&limit=80&hidebroken=true&order=votes"
                    )
                else:
                    q = urllib.parse.quote(cat.lower())
                    stations = self._radio_browser_get(
                        f"/json/stations/search?tag={q}&limit=80&hidebroken=true&order=votes"
                    )
                if not isinstance(stations, list):
                    stations = []
                self._net_cache[cat] = stations
                self.sig.log.emit(f"Internet {cat}: {len(stations)} stations")
                self.sig.net_list.emit(stations, cat)
            except Exception as e:
                self.sig.log.emit(f"Internet error: {e}")
                self.sig.net_list.emit([], f"Error: {e}")

        threading.Thread(target=work, daemon=True).start()

        # Handle Search… on main thread after empty emit
        if cat == "Search…":
            def do_search():
                text, ok = QInputDialog.getText(self, "Search radio", "Name / keyword:")
                if ok and text.strip():
                    self._search_internet(text.strip())
            QTimer.singleShot(100, do_search)

    def _search_internet(self, query):
        self.stations_list.clear()
        self.stations_list.addItem("Searching…")
        self.statusBar().showMessage(f"Searching “{query}”…")

        def work():
            try:
                q = urllib.parse.quote(query)
                stations = self._radio_browser_get(
                    f"/json/stations/search?name={q}&limit=80&hidebroken=true"
                )
                if not isinstance(stations, list):
                    stations = []
                self.sig.log.emit(f"Search {query}: {len(stations)}")
                self.sig.net_list.emit(stations, f"Search: {query}")
            except Exception as e:
                self.sig.log.emit(f"Search error: {e}")
                self.sig.net_list.emit([], f"Error: {e}")

        threading.Thread(target=work, daemon=True).start()

    def _radio_browser_get(self, path, timeout=15):
        mirrors = [
            "https://de1.api.radio-browser.info",
            "https://nl1.api.radio-browser.info",
            "https://at1.api.radio-browser.info",
            "https://fr1.api.radio-browser.info",
        ]
        last_err = None
        for base in mirrors:
            try:
                url = base + path
                req = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "SDR-Radio/1.0",
                        "Accept": "application/json",
                    },
                )
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    data = json.loads(resp.read().decode())
                    return data
            except Exception as e:
                last_err = e
                continue
        raise RuntimeError(last_err or "all mirrors failed")


    def free_all(self):
        self.stop()
        subprocess.run(["sudo", "systemctl", "stop", "readsb"], stderr=subprocess.DEVNULL)
        subprocess.run(["killall", "-9", "sdrpp", "satdump", "satdump-ui", "AIS-catcher"], stderr=subprocess.DEVNULL)
        self.toast.show_msg("All SDR processes stopped")


    def _ensure_dongle_ready(self):
        """Called once at startup – reset only if clearly locked."""
        self.log("Checking dongle…")
        subprocess.run(["killall", "-9", "rtl_fm", "play", "ffplay", "mpv"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.3)

        try:
            r = subprocess.run(["lsusb"], capture_output=True, text=True, timeout=3)
            if "0bda" not in r.stdout.lower() and "rtl283" not in r.stdout.lower():
                self.log("No RTL-SDR seen in lsusb")
                return
        except Exception:
            pass

        if self._dongle_ok():
            self.log("Dongle OK")
            return

        self.log("Dongle busy – soft reset")
        self._soft_reset_dongle()
        time.sleep(0.6)
        if self._dongle_ok():
            self.log("Dongle recovered")
        else:
            self.log("Dongle still locked – unplug/replug once if play fails")




    def _restore_right_panel(self):
        """Open right sidebar by default (or per saved prefs)."""
        try:
            want = True
            if isinstance(getattr(self, "cfg", None), dict):
                want = bool(self.cfg.get("right_visible", True))
            rp = getattr(self, "right_panel", None)
            if rp is None:
                return
            if want:
                rp.setMinimumWidth(200)
                rp.setMaximumWidth(300)
                rp.setVisible(True)
                try:
                    self.split.widget(2).setVisible(True)
                except Exception:
                    pass
                self._right_expanded = True
                labels = getattr(self, "_nav_labels", ["  Library", "  Lyrics", "  Tools", "  Log"])
                for b, lab in zip(getattr(self, "nav_btns", []), labels):
                    b.setText(lab)
                if hasattr(self, "right_stack"):
                    self.right_stack.setVisible(True)
                if hasattr(self, "btn_show_right"):
                    self.btn_show_right.setVisible(False)
                if hasattr(self, "split"):
                    total = max(900, self.split.width())
                    self.split.setSizes([int(total * 0.28), int(total * 0.50), int(total * 0.22)])
            else:
                self._collapse_right_on_start()
        except Exception as e:
            try:
                self.log(f"restore right: {e}")
            except Exception:
                pass

    def _collapse_right_on_start(self):
        """Fully hide right sidebar – no icon rail."""
        try:
            self._right_expanded = True
            rp = getattr(self, "right_panel", None)
            if rp is not None:
                rp.setVisible(False)
                rp.setMinimumWidth(0)
                rp.setMaximumWidth(0)
            if hasattr(self, "split"):
                try:
                    self.split.widget(2).setVisible(False)
                except Exception:
                    pass
                total = max(900, self.split.width())
                self.split.setSizes([int(total * 0.34), int(total * 0.66), 0])
            # Show the reopen button in the center top-right
            if hasattr(self, "btn_show_right"):
                self.btn_show_right.setVisible(True)
        except Exception as e:
            try:
                self.log(f"hide right: {e}")
            except Exception:
                pass



    def _load_prefs(self):
        """Restore user settings from config."""
        p = self.cfg if isinstance(self.cfg, dict) else {}
        # Theme
        self.dark = bool(p.get("dark", False))
        # Auto song ID (status only via hover tooltip)
        if hasattr(self, "btn_auto_side"):
            on = bool(p.get("song_id", True))
            self.cfg["song_id"] = on
            self._sync_auto_id_tooltip()
        # Gain already loaded earlier
        # Lyrics panel
        self._lyrics_open = bool(p.get("lyrics_open", False))
        # Tuner panel (band/mode/gain/freq)
        self._tuner_open = bool(p.get("tuner_open", True))
        if hasattr(self, "btn_toggle_tuner"):
            self.btn_toggle_tuner.blockSignals(True)
            self.btn_toggle_tuner.setChecked(self._tuner_open)
            self.btn_toggle_tuner.blockSignals(False)
            if not getattr(self, "_stream_mode", False):
                self._set_tuner_visible(self._tuner_open)
        # Right sidebar visible/expanded
        self._right_expanded = bool(p.get("right_expanded", True))
        self._right_visible = bool(p.get("right_visible", True))

    def _save_prefs(self):
        """Persist current UI choices."""
        try:
            self.cfg["dark"] = bool(getattr(self, "dark", False))
            self.cfg["song_id"] = bool(self.cfg.get("song_id", True))
            self.cfg["lyrics_open"] = bool(
                getattr(self, "lyrics_toggle", None) and self.lyrics_toggle.isChecked()
            )
            self.cfg["tuner_open"] = bool(getattr(self, "_tuner_open", True))
            self.cfg["right_expanded"] = bool(getattr(self, "_right_expanded", False))
            rp = getattr(self, "right_panel", None)
            self.cfg["right_visible"] = bool(rp is not None and rp.isVisible())
            if hasattr(self, "gain"):
                self.cfg["gain"] = int(self.gain.value())
            # Remember last frequency / mode / station
            if hasattr(self, "freq"):
                self.cfg["last_freq"] = float(self.freq.value())
            if hasattr(self, "mode"):
                self.cfg["last_mode"] = self.mode.currentText()
            if getattr(self, "_current_station", None):
                self.cfg["last_station"] = self._current_station
            save_json(CONFIG, self.cfg)
        except Exception as e:
            try:
                self.log(f"save prefs: {e}")
            except Exception:
                pass

    def _apply_startup(self):
        try:
            self._load_prefs()
        except Exception:
            pass
        try:
            self._restore_right_panel()
        except Exception:
            pass
        try:
            self._ensure_dongle_ready()
        except Exception as e:
            self.log(f"dongle check: {e}")
        try:
            su = self.cfg.get("startup") or {}
        except Exception:
            su = {}
        cat = su.get("cat")
        name = su.get("name")
        freq = su.get("freq")
        mode = su.get("mode")
        try:
            if cat and cat in self.stations and hasattr(self, "cats"):
                items = [self.cats.item(i).text() for i in range(self.cats.count())]
                if cat in items:
                    self.cats.setCurrentRow(items.index(cat))
                    self.load_cat(cat)
            if name and hasattr(self, "stations_list"):
                for i in range(self.stations_list.count()):
                    it = self.stations_list.item(i)
                    s = it.data(Qt.UserRole)
                    if isinstance(s, dict) and s.get("name") == name:
                        self.stations_list.setCurrentRow(i)
                        self.play_item(it)
                        return
            if freq:
                m = mode or mode_for_freq(float(freq))
                self.freq.blockSignals(True)
                self.freq.setValue(float(freq))
                self.freq.blockSignals(False)
                try:
                    self.scale.setValue(float(freq))
                except Exception:
                    pass
                self.mode.blockSignals(True)
                self.mode.setCurrentText(m)
                self.mode.blockSignals(False)
                self.play(float(freq), m, name or ("%.1f MHz" % float(freq)))
                return
            if self.stations:
                cat0 = next(iter(self.stations))
                st0 = self.stations[cat0][0]
                if hasattr(self, "cats"):
                    items = [self.cats.item(i).text() for i in range(self.cats.count())]
                    if cat0 in items:
                        self.cats.setCurrentRow(items.index(cat0))
                        self.load_cat(cat0)
                self.play(float(st0["freq"]), st0.get("mode") or mode_for_freq(st0["freq"]), st0["name"])
        except Exception as e:
            self.log("Startup error: %s" % e)


    def _switch_right_tab(self, idx):
        for i, b in enumerate(self.nav_btns):
            b.setChecked(i == idx)
        self.right_stack.setCurrentIndex(idx)
        # Keep lyrics icon state in sync with whether Lyrics tab is active
        if idx == 1:
            self._lyrics_open = True
            if hasattr(self, "lyrics_toggle"):
                self.lyrics_toggle.setChecked(True)
            for bname in ("btn_lrc", "sp_lrc"):
                b = getattr(self, bname, None)
                if b is not None:
                    b.blockSignals(True)
                    b.setChecked(True)
                    b.blockSignals(False)
            # Ensure sidebar is wide enough if user navigated here
            try:
                self._ensure_right_open_for_lyrics()
            except Exception:
                pass
        else:
            # Leaving lyrics tab via nav closes lyrics mode (icon unchecks)
            if getattr(self, "_lyrics_open", False):
                self._lyrics_open = False
                if hasattr(self, "lyrics_toggle"):
                    self.lyrics_toggle.setChecked(False)
                for bname in ("btn_lrc", "sp_lrc"):
                    b = getattr(self, bname, None)
                    if b is not None:
                        b.blockSignals(True)
                        b.setChecked(False)
                        b.blockSignals(False)

    def _toggle_right_sidebar(self):
        rp = getattr(self, "right_panel", None)
        if rp is None:
            return
        # Currently hidden / collapsed → show expanded
        if not rp.isVisible() or rp.maximumWidth() == 0 or rp.maximumWidth() <= 60:
            rp.setMinimumWidth(220)
            rp.setMaximumWidth(340)
            rp.setVisible(True)
            try:
                self.split.widget(2).setVisible(True)
            except Exception:
                pass
            self._right_expanded = True
            labels = getattr(self, "_nav_labels", ["  Library", "  Lyrics", "  Tools", "  Log"])
            for b, lab in zip(getattr(self, "nav_btns", []), labels):
                b.setText(lab)
            if hasattr(self, "right_stack"):
                self.right_stack.setVisible(True)
            # Hide center-edge reopen breadcrumb while open
            if hasattr(self, "btn_show_right"):
                self.btn_show_right.setVisible(False)
            if hasattr(self, "split"):
                total = max(900, self.split.width())
                self.split.setSizes([int(total * 0.28), int(total * 0.50), int(total * 0.22)])
            return

        # Visible → fully hide, show reopen breadcrumb in center edge
        self._right_expanded = False
        rp.setVisible(False)
        rp.setMinimumWidth(0)
        rp.setMaximumWidth(0)
        try:
            self.split.widget(2).setVisible(False)
        except Exception:
            pass
        if hasattr(self, "split"):
            total = max(900, self.split.width())
            self.split.setSizes([int(total * 0.34), int(total * 0.66), 0])
        # Breadcrumb to open the right panel again
        if hasattr(self, "btn_show_right"):
            self.btn_show_right.setVisible(True)
            self.btn_show_right.raise_()
            self.btn_show_right.setToolTip("Show side panel")


    def closeEvent(self, e):
        # In-process reload replaces this window — skip process teardown
        if getattr(self, "_closing_for_reload", False):
            try:
                app = QApplication.instance()
                if app is not None:
                    app.removeEventFilter(self)
            except Exception:
                pass
            e.accept()
            return
        try:
            self._save_prefs()
        except Exception:
            pass
        try:
            self.stop()
        except Exception:
            pass
        subprocess.run(["killall", "-9", "rtl_fm", "play", "ffplay", "mpv"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            if getattr(self, "aio_loop", None):
                self.aio_loop.call_soon_threadsafe(self.aio_loop.stop)
        except Exception:
            pass
        try:
            LOCK.unlink(missing_ok=True)
        except Exception:
            pass
        e.accept()


def main():
    acquire_single_instance_lock()
    app = QApplication(sys.argv)
    app.setApplicationName("SDR Radio")
    app.setDesktopFileName("sdr-control")
    app.setStyle("Fusion")
    w = App()
    app._sdr_main = w  # hard ref (also used after in-process reload)
    w.show()
    def cleanup():
        # Don't tear down if we're mid-reload (shouldn't quit, but be safe)
        if getattr(getattr(app, "_sdr_main", None), "_closing_for_reload", False):
            return
        subprocess.run(["killall", "-9", "rtl_fm", "play", "ffplay", "mpv"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            LOCK.unlink(missing_ok=True)
        except Exception:
            pass
    app.aboutToQuit.connect(cleanup)
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
