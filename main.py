import sys, os, json, time, math, ctypes, threading, subprocess
import comtypes, keyboard
from ctypes import cast, POINTER
from comtypes import CLSCTX_ALL, GUID, IUnknown
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
from pycaw.api.mmdeviceapi import IMMDeviceEnumerator
from PyQt6.QtWidgets import (
    QApplication, QWidget, QScrollArea, QVBoxLayout,
    QHBoxLayout, QLabel, QPushButton, QSystemTrayIcon, QMenu, QFileDialog,
    QLineEdit,
)
from PyQt6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve,
    pyqtSignal, QObject, QRectF, QRect, QPoint, QVariantAnimation,
)
from PyQt6.QtGui import (
    QPainter, QColor, QFont, QPainterPath, QLinearGradient, QPen, QBrush,
    QFontMetrics, QCursor, QWheelEvent, QFontDatabase, QKeySequence,
    QIcon, QPixmap, QAction,
)

def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False

def _is_frozen() -> bool:
    return getattr(sys, "frozen", False)

def show_admin_required_message():
    if _is_frozen():
        ctypes.windll.user32.MessageBoxW(
            0,
            "Audio Device Switcher needs to run as Administrator.\n\n"
            "Right-click the app icon and choose \"Run as administrator\", "
            "then try again.",
            "Administrator privileges required",
            0x10,
        )
    else:
        ctypes.windll.user32.MessageBoxW(
            0,
            "Audio Device Switcher needs to run as Administrator.\n\n"
            "You are running this as a Python script. Open your terminal "
            "as Administrator (right-click → \"Run as administrator\"), "
            "then run the script again:\n\n"
            "    python main.py",
            "Administrator privileges required — Python script",
            0x10,
        )

def show_admin_needed_for_action_message():
    ctypes.windll.user32.MessageBoxW(
        0,
        "Administrator permission was not granted.\n\n"
        "This action requires admin rights to register a Task Scheduler "
        "entry. Click OK and try again, accepting the UAC prompt this time.",
        "Administrator required",
        0x10,
    )

def relaunch_as_admin() -> bool:
    try:
        exe = sys.executable
        params = " ".join(f'"{a}"' for a in sys.argv)
        ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
        return ret > 32
    except Exception:
        return False

TASK_NAME = "AudioDeviceSwitcherStartup"

def app_exe_path() -> str:
    if getattr(sys, "frozen", False):
        return sys.executable
    return os.path.abspath(__file__)

