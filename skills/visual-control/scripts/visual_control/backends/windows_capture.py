"""Windows screen capture backend (zero dependencies, ctypes + GDI).

Uses ``BitBlt`` from the desktop DC into a 32bpp DIB section.  Output is raw BGRA
with a bottom-up row order (matching the DIB), which the encoder handles.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import List, Tuple

from ..driver import CAP_CAPTURE, CAP_INPUT, BaseDriver, Frame, Screen

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
        return Frame(width=width, height=height, bgra=buffer.raw[: stride * height], origin_x=x, origin_y=y)
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

    return WindowsDriver()
