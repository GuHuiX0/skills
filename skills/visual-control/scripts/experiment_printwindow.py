"""Experiment: does PrintWindow(PW_RENDERFULLCONTENT) capture the window's own
pixels while it is occluded by another window?

Run it from the skill root:  python visual-control/scripts/experiment_printwindow.py
It opens a green target window, covers it with a red one, then compares:
  * BitBlt of the target's screen rectangle (the current behaviour)
  * PrintWindow(hwnd, ..., PW_RENDERFULLCONTENT)  (the candidate)
and prints the dominant colour of each.  Green = own content, red = occluded.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from visual_control import driver as driver_mod  # noqa: E402

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

PW_RENDERFULLCONTENT = 0x00000002
SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0
BI_RGB = 0


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
user32.PrintWindow.restype = wintypes.BOOL
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
gdi32.GetDIBits.argtypes = [
    wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
    ctypes.c_void_p, ctypes.POINTER(BITMAPINFO), wintypes.UINT,
]
gdi32.GetDIBits.restype = ctypes.c_int


def _dib_from_dc(mem_dc, bitmap, width, height):
    info = BITMAPINFO()
    info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    info.bmiHeader.biWidth = width
    info.bmiHeader.biHeight = -height
    info.bmiHeader.biPlanes = 1
    info.bmiHeader.biBitCount = 32
    info.bmiHeader.biCompression = BI_RGB
    stride = width * 4
    buf = ctypes.create_string_buffer(stride * height)
    copied = gdi32.GetDIBits(mem_dc, bitmap, 0, height,
                             ctypes.cast(buf, ctypes.c_void_p), ctypes.byref(info), DIB_RGB_COLORS)
    return buf.raw[: stride * height], copied


def centre_pixel(bgra: bytes, width: int, height: int):
    offset = ((height // 2) * width + width // 2) * 4
    return (bgra[offset + 2], bgra[offset + 1], bgra[offset])


def dominant(bgra: bytes, width: int, height: int):
    counts: dict[tuple[int, int, int], int] = {}
    for y in range(5, height - 5, 13):
        for x in range(5, width - 5, 13):
            offset = (y * width + x) * 4
            key = (bgra[offset + 2], bgra[offset + 1], bgra[offset])
            counts[key] = counts.get(key, 0) + 1
    return sorted(counts.items(), key=lambda kv: -kv[1])[:3]


def print_window(hwnd_int: int):
    rect = wintypes.RECT()
    user32.GetWindowRect(wintypes.HWND(hwnd_int), ctypes.byref(rect))
    width, height = rect.right - rect.left, rect.bottom - rect.top
    screen_dc = user32.GetDC(None)
    mem_dc = gdi32.CreateCompatibleDC(screen_dc)
    bitmap = gdi32.CreateCompatibleBitmap(screen_dc, width, height)
    old = gdi32.SelectObject(mem_dc, bitmap)
    try:
        ok = user32.PrintWindow(wintypes.HWND(hwnd_int), mem_dc, PW_RENDERFULLCONTENT)
        data, copied = _dib_from_dc(mem_dc, bitmap, width, height)
        return bool(ok), copied, data, width, height
    finally:
        if old:
            gdi32.SelectObject(mem_dc, old)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(None, screen_dc)


def main() -> int:
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    harness = os.path.join(root, "visual-control", "scripts", "occlusion_window.ps1")
    result = os.path.join(os.environ.get("TEMP", "."), "vc-printwindow.jsonl")
    if os.path.exists(result):
        os.remove(result)
    pwsh = sys.executable.replace("python.exe", "powershell.exe")
    import shutil

    pwsh = shutil.which("powershell") or pwsh
    target = subprocess.Popen([pwsh, "-NoProfile", "-File", harness, "-Role", "target", "-Result", result])
    time.sleep(2.5)
    cover = subprocess.Popen([pwsh, "-NoProfile", "-File", harness, "-Role", "cover", "-Result", result])
    time.sleep(2.5)

    handles = {}
    with open(result, "r", encoding="utf-8-sig") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            import json

            payload = json.loads(line)
            handle, role, _marker = payload["value"].split("|")
            handles[role] = int(handle)
    print("handles:", handles)

    # raise the cover so the target is genuinely occluded
    user32.SetForegroundWindow(wintypes.HWND(handles["cover"]))
    time.sleep(1.0)

    driver = driver_mod.load(("capture",))
    target_win = next(w for w in driver.windows() if w.handle == handles["target"])
    print(f"target window: {target_win.width}x{target_win.height} at ({target_win.x},{target_win.y})")

    print("\n--- A) current behaviour: BitBlt of the screen rectangle ---")
    frame = driver.grab((target_win.x, target_win.y, target_win.width, target_win.height))
    print(f"   {frame.width}x{frame.height} centre RGB{centre_pixel(frame.bgra, frame.width, frame.height)}")
    for colour, count in dominant(frame.bgra, frame.width, frame.height):
        print(f"   RGB{colour}: {count}")

    print("\n--- B) PrintWindow(PW_RENDERFULLCONTENT) ---")
    ok, copied, data, width, height = print_window(handles["target"])
    print(f"   PrintWindow ok={ok} scanlines={copied}/{height}")
    print(f"   {width}x{height} centre RGB{centre_pixel(data, width, height)}")
    for colour, count in dominant(data, width, height):
        print(f"   RGB{colour}: {count}")

    print("\n--- C) PrintWindow while the target is ALSO minimised ---")
    user32.ShowWindow(wintypes.HWND(handles["target"]), 6)  # SW_MINIMIZE
    time.sleep(0.8)
    ok, copied, data, width, height = print_window(handles["target"])
    print(f"   PrintWindow ok={ok} scanlines={copied}/{height}")
    print(f"   {width}x{height} centre RGB{centre_pixel(data, width, height)}")
    for colour, count in dominant(data, width, height):
        print(f"   RGB{colour}: {count}")

    target.terminate()
    cover.terminate()
    print("\nlegend: green(0,200,60)=own content, red(220,30,30)=occluder, black/white=blank")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