def is_startup_task_installed() -> bool:
    try:
        result = subprocess.run(
            ["schtasks", "/Query", "/TN", TASK_NAME],
            capture_output=True, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return result.returncode == 0
    except Exception:
        return False

def _run_elevated_bat(bat_lines: list[str], timeout_sec: int = 25) -> tuple[bool, str]:
    temp_dir = os.environ.get("TEMP") or os.environ.get("TMP") or os.getcwd()
    token = str(int(time.time() * 1000))
    bat_path = os.path.join(temp_dir, f"ads_task_{token}.bat")
    status_path = os.path.join(temp_dir, f"ads_status_{token}.txt")
    full_lines = ["@echo off"] + bat_lines + [
        f'if errorlevel 1 (echo FAIL > "{status_path}") else (echo OK > "{status_path}")',
        f'del "%~f0"',
    ]
    try:
        with open(bat_path, "w", encoding="utf-8") as f:
            f.write("\r\n".join(full_lines) + "\r\n")
    except Exception as e:
        return False, str(e)
    try:
        ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", bat_path, "", None, 0)
        if ret <= 32:
            try:
                os.remove(bat_path)
            except Exception:
                pass
            return False, "denied"
    except Exception as e:
        return False, str(e)
    waited = 0.0
    while waited < timeout_sec:
        if os.path.exists(status_path):
            try:
                content = open(status_path, encoding="utf-8").read().strip()
            except Exception:
                content = ""
            try:
                os.remove(status_path)
            except Exception:
                pass
            return content == "OK", content
        time.sleep(0.25)
        waited += 0.25
    return False, "timeout"

def install_startup_task_elevated() -> tuple[bool, str]:
    exe = app_exe_path()
    bat_lines = [
        f'schtasks /Create /TN "{TASK_NAME}" /TR "\'{exe}\'" /SC ONLOGON /RL HIGHEST /F',
    ]
    return _run_elevated_bat(bat_lines)

def remove_startup_task_elevated() -> tuple[bool, str]:
    bat_lines = [
        f'schtasks /Delete /TN "{TASK_NAME}" /F',
    ]
    return _run_elevated_bat(bat_lines)

def _try_direct_schtasks(args: list[str]) -> bool:
    try:
        result = subprocess.run(
            args, capture_output=True, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return result.returncode == 0
    except Exception:
        return False

def add_to_startup(exit_on_denial: bool = False) -> bool:
    exe = app_exe_path()
    direct_args = [
        "schtasks", "/Create", "/TN", TASK_NAME,
        "/TR", exe, "/SC", "ONLOGON", "/RL", "HIGHEST", "/F",
    ]
    if _try_direct_schtasks(direct_args):
        return True
    ok, status = install_startup_task_elevated()
    if ok:
        return True
    if status == "denied":
        show_admin_needed_for_action_message()
        if exit_on_denial:
            sys.exit(1)
    return False

def remove_from_startup(exit_on_denial: bool = False) -> bool:
    direct_args = ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"]
    if _try_direct_schtasks(direct_args):
        return True
    ok, status = remove_startup_task_elevated()
    if ok:
        return True
    if status == "denied":
        show_admin_needed_for_action_message()
        if exit_on_denial:
            sys.exit(1)
    return False

def app_dir():
    base = getattr(sys, "_MEIPASS", None)
    return os.path.dirname(sys.executable if base else os.path.abspath(__file__))

def config_path():
    return os.path.join(app_dir(), "devices.json")

def icon_path():
    candidate = os.path.join(app_dir(), "icon.ico")
    if os.path.exists(candidate):
        return candidate
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        bundled_candidate = os.path.join(bundled, "icon.ico")
        if os.path.exists(bundled_candidate):
            return bundled_candidate
    return None

CONFIG_PATH = config_path()
DEFAULT_HOTKEY = "ctrl+]"
BG = QColor(10, 10, 14)
SURF = QColor(20, 20, 30)
SURF_HOV = QColor(26, 26, 40)
SURF_SEL = QColor(22, 30, 55)
BORDER = QColor(255, 255, 255, 20)
BORDER_HOV = QColor(255, 255, 255, 45)
BORDER_SEL = QColor(99, 179, 255, 180)
ACCENT_A = QColor(99, 179, 255)
ACCENT_B = QColor(168, 100, 255)
TEXT_PRI = QColor(230, 230, 245)
TEXT_MUT = QColor(55, 55, 80)
KNOB_OFF = QColor(42, 42, 62)
UI_FONT_CANDIDATES = [
    "Segoe UI",
    "Segoe UI Variable Display",
    "Segoe UI Variable",
    "Inter",
    "Inter Variable",
    "Inter Display",
]
_resolved_ui_font = None
_resolved_emphasis_weight = None

def ui_font_family() -> str:
    global _resolved_ui_font
    if _resolved_ui_font is not None:
        return _resolved_ui_font
    available = set(QFontDatabase.families())
    for candidate in UI_FONT_CANDIDATES:
        if candidate in available:
            _resolved_ui_font = candidate
            return candidate
    _resolved_ui_font = QFont().defaultFamily()
    return _resolved_ui_font

def ui_font_emphasis_weight() -> QFont.Weight:
    global _resolved_emphasis_weight
    if _resolved_emphasis_weight is not None:
        return _resolved_emphasis_weight
    family = ui_font_family()
    try:
        real_weights = sorted(QFontDatabase.weights(family))
    except Exception:
        real_weights = []
    for w in (QFont.Weight.DemiBold, QFont.Weight.Medium, QFont.Weight.Bold):
        if w in real_weights:
            _resolved_emphasis_weight = w
            return w
    _resolved_emphasis_weight = QFont.Weight.Normal
    return QFont.Weight.Normal

class IPolicyConfig(IUnknown):
    _iid_ = GUID("{f8679f50-850a-41cf-9c72-430f290290c8}")
    _methods_ = [
        comtypes.STDMETHOD(ctypes.HRESULT, "GetMixFormat"),
        comtypes.STDMETHOD(ctypes.HRESULT, "GetDeviceFormat"),
        comtypes.STDMETHOD(ctypes.HRESULT, "ResetDeviceFormat"),
        comtypes.STDMETHOD(ctypes.HRESULT, "SetDeviceFormat"),
        comtypes.STDMETHOD(ctypes.HRESULT, "GetProcessingPeriod"),
        comtypes.STDMETHOD(ctypes.HRESULT, "SetProcessingPeriod"),
        comtypes.STDMETHOD(ctypes.HRESULT, "GetShareMode"),
        comtypes.STDMETHOD(ctypes.HRESULT, "SetShareMode"),
        comtypes.STDMETHOD(ctypes.HRESULT, "GetPropertyValue"),
        comtypes.STDMETHOD(ctypes.HRESULT, "SetPropertyValue"),
        comtypes.STDMETHOD(ctypes.HRESULT, "SetDefaultEndpoint", [ctypes.c_wchar_p, ctypes.c_uint]),
        comtypes.STDMETHOD(ctypes.HRESULT, "SetEndpointVisibility"),
    ]

POLICY_CONFIG_CLSID = GUID("{870af99c-171d-4f9e-af0d-e63df40c2bc9}")
CLSID_MMDEVICE_ENUMERATOR = GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
DEVICE_STATE_ACTIVE = 0x00000001

def set_default_device(device_id):
    policy = comtypes.CoCreateInstance(POLICY_CONFIG_CLSID, IPolicyConfig, CLSCTX_ALL)
    for role in (0, 1, 2):
        policy.SetDefaultEndpoint(device_id, role)

def is_device_active(device_id: str) -> bool:
    try:
        enum = comtypes.CoCreateInstance(CLSID_MMDEVICE_ENUMERATOR, IMMDeviceEnumerator, CLSCTX_ALL)
        device = enum.GetDevice(device_id)
        return device.GetState() == DEVICE_STATE_ACTIVE
    except Exception:
        return False

def get_volume_percent(device_id):
    for attempt in range(2):
        try:
            enum = comtypes.CoCreateInstance(CLSID_MMDEVICE_ENUMERATOR, IMMDeviceEnumerator, CLSCTX_ALL)
            device = enum.GetDevice(device_id)
            iface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            vol = cast(iface, POINTER(IAudioEndpointVolume))
            return round(vol.GetMasterVolumeLevelScalar() * 100)
        except Exception:
            if attempt == 0:
                time.sleep(0.25)
    return 0

def enumerate_devices() -> list[dict]:
    seen = set()
    result = []
    for d in AudioUtilities.GetAllDevices():
        try:
            state = d._dev.GetState()
        except Exception:
            state = DEVICE_STATE_ACTIVE
        if state != DEVICE_STATE_ACTIVE:
            continue
        if d.id in seen:
            continue
        seen.add(d.id)
        result.append({"id": d.id, "name": d.FriendlyName})
    return result

DEVICE_CATEGORIES = [
    (("headphone", "headset", "earphone", "earbud", "airpod"), "🎧", "Headphones"),
    (("line out", "line-out", "lineout"), "🔌", "Line Out"),
    (("digital out", "spdif", "s/pdif", "optical", "toslink"), "📡", "Digital Out"),
    (("hdmi",), "📺", "HDMI"),
    (("displayport", "display port"), "🖥️", "DisplayPort"),
    (("bluetooth", "bt audio", "hands-free", "hfp"), "📶", "Bluetooth"),
    (("usb",), "🔊", "USB Audio"),
    (("speaker",), "🔊", "Speakers"),
    (("monitor",), "🖥️", "Monitor Audio"),
    (("virtual", "cable", "vb-audio", "voicemeeter"), "🎚️", "Virtual Device"),
]

CATEGORY_OPTIONS = [
    ("🔊", "Speakers"),
    ("🎧", "Headphones"),
    ("🔌", "Line Out"),
    ("📡", "Digital Out"),
    ("📺", "HDMI"),
    ("🖥️", "DisplayPort"),
    ("📶", "Bluetooth"),
    ("🎚️", "Virtual Device"),
    ("🔊", "Audio Device"),
]
DEFAULT_ICON = "🔊"
DEFAULT_LABEL = "Audio Device"

def classify_device(device) -> tuple[str, str]:
    if isinstance(device, dict):
        custom_icon = device.get("custom_icon")
        custom_label = device.get("custom_label")
        if custom_icon and custom_label:
            return custom_icon, custom_label
        idx = device.get("category_index")
        if idx is not None and 0 <= idx < len(CATEGORY_OPTIONS):
            return CATEGORY_OPTIONS[idx]
        name = device.get("name", "")
    else:
        name = device
    lower = name.lower()
    for keywords, icon, label in DEVICE_CATEGORIES:
        if any(k in lower for k in keywords):
            return icon, label
    return DEFAULT_ICON, DEFAULT_LABEL

def load_config():
    if not os.path.exists(CONFIG_PATH):
        return None
    try:
        data = json.loads(open(CONFIG_PATH, encoding="utf-8").read())
    except Exception:
        return None
    if isinstance(data, list):
        if len(data) >= 2:
            return {"devices": data, "hotkey": DEFAULT_HOTKEY}
        return None
    if isinstance(data, dict):
        devices = data.get("devices")
        hotkey = data.get("hotkey", DEFAULT_HOTKEY)
        if isinstance(devices, list) and len(devices) >= 2:
            return {"devices": devices, "hotkey": hotkey}
    return None

def save_config(devices, hotkey):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump({"devices": devices, "hotkey": hotkey}, f, ensure_ascii=False, indent=2)

SCROLL_FPS = 8  
SCROLLBAR_SS = """
    QScrollBar:vertical {
        background: transparent;
        width: 4px;
        margin: 0;
    }
    QScrollBar::handle:vertical {
        background: rgba(255,255,255,0.18);
        border-radius: 2px;
        min-height: 24px;
    }
    QScrollBar::handle:vertical:hover { background: rgba(255,255,255,0.30); }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; border: none; }
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
"""

class SmoothScrollArea(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._anim = QPropertyAnimation(self.verticalScrollBar(), b"value", self)
        self._anim.setDuration(300)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.setStyleSheet(
            f"QScrollArea {{ border: none; background: transparent; }} {SCROLLBAR_SS}"
        )

    def wheelEvent(self, e: QWheelEvent):
        delta = e.angleDelta().y()
        bar = self.verticalScrollBar()
        current = bar.value()
        target = max(bar.minimum(), min(bar.maximum(), current - int(delta * 0.8)))
        self._anim.stop()
        self._anim.setStartValue(current)
        self._anim.setEndValue(target)
        self._anim.start()
        e.accept()

CARD_H = 92
TOG_W = 46
TOG_H = 26
KNOB_D = TOG_H - 8
TOG_OFF = 4.0
TOG_ON = float(TOG_W - KNOB_D - 4)
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_ROUND = 2
DWMWCP_ROUND_SMALL = 3

def _apply_dwm_rounded_corners(hwnd: int, small: bool = False):
    try:
        pref = ctypes.c_int(DWMWCP_ROUND_SMALL if small else DWMWCP_ROUND)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd,
            DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(pref),
            ctypes.sizeof(pref),
        )
    except Exception:
        pass  

def _make_fade_anim(widget: QWidget, duration_in: int, duration_out: int):
    anim_in = QPropertyAnimation(widget, b"windowOpacity", widget)
    anim_in.setDuration(duration_in)
    anim_in.setStartValue(0.0)
    anim_in.setEndValue(1.0)
    anim_in.setEasingCurve(QEasingCurve.Type.OutCubic)
    anim_out = QPropertyAnimation(widget, b"windowOpacity", widget)
    anim_out.setDuration(duration_out)
    anim_out.setStartValue(1.0)
    anim_out.setEndValue(0.0)
    anim_out.setEasingCurve(QEasingCurve.Type.InQuad)
    return anim_in, anim_out

class CategoryDropdown(QWidget):
    picked = pyqtSignal(int)
    custom_requested = pyqtSignal()
    closed = pyqtSignal()
    ROW_H = 34
    BG = QColor(18, 18, 28)

    def __init__(self, current_index: int, anchor_global: QPoint, parent=None):
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._current = current_index
        self._hover_i = -1
        self._options = CATEGORY_OPTIONS
        self._closing = False
        self.setMouseTracking(True)
        w = 200
        row_count = len(self._options) + 1
        h = self.ROW_H * row_count + 18
        self.resize(w, h)
        self.move(anchor_global)
        self.setWindowOpacity(0.0)
        f_emoji = QFont("Segoe UI Emoji", 12)
        f_item = QFont(ui_font_family(), 10)
        f_item.setWeight(ui_font_emphasis_weight())
        self._text_lbls = []
        for i, (icon, label) in enumerate(self._options):
            ry = 7 + i * self.ROW_H
            icon_lbl = QLabel(icon, self)
            icon_lbl.setFont(f_emoji)
            icon_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            icon_lbl.setStyleSheet("background: transparent; color: #e6e6f5;")
            icon_lbl.setGeometry(14, ry, 26, self.ROW_H)
            text_lbl = QLabel(label, self)
            text_lbl.setFont(f_item)
            text_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            text_lbl.setGeometry(44, ry, w - 60, self.ROW_H)
            self._text_lbls.append(text_lbl)
            check_lbl = QLabel("✓" if i == current_index else "", self)
            check_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            check_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            check_lbl.setStyleSheet("background: transparent; color: #a864ff;")
            check_lbl.setGeometry(w - 28, ry, 20, self.ROW_H)
        self._custom_row_y = 11 + len(self._options) * self.ROW_H
        custom_icon_lbl = QLabel("✏️", self)
        custom_icon_lbl.setFont(f_emoji)
        custom_icon_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        custom_icon_lbl.setStyleSheet("background: transparent; color: #7ab8ff;")
        custom_icon_lbl.setGeometry(14, self._custom_row_y, 26, self.ROW_H)
        custom_text_lbl = QLabel("Custom…", self)
        custom_text_lbl.setFont(f_item)
        custom_text_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        custom_text_lbl.setStyleSheet("background: transparent; color: #7ab8ff;")
        custom_text_lbl.setGeometry(44, self._custom_row_y, w - 60, self.ROW_H)
        self._refresh_row_colors()
        self._anim_in = QPropertyAnimation(self, b"windowOpacity", self)
        self._anim_in.setDuration(160)
        self._anim_in.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim_out = QPropertyAnimation(self, b"windowOpacity", self)
        self._anim_out.setDuration(110)
        self._anim_out.setEasingCurve(QEasingCurve.Type.InQuad)
        self._anim_out.finished.connect(self._finish_close)
        QApplication.instance().installEventFilter(self)

    def showEvent(self, e):
        super().showEvent(e)
        _apply_dwm_rounded_corners(int(self.winId()), small=True)
        self._anim_out.stop()
        self._anim_in.setStartValue(0.0)
        self._anim_in.setEndValue(1.0)
        self._anim_in.start()

    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent
        if event.type() == QEvent.Type.MouseButtonPress:
            try:
                gpos = event.globalPosition().toPoint()
            except AttributeError:
                gpos = event.globalPos()
            if not self.geometry().contains(gpos):
                self.close_animated()
        return False

    def close_animated(self):
        if self._closing:
            return
        self._closing = True
        QApplication.instance().removeEventFilter(self)
        self._anim_in.stop()
        self._anim_out.setStartValue(self.windowOpacity())
        self._anim_out.setEndValue(0.0)
        self._anim_out.start()

    def _finish_close(self):
        self.closed.emit()
        self.close()

    def _refresh_row_colors(self):
        for i, text_lbl in enumerate(self._text_lbls):
            col = "#ebebf8" if i == self._current else "#b0b0cc"
            text_lbl.setStyleSheet(f"background: transparent; color: {col};")

    def _row_at(self, pos) -> int:
        if not self.rect().contains(pos):
            return -1
        if self._custom_row_y <= pos.y() < self._custom_row_y + self.ROW_H:
            return len(self._options)
        row = int(pos.y() - 7) // self.ROW_H
        return row if 0 <= row < len(self._options) else -1

    def mouseMoveEvent(self, e):
        row = self._row_at(e.position().toPoint())
        if row != self._hover_i:
            self._hover_i = row
            self.update()

    def mousePressEvent(self, e):
        row = self._row_at(e.position().toPoint())
        if row == len(self._options):
            QApplication.instance().removeEventFilter(self)
            self._closing = True
            self._anim_in.stop()
            self._anim_out.setStartValue(self.windowOpacity())
            self._anim_out.setEndValue(0.0)
            self._anim_out.finished.disconnect()
            self._anim_out.finished.connect(self._finish_close_then_custom)
            self._anim_out.start()
        elif 0 <= row < len(self._options):
            self.picked.emit(row)
            self.close_animated()

    def _finish_close_then_custom(self):
        self.closed.emit()
        self.custom_requested.emit()
        self.close()

    def leaveEvent(self, e):
        self._hover_i = -1
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, self.BG)
        p.setPen(QPen(QColor(255, 255, 255, 18)))
        p.drawLine(1, 0, w - 2, 0)
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(len(self._options)):
            ry = 7 + i * self.ROW_H
            if i == self._hover_i:
                hp = QPainterPath()
                hp.addRoundedRect(QRectF(4, ry, w - 8, self.ROW_H - 2), 6, 6)
                p.fillPath(hp, QColor(255, 255, 255, 16))
            elif i == self._current:
                sp = QPainterPath()
                sp.addRoundedRect(QRectF(4, ry, w - 8, self.ROW_H - 2), 6, 6)
                p.fillPath(sp, QColor(168, 100, 255, 22))          
        divider_y = self._custom_row_y - 5
        p.setPen(QPen(QColor(255, 255, 255, 16)))
        p.drawLine(10, divider_y, w - 10, divider_y)
        if self._hover_i == len(self._options):
            p.setPen(Qt.PenStyle.NoPen)
            cp = QPainterPath()
            cp.addRoundedRect(QRectF(4, self._custom_row_y, w - 8, self.ROW_H - 2), 6, 6)
            p.fillPath(cp, QColor(255, 255, 255, 16))

class RecordButton(QWidget):
    clicked = pyqtSignal()
    def __init__(self, parent=None):
        super().__init__(parent)
        self._recording = False
        self._hovered = False
        self._press_scale = 1.0          
        self.setFixedHeight(34)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._label = QLabel("Record", self)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        f = QFont(ui_font_family(), 10)
        f.setWeight(ui_font_emphasis_weight())
        self._label.setFont(f)
        self._press_anim = QVariantAnimation(self)
        self._press_anim.setDuration(120)
        self._press_anim.setEasingCurve(QEasingCurve.Type.OutBack)
        self._press_anim.valueChanged.connect(self._on_scale_changed)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._label.setGeometry(self.rect())

    def set_recording(self, recording: bool):
        self._recording = recording
        self._label.setText("Stop" if recording else "Record")
        color = "#ffffff" if recording else "#08081a"
        self._label.setStyleSheet(f"background: transparent; color: {color};")
        self.update()

    def enterEvent(self, e):
        self._hovered = True
        self.update()

    def leaveEvent(self, e):
        self._hovered = False
        self.update()

    def mousePressEvent(self, e):
        self._press_anim.stop()
        self._press_anim.setStartValue(self._press_scale)
        self._press_anim.setEndValue(0.93)
        self._press_anim.setEasingCurve(QEasingCurve.Type.OutQuad)
        self._press_anim.start()

    def mouseReleaseEvent(self, e):
        self._press_anim.stop()
        self._press_anim.setStartValue(self._press_scale)
        self._press_anim.setEndValue(1.0)
        self._press_anim.setEasingCurve(QEasingCurve.Type.OutBack)
        self._press_anim.start()
        if self.rect().contains(e.pos()):
            self.clicked.emit()

    def _on_scale_changed(self, val):
        self._press_scale = val
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        w, h = float(self.width()), float(self.height())
        s = self._press_scale
        p.translate(w / 2, h / 2)
        p.scale(s, s)
        p.translate(-w / 2, -h / 2)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, w, h), 9, 9)
        if self._recording:
            color = QColor(220, 70, 70) if self._hovered else QColor(200, 60, 60)
            p.fillPath(path, color)
        else:
            g = QLinearGradient(0, 0, w, 0)
            g.setColorAt(0, QColor(130, 190, 255) if self._hovered else ACCENT_A)
            g.setColorAt(1, QColor(195, 130, 255) if self._hovered else ACCENT_B)
            p.fillPath(path, QBrush(g))

