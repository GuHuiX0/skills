"""Windows input backend: SendInput based pointer + keyboard primitives.

Every action is expressed through ``SendInput`` with absolute virtual-desktop
coordinates so that the coordinates returned by ``observe_screen`` can be fed
straight back into ``click``/``drag`` without any conversion.

Also provides window enumeration/focus, which the agent uses to find target
coordinates and to make sure a click lands on the intended window.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes
from typing import Dict, List, Optional, Tuple

from ..driver import CAP_INPUT, BaseDriver, DriverError, WindowInfo

BACKEND_INFO = {
    "name": "windows-input",
    "platform": "win32",
    "capabilities": (CAP_INPUT, "windows"),
    "requires": "built-in (ctypes)",
}

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# --- SendInput constants ---------------------------------------------------
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008

WHEEL_DELTA = 120
SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 78, 79

SW_RESTORE = 9
SW_MINIMIZE = 6
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.WindowFromPoint.argtypes = [wintypes.POINT]
user32.WindowFromPoint.restype = wintypes.HWND
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.IsIconic.argtypes = [wintypes.HWND]
user32.GetForegroundWindow.restype = ctypes.c_void_p
# NOTE: GetForegroundWindow comes back as a plain Python int (or None), while
# wintypes.HWND objects are c_void_p, and comparing the two is always False.
# Every handle comparison here goes through _hwnd() so that trap cannot come back.
user32.IsWindow.argtypes = [ctypes.c_void_p]
user32.IsWindow.restype = wintypes.BOOL


def _hwnd(handle) -> int:
    """Normalise anything window-handle-like to a plain int."""
    if handle is None:
        return 0
    if isinstance(handle, int):
        return handle
    try:
        return int(ctypes.cast(handle, ctypes.c_void_p).value or 0)
    except Exception:
        try:
            return int(handle)
        except Exception:
            return 0
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.IsZoomed.argtypes = [wintypes.HWND]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = wintypes.LONG
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.SetWindowPos.restype = wintypes.BOOL
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
user32.AttachThreadInput.restype = wintypes.BOOL
user32.BringWindowToTop.argtypes = [wintypes.HWND]
user32.BringWindowToTop.restype = wintypes.BOOL
user32.SetActiveWindow.argtypes = [wintypes.HWND]
user32.SetActiveWindow.restype = wintypes.HWND

HWND_TOP = 0
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_SHOWWINDOW = 0x0040

_WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000

# --- key name -> virtual key code -----------------------------------------
VK: Dict[str, int] = {
    "backspace": 0x08, "tab": 0x09, "enter": 0x0D, "return": 0x0D, "shift": 0x10,
    "ctrl": 0x11, "control": 0x11, "alt": 0x12, "pause": 0x13, "capslock": 0x14,
    "esc": 0x1B, "escape": 0x1B, "space": 0x20, "spacebar": 0x20, "pgup": 0x21,
    "pageup": 0x21, "pgdn": 0x22, "pagedown": 0x22, "end": 0x23, "home": 0x24,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28, "printscreen": 0x2C,
    "insert": 0x2D, "ins": 0x2D, "delete": 0x2E, "del": 0x2E, "lwin": 0x5B,
    "win": 0x5B, "meta": 0x5B, "cmd": 0x5B, "super": 0x5B, "rwin": 0x5C,
    "apps": 0x5D, "menu": 0x5D, "numlock": 0x90, "scrolllock": 0x91,
    "lshift": 0xA0, "rshift": 0xA1, "lctrl": 0xA2, "rctrl": 0xA3,
    "lalt": 0xA4, "ralt": 0xA5, "altgr": 0xA5, "playpause": 0xB3,
    "volumemute": 0xAD, "volumedown": 0xAE, "volumeup": 0xAF,
    "nexttrack": 0xB0, "prevtrack": 0xB1, "stopmedia": 0xB2,
    "browserback": 0xA6, "browserforward": 0xA7, "browserrefresh": 0xA8,
    "browserhome": 0xAC, "launchmail": 0xB4, "launchapp1": 0xB6,
    "numpad0": 0x60, "numpad1": 0x61, "numpad2": 0x62, "numpad3": 0x63,
    "numpad4": 0x64, "numpad5": 0x65, "numpad6": 0x66, "numpad7": 0x67,
    "numpad8": 0x68, "numpad9": 0x69, "multiply": 0x6A, "add": 0x6B,
    "separator": 0x6C, "subtract": 0x6D, "decimal": 0x6E, "divide": 0x6F,
    "num0": 0x60, "num1": 0x61, "num2": 0x62, "num3": 0x63, "num4": 0x64,
    "num5": 0x65, "num6": 0x66, "num7": 0x67, "num8": 0x68, "num9": 0x69,
    "`": 0xC0, "-": 0xBD, "=": 0xBB, "[": 0xDB, "]": 0xDD, "\\": 0xDC,
    ";": 0xBA, "'": 0xDE, ",": 0xBC, ".": 0xBE, "/": 0xBF, "plus": 0xBB,
    "minus": 0xBD, "comma": 0xBC, "period": 0xBE, "slash": 0xBF,
    "semicolon": 0xBA, "quote": 0xDE, "backslash": 0xDC, "grave": 0xC0,
    "leftbracket": 0xDB, "rightbracket": 0xDD,
}

for _i in range(1, 25):
    VK[f"f{_i}"] = 0x6F + _i  # VK_F1 == 0x70
for _c in "abcdefghijklmnopqrstuvwxyz":
    VK[_c] = ord(_c.upper())
for _d in "0123456789":
    VK[_d] = ord(_d)

ALIASES = {
    "esc": "esc",
    "cmdorctrl": "ctrl",
    "command": "win",
    "option": "alt",
    "return": "enter",
    "spacebar": "space",
    "winleft": "lwin",
    "winright": "rwin",
    "pagedown": "pgdn",
    "pageup": "pgup",
    "prtsc": "printscreen",
    "print": "printscreen",
    "del": "delete",
    "ins": "insert",
}


def normalize_key(key: str) -> str:
    k = (key or "").strip().lower()
    k = k.replace("control", "ctrl")
    return ALIASES.get(k, k)


def key_vk(key: str) -> int:
    k = normalize_key(key)
    if k in VK:
        return VK[k]
    if len(k) == 1:
        return ord(k.upper())
    raise DriverError(f"unknown key name: {key!r}")


def _send(*inputs: INPUT) -> None:
    if not inputs:
        return
    array = (INPUT * len(inputs))(*inputs)
    sent = user32.SendInput(len(inputs), array, ctypes.sizeof(INPUT))
    if sent != len(inputs):
        raise DriverError(f"SendInput delivered {sent}/{len(inputs)} events (error {ctypes.get_last_error()})")


def _mouse_input(flags: int, dx: int = 0, dy: int = 0, data: int = 0) -> INPUT:
    return INPUT(
        type=INPUT_MOUSE,
        mi=MOUSEINPUT(dx=dx, dy=dy, mouseData=data & 0xFFFFFFFF, dwFlags=flags, time=0, dwExtraInfo=0),
    )


def _key_input(vk: int, up: bool = False, extended: bool = False) -> INPUT:
    flags = (KEYEVENTF_KEYUP if up else 0) | (KEYEVENTF_EXTENDEDKEY if extended else 0)
    return INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags, time=0, dwExtraInfo=0))


def _unicode_input(ch: str, up: bool) -> INPUT:
    return INPUT(
        type=INPUT_KEYBOARD,
        ki=KEYBDINPUT(wVk=0, wScan=ord(ch) & 0xFFFF, dwFlags=KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if up else 0), time=0, dwExtraInfo=0),
    )


_EXTENDED_VKS = {
    0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28,  # pgup pgdn end home arrows
    0x2D, 0x2E, 0x5B, 0x5C, 0x5D, 0xA3, 0xA5,          # insert del win apps rctrl ralt
}


def _absolute_coords(x: int, y: int) -> Tuple[int, int]:
    vx = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    vy = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    vw = max(1, user32.GetSystemMetrics(SM_CXVIRTUALSCREEN))
    vh = max(1, user32.GetSystemMetrics(SM_CYVIRTUALSCREEN))
    # 0..65535 inclusive normalisation across the whole virtual desktop.
    nx = int(round((x - vx) * 65535.0 / max(1, vw - 1)))
    ny = int(round((y - vy) * 65535.0 / max(1, vh - 1)))
    return max(0, min(65535, nx)), max(0, min(65535, ny))


def _process_name(pid: int) -> str:
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buffer = ctypes.create_unicode_buffer(1024)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return os.path.basename(buffer.value)
        return ""
    finally:
        kernel32.CloseHandle(handle)


def _window_title(hwnd) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def list_windows(min_width: int = 0, min_height: int = 0) -> List[WindowInfo]:
    foreground = user32.GetForegroundWindow()
    out: List[WindowInfo] = []

    def _cb(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        title = _window_title(hwnd)
        if not title:
            return True
        ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if ex_style & WS_EX_TOOLWINDOW:
            return True
        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return True
        width = rect.right - rect.left
        height = rect.bottom - rect.top
        if width < min_width or height < min_height:
            return True
        pid = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        out.append(
            WindowInfo(
                handle=_hwnd(hwnd),
                title=title,
                process=_process_name(pid.value) if pid.value else "",
                x=rect.left,
                y=rect.top,
                width=width,
                height=height,
                minimized=bool(user32.IsIconic(hwnd)),
                foreground=bool(_hwnd(hwnd) == _hwnd(foreground)),
            )
        )
        return True

    user32.EnumWindows(_WNDENUMPROC(_cb), 0)
    return out


RIGHT_BUTTONS = {"right", "r", "secondary"}
MIDDLE_BUTTONS = {"middle", "m", "wheel", "tertiary"}


def probe() -> Tuple[bool, str]:
    if sys.platform != "win32":
        return False, "not a Windows host"
    if ctypes.sizeof(INPUT) not in (28, 40):  # 32-bit / 64-bit layouts
        return False, f"unexpected INPUT size {ctypes.sizeof(INPUT)}"
    if not user32.GetSystemMetrics(0):
        return False, "no display reported by GetSystemMetrics"
    return True, ""


class WindowsInputDriver(BaseDriver):
    name = "windows-input"
    capabilities = (CAP_INPUT, "windows")
    platform = "win32"

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.journal: List[Dict[str, object]] = []

    # -- helpers ---------------------------------------------------------
    def _record(self, action: str, **kwargs) -> None:
        self.journal.append({"action": action, **kwargs})

    def _down_flags(self, button: str) -> int:
        b = (button or "left").lower()
        if b in RIGHT_BUTTONS:
            return MOUSEEVENTF_RIGHTDOWN
        if b in MIDDLE_BUTTONS:
            return MOUSEEVENTF_MIDDLEDOWN
        return MOUSEEVENTF_LEFTDOWN

    def _up_flags(self, button: str) -> int:
        b = (button or "left").lower()
        if b in RIGHT_BUTTONS:
            return MOUSEEVENTF_RIGHTUP
        if b in MIDDLE_BUTTONS:
            return MOUSEEVENTF_MIDDLEUP
        return MOUSEEVENTF_LEFTUP

    # -- pointer ---------------------------------------------------------
    def cursor_pos(self) -> Tuple[int, int]:
        point = wintypes.POINT()
        if not user32.GetCursorPos(ctypes.byref(point)):
            raise DriverError("GetCursorPos failed")
        return int(point.x), int(point.y)

    def move(self, x: int, y: int, duration: float = 0.0) -> None:
        self._record("move", x=int(x), y=int(y), duration=duration)
        if self.dry_run:
            return
        start = self.cursor_pos()
        target = (int(x), int(y))
        if duration and duration > 0:
            steps = max(2, min(120, int(duration / 0.01)))
            for point in self._interpolate(start, target, steps):
                nx, ny = _absolute_coords(*point)
                _send(_mouse_input(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, nx, ny))
                time.sleep(duration / steps)
            return
        nx, ny = _absolute_coords(*target)
        _send(_mouse_input(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, nx, ny))

    def click(self, x=None, y=None, button="left", count=1, interval=0.08, duration=0.0) -> None:
        count = max(1, int(count))
        self._record("click", x=None if x is None else int(x), y=None if y is None else int(y),
                     button=button, count=count, interval=interval)
        if self.dry_run:
            return
        if x is not None and y is not None:
            self.move(x, y, duration)
        down, up = self._down_flags(button), self._up_flags(button)
        for index in range(count):
            _send(_mouse_input(down), _mouse_input(up))
            if index != count - 1:
                time.sleep(max(0.0, interval))

    def scroll(self, amount, horizontal=0, x=None, y=None) -> None:
        vertical = int(amount or 0)
        horiz = int(horizontal or 0)
        self._record("scroll", amount=vertical, horizontal=horiz,
                     x=None if x is None else int(x), y=None if y is None else int(y))
        if self.dry_run:
            return
        if x is not None and y is not None:
            self.move(x, y, 0.0)
        if vertical:
            data = (WHEEL_DELTA * vertical) & 0xFFFFFFFF
            _send(_mouse_input(MOUSEEVENTF_WHEEL, data=data))
        if horiz:
            data = (WHEEL_DELTA * horiz) & 0xFFFFFFFF
            _send(_mouse_input(MOUSEEVENTF_HWHEEL, data=data))

    def drag(self, from_xy, to_xy, button="left", duration=0.5, steps=0) -> None:
        start = (int(from_xy[0]), int(from_xy[1]))
        end = (int(to_xy[0]), int(to_xy[1]))
        self._record("drag", start=start, end=end, button=button, duration=duration)
        if self.dry_run:
            return
        self.move(*start, 0.0)
        time.sleep(0.05)
        down, up = self._down_flags(button), self._up_flags(button)
        _send(_mouse_input(down))
        try:
            if steps <= 0:
                steps = max(8, min(120, int((duration or 0.5) / 0.01)))
            delay = (duration or 0.5) / steps
            for point in self._interpolate(start, end, steps):
                nx, ny = _absolute_coords(*point)
                _send(_mouse_input(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, nx, ny))
                time.sleep(delay)
        finally:
            _send(_mouse_input(up))

    # -- keyboard --------------------------------------------------------
    def key_down(self, key: str) -> None:
        self._record("key_down", key=key)
        if self.dry_run:
            return
        vk = key_vk(key)
        _send(_key_input(vk, up=False, extended=vk in _EXTENDED_VKS))

    def key_up(self, key: str) -> None:
        self._record("key_up", key=key)
        if self.dry_run:
            return
        vk = key_vk(key)
        _send(_key_input(vk, up=True, extended=vk in _EXTENDED_VKS))

    def hotkey(self, keys: List[str], hold: float = 0.02) -> None:
        """Press *keys* together, e.g. ``["ctrl", "shift", "s"]``."""
        self._record("hotkey", keys=list(keys))
        if self.dry_run:
            return
        vks = [key_vk(k) for k in keys if str(k).strip()]
        if not vks:
            raise DriverError("hotkey requires at least one key")
        for vk in vks:
            _send(_key_input(vk, up=False, extended=vk in _EXTENDED_VKS))
        time.sleep(max(0.0, hold))
        for vk in reversed(vks):
            _send(_key_input(vk, up=True, extended=vk in _EXTENDED_VKS))

    def press(self, keys: List[str], repeat: int = 1, interval: float = 0.05) -> None:
        for _ in range(max(1, int(repeat))):
            self.hotkey(keys)
            time.sleep(max(0.0, interval))

    def type_text(self, text: str, method: str = "unicode", interval: float = 0.01) -> None:
        method = (method or "unicode").lower()
        self._record("type_text", text=text, method=method, length=len(text or ""))
        if self.dry_run:
            return
        text = text or ""
        if method == "clipboard":
            self._type_via_clipboard(text)
            return
        if method == "text":
            method = "unicode"
        if method == "unicode":
            # Batch into chunks so very long strings do not exceed SendInput limits.
            batch: List[INPUT] = []
            for ch in text:
                batch.append(_unicode_input(ch, False))
                batch.append(_unicode_input(ch, True))
                if len(batch) >= 128:
                    _send(*batch)
                    batch = []
                    if interval:
                        time.sleep(interval * 64)
            if batch:
                _send(*batch)
            return
        if method == "key":
            delay = interval or 0.01
            for ch in text:
                needs_shift = ch.isupper() or ch in '~!@#$%^&*()_+{}|:"<>?'
                key_map = {
                    "!": "1", "@": "2", "#": "3", "$": "4", "%": "5", "^": "6", "&": "7",
                    "*": "8", "(": "9", ")": "0", "_": "-", "+": "=", "{": "[", "}": "]",
                    "|": "\\", ":": ";", '"': "'", "<": ",", ">": ".", "?": "/", "~": "`",
                }
                base = key_map.get(ch, ch)
                vk = key_vk(base if not ch.isalpha() else ch)
                if needs_shift:
                    shift = VK["shift"]
                    _send(_key_input(shift, up=False), _key_input(vk, up=False), _key_input(vk, up=True), _key_input(shift, up=True))
                else:
                    _send(_key_input(vk, up=False), _key_input(vk, up=True))
                time.sleep(delay)
            return
        raise DriverError(f"unknown type method: {method!r} (use unicode|key|clipboard)")

    def _type_via_clipboard(self, text: str) -> None:
        if not self._set_clipboard(text):
            raise DriverError("clipboard method unavailable on this system; use method='unicode'")
        time.sleep(0.05)
        self.hotkey(["ctrl", "v"])

    def _set_clipboard(self, text: str) -> bool:
        try:  # pragma: no cover - optional
            import tkinter  # type: ignore

            root = tkinter.Tk()
            root.withdraw()
            root.clipboard_clear()
            root.clipboard_append(text)
            root.update()
            root.destroy()
            return True
        except Exception:
            pass
        try:
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", "Set-Clipboard -Value ([Console]::In.ReadToEnd())"],
                input=text.encode("utf-8"),
                capture_output=True,
                timeout=15,
                check=False,
            )
            return proc.returncode == 0
        except Exception:
            return False

    # -- windows ---------------------------------------------------------
    def windows(self) -> List[WindowInfo]:
        return list_windows()

    def is_active(self, handle: int) -> bool:
        """True when *handle* is the foreground (active) window right now."""
        hwnd = wintypes.HWND(int(handle))
        return bool(user32.IsWindow(hwnd) and _hwnd(user32.GetForegroundWindow()) == _hwnd(hwnd))

    def focus_window(self, handle: int, force: bool = False) -> bool:
        """Bring *handle* to the foreground.

        Plain ``SetForegroundWindow`` is often refused by the foreground lock when
        the calling process does not own the current foreground window - which is
        exactly the situation of an agent-driven shell.  ``force=True`` escalates
        through ``AttachThreadInput``, the standard workaround; it may briefly
        reactivate the previous window, so it is opt-in.
        """
        hwnd = wintypes.HWND(int(handle))
        if not user32.IsWindow(hwnd):
            return False
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
            time.sleep(0.15)
        # Windows can refuse activation or apply it with a short delay, so give it
        # a couple of tries before declaring failure.
        for attempt in range(3):
            user32.SetForegroundWindow(hwnd)
            time.sleep(0.08 * (attempt + 1))
            if _hwnd(user32.GetForegroundWindow()) == _hwnd(hwnd):
                return True
        if not force:
            return False
        return self._force_foreground(hwnd)

    def _force_foreground(self, hwnd) -> bool:
        target_hwnd = _hwnd(hwnd)
        target_thread = user32.GetWindowThreadProcessId(hwnd, None)
        current_thread = kernel32.GetCurrentThreadId()
        foreground = user32.GetForegroundWindow()
        foreground_thread = user32.GetWindowThreadProcessId(foreground, None) if foreground else 0
        attached = []
        try:
            for thread in {foreground_thread, current_thread}:
                if thread and thread != target_thread and user32.AttachThreadInput(thread, target_thread, True):
                    attached.append(thread)
            user32.ShowWindow(hwnd, SW_RESTORE)
            user32.BringWindowToTop(hwnd)
            user32.SetWindowPos(hwnd, HWND_TOP, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
            user32.SetForegroundWindow(hwnd)
            user32.SetActiveWindow(hwnd)
            time.sleep(0.12)
        finally:
            for thread in attached:
                user32.AttachThreadInput(thread, target_thread, False)
        return bool(_hwnd(user32.GetForegroundWindow()) == target_hwnd)


def build(dry_run: bool = False):
    return WindowsInputDriver(dry_run=dry_run)
