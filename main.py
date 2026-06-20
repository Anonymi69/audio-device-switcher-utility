import sys, os, json, time, math, ctypes, threading
import comtypes, keyboard
from ctypes import cast, POINTER
from comtypes import CLSCTX_ALL, GUID, IUnknown
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
from pycaw.api.mmdeviceapi import IMMDeviceEnumerator

from PyQt6.QtWidgets import (
    QApplication, QWidget, QScrollArea, QVBoxLayout,
    QHBoxLayout, QLabel, QPushButton,
)
from PyQt6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve,
    pyqtSignal, QObject, QRectF, QRect, QPoint,
)
from PyQt6.QtGui import (
    QPainter, QColor, QFont, QPainterPath, QLinearGradient, QPen, QBrush,
    QFontMetrics, QCursor, QWheelEvent, QFontDatabase, QKeySequence,
)


def config_path():
    base = getattr(sys, "_MEIPASS", None)
    exe_dir = os.path.dirname(sys.executable if base else os.path.abspath(__file__))
    return os.path.join(exe_dir, "devices.json")


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
    "Inter",
    "Inter Variable",
    "Inter Display",
    "Segoe UI Variable Display",
    "Segoe UI Variable",
    "Segoe UI",
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


SCROLL_IMPULSE = 80
SCROLL_FRICTION = 0.82
SCROLL_FPS = 16


class SmoothScrollArea(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._vel = 0.0
        self._tick_tmr = QTimer(self)
        self._tick_tmr.setInterval(SCROLL_FPS)
        self._tick_tmr.timeout.connect(self._scroll_tick)

    def wheelEvent(self, e: QWheelEvent):
        notches = e.angleDelta().y() / 120.0
        self._vel -= notches * SCROLL_IMPULSE
        if not self._tick_tmr.isActive():
            self._tick_tmr.start()
        e.accept()

    def _scroll_tick(self):
        if abs(self._vel) < 0.5:
            self._vel = 0.0
            self._tick_tmr.stop()
            return
        bar = self.verticalScrollBar()
        bar.setValue(int(bar.value() + self._vel))
        self._vel *= SCROLL_FRICTION


CARD_H = 92
TOG_W = 46
TOG_H = 26
KNOB_D = TOG_H - 8
TOG_OFF = 4.0
TOG_ON = float(TOG_W - KNOB_D - 4)


class CategoryDropdown(QWidget):
    picked = pyqtSignal(int)
    closed = pyqtSignal()
    ROW_H = 34

    def __init__(self, current_index: int, parent=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._current = current_index
        self._hover_i = -1
        self._options = CATEGORY_OPTIONS
        self._closing = False
        self.setMouseTracking(True)

        w = 190
        h = self.ROW_H * len(self._options) + 8
        self.resize(w, h)
        self.setWindowOpacity(0.0)

        f_emoji = QFont("Segoe UI Emoji", 12)
        f_item = QFont(ui_font_family(), 10)
        f_item.setWeight(ui_font_emphasis_weight())

        self._text_lbls = []
        for i, (icon, label) in enumerate(self._options):
            ry = 4 + i * self.ROW_H

            icon_lbl = QLabel(icon, self)
            icon_lbl.setFont(f_emoji)
            icon_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            icon_lbl.setStyleSheet("background: transparent; color: #e6e6f5;")
            icon_lbl.setGeometry(14, ry, 26, self.ROW_H)

            text_lbl = QLabel(label, self)
            text_lbl.setFont(f_item)
            text_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            text_lbl.setGeometry(40, ry, w - 54, self.ROW_H)
            self._text_lbls.append(text_lbl)

            check_lbl = QLabel("✓" if i == current_index else "", self)
            check_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            check_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            check_lbl.setStyleSheet("background: transparent; color: #a864ff;")
            check_lbl.setGeometry(w - 28, ry, 20, self.ROW_H)

        self._refresh_row_colors()
        self._fade_anim = QPropertyAnimation(self, b"windowOpacity")

    def showEvent(self, e):
        super().showEvent(e)
        self._fade_anim.stop()
        self._fade_anim.setDuration(120)
        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade_anim.start()

    def close_animated(self):
        if self._closing:
            return
        self._closing = True
        self._fade_anim.stop()
        self._fade_anim.setDuration(100)
        self._fade_anim.setStartValue(self.windowOpacity())
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.InCubic)
        self._fade_anim.finished.connect(self._finish_close)
        self._fade_anim.start()

    def _finish_close(self):
        self.closed.emit()
        self.close()

    def _refresh_row_colors(self):
        for i, text_lbl in enumerate(self._text_lbls):
            col = "#ebebf8" if i == self._current else "#bebed2"
            text_lbl.setStyleSheet(f"background: transparent; color: {col};")

    def mouseMoveEvent(self, e):
        pos = e.position().toPoint()
        if not self.rect().contains(pos):
            if self._hover_i != -1:
                self._hover_i = -1
                self.update()
            return
        row = int(pos.y() - 4) // self.ROW_H
        row = row if 0 <= row < len(self._options) else -1
        if row != self._hover_i:
            self._hover_i = row
            self.update()

    def mousePressEvent(self, e):
        pos = e.position().toPoint()
        if self.rect().contains(pos):
            row = int(pos.y() - 4) // self.ROW_H
            if 0 <= row < len(self._options):
                self.picked.emit(row)
        self.close_animated()

    def leaveEvent(self, e):
        self._hover_i = -1
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        w, h = self.width(), self.height()

        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, w, h), 12, 12)
        p.fillPath(path, QColor(16, 16, 24, 250))
        pen = QPen(QColor(255, 255, 255, 30))
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

        for i in range(len(self._options)):
            ry = 4 + i * self.ROW_H
            row_rect = QRectF(4, ry, w - 8, self.ROW_H - 2)
            if i == self._hover_i:
                rp = QPainterPath()
                rp.addRoundedRect(row_rect, 8, 8)
                p.fillPath(rp, QColor(99, 179, 255, 35))
            elif i == self._current:
                rp = QPainterPath()
                rp.addRoundedRect(row_rect, 8, 8)
                p.fillPath(rp, QColor(168, 100, 255, 22))