class RecordingDot(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(8, 8)
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)

    def start(self):
        self._phase = 0.0
        self._timer.start()

    def stop(self):
        self._timer.stop()
        self.update()

    def _tick(self):
        self._phase += 0.12
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pulse = 0.5 + 0.5 * abs(math.sin(self._phase))
        alpha = int(120 + pulse * 135)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 80, 80, alpha))
        p.drawEllipse(0, 0, 8, 8)

class HotkeyCaptureDropdown(QWidget):
    picked = pyqtSignal(str)
    closed = pyqtSignal()
    AUTO_STOP_KEY_COUNT = 3
    AUTO_STOP_TIMEOUT_MS = 900

    def __init__(self, current_hotkey: str, parent=None):
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.resize(270, 100)
        self.setWindowOpacity(0.0)
        self._current_hotkey = current_hotkey
        self._recording = False
        self._closing = False
        self._captured_mods = []
        self._captured_key = None
        self._result_text = current_hotkey
        self._timeout_tmr = QTimer(self)
        self._timeout_tmr.setSingleShot(True)
        self._timeout_tmr.timeout.connect(self._stop_recording)
        self._dot = RecordingDot(self)
        self._dot.hide()
        self._combo_lbl = QLabel(current_hotkey.upper(), self)
        self._combo_lbl.setGeometry(0, 18, 270, 36)
        self._combo_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f_combo = QFont("Segoe UI", 14)
        f_combo.setWeight(QFont.Weight.DemiBold)
        self._combo_lbl.setFont(f_combo)
        self._combo_lbl.setStyleSheet("background: transparent; color: #e8e8f4;")
        self._record_btn = RecordButton(self)
        self._record_btn.setGeometry(20, 58, 230, 34)
        self._record_btn.clicked.connect(self._on_record_clicked)
        self._anim_in = QPropertyAnimation(self, b"windowOpacity", self)
        self._anim_in.setDuration(180)
        self._anim_in.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim_out = QPropertyAnimation(self, b"windowOpacity", self)
        self._anim_out.setDuration(130)
        self._anim_out.setEasingCurve(QEasingCurve.Type.InQuad)
        self._anim_out.finished.connect(self._finish_close)
        QApplication.instance().installEventFilter(self)

    def showEvent(self, e):
        super().showEvent(e)
        _apply_dwm_rounded_corners(int(self.winId()), small=True)
        self.setFocus()
        self.activateWindow()
        self._anim_out.stop()
        self._anim_in.setStartValue(0.0)
        self._anim_in.setEndValue(1.0)
        self._anim_in.start()

    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent
        if event.type() == QEvent.Type.MouseButtonPress:
            try:
                gpos = event.globalPosition().toPoint()
            except AttributeError:
                gpos = event.globalPos()
            if not self.geometry().contains(gpos):
                self.close_animated()
                return True  
        return False

    def close_animated(self):
        if self._closing:
            return
        self._closing = True
        QApplication.instance().removeEventFilter(self)
        self._timeout_tmr.stop()
        self._dot.stop()
        self._anim_in.stop()
        self._anim_out.setStartValue(self.windowOpacity())
        self._anim_out.setEndValue(0.0)
        self._anim_out.start()

    def _finish_close(self):
        self.closed.emit()
        self.close()

    def _on_record_clicked(self):
        if self._recording:
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self):
        self._recording = True
        self._captured_mods = []
        self._captured_key = None
        self._combo_lbl.setText("Press keys…")
        self._combo_lbl.setStyleSheet("background: transparent; color: #ff8888;")
        self._record_btn.set_recording(True)
        fm = QFontMetrics(self._combo_lbl.font())
        text_w = fm.horizontalAdvance("Press keys…")
        dot_x = (self.width() - text_w) // 2 + text_w + 8
        self._dot.move(dot_x, 30)
        self._dot.show()
        self._dot.start()
        self.setFocus()
        self.activateWindow()
        self.update()

    def _stop_recording(self):
        self._recording = False
        self._timeout_tmr.stop()
        self._dot.stop()
        self._dot.hide()
        self._combo_lbl.setStyleSheet("background: transparent; color: #e8e8f4;")
        self._record_btn.set_recording(False)
        if self._captured_key is not None:
            parts = self._captured_mods + [self._captured_key]
            self._result_text = "+".join(parts)
            self._combo_lbl.setText(" + ".join(p.capitalize() for p in parts))
            self.picked.emit(self._result_text)
        else:
            self._combo_lbl.setText(self._current_hotkey.upper())
        self.update()

    def keyPressEvent(self, e):
        if not self._recording:
            if e.key() == Qt.Key.Key_Escape:
                self.close_animated()
            return
        key = e.key()
        if key in (Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_Shift, Qt.Key.Key_Meta):
            mod_name = {
                Qt.Key.Key_Control: "ctrl",
                Qt.Key.Key_Alt: "alt",
                Qt.Key.Key_Shift: "shift",
                Qt.Key.Key_Meta: "meta",
            }[key]
            if mod_name not in self._captured_mods and len(self._captured_mods) < 2:
                self._captured_mods.append(mod_name)
                preview = " + ".join(m.capitalize() for m in self._captured_mods)
                self._combo_lbl.setText(preview)
                self._timeout_tmr.start(self.AUTO_STOP_TIMEOUT_MS)
            return
        key_name = QKeySequence(key).toString().lower()
        if not key_name:
            return
        total_keys = len(self._captured_mods) + 1
        if total_keys > self.AUTO_STOP_KEY_COUNT:
            return
        self._captured_key = key_name
        parts = self._captured_mods + [key_name]
        self._combo_lbl.setText(" + ".join(p.capitalize() for p in parts))
        if total_keys >= self.AUTO_STOP_KEY_COUNT:
            self._timeout_tmr.stop()
            self._stop_recording()
        else:
            self._timeout_tmr.start(self.AUTO_STOP_TIMEOUT_MS)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(16, 16, 26))
        p.setPen(QPen(QColor(255, 255, 255, 28)))
        p.drawLine(1, 0, w - 2, 0)
        p.drawLine(0, 0, 0, h - 1)
        p.drawLine(w - 1, 0, w - 1, h - 1)
        p.drawLine(1, h - 1, w - 2, h - 1)

def custom_icons_dir():
    d = os.path.join(app_dir(), "icons")
    os.makedirs(d, exist_ok=True)
    return d

class ImagePreviewLabel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self._cropped: QPixmap | None = None

    def set_image(self, path: str):
        full = QPixmap(path)
        if full.isNull():
            self._cropped = None
            self.update()
            return
        sw, sh = full.width(), full.height()
        side = min(sw, sh)
        x = (sw - side) // 2
        y = (sh - side) // 2
        cropped = full.copy(x, y, side, side)
        self._cropped = cropped.scaled(
            self.width(), self.height(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.update()

    def clear(self):
        self._cropped = None
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        w, h = self.width(), self.height()
        r = 16.0  
        path = QPainterPath()
        path.addRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), r, r)
        p.setClipPath(path)
        p.fillPath(path, QColor(255, 255, 255, 18))
        if self._cropped:
            px = (w - self._cropped.width()) // 2
            py = (h - self._cropped.height()) // 2
            p.drawPixmap(px, py, self._cropped)
        else:
            p.setPen(QPen(QColor(255, 255, 255, 40)))
            p.setFont(QFont("Segoe UI", 8))
            p.drawText(QRectF(0, 0, w, h), Qt.AlignmentFlag.AlignCenter, "No\nimage")
        p.setClipping(False)
        pen = QPen(QColor(255, 255, 255, 45))
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

