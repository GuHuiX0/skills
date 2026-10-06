"""Windows screen capture backend (zero dependencies, ctypes + GDI).

Two capture paths, because they answer different questions:

* ``grab()`` - BitBlt of a *screen region*.  Faithful to the desktop, so it shows
  whatever is physically on top, occluding windows included.
* ``grab_window()`` - ``PrintWindow(PW_RENDERFULLCONTENT)``: the window's own
  pixels, rendered by the window itself.  Verified on this host: with a covering
  window raised, ``grab()`` returned the occluder while ``grab_window()`` returned
  the target's own content.  The window must be *visible* - a minimised window has
  no DWM surface and comes back as a title-bar strip.
"""

from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes
from typing import List, Optional, Tuple

from ..driver import CAP_CAPTURE, CAP_INPUT, DriverError, BaseDriver, Frame, Screen

BACKEND_INFO = {
    "name": "windows",
    "platform": "win32",
    "default_for": "win32",
    "capabilities": (CAP_CAPTURE, CAP_INPUT, "windows"),
    "requires": "built-in (ctypes)",
}

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0
BI_RGB = 0
PW_CLIENTONLY = 0x00000001
PW_RENDERFULLCONTENT = 0x00000002
SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 78, 79
MONITORINFOF_PRIMARY = 0x1


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", wintypes.DWORD),
    ]


gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.BitBlt.argtypes = [
    wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD,
]
gdi32.BitBlt.restype = wintypes.BOOL
gdi32.GetDIBits.argtypes = [
    wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
    ctypes.c_void_p, ctypes.POINTER(BITMAPINFO), wintypes.UINT,
]
gdi32.GetDIBits.restype = ctypes.c_int
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int
user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
user32.PrintWindow.restype = wintypes.BOOL
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL

_MONITORENUMPROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(RECT), wintypes.LPARAM
)

_dpi_done = False


def enable_dpi_awareness() -> None:
    """Opt into physical pixels so screenshot coords == click coords."""
    global _dpi_done
    if _dpi_done:
        return
    _dpi_done = True
    try:
        # -4 == DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except Exception:
        pass
    try:
        ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
        return
    except Exception:
        pass
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass


def probe() -> Tuple[bool, str]:
    if sys.platform != "win32":
        return False, "not a Windows host"
    try:
        enable_dpi_awareness()
        if not user32.GetDC(None):
            return False, "GetDC(desktop) failed"
        user32.ReleaseDC(None, user32.GetDC(None))
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    return True, ""


def _monitors() -> List[Tuple[int, int, int, int, bool, str]]:
    out: List[Tuple[int, int, int, int, bool, str]] = []

    def _cb(hmon, hdc, lprect, lparam):
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            r = info.rcMonitor
            out.append(
                (
                    r.left,
                    r.top,
                    r.right - r.left,
                    r.bottom - r.top,
                    bool(info.dwFlags & MONITORINFOF_PRIMARY),
                    "",
                )
            )
        return True

    if not user32.EnumDisplayMonitors(None, None, _MONITORENUMPROC(_cb), 0):
        out = []
    if not out:
        out.append(
            (
                0,
                0,
                user32.GetSystemMetrics(0),
                user32.GetSystemMetrics(1),
                True,
                "display",
            )
        )
    return out


def virtual_bounds() -> Tuple[int, int, int, int]:
    x = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    y = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    w = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
    h = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
    if w <= 0 or h <= 0:
        x, y, w, h = 0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    return x, y, w, h


def _dib_from_bitmap(mem_dc, bitmap, width: int, height: int) -> bytes:
    info = BITMAPINFO()
    info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    info.bmiHeader.biWidth = width
    info.bmiHeader.biHeight = -height  # negative => top-down rows
    info.bmiHeader.biPlanes = 1
    info.bmiHeader.biBitCount = 32
    info.bmiHeader.biCompression = BI_RGB

    stride = width * 4
    buffer = ctypes.create_string_buffer(stride * height)
    copied = gdi32.GetDIBits(
        mem_dc, bitmap, 0, height, ctypes.cast(buffer, ctypes.c_void_p), ctypes.byref(info), DIB_RGB_COLORS
    )
    if copied != height:
        raise RuntimeError(f"GetDIBits returned {copied} of {height} scanlines")
    return buffer.raw[: stride * height]