class RecordButton(QWidget):
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._recording = False
        self._hovered = False
        self.setFixedHeight(34)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        self._label = QLabel("Record", self)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        f = QFont(ui_font_family(), 10)
        f.setWeight(ui_font_emphasis_weight())
        self._label.setFont(f)

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
        self.clicked.emit()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        w, h = float(self.width()), float(self.height())
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
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.resize(270, 132)
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

        self._title_lbl = QLabel("Current Hotkey", self)
        self._title_lbl.setGeometry(0, 14, 270, 18)
        self._title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f_title = QFont(ui_font_family(), 9)
        f_title.setWeight(ui_font_emphasis_weight())
        self._title_lbl.setFont(f_title)
        self._title_lbl.setStyleSheet("background: transparent; color: #9696af;")

        self._dot = RecordingDot(self)
        self._dot.hide()

        self._combo_lbl = QLabel(current_hotkey.upper(), self)
        self._combo_lbl.setGeometry(0, 36, 270, 28)
        self._combo_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f_combo = QFont(ui_font_family(), 14)
        f_combo.setWeight(ui_font_emphasis_weight())
        self._combo_lbl.setFont(f_combo)
        self._combo_lbl.setStyleSheet("background: transparent; color: #e8e8f4;")

        self._record_btn = RecordButton(self)
        self._record_btn.setGeometry(20, 76, 230, 34)
        self._record_btn.clicked.connect(self._on_record_clicked)

        self._hint_lbl = QLabel("Up to 3 keys  ·  stops automatically", self)
        self._hint_lbl.setGeometry(0, 114, 270, 16)
        self._hint_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f_hint = QFont(ui_font_family(), 8)
        self._hint_lbl.setFont(f_hint)
        self._hint_lbl.setStyleSheet("background: transparent; color: #45456a;")

        self._fade_anim = QPropertyAnimation(self, b"windowOpacity")

    def showEvent(self, e):
        super().showEvent(e)
        self.setFocus()
        self._fade_anim.stop()
        self._fade_anim.setDuration(120)
        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade_anim.start()

    def close_animated(self):
        if self._closing:
            return
        self._closing = True
        self._timeout_tmr.stop()
        self._dot.stop()
        self._fade_anim.stop()
        self._fade_anim.setDuration(100)
        self._fade_anim.setStartValue(self.windowOpacity())
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.InCubic)
        self._fade_anim.finished.connect(self._finish_close)
        self._fade_anim.start()

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
        self._title_lbl.setText("Recording")
        self._title_lbl.setStyleSheet("background: transparent; color: #ff6868;")
        self._combo_lbl.setText("Press keys...")
        self._record_btn.set_recording(True)
        fm = QFontMetrics(self._title_lbl.font())
        text_w = fm.horizontalAdvance("Recording")
        dot_x = (self.width() - text_w) // 2 + text_w + 8
        self._dot.move(dot_x, 17)
        self._dot.show()
        self._dot.start()
        self.setFocus()

    def _stop_recording(self):
        self._recording = False
        self._timeout_tmr.stop()
        self._dot.stop()
        self._dot.hide()
        self._title_lbl.setText("Current Hotkey")
        self._title_lbl.setStyleSheet("background: transparent; color: #9696af;")
        self._record_btn.set_recording(False)
        if self._captured_key is not None:
            parts = self._captured_mods + [self._captured_key]
            self._result_text = "+".join(parts)
            self._combo_lbl.setText(" + ".join(p.capitalize() for p in parts))
            self.picked.emit(self._result_text)
        else:
            self._combo_lbl.setText(self._current_hotkey.upper())

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
        self._captured_key = key_name
        parts = self._captured_mods + [key_name]
        self._combo_lbl.setText(" + ".join(p.capitalize() for p in parts))

        total_keys = len(self._captured_mods) + 1
        if total_keys >= self.AUTO_STOP_KEY_COUNT:
            self._timeout_tmr.stop()
            self._stop_recording()
        else:
            self._timeout_tmr.start(self.AUTO_STOP_TIMEOUT_MS)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        w, h = self.width(), self.height()
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, w, h), 14, 14)
        p.fillPath(path, QColor(16, 16, 24, 250))
        border_color = QColor(255, 90, 90, 160) if self._recording else QColor(99, 179, 255, 140)
        pen = QPen(border_color)
        pen.setWidthF(1.2)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)


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

        self.setFixedHeight(CARD_H)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setToolTip("click the dropdown menu for custom device name & icon")

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
            self._open_dropdown.close_animated()
            self._open_dropdown = None
            return
        cur_idx = self._current_category_index()
        dropdown = CategoryDropdown(cur_idx, self)
        dropdown.picked.connect(self._on_category_picked)
        dropdown.closed.connect(self._on_dropdown_closed)
        global_pt = self.mapToGlobal(QPoint(self._chip_rect.x(), self._chip_rect.bottom() + 4))
        dropdown.move(global_pt)
        dropdown.show()
        self._open_dropdown = dropdown

    def _on_dropdown_closed(self):
        self._open_dropdown = None

    def _on_category_picked(self, idx: int):
        self.device["category_index"] = idx
        self.category_changed.emit()
        self._refresh_labels()
        self.update()

    def _refresh_labels(self):
        w, h = self.width(), self.height()
        icon, label = classify_device(self.device)
        is_override = self.device.get("category_index") is not None
        self._is_override = is_override

        self._icon_lbl.setText(icon)
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
        chip_h = 22
        chevron_w = 16
        fm3 = QFontMetrics(self._chip_text_lbl.font())
        chip_text_w = fm3.horizontalAdvance(label) + 4
        chip_w = chip_pad_x + 18 + chip_text_w + chevron_w + chip_pad_x
        chip_x = name_x
        chip_y = 62
        self._chip_rect = QRect(chip_x, chip_y, chip_w, chip_h)

        self._chip_icon_lbl.setText(icon)
        self._chip_icon_lbl.setGeometry(chip_x + chip_pad_x - 2, chip_y, 20, chip_h)

        chip_text_col = "#c8c8e0" if not is_override else "#c8aaff"
        self._chip_text_lbl.setStyleSheet(f"background: transparent; color: {chip_text_col};")
        self._chip_text_lbl.setText(label)
        self._chip_text_lbl.setGeometry(chip_x + chip_pad_x + 16, chip_y, chip_text_w + 4, chip_h)

        chevron_col = "#6699ff" if self._chip_hov else "#9696af"
        self._chip_chevron_lbl.setStyleSheet(f"background: transparent; color: {chevron_col};")
        self._chip_chevron_lbl.setGeometry(chip_x + chip_w - chevron_w - 6, chip_y, chevron_w, chip_h)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._refresh_labels()

    def enterEvent(self, e):
        self._hovered = True
        self.update()

    def leaveEvent(self, e):
        self._hovered = False
        self._chip_hov = False
        self._refresh_labels()
        self.update()

    def mouseMoveEvent(self, e):
        over_chip = self._chip_rect.contains(e.pos())
        if over_chip != self._chip_hov:
            self._chip_hov = over_chip
            self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            self._refresh_labels()
            self.update()

    def mousePressEvent(self, e):
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
        bg = SURF_SEL if self._selected else (SURF_HOV if self._hovered else SURF)
        p.fillPath(path, bg)

        if self._selected:
            bar = QPainterPath()
            bar.addRoundedRect(QRectF(1, 18, 3, h - 36), 2, 2)
            g = QLinearGradient(0, 18, 0, h - 18)
            g.setColorAt(0, ACCENT_A)
            g.setColorAt(1, ACCENT_B)
            p.fillPath(bar, QBrush(g))

        bc = BORDER_SEL if self._selected else (BORDER_HOV if self._hovered else BORDER)
        pen = QPen(bc)
        pen.setWidthF(1.2)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

        chip_path = QPainterPath()
        chip_path.addRoundedRect(QRectF(self._chip_rect), 11, 11)

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
        self.update()

    def leaveEvent(self, e):
        self._hovered = False
        self._chip_hov = False
        self.update()

    def mouseMoveEvent(self, e):
        over_chip = self._chip_rect.contains(e.pos())
        if over_chip != self._chip_hov:
            self._chip_hov = over_chip
            self.update()

    def mousePressEvent(self, e):
        if self._open_dropdown is not None:
            self._open_dropdown.close_animated()
            self._open_dropdown = None
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
        bg = SURF_HOV if self._hovered else SURF
        p.fillPath(path, bg)

        pen = QPen(BORDER_HOV if self._hovered else BORDER)
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