class CustomDeviceDialog(QWidget):
    saved = pyqtSignal(str, str)
    closed = pyqtSignal()
    _TAB_EMOJI = 0
    _TAB_IMAGE = 1
    def __init__(self, current_icon: str, current_label: str, setup_window: QWidget):
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self._setup_window = setup_window
        self._closing = False
        self._icon_image_path = None
        self._current_preview_emoji = current_icon if not current_icon.startswith("file:") else "🔊"
        starts_on_image = current_icon.startswith("file:")
        self._active_tab = self._TAB_IMAGE if starts_on_image else self._TAB_EMOJI
        W, H = 360, 354
        self.setFixedSize(W, H)
        self.setWindowOpacity(0.0)
        self._title_lbl = QLabel("Customise Device", self)
        self._title_lbl.setGeometry(0, 18, W, 22)
        self._title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f_title = QFont(ui_font_family(), 11)
        f_title.setWeight(ui_font_emphasis_weight())
        self._title_lbl.setFont(f_title)
        self._title_lbl.setStyleSheet("background: transparent; color: #d0d0e8;")
        close_btn = QPushButton("✕", self)
        close_btn.setFixedSize(28, 28)
        close_btn.move(W - 38, 14)
        close_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        close_btn.setStyleSheet("""
            QPushButton { background: transparent; color: #404060;
                          border: none; font-size: 13px; border-radius: 7px; }
            QPushButton:hover { background: rgba(255,60,60,0.22); color: #ff6060; }
        """)
        close_btn.clicked.connect(self.close_animated)
        SEG_W, SEG_H = 200, 30
        seg_x = (W - SEG_W) // 2
        seg_y = 50
        self._seg_x, self._seg_y, self._seg_w, self._seg_h = seg_x, seg_y, SEG_W, SEG_H
        HALF = SEG_W // 2
        self._tab_emoji_lbl = QLabel("Emoji", self)
        self._tab_emoji_lbl.setGeometry(seg_x, seg_y, HALF, SEG_H)
        self._tab_emoji_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._tab_emoji_lbl.setFont(QFont("Segoe UI", 10))
        self._tab_emoji_lbl.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._tab_emoji_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self._tab_emoji_lbl.mousePressEvent = lambda e: self._switch_tab(self._TAB_EMOJI)
        self._tab_image_lbl = QLabel("Image", self)
        self._tab_image_lbl.setGeometry(seg_x + HALF, seg_y, HALF, SEG_H)
        self._tab_image_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._tab_image_lbl.setFont(QFont("Segoe UI", 10))
        self._tab_image_lbl.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._tab_image_lbl.mousePressEvent = lambda e: self._switch_tab(self._TAB_IMAGE)
        self._update_tab_styles()
        content_y = seg_y + SEG_H + 16
        PAGE_H = 110
        self._emoji_page = QWidget(self)
        self._emoji_page.setGeometry(0, content_y, W, PAGE_H)
        self._emoji_page.setStyleSheet("background: transparent;")
        PREV_SIZE = 72
        self._emoji_preview = QLabel(self._current_preview_emoji, self._emoji_page)
        self._emoji_preview.setGeometry((W - PREV_SIZE) // 2, 0, PREV_SIZE, PREV_SIZE)
        self._emoji_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._emoji_preview.setFont(QFont("Segoe UI Emoji", 32))
        self._emoji_preview.setStyleSheet(
            "background: rgba(255,255,255,0.07);"
            "border-radius: 16px;"
            "border: 1px solid rgba(255,255,255,0.16);"
        )
        self._emoji_preview.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._emoji_panel = None
        tap_lbl = QLabel("Click to pick an emoji  ·  Right-click to paste", self._emoji_page)
        tap_lbl.setGeometry(0, PREV_SIZE + 8, W, 18)
        tap_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tap_lbl.setFont(QFont("Segoe UI", 9))
        tap_lbl.setStyleSheet("background: transparent; color: #6868a0;")
        def _on_preview_click(e):
            if e.button() == Qt.MouseButton.RightButton:
                self._paste_clipboard_emoji()
            else:
                self._open_emoji_panel()
        self._emoji_preview.mousePressEvent = _on_preview_click
        self._image_page = QWidget(self)
        self._image_page.setGeometry(0, content_y, W, PAGE_H)
        self._image_page.setStyleSheet("background: transparent;")
        PREV_IMG = 72
        self._img_preview = ImagePreviewLabel(self._image_page)
        self._img_preview.setGeometry((W - PREV_IMG) // 2, 0, PREV_IMG, PREV_IMG)
        if starts_on_image:
            filename = current_icon[5:]
            full_path = os.path.join(custom_icons_dir(), filename)
            if os.path.exists(full_path):
                self._img_preview.set_image(full_path)
                self._icon_image_path = full_path
        self._browse_btn = QPushButton("Choose any image…", self._image_page)
        self._browse_btn.setGeometry((W - 200) // 2, PREV_IMG + 10, 200, 26)
        self._browse_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._browse_btn.setFont(QFont("Segoe UI", 9))
        self._browse_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,0.07);
                color: #b0b0d0;
                border: 1px solid rgba(255,255,255,0.16);
                border-radius: 6px;
            }
            QPushButton:hover {
                background: rgba(99,179,255,0.16);
                border: 1px solid rgba(99,179,255,0.50);
                color: #ddeeff;
            }
            QPushButton:pressed { background: rgba(99,179,255,0.08); }
        """)
        self._browse_btn.clicked.connect(self._on_browse)
        name_y = content_y + PAGE_H + 12
        name_hint = QLabel("Display name", self)
        name_hint.setGeometry(28, name_y, 200, 16)
        name_hint.setFont(QFont("Segoe UI", 9))
        name_hint.setStyleSheet("background: transparent; color: #6868a0;")
        self._label_input = QLineEdit(self)
        self._label_input.setGeometry(28, name_y + 18, W - 56, 40)
        self._label_input.setPlaceholderText("Name shown in the OSD overlay")
        self._label_input.setText(current_label if current_label != DEFAULT_LABEL else "")
        self._label_input.setFont(QFont("Segoe UI", 11))
        self._label_input.setStyleSheet("""
            QLineEdit {
                background: rgba(255,255,255,0.07);
                color: #e0e0f4;
                border: 1px solid rgba(255,255,255,0.16);
                border-radius: 6px;
                padding: 0 12px;
            }
            QLineEdit:focus { border: 1px solid rgba(99,179,255,0.75); }
        """)
        save_y = name_y + 72
        self._save_btn = QPushButton("Save", self)
        self._save_btn.setGeometry(28, save_y, W - 56, 40)
        self._save_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._save_btn.setFont(QFont("Segoe UI", 11))
        self._save_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #5ca8f0, stop:1 #9a5ce8);
                color: #ffffff;
                border: none;
                border-radius: 6px;
                font-weight: normal;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #78bbff, stop:1 #b278ff);
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #4090d8, stop:1 #8040d0);
            }
        """)
        self._save_btn.clicked.connect(self._on_save)
        self._drag_pos = None
        self._anim_in = QPropertyAnimation(self, b"windowOpacity", self)
        self._anim_in.setDuration(180)
        self._anim_in.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim_out = QPropertyAnimation(self, b"windowOpacity", self)
        self._anim_out.setDuration(130)
        self._anim_out.setEasingCurve(QEasingCurve.Type.InQuad)
        self._anim_out.finished.connect(self._finish_close)
        self._switch_tab(self._active_tab, animate=False)

    def _open_emoji_panel(self):
        if self._emoji_panel is not None:
            self._close_emoji_panel()
            return
        EMOJI_CATEGORIES = {
            "Audio":   ["🔊","🔇","🔈","🔉","🎵","🎶","🎤","🎧","🎼","🎹","🥁","🎸","🎺","🎻","📻","🔔","🔕"],
            "Devices": ["💻","🖥️","🖨️","⌨️","🖱️","📱","📲","☎️","📞","📟","📠","📺","📷","📸","📹","🎥","📡"],
            "Symbols": ["⭐","✅","❌","⚠️","ℹ️","🔴","🟠","🟡","🟢","🔵","🟣","⚫","⚪","🔶","🔷","🔸","🔹"],
            "Objects": ["🏠","🏢","🚀","✈️","🚗","🎮","🕹️","💾","💿","📀","🖲️","📦","📁","📂","🗂️","🗃️"],
            "Faces":   ["😀","😎","🤖","👾","🦾","💪","👍","👎","❤️","🔥","⚡","💥","✨","🌟","💫","🎯","🏆"],
        }
        W, H = self.width(), self.height()
        panel = QWidget(self)
        panel.setGeometry(0, 0, W, H)
        panel.setStyleSheet("background: rgb(14,14,24);")  
        panel.raise_()
        panel.show()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(0)
        hdr = QHBoxLayout()
        title = QLabel("Pick an emoji", panel)
        title.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        title.setStyleSheet("color: #c0c0e0; background: transparent;")
        close_btn = QPushButton("✕", panel)
        close_btn.setFixedSize(24, 24)
        close_btn.setStyleSheet("""
            QPushButton { background: transparent; color: #505070;
                          border: none; font-size: 12px; border-radius: 5px; }
            QPushButton:hover { background: rgba(255,60,60,0.22); color: #ff6060; }
        """)
        close_btn.clicked.connect(self._close_emoji_panel)
        hdr.addWidget(title)
        hdr.addStretch()
        hdr.addWidget(close_btn)
        layout.addLayout(hdr)
        layout.addSpacing(6)
        scroll = SmoothScrollArea(panel)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"""
            QScrollArea {{ border: none; background: transparent; }}
            {SCROLLBAR_SS}
        """)
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        grid_layout = QVBoxLayout(inner)
        grid_layout.setContentsMargins(0, 0, 4, 0)
        grid_layout.setSpacing(2)
        f_emoji = QFont("Segoe UI Emoji", 18)
        f_cat = QFont("Segoe UI", 8)
        f_cat.setWeight(QFont.Weight.DemiBold)
        COLS = 8
        CELL = (W - 40) // COLS
        for cat, emojis in EMOJI_CATEGORIES.items():
            cat_lbl = QLabel(cat.upper(), inner)
            cat_lbl.setFont(f_cat)
            cat_lbl.setStyleSheet("color: #44446a; background: transparent; padding: 6px 0 2px 2px;")
            grid_layout.addWidget(cat_lbl)
            i = 0
            while i < len(emojis):
                row_w = QWidget(inner)
                row_w.setStyleSheet("background: transparent;")
                row_l = QHBoxLayout(row_w)
                row_l.setContentsMargins(0, 0, 0, 0)
                row_l.setSpacing(2)
                for j in range(COLS):
                    if i + j < len(emojis):
                        em = emojis[i + j]
                        btn = QPushButton(em, inner)
                        btn.setFixedSize(CELL, CELL)
                        btn.setFont(f_emoji)
                        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
                        btn.setStyleSheet("""
                            QPushButton { background: transparent; border: none; border-radius: 6px; }
                            QPushButton:hover { background: rgba(255,255,255,0.12); }
                            QPushButton:pressed { background: rgba(99,179,255,0.25); }
                        """)
                        btn.clicked.connect(lambda _, e=em: self._on_emoji_picked(e))
                        row_l.addWidget(btn)
                row_l.addStretch()
                grid_layout.addWidget(row_w)
                i += COLS
        grid_layout.addStretch()
        scroll.setWidget(inner)
        layout.addWidget(scroll)
        from PyQt6.QtWidgets import QGraphicsOpacityEffect
        eff = QGraphicsOpacityEffect(panel)
        eff.setOpacity(0.0)
        panel.setGraphicsEffect(eff)
        anim = QPropertyAnimation(eff, b"opacity", panel)
        anim.setDuration(160)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        self._emoji_panel = panel

    def _close_emoji_panel(self):
        if self._emoji_panel is None:
            return
        panel = self._emoji_panel
        self._emoji_panel = None
        from PyQt6.QtWidgets import QGraphicsOpacityEffect
        eff = QGraphicsOpacityEffect(panel)
        eff.setOpacity(1.0)
        panel.setGraphicsEffect(eff)
        anim = QPropertyAnimation(eff, b"opacity", panel)
        anim.setDuration(120)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.Type.InQuad)
        anim.finished.connect(panel.deleteLater)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    def _on_emoji_picked(self, emoji: str):
        self._current_preview_emoji = emoji
        self._emoji_preview.setText(emoji)
        self._close_emoji_panel()

    def _on_emoji_panel_closed(self):
        self._emoji_panel = None

    def _paste_clipboard_emoji(self):
        clipboard = QApplication.clipboard()
        text = clipboard.text().strip()
        if text:
            if any(ord(c) > 127 for c in text) and len(text) <= 8:
                self._emoji_input.setText(text)
                self._on_emoji_typed(text)

    def _on_emoji_typed(self, text: str):
        if not text.strip():
            self._emoji_preview.setText("🙂")
            self._current_preview_emoji = ""
            return
        first = self._first_emoji(text.strip())
        if first:
            self._emoji_preview.setText(first)
            self._current_preview_emoji = first
            if text.strip() != first:
                self._emoji_input.blockSignals(True)
                self._emoji_input.setText(first)
                self._emoji_input.blockSignals(False)

    @staticmethod
    def _first_emoji(text: str) -> str:
        if not text:
            return ""
        JOINERS = {0x200D}  
        def _is_modifier(cp):
            return (0x1F3FB <= cp <= 0x1F3FF   
                    or 0xFE00 <= cp <= 0xFE0F   
                    or cp == 0x20E3             
                    or 0xE0020 <= cp <= 0xE007F) 
        cps = [ord(c) for c in text]
        i = 0
        result_cps = []
        while i < len(cps):
            cp = cps[i]
            result_cps.append(cp)
            i += 1
            while i < len(cps):
                next_cp = cps[i]
                if next_cp in JOINERS:
                    result_cps.append(next_cp)
                    i += 1
                    if i < len(cps):
                        result_cps.append(cps[i])
                        i += 1
                elif _is_modifier(next_cp):
                    result_cps.append(next_cp)
                    i += 1
                else:
                    break
            break  
        return "".join(chr(c) for c in result_cps)

    def _switch_tab(self, tab: int, animate: bool = True):
        if tab == self._active_tab and animate:
            return
        self._active_tab = tab
        self._update_tab_styles()
        self.update()  
        if not animate:
            self._emoji_page.setVisible(tab == self._TAB_EMOJI)
            self._image_page.setVisible(tab == self._TAB_IMAGE)
            return
        outgoing = self._image_page if tab == self._TAB_EMOJI else self._emoji_page
        incoming = self._emoji_page if tab == self._TAB_EMOJI else self._image_page
        fade_out = QPropertyAnimation(outgoing, b"windowOpacity", self)
        fade_out.setDuration(100)
        fade_out.setStartValue(1.0)
        fade_out.setEndValue(0.0)
        fade_out.setEasingCurve(QEasingCurve.Type.InQuad)

        def _do_swap():
            outgoing.setVisible(False)
            outgoing.setWindowOpacity(1.0)
            incoming.setWindowOpacity(0.0)
            incoming.setVisible(True)
            fade_in = QPropertyAnimation(incoming, b"windowOpacity", self)
            fade_in.setDuration(140)
            fade_in.setStartValue(0.0)
            fade_in.setEndValue(1.0)
            fade_in.setEasingCurve(QEasingCurve.Type.OutCubic)
            fade_in.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        fade_out.finished.connect(_do_swap)
        fade_out.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    def _update_tab_styles(self):
        active_col  = "#c8deff"
        inactive_col = "#44446a"
        self._tab_emoji_lbl.setStyleSheet(
            f"background: transparent; color: {'#c8deff' if self._active_tab == self._TAB_EMOJI else '#44446a'};"
        )
        self._tab_image_lbl.setStyleSheet(
            f"background: transparent; color: {'#c8deff' if self._active_tab == self._TAB_IMAGE else '#44446a'};"
        )

    def show_centered(self):
        sw = self._setup_window
        cx = sw.geometry().center().x()
        cy = sw.geometry().center().y()
        self.move(cx - self.width() // 2, cy - self.height() // 2)
        self.show()

    def show_near(self, _anchor):
        self.show_centered()

    def showEvent(self, e):
        super().showEvent(e)
        _apply_dwm_rounded_corners(int(self.winId()))
        self._label_input.setFocus()
        self._anim_out.stop()
        self._anim_in.setStartValue(0.0)
        self._anim_in.setEndValue(1.0)
        self._anim_in.start()

    def close_animated(self):
        if self._closing:
            return
        self._closing = True
        self._anim_in.stop()
        self._anim_out.setStartValue(self.windowOpacity())
        self._anim_out.setEndValue(0.0)
        self._anim_out.start()

    def _finish_close(self):
        if self._emoji_panel:
            self._emoji_panel.deleteLater()
            self._emoji_panel = None
        self.closed.emit()
        self.close()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag_pos and e.buttons() == Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, e):
        self._drag_pos = None

    def _on_browse(self):
        dialog = QFileDialog(self)
        dialog.setWindowTitle("Choose an image")
        dialog.setNameFilter(
            "All Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tiff *.tif *.ico *.svg);;"
            "PNG (*.png);;JPEG (*.jpg *.jpeg);;ICO (*.ico);;All files (*)"
        )
        dialog.setFileMode(QFileDialog.FileMode.ExistingFile)
        dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        dialog.setWindowFlags(
            dialog.windowFlags() | Qt.WindowType.WindowStaysOnTopHint
        )
        if dialog.exec():
            files = dialog.selectedFiles()
            if files:
                path = files[0]
                self._icon_image_path = path
                self._img_preview.set_image(path)
                name = os.path.basename(path)
                short = name if len(name) <= 28 else "…" + name[-26:]
                self._browse_btn.setText(f"✓  {short}")

    def _on_save(self):
        label = self._label_input.text().strip() or DEFAULT_LABEL

        if self._active_tab == self._TAB_IMAGE and self._icon_image_path:
            try:
                dest_dir = custom_icons_dir()
                ext = os.path.splitext(self._icon_image_path)[1] or ".png"
                dest_name = f"custom_{abs(hash(self._icon_image_path)) % 100000}{ext}"
                dest_path = os.path.join(dest_dir, dest_name)
                with open(self._icon_image_path, "rb") as src, open(dest_path, "wb") as dst:
                    dst.write(src.read())
                icon_value = f"file:{dest_name}"
            except Exception:
                icon_value = DEFAULT_ICON
        else:
            icon_value = self._current_preview_emoji or self._emoji_input.text().strip() or DEFAULT_ICON
        self.saved.emit(icon_value, label)
        self.close_animated()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.close_animated()
        elif e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._on_save()
        else:
            super().keyPressEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(16, 16, 26))
        p.setPen(QPen(QColor(255, 255, 255, 16)))
        p.drawLine(1, 0, w - 2, 0)
        sx, sy, sw2, sh = self._seg_x, self._seg_y, self._seg_w, self._seg_h
        HALF = sw2 // 2
        p.setPen(Qt.PenStyle.NoPen)
        track = QPainterPath()
        track.addRoundedRect(QRectF(sx, sy, sw2, sh), sh / 2, sh / 2)
        p.fillPath(track, QColor(255, 255, 255, 10))
        px = sx if self._active_tab == self._TAB_EMOJI else sx + HALF
        active_pill = QPainterPath()
        active_pill.addRoundedRect(QRectF(px + 2, sy + 2, HALF - 4, sh - 4), (sh - 4) / 2, (sh - 4) / 2)
        p.fillPath(active_pill, QColor(80, 140, 220, 55))  