def grab_region(x: int, y: int, width: int, height: int) -> Frame:
    enable_dpi_awareness()
    if width <= 0 or height <= 0:
        raise ValueError("capture width/height must be positive")

    screen_dc = user32.GetDC(None)
    if not screen_dc:
        raise RuntimeError("GetDC(desktop) failed")
    mem_dc = gdi32.CreateCompatibleDC(screen_dc)
    bitmap = gdi32.CreateCompatibleBitmap(screen_dc, width, height)
    old_obj = None
    try:
        if not mem_dc or not bitmap:
            raise RuntimeError("failed to create GDI bitmap")
        old_obj = gdi32.SelectObject(mem_dc, bitmap)
        if not gdi32.BitBlt(mem_dc, 0, 0, width, height, screen_dc, x, y, SRCCOPY):
            raise RuntimeError(f"BitBlt failed (error {ctypes.get_last_error()})")
        return Frame(
            width=width,
            height=height,
            bgra=_dib_from_bitmap(mem_dc, bitmap, width, height),
            origin_x=x,
            origin_y=y,
        )
    finally:
        if old_obj:
            gdi32.SelectObject(mem_dc, old_obj)
        if bitmap:
            gdi32.DeleteObject(bitmap)
        if mem_dc:
            gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(None, screen_dc)


class FocusForegroundCapture:
    """Context manager: make *handle* the foreground window, then put things back.

    Used as the last-resort capture path.  ``PrintWindow`` occasionally returns an
    empty surface (accelerated/protected composition); when that happens the only
    way to get *that window's* pixels is the real one - raise it, BitBlt its
    rectangle, and restore whatever was in front before.

    Raising usually succeeds with plain ``SetForegroundWindow`` (the foreground
    lock grants it once, to whatever asked last), but putting focus *back* is
    normally refused, so the restore escalates through ``AttachThreadInput``.

    Yields a dict describing what happened, so callers can report it honestly.
    """

    def __init__(self, handle, restore: bool = True, settle: float = 0.25, escalate_restore: bool = True):
        self.handle = int(handle)
        self.restore = restore
        self.settle = settle
        self.escalate_restore = escalate_restore
        self.state = {
            "target_was_active": False,
            "raised": False,
            "restore_attempted": False,
            "restored": False,
        }
        self._previous = 0

    def __enter__(self):
        enable_dpi_awareness()
        previous = _hwnd(user32.GetForegroundWindow())
        self._previous = previous
        self.state["previous_foreground"] = previous
        self.state["previous_title"] = _title_of(previous)
        self.state["target_title"] = _title_of(self.handle)
        if previous == self.handle:
            self.state["target_was_active"] = True
            return self.state
        self.state["raised"] = bool(_focus_now(self.handle))
        time.sleep(self.settle)
        self.state["foreground_after_raise"] = _hwnd(user32.GetForegroundWindow())
        return self.state

    def __exit__(self, exc_type, exc, tb):
        if self.restore and not self.state["target_was_active"] and self._previous:
            self.state["restore_attempted"] = True
            self.state["restored"] = bool(_focus_now(self._previous, tries=3))
            if not self.state["restored"] and self.escalate_restore:
                from .windows_input import force_foreground

                self.state["restore_escalated"] = True
                self.state["restored"] = bool(force_foreground(self._previous))
        self.state["foreground_at_exit"] = _hwnd(user32.GetForegroundWindow())
        return False


def _title_of(handle) -> str:
    hwnd = wintypes.HWND(int(handle)) if handle else None
    if not hwnd or not user32.IsWindow(hwnd):
        return ""
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value[:80]


def _focus_now(handle: int, tries: int = 3) -> bool:
    """Best-effort SetForegroundWindow with a short poll; no AttachThreadInput."""
    hwnd = wintypes.HWND(int(handle))
    if not user32.IsWindow(hwnd):
        return False
    if _hwnd(user32.GetForegroundWindow()) == int(handle):
        return True
    for attempt in range(max(1, tries)):
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.08 * (attempt + 1))
        if _hwnd(user32.GetForegroundWindow()) == int(handle):
            return True
    return False


