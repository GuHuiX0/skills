# Backends and extension points

`visual_control` talks to the desktop through a *driver*. This distribution ships
**Windows only** - one capture driver and one input driver, which cover all six
actions. Everything else (remote desktop, VNC, WebDriver, a mock recorder, a port
to another OS) is a new module under `scripts/visual_control/backends/`, with no
changes to the CLI, the encoder or the skill contract.

## Where things live

```
scripts/visual_control/
├── cli.py                  # commands, argument parsing, JSON output
├── driver.py               # Driver protocol, backend discovery/selection, models
├── png.py                  # PNG encoder (zlib) + optional Pillow bridge
└── backends/
    ├── windows_capture.py  # GDI capture + SendInput input (the full driver)
    ├── windows_input.py    # SendInput pointer/keyboard/window primitives
    └── __init__.py         # discovery happens here (package scan)
```

`driver.SUPPORTED_PLATFORMS = ("win32",)` is the only gate: on any other host the
registry fails fast with a message pointing at this file.

## Driver contract

A driver subclasses `visual_control.driver.BaseDriver`. `capabilities` declares
what it can do; the CLI requests the capabilities it needs and the registry raises
a clear error if none is available.

```python
CAP_CAPTURE = "capture"   # screens(), grab(region)
CAP_INPUT   = "input"     # cursor_pos, move, click, scroll, drag, key_down/up,
                          # type_text, hotkey (optional), windows (optional)
```

| Method | Contract |
| --- | --- |
| `screens() -> list[Screen]` | physical bounds + `primary` flag per display |
| `grab((x, y, w, h)) -> Frame` | BGRA bytes, `width*height*4`, optional `origin_x/origin_y` |
| `cursor_pos() -> (x, y)` | physical pixels |
| `move(x, y, duration)` | `duration` > 0 interpolates for smooth/hoverable motion |
| `click(x, y, button, count, interval, duration)` | `x/y` may be `None` = current position |
| `scroll(amount, horizontal, x, y)` | signed wheel notches, positive = up/away |
| `drag(from, to, button, duration, steps)` | press, interpolate, release |
| `key_down/key_up(key)` | named keys, `windows_input.VK` / `key_vk()` |
| `type_text(text, method)` | `unicode` \| `key` \| `clipboard` |
| `hotkey(keys, hold)` | optional; the CLI falls back to key_down/key_up pairs |
| `windows() -> list[WindowInfo]` | optional; titles, bounds, HWND, process, pid |
| `focus_window(handle, force=False) -> bool` | optional; `force` may escalate (AttachThreadInput) |
| `is_active(handle) -> bool` | optional; live "is this the foreground window" check |

`focus_window(handle, force=False)` must accept the keyword, and
`is_active(handle)` is what the CLI trusts instead of the window-list snapshot:
the snapshot is a few milliseconds old and its `foreground` flag is only a hint.

`Frame.bgr_rows()` yields BGRA scanlines; feed them through
`png.bgra_rows_to_rgb()` and `png.write_image()`/`encode_png()` to get a file.
Keep capture buffers raw and let the encoder own scaling - `--scale` must never
change the coordinate space the CLI reports.

## Discovery and selection

`driver.load(required, name=None, **build_kwargs)`:

1. The host platform is checked against `driver.SUPPORTED_PLATFORMS` and rejected
   early on anything that is not `win32`.
2. Every `backends/*.py` module is imported and asked for `BACKEND_INFO`,
   `probe()` and `build()`.
3. Candidates are ranked: explicit name or `VISUAL_CONTROL_BACKEND(S)` first, then
   backends whose declared capabilities cover the request, then the platform
   default, then the rest.
4. The first candidate that probes usable, builds, and really exposes the
   required capabilities wins. Results are cached per capability set.

`python scripts/visual_control.py backends` prints this table for the current
machine, including the reason each backend was rejected.

## Template

A Windows transport (for example a remote session you drive over a socket) instead
of a raw desktop driver:

```python
"""My transport backend."""
from ..driver import CAP_CAPTURE, CAP_INPUT, BaseDriver, DriverError, Frame, Screen

BACKEND_INFO = {
    "name": "my-transport",
    "platform": "win32",
    "capabilities": (CAP_CAPTURE, CAP_INPUT),
    "requires": "my-sdk",
}

def probe():
    try:
        import my_sdk            # noqa: F401
    except Exception as exc:
        return False, f"my-sdk missing: {exc}"
    return True, ""

class MyDriver(BaseDriver):
    name = "my-transport"

    def screens(self):
        return [Screen(index=0, x=0, y=0, width=1920, height=1080, primary=True)]

    def grab(self, region):
        x, y, w, h = region
        pixels = fetch_bgra(x, y, w, h)       # bytes, w*h*4, BGRA
        return Frame(width=w, height=h, bgra=pixels, origin_x=x, origin_y=y)

    def click(self, x=None, y=None, button="left", count=1, interval=0.08, duration=0.0):
        send_click(x, y, button, count)       # raise DriverError on failure

def build(dry_run=False):
    return MyDriver()
```

Rules of thumb:

- Accept `dry_run=False` in `build()` (or have no parameters) so `--dry-run` works;
  when `dry_run` is true, record the plan in `self.journal` and return without
  touching anything.
- Return physical pixel coordinates that match what `grab()` sees - a coordinate
  reported by `observe` must be clickable by `click`.
- Raise `DriverError` with an actionable message; never print to stdout, the CLI
  owns stdout.
- Keep the module import-safe: a missing SDK must only fail `probe()`, never the
  import of the package.
- Prefer **extending** `windows_input.WindowsInputDriver` (as `windows_capture`
  does) over reimplementing pointer and keyboard primitives.
- Windows gotcha worth repeating: `GetForegroundWindow()` returns a plain `int`,
  while `wintypes.HWND(x)` is a `c_void_p`, and comparing the two is **always
  False**. Compare `_hwnd(a) == _hwnd(b)` (see `windows_input._hwnd`); a silent
  always-False handle comparison is how "focus" and "active window" quietly break.

## Window targeting

`cli.py` resolves `--window` into a `WindowInfo` (`_find_window`) and supports the
aliases `active` (live foreground), `last` (persisted in
`$TEMP/visual-control-skill/last-window.json`, overridable with
`VISUAL_CONTROL_STATE_DIR`), `proc:<name>`, `pid:<n>`, an HWND, or a title /
process substring (exact match first, then substring, preferring the active and
non-minimised window). Points given with `--at`/`--start`/`--to` are then made
window-relative by `_resolve_point`, which also understands `50%,50%` and
`0.5,0.5` fractions.

## Coordinate space and DPI

- The driver calls `SetProcessDpiAwarenessContext(PER_MONITOR_AWARE_V2)` before any
  measurement, so `GetSystemMetrics`, `GetWindowRect`, `BitBlt`, `SetCursorPos` and
  `SendInput` all speak physical pixels of the virtual desktop. The origin is the
  primary monitor's top-left; monitors placed left of or above it have negative
  coordinates.
- `SendInput` absolute moves are normalised to 0-65535 across the whole virtual
  desktop (see `_absolute_coords`), which is what keeps multi-monitor clicks exact.
- Coordinates come from `GetMonitorInfo` / `GetWindowRect`, which report the same
  space BitBlt captures. The end-to-end test asserts exactly this by comparing the
  skill's rect with a native `GetWindowRect` in the target process.
- A **DPI-unaware** target application (legacy Win32 without a manifest) has its
  rectangle virtualised for everyone, so its reported rect is scaled relative to
  physical pixels. For such apps, capture the window and click the pixels you see
  in the image instead of trusting its rect.

## Tests to run after changing a backend

```powershell
python scripts/visual_control.py backends
python scripts/visual_control.py selftest
powershell -File scripts/e2e_input_test.ps1     # real click/type/hotkey/scroll/drag
```

The end-to-end script opens a throwaway WinForms window, drives it with the CLI,
and asserts the application actually received the events. Extend it when you add a
capability - it is the only thing that catches coordinate regressions.