def set_icon_on_label(label: QLabel, icon_value: str, pixel_size: int):
    if icon_value and icon_value.startswith("file:"):
        filename = icon_value[5:]
        full_path = os.path.join(custom_icons_dir(), filename)
        if os.path.exists(full_path):
            pixmap = QPixmap(full_path)
            if not pixmap.isNull():
                scaled = pixmap.scaled(
                    pixel_size, pixel_size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                label.setPixmap(scaled)
                label.setText("")
                return
    label.setPixmap(QPixmap())
    label.setText(icon_value or DEFAULT_ICON)

class DeviceCard(QWidget):
    selection_changed = pyqtSignal(bool)
    category_changed = pyqtSignal()
    def __init__(self, device: dict, parent=None):
        super().__init__(parent)
        self.device = device
        self._selected = False
        self._hovered = False
        self._chip_hov = False
        self._knob_x = TOG_OFF
        self._tick_tmr = QTimer(self)
        self._tick_tmr.setInterval(8)
        self._tick_tmr.timeout.connect(self._knob_tick)
        self._hover_alpha = 0.0         
        self._hover_tmr = QTimer(self)
        self._hover_tmr.setInterval(12)
        self._hover_tmr.timeout.connect(self._hover_tick)
        self.setFixedHeight(CARD_H)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setToolTip(device.get("name", ""))
        self._icon_lbl = QLabel(self)
        self._icon_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._icon_lbl.setFont(QFont("Segoe UI Emoji", 18))
        self._icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_lbl.setStyleSheet("background: transparent;")
        self._name_lbl = QLabel(self)
        self._name_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        f_name = QFont(ui_font_family(), 11)
        f_name.setWeight(ui_font_emphasis_weight())
        self._name_lbl.setFont(f_name)
        self._name_lbl.setStyleSheet("background: transparent;")
        self._id_lbl = QLabel(self)
        self._id_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._id_lbl.setFont(QFont("Consolas", 9))
        self._id_lbl.setStyleSheet("background: transparent;")
        self._chip_icon_lbl = QLabel(self)
        self._chip_icon_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._chip_icon_lbl.setFont(QFont("Segoe UI Emoji", 11))
        self._chip_icon_lbl.setStyleSheet("background: transparent;")
        self._chip_text_lbl = QLabel(self)
        self._chip_text_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        f_chip = QFont(ui_font_family(), 9)
        f_chip.setWeight(ui_font_emphasis_weight())
        self._chip_text_lbl.setFont(f_chip)
        self._chip_text_lbl.setStyleSheet("background: transparent;")
        self._chip_chevron_lbl = QLabel("▾", self)
        self._chip_chevron_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._chip_chevron_lbl.setFont(QFont(ui_font_family(), 9))
        self._chip_chevron_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._chip_chevron_lbl.setStyleSheet("background: transparent;")
        self._chip_rect = QRect()
        self._is_override = False
        self._open_dropdown = None
        self._refresh_labels()

    def _hover_tick(self):
        target = 1.0 if self._hovered else 0.0
        step = 0.13
        diff = target - self._hover_alpha
        if abs(diff) < 0.01:
            self._hover_alpha = target
            self._hover_tmr.stop()
        else:
            self._hover_alpha += diff * step * 6   # fast lerp
        self.update()

    def _knob_tick(self):
        target = TOG_ON if self._selected else TOG_OFF
        self._knob_x += (target - self._knob_x) * 0.30
        if abs(self._knob_x - target) < 0.5:
            self._knob_x = target
            self._tick_tmr.stop()
        self.update()

    def _toggle(self):
        self._selected = not self._selected
        self._tick_tmr.start()
        self.selection_changed.emit(self._selected)
        self._refresh_labels()
        self.update()

    def is_checked(self):
        return self._selected

    def _current_category_index(self) -> int:
        idx = self.device.get("category_index")
        if idx is not None and 0 <= idx < len(CATEGORY_OPTIONS):
            return idx
        _icon, label = classify_device(self.device)
        for i, (_ic, lb) in enumerate(CATEGORY_OPTIONS):
            if lb == label:
                return i
        return len(CATEGORY_OPTIONS) - 1

    def _open_category_dropdown(self):
        if self._open_dropdown is not None:
            if isinstance(self._open_dropdown, CustomDeviceDialog):
                self._open_dropdown.raise_()
                self._open_dropdown.activateWindow()
                return
            self._open_dropdown.close_animated()
            self._open_dropdown = None
            return
        cur_idx = self._current_category_index()
        anchor = self.mapToGlobal(QPoint(self._chip_rect.x(), self._chip_rect.bottom() + 4))
        dropdown = CategoryDropdown(cur_idx, anchor, self)
        dropdown.picked.connect(self._on_category_picked)
        dropdown.custom_requested.connect(self._on_custom_requested)
        dropdown.closed.connect(self._on_dropdown_closed)
        dropdown.show()
        self._open_dropdown = dropdown

    def _on_dropdown_closed(self):
        self._open_dropdown = None

    def _on_category_picked(self, idx: int):
        self.device["category_index"] = idx
        self.device.pop("custom_icon", None)
        self.device.pop("custom_label", None)
        self.category_changed.emit()
        self._refresh_labels()
        self.update()

    def _on_custom_requested(self):
        icon, label = classify_device(self.device)
        setup = self.window()
        if hasattr(setup, '_is_locked') and setup._is_locked():
            setup._beep_and_focus_modal()
            return
        dialog = CustomDeviceDialog(icon, label, setup)
        dialog.saved.connect(self._on_custom_saved)
        dialog.closed.connect(self._on_custom_dialog_closed)
        anchor = self.mapToGlobal(QPoint(self._chip_rect.x(), self._chip_rect.bottom() + 4))
        if hasattr(setup, 'set_modal_dialog'):
            setup.set_modal_dialog(dialog)
        dialog.show_near(anchor)
        self._open_dropdown = dialog

    def _on_custom_dialog_closed(self):
        self._open_dropdown = None
        setup = self.window()
        if hasattr(setup, 'set_modal_dialog'):
            setup.set_modal_dialog(None)

    def _on_custom_saved(self, icon_value: str, label: str):
        self.device["custom_icon"] = icon_value
        self.device["custom_label"] = label
        self.device.pop("category_index", None)
        self.category_changed.emit()
        self._refresh_labels()
        self.update()

    def _refresh_labels(self):
        w, h = self.width(), self.height()
        icon, label = classify_device(self.device)
        is_override = (
            self.device.get("category_index") is not None
            or self.device.get("custom_icon") is not None
        )
        self._is_override = is_override
        set_icon_on_label(self._icon_lbl, icon, 26)
        self._icon_lbl.setGeometry(14, 0, 38, 56)
        tog_x = w - TOG_W - 16
        name_x = 60
        text_w = max(10, tog_x - name_x - 12)
        name_col = "#e8e8f4" if self._selected else "#b9b9d2"
        self._name_lbl.setStyleSheet(f"background: transparent; color: {name_col};")
        fm = QFontMetrics(self._name_lbl.font())
        elided_name = fm.elidedText(self.device["name"], Qt.TextElideMode.ElideRight, text_w)
        self._name_lbl.setText(elided_name)
        self._name_lbl.setGeometry(name_x, 10, text_w, 24)
        id_col = "#505073" if self._selected else "#373750"
        self._id_lbl.setStyleSheet(f"background: transparent; color: {id_col};")
        fm2 = QFontMetrics(self._id_lbl.font())
        short_id = self.device["id"][-44:]
        elided_id = fm2.elidedText(short_id, Qt.TextElideMode.ElideRight, text_w)
        self._id_lbl.setText(elided_id)
        self._id_lbl.setGeometry(name_x, 35, text_w, 18)
        chip_pad_x = 10
        chip_h = 24
        chevron_w = 16
        icon_w = 20
        gap = 6  
        fm3 = QFontMetrics(self._chip_text_lbl.font())
        chip_text_w = fm3.horizontalAdvance(label) + 4
        chip_w = chip_pad_x + icon_w + gap + chip_text_w + chevron_w + chip_pad_x
        chip_x = name_x
        chip_y = 60
        self._chip_rect = QRect(chip_x, chip_y, chip_w, chip_h)
        set_icon_on_label(self._chip_icon_lbl, icon, 14)
        self._chip_icon_lbl.setGeometry(chip_x + chip_pad_x, chip_y, icon_w, chip_h)
        chip_text_col = "#c8c8e0" if not is_override else "#c8aaff"
        self._chip_text_lbl.setStyleSheet(f"background: transparent; color: {chip_text_col};")
        self._chip_text_lbl.setText(label)
        self._chip_text_lbl.setGeometry(chip_x + chip_pad_x + icon_w + gap, chip_y, chip_text_w + 4, chip_h)
        chevron_col = "#6699ff" if self._chip_hov else "#9696af"
        self._chip_chevron_lbl.setStyleSheet(f"background: transparent; color: {chevron_col};")
        self._chip_chevron_lbl.setGeometry(chip_x + chip_w - chevron_w - 4, chip_y, chevron_w, chip_h)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._refresh_labels()

    def enterEvent(self, e):
        self._hovered = True
        self._hover_tmr.start()

    def leaveEvent(self, e):
        self._hovered = False
        self._chip_hov = False
        self._hover_tmr.start()
        self._refresh_labels()

    def mouseMoveEvent(self, e):
        over_chip = self._chip_rect.contains(e.pos())
        if over_chip != self._chip_hov:
            self._chip_hov = over_chip
            self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            self._refresh_labels()
            self.update()

    def mousePressEvent(self, e):
        setup = self.window()
        if hasattr(setup, '_is_locked') and setup._is_locked():
            setup._beep_and_focus_modal()
            return
        if self._chip_rect.contains(e.pos()):
            self._open_category_dropdown()
        else:
            self._toggle()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        w, h = self.width(), self.height()
        card_rect = QRectF(1, 1, w - 2, h - 2)
        path = QPainterPath()
        path.addRoundedRect(card_rect, 13, 13)
        if self._selected:
            bg = SURF_SEL
        else:
            a = self._hover_alpha
            r = int(SURF.red()   + (SURF_HOV.red()   - SURF.red())   * a)
            g = int(SURF.green() + (SURF_HOV.green() - SURF.green()) * a)
            b = int(SURF.blue()  + (SURF_HOV.blue()  - SURF.blue())  * a)
            bg = QColor(r, g, b)
        p.fillPath(path, bg)
        if self._selected:
            bar = QPainterPath()
            bar.addRoundedRect(QRectF(1, 18, 3, h - 36), 2, 2)
            g2 = QLinearGradient(0, 18, 0, h - 18)
            g2.setColorAt(0, ACCENT_A)
            g2.setColorAt(1, ACCENT_B)
            p.fillPath(bar, QBrush(g2))
        if self._selected:
            bc = BORDER_SEL
        else:
            a = self._hover_alpha
            br = int(BORDER.red()   + (BORDER_HOV.red()   - BORDER.red())   * a)
            bg2= int(BORDER.green() + (BORDER_HOV.green() - BORDER.green()) * a)
            bb = int(BORDER.blue()  + (BORDER_HOV.blue()  - BORDER.blue())  * a)
            ba = int(BORDER.alpha() + (BORDER_HOV.alpha() - BORDER.alpha()) * a)
            bc = QColor(br, bg2, bb, ba)
        pen = QPen(bc)
        pen.setWidthF(1.2)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        chip_path = QPainterPath()
        chip_r = self._chip_rect.height() / 2.0  
        chip_path.addRoundedRect(QRectF(self._chip_rect), chip_r, chip_r)
        if self._chip_hov:
            chip_bg, chip_border = QColor(99, 179, 255, 45), QColor(99, 179, 255, 140)
        elif self._is_override:
            chip_bg, chip_border = QColor(168, 100, 255, 28), QColor(168, 100, 255, 90)
        else:
            chip_bg, chip_border = QColor(255, 255, 255, 14), QColor(255, 255, 255, 30)
        p.fillPath(chip_path, chip_bg)
        cpen = QPen(chip_border)
        cpen.setWidthF(1.0)
        p.setPen(cpen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(chip_path)
        tog_x = w - TOG_W - 16
        tog_y = 16
        tr = QRectF(tog_x, tog_y, TOG_W, TOG_H)
        tpath = QPainterPath()
        tpath.addRoundedRect(tr, TOG_H / 2, TOG_H / 2)
        if self._selected:
            tg = QLinearGradient(tog_x, 0, tog_x + TOG_W, 0)
            tg.setColorAt(0, ACCENT_A)
            tg.setColorAt(1, ACCENT_B)
            p.fillPath(tpath, QBrush(tg))
        else:
            p.fillPath(tpath, KNOB_OFF)
        kx = tog_x + self._knob_x
        ky = float(tog_y + (TOG_H - KNOB_D) / 2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 55))
        p.drawEllipse(QRectF(kx, ky + 1.5, KNOB_D, KNOB_D))
        p.setBrush(QColor(255, 255, 255))
        p.drawEllipse(QRectF(kx, ky, KNOB_D, KNOB_D))

class HotkeyRow(QWidget):
    changed = pyqtSignal(str)
    def __init__(self, hotkey: str, parent=None):
        super().__init__(parent)
        self.hotkey = hotkey
        self._hovered = False
        self._chip_hov = False
        self._hover_alpha = 0.0
        self._hover_tmr = QTimer(self)
        self._hover_tmr.setInterval(12)
        self._hover_tmr.timeout.connect(self._hover_tick)
        self.setFixedHeight(58)
        self.setMouseTracking(True)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setToolTip("click to record a new switch hotkey")
        self._title_lbl = QLabel("Switch Hotkey", self)
        f_title = QFont(ui_font_family(), 11)
        f_title.setWeight(ui_font_emphasis_weight())
        self._title_lbl.setFont(f_title)
        self._title_lbl.setStyleSheet("background: transparent; color: #c8c8e0;")
        self._title_lbl.setGeometry(16, 8, 200, 22)
        self._sub_lbl = QLabel("Used to cycle between your devices", self)
        self._sub_lbl.setFont(QFont(ui_font_family(), 9))
        self._sub_lbl.setStyleSheet("background: transparent; color: #55557a;")
        self._sub_lbl.setGeometry(16, 30, 260, 18)
        self._chip_lbl = QLabel(self)
        f_chip = QFont(ui_font_family(), 10)
        f_chip.setWeight(ui_font_emphasis_weight())
        self._chip_lbl.setFont(f_chip)
        self._chip_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._chip_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._chip_rect = QRect()
        self._open_dropdown = None
        self._refresh()
    def _hover_tick(self):
        target = 1.0 if self._hovered else 0.0
        diff = target - self._hover_alpha
        if abs(diff) < 0.01:
            self._hover_alpha = target
            self._hover_tmr.stop()
        else:
            self._hover_alpha += diff * 0.78
        self.update()

    def _refresh(self):
        w = self.width()
        fm = QFontMetrics(self._chip_lbl.font())
        text = self.hotkey.upper()
        chip_w = fm.horizontalAdvance(text) + 28
        chip_h = 30
        chip_x = w - chip_w - 16
        chip_y = (self.height() - chip_h) // 2
        self._chip_rect = QRect(chip_x, chip_y, chip_w, chip_h)
        self._chip_lbl.setText(text)
        self._chip_lbl.setGeometry(self._chip_rect)
        self._chip_lbl.setStyleSheet("background: transparent; color: #c8c8e0;")

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._refresh()

    def enterEvent(self, e):
        self._hovered = True
        self._hover_tmr.start()

    def leaveEvent(self, e):
        self._hovered = False
        self._chip_hov = False
        self._hover_tmr.start()

    def mouseMoveEvent(self, e):
        over_chip = self._chip_rect.contains(e.pos())
        if over_chip != self._chip_hov:
            self._chip_hov = over_chip
            self.update()

    def mousePressEvent(self, e):
        if self._open_dropdown is not None:
            return  
        dropdown = HotkeyCaptureDropdown(self.hotkey, self)
        dropdown.picked.connect(self._on_picked)
        dropdown.closed.connect(self._on_dropdown_closed)
        global_pt = self.mapToGlobal(QPoint(self._chip_rect.x(), self._chip_rect.bottom() + 6))
        dropdown.move(global_pt)
        dropdown.show()
        self._open_dropdown = dropdown

    def _on_dropdown_closed(self):
        self._open_dropdown = None

    def _on_picked(self, new_hotkey: str):
        self.hotkey = new_hotkey
        self._refresh()
        self.changed.emit(new_hotkey)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        w, h = self.width(), self.height()
        card_rect = QRectF(1, 1, w - 2, h - 2)
        path = QPainterPath()
        path.addRoundedRect(card_rect, 13, 13)
        a = self._hover_alpha
        r = int(SURF.red()   + (SURF_HOV.red()   - SURF.red())   * a)
        g = int(SURF.green() + (SURF_HOV.green() - SURF.green()) * a)
        b = int(SURF.blue()  + (SURF_HOV.blue()  - SURF.blue())  * a)
        p.fillPath(path, QColor(r, g, b))
        br = int(BORDER.red()   + (BORDER_HOV.red()   - BORDER.red())   * a)
        bg2= int(BORDER.green() + (BORDER_HOV.green() - BORDER.green()) * a)
        bb = int(BORDER.blue()  + (BORDER_HOV.blue()  - BORDER.blue())  * a)
        ba = int(BORDER.alpha() + (BORDER_HOV.alpha() - BORDER.alpha()) * a)
        pen = QPen(QColor(br, bg2, bb, ba))
        pen.setWidthF(1.2)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        chip_path = QPainterPath()
        chip_path.addRoundedRect(QRectF(self._chip_rect), 9, 9)
        if self._chip_hov:
            p.fillPath(chip_path, QColor(99, 179, 255, 45))
            cpen = QPen(QColor(99, 179, 255, 140))
        else:
            p.fillPath(chip_path, QColor(255, 255, 255, 14))
            cpen = QPen(QColor(255, 255, 255, 30))
        cpen.setWidthF(1.0)
        p.setPen(cpen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(chip_path)

class StartupRow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._hovered = False
        self._busy = False
        self._knob_x = TOG_OFF
        self._tick_tmr = QTimer(self)
        self._tick_tmr.setInterval(8)
        self._tick_tmr.timeout.connect(self._knob_tick)
        self._hover_alpha = 0.0
        self._hover_tmr = QTimer(self)
        self._hover_tmr.setInterval(12)
        self._hover_tmr.timeout.connect(self._hover_tick)
        self._disabled = not _is_frozen()
        self.setFixedHeight(58)
        self.setMouseTracking(True)
        if self._disabled:
            self.setCursor(QCursor(Qt.CursorShape.ForbiddenCursor))
            self.setToolTip("Only available when running as a compiled .exe")
        else:
            self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            self.setToolTip("launch automatically when you log into Windows")
        self._title_lbl = QLabel("Launch at Startup", self)
        f_title = QFont(ui_font_family(), 11)
        f_title.setWeight(ui_font_emphasis_weight())
        self._title_lbl.setFont(f_title)
        col = "#505060" if self._disabled else "#c8c8e0"
        self._title_lbl.setStyleSheet(f"background: transparent; color: {col};")
        self._title_lbl.setGeometry(16, 8, 280, 22)
        sub_text = "Not available for raw script" if self._disabled else "Adds a Task Scheduler entry, runs elevated"
        self._sub_lbl = QLabel(sub_text, self)
        self._sub_lbl.setFont(QFont(ui_font_family(), 9))
        self._sub_lbl.setStyleSheet("background: transparent; color: #55557a;")
        self._sub_lbl.setGeometry(16, 30, 320, 18)
        self._selected = (not self._disabled) and is_startup_task_installed()
        self._knob_x = TOG_ON if self._selected else TOG_OFF

    def _hover_tick(self):
        target = 1.0 if self._hovered else 0.0
        diff = target - self._hover_alpha
        if abs(diff) < 0.01:
            self._hover_alpha = target
            self._hover_tmr.stop()
        else:
            self._hover_alpha += diff * 0.78
        self.update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.update()

    def enterEvent(self, e):
        if self._disabled:
            return
        self._hovered = True
        self._hover_tmr.start()

    def leaveEvent(self, e):
        if self._disabled:
            return
        self._hovered = False
        self._hover_tmr.start()

    def _knob_tick(self):
        target = TOG_ON if self._selected else TOG_OFF
        self._knob_x += (target - self._knob_x) * 0.30
        if abs(self._knob_x - target) < 0.5:
            self._knob_x = target
            self._tick_tmr.stop()
        self.update()

    def mousePressEvent(self, e):
        if self._disabled or self._busy:
            return
        self._busy = True
        self.setCursor(QCursor(Qt.CursorShape.WaitCursor))
        if self._selected:
            ok = remove_from_startup(exit_on_denial=True)
            if ok:
                self._selected = False
                self._tick_tmr.start()
        else:
            ok = add_to_startup(exit_on_denial=True)
            if ok:
                self._selected = True
                self._tick_tmr.start()
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._busy = False
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        w, h = self.width(), self.height()
        card_rect = QRectF(1, 1, w - 2, h - 2)
        path = QPainterPath()
        path.addRoundedRect(card_rect, 13, 13)
        a = self._hover_alpha
        r = int(SURF.red()   + (SURF_HOV.red()   - SURF.red())   * a)
        g = int(SURF.green() + (SURF_HOV.green() - SURF.green()) * a)
        b = int(SURF.blue()  + (SURF_HOV.blue()  - SURF.blue())  * a)
        p.fillPath(path, QColor(r, g, b))
        br = int(BORDER.red()   + (BORDER_HOV.red()   - BORDER.red())   * a)
        bg2= int(BORDER.green() + (BORDER_HOV.green() - BORDER.green()) * a)
        bb = int(BORDER.blue()  + (BORDER_HOV.blue()  - BORDER.blue())  * a)
        ba = int(BORDER.alpha() + (BORDER_HOV.alpha() - BORDER.alpha()) * a)
        pen = QPen(QColor(br, bg2, bb, ba))
        pen.setWidthF(1.2)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        tog_x = w - TOG_W - 16
        tog_y = (h - TOG_H) // 2
        tr = QRectF(tog_x, tog_y, TOG_W, TOG_H)
        tpath = QPainterPath()
        tpath.addRoundedRect(tr, TOG_H / 2, TOG_H / 2)
        if self._disabled:
            p.fillPath(tpath, QColor(28, 28, 38))
        elif self._selected:
            tg = QLinearGradient(tog_x, 0, tog_x + TOG_W, 0)
            tg.setColorAt(0, ACCENT_A)
            tg.setColorAt(1, ACCENT_B)
            p.fillPath(tpath, QBrush(tg))
        else:
            p.fillPath(tpath, KNOB_OFF)
        kx = tog_x + self._knob_x
        ky = float(tog_y + (TOG_H - KNOB_D) / 2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 55))
        p.drawEllipse(QRectF(kx, ky + 1.5, KNOB_D, KNOB_D))
        p.setBrush(QColor(55, 55, 65) if self._disabled else QColor(255, 255, 255))
        p.drawEllipse(QRectF(kx, ky, KNOB_D, KNOB_D))

class GradientButton(QWidget):
    clicked = pyqtSignal()
    def __init__(self, parent=None):
        super().__init__(parent)
        self._enabled = False
        self._hovered = False
        self._press_scale = 1.0
        self.setFixedHeight(50)
        self._label = QLabel("Select at least 2 devices", self)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        f = QFont(ui_font_family(), 12)
        f.setWeight(ui_font_emphasis_weight())
        self._label.setFont(f)
        self._apply_label_color()
        self._press_anim = QVariantAnimation(self)
        self._press_anim.setDuration(160)
        self._press_anim.valueChanged.connect(self._on_scale_changed)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._label.setGeometry(self.rect())

    def _apply_label_color(self):
        color = "#08081a" if self._enabled else "#414160"
        self._label.setStyleSheet(f"background: transparent; color: {color};")

    def set_state(self, enabled: bool, text: str):
        self._enabled = enabled
        self._label.setText(text)
        self._apply_label_color()
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor if enabled else Qt.CursorShape.ArrowCursor))
        self.update()

    def enterEvent(self, e):
        self._hovered = True
        self.update()

    def leaveEvent(self, e):
        self._hovered = False
        self.update()

    def mousePressEvent(self, e):
        if not self._enabled:
            return
        self._press_anim.stop()
        self._press_anim.setStartValue(self._press_scale)
        self._press_anim.setEndValue(0.96)
        self._press_anim.setEasingCurve(QEasingCurve.Type.OutQuad)
        self._press_anim.start()

    def mouseReleaseEvent(self, e):
        if not self._enabled:
            return
        self._press_anim.stop()
        self._press_anim.setStartValue(self._press_scale)
        self._press_anim.setEndValue(1.0)
        self._press_anim.setEasingCurve(QEasingCurve.Type.OutBack)
        self._press_anim.start()
        if self.rect().contains(e.pos()):
            self.clicked.emit()

    def _on_scale_changed(self, val):
        self._press_scale = val
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        w, h = float(self.width()), float(self.height())
        s = self._press_scale
        p.translate(w / 2, h / 2)
        p.scale(s, s)
        p.translate(-w / 2, -h / 2)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, w, h), 12, 12)

        if self._enabled:
            g = QLinearGradient(0, 0, w, 0)
            g.setColorAt(0, QColor(130, 190, 255) if self._hovered else ACCENT_A)
            g.setColorAt(1, QColor(195, 130, 255) if self._hovered else ACCENT_B)
            p.fillPath(path, QBrush(g))
            gloss = QPainterPath()
            gloss.addRoundedRect(QRectF(0, 0, w, h * 0.5), 12, 12)
            p.fillPath(gloss, QColor(255, 255, 255, 22))
        else:
            p.fillPath(path, QColor(25, 25, 40))