class GradientButton(QWidget):
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._enabled = False
        self._hovered = False
        self.setFixedHeight(50)

        self._label = QLabel("Select at least 2 devices", self)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        f = QFont(ui_font_family(), 12)
        f.setWeight(ui_font_emphasis_weight())
        self._label.setFont(f)
        self._apply_label_color()

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
        if self._enabled:
            self.clicked.emit()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        w, h = float(self.width()), float(self.height())
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

        self.setWindowTitle("Volume Switcher")
        self.setFixedWidth(500)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._build_ui()
        self.adjustSize()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag_pos and e.buttons() == Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, e):
        self._drag_pos = None

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, self.width(), self.height()), 20, 20)
        p.fillPath(path, BG)
        g = QLinearGradient(0, 0, 0, 100)
        g.setColorAt(0, QColor(255, 255, 255, 10))
        g.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillPath(path, QBrush(g))
        pen = QPen(QColor(255, 255, 255, 22))
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

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
        close.clicked.connect(self.close)

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
        bl.addSpacing(10)

        scroll = SmoothScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("""
            QScrollArea { border: none; background: transparent; }
            QWidget#inner { background: transparent; }
            QScrollBar:vertical { background: rgba(255,255,255,0.03); width: 4px; border-radius: 2px; }
            QScrollBar::handle:vertical { background: rgba(255,255,255,0.14); border-radius: 2px; min-height: 20px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
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

    def _on_hotkey_changed(self, hotkey: str):
        self._hotkey = hotkey

    def _refresh_btn(self):
        n = sum(1 for c in self._cards if c.is_checked())
        ok = n >= 2
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
        self.icon_lbl.setText(icon)
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


class Bridge(QObject):
    show_osd = pyqtSignal(str, str, int)


def start_switcher(devices, hotkey):
    app = QApplication.instance()
    app._osd = OSDWindow()
    app._bridge = Bridge()
    osd = app._osd
    bridge = app._bridge
    bridge.show_osd.connect(osd.show_popup)
    index = [0]

    def toggle():
        index[0] = (index[0] + 1) % len(devices)
        dev = devices[index[0]]
        try:
            set_default_device(dev["id"])
            time.sleep(0.20)
            vol = get_volume_percent(dev["id"])
            icon, label = classify_device(dev)
            bridge.show_osd.emit(icon, label, vol)
        except Exception:
            pass

    try:
        keyboard.unhook_all_hotkeys()
    except Exception:
        pass
    keyboard.add_hotkey(hotkey, toggle)

    if not getattr(app, "_keyboard_thread_started", False):
        threading.Thread(target=keyboard.wait, daemon=True).start()
        app._keyboard_thread_started = True


def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setFont(QFont(ui_font_family(), 10))
    app.setStyleSheet("""
        QToolTip {
            background-color: #14141e;
            color: #e8e8f4;
            border: 1px solid rgba(255,255,255,0.18);
            border-radius: 6px;
            padding: 6px 10px;
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