def _hwnd(value) -> int:
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    try:
        return int(ctypes.cast(value, ctypes.c_void_p).value or 0)
    except Exception:
        try:
            return int(value)
        except Exception:
            return 0


def grab_window_pixels(handle: int) -> Frame:
    """Capture the window's own content, regardless of what covers it.

    Uses ``PrintWindow`` with ``PW_RENDERFULLCONTENT``, which makes the window
    render itself into our DC (that is what makes it occlusion independent - and
    also what makes it usable for windows that are partially off-screen).
    Coordinates of the returned frame are the window's screen rectangle, so points
    measured on the image stay valid for input.
    """
    enable_dpi_awareness()
    hwnd = wintypes.HWND(int(handle))
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise DriverError(f"GetWindowRect failed for HWND {int(handle)}")
    width = rect.right - rect.left
    height = rect.bottom - rect.top
    if width <= 0 or height <= 0:
        raise DriverError(f"window HWND {int(handle)} has an empty rectangle ({width}x{height})")
    if user32.IsIconic(hwnd):
        raise DriverError(
            f"window HWND {int(handle)} is minimised; a minimised window has no DWM surface to "
            "capture. Restore it first (omit --no-activate and pass --focus, or click the taskbar)."
        )

    screen_dc = user32.GetDC(None)
    mem_dc = gdi32.CreateCompatibleDC(screen_dc)
    bitmap = gdi32.CreateCompatibleBitmap(screen_dc, width, height)
    old_obj = None
    try:
        if not mem_dc or not bitmap:
            raise DriverError("failed to create a GDI bitmap for window capture")
        old_obj = gdi32.SelectObject(mem_dc, bitmap)
        ok = user32.PrintWindow(hwnd, mem_dc, PW_RENDERFULLCONTENT)
        pixels = _dib_from_bitmap(mem_dc, bitmap, width, height)
        if not ok:
            raise DriverError(
                f"PrintWindow failed for HWND {int(handle)} (error {ctypes.get_last_error()}); "
                "the window may be privileged, protected or on another desktop"
            )
        return Frame(width=width, height=height, bgra=pixels, origin_x=rect.left, origin_y=rect.top)
    finally:
        if old_obj:
            gdi32.SelectObject(mem_dc, old_obj)
        if bitmap:
            gdi32.DeleteObject(bitmap)
        if mem_dc:
            gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(None, screen_dc)


def build():
    from .windows_input import WindowsInputDriver

    class WindowsDriver(WindowsInputDriver):
        """Full Windows driver: GDI capture + SendInput input."""

        name = "windows"
        capabilities = (CAP_CAPTURE, CAP_INPUT, "windows")

        def screens(self) -> List[Screen]:
            # GetMonitorInfo already reports the same virtual-desktop space that
            # BitBlt/SetCursorPos use (primary monitor origin is 0,0 on Windows).
            mons = _monitors()
            result = [
                Screen(index=index, x=mx, y=my, width=mw, height=mh, primary=primary, name=name or f"display-{index}")
                for index, (mx, my, mw, mh, primary, name) in enumerate(mons)
            ]
            if not result:
                vx, vy, vw, vh = virtual_bounds()
                result.append(Screen(index=0, x=vx, y=vy, width=vw, height=vh, primary=True, name="display-0"))
            return result

        def grab(self, region: Tuple[int, int, int, int]) -> Frame:
            x, y, width, height = region
            vx, vy, vw, vh = virtual_bounds()
            # Clamp to the virtual desktop, keeping the physical origin accurate.
            gx = max(x, vx)
            gy = max(y, vy)
            gw = min(x + width, vx + vw) - gx
            gh = min(y + height, vy + vh) - gy
            if gw <= 0 or gh <= 0:
                raise ValueError(f"region {(x, y, width, height)} is outside the virtual desktop")
            return grab_region(gx, gy, gw, gh)

        def grab_window(self, handle: int) -> Frame:
            """Occlusion-independent capture of one window (PrintWindow)."""
            return grab_window_pixels(handle)

    return WindowsDriver()