class SetupWindow(QWidget):
    devices_saved = pyqtSignal(list, str)
    def __init__(self, all_devices: list[dict], initial_hotkey: str = DEFAULT_HOTKEY):
        super().__init__()
        self._devices = all_devices
        self._cards: list[DeviceCard] = []
        self._drag_pos = None
        self._hotkey = initial_hotkey
        self._modal_dialog = None
        self._initial_hotkey = initial_hotkey
        config = load_config()
        self._initial_device_ids = (
            {d["id"] for d in config["devices"]} if config else set()
        )
        self._is_edit_mode = getattr(QApplication.instance(), "_tray_started", False)
        self.setWindowTitle("Volume Switcher")
        self.setFixedWidth(500)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self._build_ui()
        self.adjustSize()

    def set_modal_dialog(self, dialog):
        self._modal_dialog = dialog

    def _is_locked(self) -> bool:
        return self._modal_dialog is not None and self._modal_dialog.isVisible()

    def _beep_and_focus_modal(self):
        ctypes.windll.user32.MessageBeep(0xFFFFFFFF)  
        if self._modal_dialog:
            self._modal_dialog.raise_()
            self._modal_dialog.activateWindow()

    def mousePressEvent(self, e):
        if self._is_locked():
            self._beep_and_focus_modal()
            return
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._is_locked():
            return
        if self._drag_pos and e.buttons() == Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, e):
        if self._is_locked():
            return
        self._drag_pos = None

    def showEvent(self, e):
        super().showEvent(e)
        _apply_dwm_rounded_corners(int(self.winId()))

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, BG)
        g = QLinearGradient(0, 0, 0, 80)
        g.setColorAt(0, QColor(255, 255, 255, 12))
        g.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillRect(0, 0, w, 80, QBrush(g))
        p.setPen(QPen(QColor(255, 255, 255, 28)))
        p.drawLine(1, 0, w - 2, 0)    
        p.drawLine(0, 0, 0, h - 1)    
        p.drawLine(w - 1, 0, w - 1, h - 1)  
        p.drawLine(1, h - 1, w - 2, h - 1)  

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        tbar = QWidget()
        tbar.setFixedHeight(58)
        tbar.setStyleSheet("background: transparent;")
        tb = QHBoxLayout(tbar)
        tb.setContentsMargins(24, 0, 14, 0)
        tb.setSpacing(10)
        icon = QLabel("🎵")
        icon.setFont(QFont("Segoe UI Emoji", 15))
        icon.setStyleSheet("background: transparent; color: white;")
        title = QLabel("Device Setup")
        tf = QFont(ui_font_family(), 14)
        tf.setWeight(ui_font_emphasis_weight())
        title.setFont(tf)
        title.setStyleSheet("color: #e8e8f4; background: transparent;")
        close = QPushButton("✕")
        close.setFixedSize(30, 30)
        close.setStyleSheet("""
            QPushButton { background: transparent; color: #505070; border: none; font-size: 14px; border-radius: 7px; }
            QPushButton:hover { background: rgba(255,55,55,0.22); color: #ff5555; }
        """)
        close.clicked.connect(self._on_close_clicked)
        tb.addWidget(icon)
        tb.addWidget(title)
        tb.addStretch()
        tb.addWidget(close)
        root.addWidget(tbar)
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: rgba(255,255,255,0.05);")
        root.addWidget(sep)
        body = QWidget()
        body.setStyleSheet("background: transparent;")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(20, 18, 20, 22)
        bl.setSpacing(0)
        sub = QLabel("Pick the devices you want to cycle through.\nYou need at least two.")
        sub.setFont(QFont(ui_font_family(), 11))
        sub.setStyleSheet("color: #5a5a7a; background: transparent;")
        bl.addWidget(sub)
        bl.addSpacing(14)
        self._hotkey_row = HotkeyRow(self._hotkey)
        self._hotkey_row.changed.connect(self._on_hotkey_changed)
        bl.addWidget(self._hotkey_row)
        bl.addSpacing(8)
        self._startup_row = StartupRow()
        bl.addWidget(self._startup_row)
        bl.addSpacing(10)
        scroll = SmoothScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"""
            QScrollArea {{ border: none; background: transparent; }}
            QWidget#inner {{ background: transparent; }}
            {SCROLLBAR_SS}
        """)
        inner = QWidget()
        inner.setObjectName("inner")
        inner.setStyleSheet("background: transparent;")
        il = QVBoxLayout(inner)
        il.setContentsMargins(0, 0, 4, 0)
        il.setSpacing(7)
        for dev in self._devices:
            card = DeviceCard(dev)
            card.selection_changed.connect(self._refresh_btn)
            card.category_changed.connect(self._refresh_btn)
            il.addWidget(card)
            self._cards.append(card)
        il.addStretch()
        scroll.setWidget(inner)
        scroll.setFixedHeight(min(len(self._devices) * (CARD_H + 7) + 14, 380))
        bl.addWidget(scroll)
        bl.addSpacing(6)
        hint = QLabel(f"  Saves to  {CONFIG_PATH}")
        hint.setFont(QFont("Consolas", 9))
        hint.setStyleSheet("color: #282840; background: transparent;")
        bl.addWidget(hint)
        bl.addSpacing(12)
        self._btn = GradientButton()
        self._btn.clicked.connect(self._on_save)
        bl.addWidget(self._btn)
        root.addWidget(body)
        QTimer.singleShot(0, self._refresh_btn)

    def _on_close_clicked(self):
        app = QApplication.instance()
        if getattr(app, "_tray_started", False):
            self.close()
        else:
            QApplication.quit()

    def _on_hotkey_changed(self, hotkey: str):
        self._hotkey = hotkey
        self._refresh_btn()

    def _has_changes(self) -> bool:
        selected_ids = {c.device["id"] for c in self._cards if c.is_checked()}
        return (
            selected_ids != self._initial_device_ids
            or self._hotkey != self._initial_hotkey
        )

    def _refresh_btn(self):
        n = sum(1 for c in self._cards if c.is_checked())
        ok = n >= 2

        if self._is_edit_mode:
            if ok and self._has_changes():
                self._btn.set_state(True, f"Save  ·  {n} devices selected")
            elif ok:
                self._btn.set_state(False, "No changes to save")
            else:
                self._btn.set_state(False, "Select 1 more device" if n == 1 else "Select at least 2 devices")
        else:
            text = (
                f"Save & start  ·  {n} devices selected" if ok
                else ("Select 1 more device" if n == 1 else "Select at least 2 devices")
            )
            self._btn.set_state(ok, text)

    def _on_save(self):
        selected = [c.device for c in self._cards if c.is_checked()]
        if len(selected) < 2:
            return
        try:
            save_config(selected, self._hotkey)
        except Exception:
            return
        self.devices_saved.emit(selected, self._hotkey)
        self.close()

class VolumeBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._vol = 50

    def set_volume(self, v):
        self._vol = max(0, min(100, v))
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        w, h = float(self.width()), float(self.height())
        r = h / 2
        track = QPainterPath()
        track.addRoundedRect(QRectF(0, 0, w, h), r, r)
        p.fillPath(track, QColor(255, 255, 255, 40))
        fw = w * self._vol / 100
        if fw > 0:
            fill = QPainterPath()
            fill.addRoundedRect(QRectF(0, 0, fw, h), r, r)
            g = QLinearGradient(0, 0, fw, 0)
            g.setColorAt(0, ACCENT_A)
            g.setColorAt(1, ACCENT_B)
            p.fillPath(fill, QBrush(g))

class OSDWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.BypassWindowManagerHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(310, 108)
        self.setWindowOpacity(0.0)
        self._anim = None
        self._hide = QTimer(self)
        self._hide.setSingleShot(True)
        self._hide.timeout.connect(self._fade_out)
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 15)
        lay.setSpacing(0)
        row1 = QHBoxLayout()
        row1.setSpacing(12)
        self.icon_lbl = QLabel("🔊")
        self.icon_lbl.setFont(QFont("Segoe UI Emoji", 17))
        self.icon_lbl.setFixedWidth(30)
        self.icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        self.icon_lbl.setStyleSheet("background: transparent;")
        self.name_lbl = QLabel("Speakers")
        nf = QFont(ui_font_family(), 13)
        nf.setWeight(ui_font_emphasis_weight())
        self.name_lbl.setFont(nf)
        self.name_lbl.setStyleSheet("color: rgba(240,240,248,230); background: transparent;")
        row1.addWidget(self.icon_lbl)
        row1.addWidget(self.name_lbl, 1)
        row2 = QHBoxLayout()
        row2.setSpacing(10)
        self.bar = VolumeBar()
        self.bar.setFixedHeight(5)
        self.vol_lbl = QLabel("50%")
        self.vol_lbl.setFont(QFont(ui_font_family(), 11))
        self.vol_lbl.setStyleSheet("color: rgba(180,180,200,180); background: transparent;")
        self.vol_lbl.setFixedWidth(36)
        self.vol_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row2.addWidget(self.bar, 1)
        row2.addWidget(self.vol_lbl)
        lay.addLayout(row1)
        lay.addSpacing(14)
        lay.addLayout(row2)

    def show_popup(self, icon: str, label: str, volume: int):
        set_icon_on_label(self.icon_lbl, icon, 22)
        fm = QFontMetrics(self.name_lbl.font())
        available_w = self.width() - 18 - 30 - 12 - 18
        elided = fm.elidedText(label, Qt.TextElideMode.ElideRight, available_w)
        self.name_lbl.setText(elided)
        self.vol_lbl.setText(f"{volume}%")
        self.bar.set_volume(volume)
        self._hide.stop()
        if self._anim:
            self._anim.stop()
        self.move(24, 24)
        self.show()
        self.raise_()
        self._animate(1.0, 160, QEasingCurve.Type.OutCubic)
        self._hide.start(2700)

    def show_unavailable(self, label: str):
        set_icon_on_label(self.icon_lbl, "⚠️", 22)
        fm = QFontMetrics(self.name_lbl.font())
        available_w = self.width() - 18 - 30 - 12 - 18
        elided = fm.elidedText(f"{label} unavailable", Qt.TextElideMode.ElideRight, available_w)
        self.name_lbl.setText(elided)
        self.vol_lbl.setText("")
        self.bar.set_volume(0)
        self._hide.stop()
        if self._anim:
            self._anim.stop()
        self.move(24, 24)
        self.show()
        self.raise_()
        self._animate(1.0, 160, QEasingCurve.Type.OutCubic)
        self._hide.start(2200)

    def _fade_out(self):
        if self._anim:
            self._anim.stop()
        self._animate(0.0, 380, QEasingCurve.Type.InCubic, on_finish=self.hide)

    def _animate(self, to, dur, curve, on_finish=None):
        self._anim = QPropertyAnimation(self, b"windowOpacity")
        self._anim.setDuration(dur)
        self._anim.setStartValue(self.windowOpacity())
        self._anim.setEndValue(to)
        self._anim.setEasingCurve(curve)
        if on_finish:
            self._anim.finished.connect(on_finish)
        self._anim.start()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = self.rect().adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(QRectF(r.x(), r.y(), r.width(), r.height()), 14, 14)
        p.setClipPath(path)
        p.fillPath(path, QColor(18, 18, 24, 242))
        g = QLinearGradient(0, 0, 0, 40)
        g.setColorAt(0, QColor(255, 255, 255, 18))
        g.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillPath(path, QBrush(g))
        p.setClipping(False)
        pen = QPen(QColor(255, 255, 255, 28))
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

class TrayIcon(QSystemTrayIcon):
    def __init__(self, parent=None):
        ico_path = icon_path()
        icon = QIcon(ico_path) if ico_path else QApplication.style().standardIcon(
            QApplication.style().StandardPixmap.SP_MediaVolume
        )
        super().__init__(icon, parent)
        self.setToolTip("Audio Device Switcher")
        self._menu = QMenu()
        self._edit_action = QAction("Edit")
        self._edit_action.triggered.connect(self._on_edit)
        self._menu.addAction(self._edit_action)
        self._menu.addSeparator()
        self._startup_action = QAction("Add to Startup")
        self._startup_action.triggered.connect(self._on_startup_toggled)
        if not _is_frozen():
            self._startup_action.setEnabled(False)
            self._startup_action.setText("Add to Startup")
        self._menu.addAction(self._startup_action)
        self._menu.addSeparator()
        self._close_action = QAction("Close")
        self._close_action.triggered.connect(self._on_close)
        self._menu.addAction(self._close_action)
        self.setContextMenu(self._menu)
        self._setup_win = None
        self._refresh_startup_label()
        self.activated.connect(self._on_activated)

    def _refresh_startup_label(self):
        if not _is_frozen():
            return  
        installed = is_startup_task_installed()
        self._startup_action.setText("Remove from Startup" if installed else "Add to Startup")

    def _on_startup_toggled(self):
        if is_startup_task_installed():
            remove_from_startup(exit_on_denial=True)
        else:
            add_to_startup(exit_on_denial=True)
        self._refresh_startup_label()

    def _on_edit(self):
        if self._setup_win is not None and self._setup_win.isVisible():
            self._setup_win.raise_()
            self._setup_win.activateWindow()
            return
        config = load_config()
        try:
            all_devices = enumerate_devices()
        except Exception:
            return
        hotkey = config["hotkey"] if config else DEFAULT_HOTKEY
        self._setup_win = SetupWindow(all_devices, hotkey)
        if config:
            configured_ids = {d["id"] for d in config["devices"]}
            id_to_saved = {d["id"]: d for d in config["devices"]}
            for card in self._setup_win._cards:
                did = card.device["id"]
                if did in configured_ids:
                    saved = id_to_saved[did]
                    card.device.update(saved)
                    card._selected = True
                    card._knob_x = TOG_ON
                    card._refresh_labels()
        self._setup_win.devices_saved.connect(self._on_devices_saved)
        self._setup_win.show()
        self._setup_win.raise_()

    def _on_devices_saved(self, devices, hotkey):
        start_switcher(devices, hotkey)

    def _on_close(self):
        QApplication.instance().quit()

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.contextMenu().popup(QCursor.pos())

class Bridge(QObject):
    show_osd = pyqtSignal(str, str, int)
    show_unavailable = pyqtSignal(str)

def _keyboard_listener_thread():
    comtypes.CoInitialize()
    try:
        keyboard.wait()
    finally:
        comtypes.CoUninitialize()

def start_switcher(devices, hotkey):
    app = QApplication.instance()
    app._osd = OSDWindow()
    app._bridge = Bridge()
    osd = app._osd
    bridge = app._bridge
    bridge.show_osd.connect(osd.show_popup)
    bridge.show_unavailable.connect(osd.show_unavailable)
    index = [0]
    unavailable = set()
    if not getattr(app, "_tray_started", False):
        app._tray = TrayIcon()
        app._tray.show()
        app._tray_started = True

    def try_switch_to(i: int) -> bool:
        dev = devices[i]
        if not is_device_active(dev["id"]):
            unavailable.add(i)
            return False
        try:
            set_default_device(dev["id"])
            unavailable.discard(i)
            return True
        except Exception:
            unavailable.add(i)
            return False

    def toggle():
        n = len(devices)
        next_i = (index[0] + 1) % n
        if try_switch_to(next_i):
            index[0] = next_i
        else:
            _icon, skipped_label = classify_device(devices[next_i])
            landed = None
            for step in range(2, n + 1):
                candidate = (index[0] + step) % n
                if candidate in unavailable:
                    continue
                if try_switch_to(candidate):
                    landed = candidate
                    break
            if landed is None:
                if len(unavailable) >= n:
                    bridge.show_unavailable.emit("All devices")
                else:
                    bridge.show_unavailable.emit(skipped_label)
                return
            index[0] = landed
            bridge.show_unavailable.emit(skipped_label)
            time.sleep(1.6)
        time.sleep(0.20)
        dev = devices[index[0]]
        vol = get_volume_percent(dev["id"])
        icon, label = classify_device(dev)
        bridge.show_osd.emit(icon, label, vol)

    try:
        keyboard.unhook_all_hotkeys()
    except Exception:
        pass

    _held = [False]

    def _on_hotkey():
        if _held[0]:
            return  
        _held[0] = True
        toggle()

    def _on_release(e):
        _held[0] = False
    keyboard.add_hotkey(hotkey, _on_hotkey)
    keyboard.on_release(_on_release)
    if not getattr(app, "_keyboard_thread_started", False):
        threading.Thread(target=_keyboard_listener_thread, daemon=True).start()
        app._keyboard_thread_started = True

def main():
    if not is_admin():
        show_admin_required_message()
        sys.exit(1)
    os.environ.setdefault("QT_QPA_PLATFORM", "windows:darkmode=2")
    os.environ.setdefault("QSG_RHI_BACKEND", "d3d11")
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    ico_path = icon_path()
    if ico_path:
        app.setWindowIcon(QIcon(ico_path))
    segoe = QFont("Segoe UI", 10)
    segoe.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
    segoe.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(segoe)
    app.setStyleSheet("""
        QToolTip {
            background-color: #14141e;
            color: #e8e8f4;
            border: 1px solid rgba(255,255,255,0.18);
            border-radius: 6px;
            padding: 6px 10px;
            font-family: "Segoe UI";
            font-size: 10pt;
        }
    """)
    config = load_config()
    if config is None:
        try:
            all_devices = enumerate_devices()
        except Exception:
            sys.exit(1)
        setup = SetupWindow(all_devices)
        def on_saved(devices, hotkey):
            start_switcher(devices, hotkey)
        setup.devices_saved.connect(on_saved)
        setup.show()
    else:
        start_switcher(config["devices"], config["hotkey"])
    sys.exit(app.exec())

if __name__ == "__main__":
    main() 

#i hate myself thats why i made this and cause i am unemplyed :)