"""Command line interface for the ``visual-control`` skill.

Six actions requested by the skill contract:

1. ``observe``   - screenshot the screen / a region / a window (+ optional grid)
2. ``click``     - pointer click (single, double, right, middle)
3. ``type``      - type text (unicode / keycode / clipboard)
4. ``hotkey``    - key combinations and key presses
5. ``scroll``    - vertical / horizontal wheel scrolling
6. ``drag``      - press-drag-release (with optional start point)

Extras that make those six usable: ``screens``, ``windows``, ``focus``,
``selftest``, ``backends``.

Every invocation prints exactly one JSON object on stdout::

    {"ok": true, "command": "click", ...}

``--dry-run`` validates the full plan (including key names, buttons, ranges)
without touching the pointer or keyboard, which lets an agent verify a plan
before moving the user's mouse.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import driver as driver_mod
from .driver import CAP_CAPTURE, CAP_INPUT, DriverError
from .png import bgra_rows_to_rgb, scale_rgb_rows, write_image

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2

DISCLAIMER = "synthetic pointer/keyboard input; visible on the real desktop"


class CliError(Exception):
    """User facing error (exit code 1, no traceback)."""


class _Parser(argparse.ArgumentParser):
    def error(self, message):  # pragma: no cover - argparse plumbing
        raise CliError(f"{message}\n{self.format_usage().strip()}")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_WINDOW_ALIASES = {
    "active": {"active", "fg", "foreground", "current", "focused"},
    "last": {"last", "previous", "prev"},
}

#: Remembers the window a command resolved so ``--window last`` can reuse it.
#: Every CLI invocation is a fresh process, so this is persisted to a small JSON
#: file next to the temp dir rather than kept in memory.
_LAST_WINDOW: Dict[str, Any] = {}
_LAST_WINDOW_FILE = os.path.join(
    os.environ.get("VISUAL_CONTROL_STATE_DIR") or os.path.join(tempfile.gettempdir(), "visual-control-skill"),
    "last-window.json",
)


def _text(value) -> str:
    """str() that also copes with argparse giving us a list or an int HWND."""
    if isinstance(value, (list, tuple)):
        value = " ".join(str(v) for v in value)
    return str(value).strip()


def _split_point(value, what: str) -> List[str]:
    """Split ``'640,360'`` / ``'50%,50%'`` / ``['640', '360']`` into two tokens."""
    if isinstance(value, (list, tuple)):
        parts = [str(v) for v in value]
    else:
        text = str(value).strip().lower()
        if text.startswith("px:"):
            text = text[3:]
        for separator in (",", ";", "|", "x", " "):
            if separator in text:
                text = text.replace(separator, " ")
        parts = text.split()
    if len(parts) != 2:
        raise CliError(f"{what} expects 'X,Y' or '50%,50%' (got {value!r})")
    return parts


def _is_relative(parts: Sequence[Any]) -> bool:
    return any(str(token).strip().endswith("%") or "." in str(token) for token in parts)


def _fraction(token: Any, what: str) -> float:
    text = str(token).strip().rstrip("%")
    try:
        value = float(text)
    except ValueError as exc:
        raise CliError(f"{what} expects a numeric fraction (got {token!r})") from exc
    if value > 1.0:
        value = value / 100.0
    return max(0.0, min(1.0, value))


def _absolute_point(parts: Sequence[str], what: str) -> Tuple[int, int]:
    try:
        return int(round(float(str(parts[0]).strip()))), int(round(float(str(parts[1]).strip())))
    except ValueError as exc:
        raise CliError(f"{what} expects numeric X,Y (got {list(parts)!r})") from exc


def _remember_window(info) -> None:
    """Persist the resolved window so the next invocation can use 'last'."""
    _LAST_WINDOW["handle"] = _hwnd_of(info)
    _LAST_WINDOW["title"] = info.title
    try:
        os.makedirs(os.path.dirname(_LAST_WINDOW_FILE), exist_ok=True)
        with open(_LAST_WINDOW_FILE, "w", encoding="utf-8") as fh:
            json.dump({"handle": _LAST_WINDOW["handle"], "title": info.title, "at": time.time()}, fh)
    except OSError:
        pass  # remembering is best-effort; never fail a command over it


def _hwnd_of(info) -> int:
    try:
        return int(info.handle)
    except (TypeError, ValueError):
        return 0


def _last_window_info():
    if not _LAST_WINDOW:
        try:
            with open(_LAST_WINDOW_FILE, "r", encoding="utf-8") as fh:
                stored = json.load(fh)
            if isinstance(stored, dict) and stored.get("handle"):
                _LAST_WINDOW.update(stored)
        except (OSError, ValueError):
            return None
    handle = _LAST_WINDOW.get("handle")
    if not handle:
        return None
    from .driver import WindowInfo

    return WindowInfo(
        handle=int(handle), title=str(_LAST_WINDOW.get("title", "")), process="", x=0, y=0, width=0, height=0
    )


def _window_ref(info, focus_state: str) -> Dict[str, Any]:
    payload = {
        "handle": _hwnd_of(info),
        "title": info.title,
        "process": info.process,
        "bounds": {"x": info.x, "y": info.y, "width": info.width, "height": info.height},
        "focus": focus_state,
    }
    return payload


def parse_coords(value: Optional[str], what: str = "--at") -> Optional[Tuple[int, int]]:
    """Parse ``X,Y`` into integer pixels, or a relative pair for percentages.

    Tolerant on purpose: PowerShell expands an unquoted ``200,80`` into two
    arguments, so ``X Y`` and ``X;Y`` are accepted too.  A percentage or decimal
    pair (``50%,50%``, ``0.5,0.5``) is kept as-is so the caller can resolve it
    against a window; use :func:`_resolve_point` for that.
    """
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        parts = [str(v) for v in value]
    else:
        text = str(value).strip().lower()
        if text.startswith("px:"):
            text = text[3:]
        for separator in (",", ";", "x", "|", " "):
            if separator in text:
                text = text.replace(separator, " ")
        parts = text.split()
    if len(parts) != 2:
        raise CliError(f"{what} expects 'X,Y' (got {value!r})")
    if _is_relative(parts):
        _fraction(parts[0], what)
        _fraction(parts[1], what)
        return (parts[0], parts[1])  # type: ignore[return-value]
    try:
        return int(round(float(parts[0]))), int(round(float(parts[1])))
    except ValueError as exc:
        raise CliError(f"{what} expects numeric X,Y (got {value!r})") from exc


def parse_keys(value: Optional[str]) -> List[str]:
    """Parse ``ctrl+shift+s`` / ``ctrl,shift,s`` into key tokens."""
    if not value:
        raise CliError("--keys is required (e.g. --keys ctrl+shift+s)")
    raw = str(value).replace(",", "+")
    keys = [token.strip() for token in raw.split("+") if token.strip()]
    if not keys:
        raise CliError(f"could not parse keys from {value!r}")
    return keys


def _json_print(payload: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=True, indent=2) + "\n")
    sys.stdout.flush()


def _resolve_output(path: Optional[str], prefix: str, out_dir: Optional[str]) -> str:
    if path:
        resolved = os.path.abspath(os.path.expanduser(path))
    else:
        base = os.path.expanduser(out_dir) if out_dir else tempfile.gettempdir()
        os.makedirs(base, exist_ok=True)
        resolved = os.path.join(base, f"{prefix}-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}.png")
    parent = os.path.dirname(resolved)
    if parent:
        os.makedirs(parent, exist_ok=True)
    return resolved


def _account_scale(scale: float) -> float:
    if not 0.1 <= scale <= 1.0:
        raise CliError("--scale must be between 0.1 and 1.0")
    return scale


def rgb_rows(frame) -> List[bytes]:
    return list(bgra_rows_to_rgb(f for f in frame.bgr_rows()))


def apply_grid(rows: List[bytes], width: int, height: int, step: int, origin: Tuple[int, int]) -> Dict[str, Any]:
    """Burn a coordinate ruler into the image (top edge + left edge)."""
    pixels = [bytearray(row) for row in rows]

    def put(x: int, y: int) -> None:
        if 0 <= x < width and 0 <= y < height:
            offset = x * 3
            pixels[y][offset : offset + 3] = b"\xff\x00\x00"

    for x in range(0, width, step):
        for y in range(0, 3):
            put(x, y)
        label = origin[0] + x
        for index, char in enumerate(str(label)):
            glyph = _GLYPHS.get(char)
            if not glyph:
                continue
            for gy, row_bits in enumerate(glyph):
                for gx, bit in enumerate(row_bits):
                    if bit == "1":
                        put(x + 3 + index * 4 + gx, 5 + gy)
    for y in range(0, height, step):
        for x in range(0, 3):
            put(x, y)
    return {
        "step_px": step,
        "origin": list(origin),
        "note": "red ruler marks every N physical pixels; labels are physical X coordinates",
    }


# 3x5 pixel digits for the ruler labels.
_GLYPHS = {
    "0": ("111", "101", "101", "101", "111"),
    "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"),
    "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"),
    "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"),
    "7": ("111", "001", "010", "010", "010"),
    "8": ("111", "101", "111", "101", "111"),
    "9": ("111", "101", "111", "001", "111"),
}


def _observe(args) -> Dict[str, Any]:
    driver = driver_mod.load((CAP_CAPTURE,), args.backend)
    screens = driver.screens()
    if args.screen is not None:
        match = [s for s in screens if s.index == args.screen]
        if not match:
            raise CliError(f"screen {args.screen} not found (available: {[s.index for s in screens]})")
        chosen = match[0]
    else:
        chosen = next((s for s in screens if s.primary), screens[0]) if screens else None
    if chosen is None:
        raise CliError("no screens reported by the backend")

    region = (chosen.x, chosen.y, chosen.width, chosen.height)
    region_source = f"screen-{chosen.index}"

    if args.region:
        parts = [p for p in str(args.region).split(",") if p.strip() != ""]
        if len(parts) != 4:
            raise CliError("--region expects 'X,Y,W,H'")
        try:
            region = tuple(int(round(float(p))) for p in parts)  # type: ignore[assignment]
        except ValueError as exc:
            raise CliError("--region expects integers 'X,Y,W,H'") from exc
        region_source = "explicit"

    if args.window:
        info, focus_state = _target_window(driver, args)
        x, y, width, height = info.x, info.y, info.width, info.height
        if args.region:
            rx, ry, rw, rh = region
            region = (x + rx, y + ry, min(rw, width), min(rh, height))
        else:
            region = (x, y, width, height)
        region_source = f"window:{info.title}"
        window_meta = _window_ref(info, focus_state)
    else:
        window_meta = None

    frame = driver.grab(region)
    scale = _account_scale(args.scale)
    rows = rgb_rows(frame)
    grid_meta = None
    if args.grid:
        step = max(20, int(args.grid))
        grid_meta = apply_grid(rows, frame.width, frame.height, step, (frame.origin_x, frame.origin_y))
    if scale < 1.0:
        rows, out_w, out_h = scale_rgb_rows(rows, frame.width, frame.height, scale)
    else:
        out_w, out_h = frame.width, frame.height

    from .png import encode_png

    path = _resolve_output(args.out, "screen", args.out_dir)
    with open(path, "wb") as fh:
        fh.write(encode_png(out_w, out_h, rows))

    encoded = os.path.getsize(path)
    result: Dict[str, Any] = {
        "path": path,
        "region": {"x": frame.origin_x, "y": frame.origin_y, "width": frame.width, "height": frame.height},
        "image": {"width": out_w, "height": out_h, "scale": scale, "bytes": encoded},
        "region_source": region_source,
        "driver": driver.name,
        "coordinate_space": "physical screen pixels (top-left origin, multi-monitor aware)",
        "bytes": encoded,
    }
    if window_meta:
        result["window"] = window_meta
    if args.with_cursor:
        input_driver = driver_mod.load((CAP_INPUT,), args.backend)
        cx, cy = input_driver.cursor_pos()
        result["cursor"] = {
            "x": cx,
            "y": cy,
            "in_image": bool(frame.origin_x <= cx < frame.origin_x + frame.width and frame.origin_y <= cy < frame.origin_y + frame.height),
        }
    if args.with_windows:
        result["windows"] = [w.as_dict() for w in _windows_for(driver, args)]
    if grid_meta:
        result["grid"] = grid_meta
    result["screens"] = [s.as_dict() for s in screens]
    return result


def _windows_for(driver, args) -> List[Any]:
    try:
        wins = driver.windows()
    except DriverError:
        wins = []
    min_w = getattr(args, "min_width", 0) or 0
    min_h = getattr(args, "min_height", 0) or 0
    wins = [w for w in wins if w.width >= min_w and w.height >= min_h]
    match = getattr(args, "match", None)
    if match:
        needle = str(match).strip().lower()
        if needle in _WINDOW_ALIASES["active"]:
            wins = [w for w in wins if w.foreground]
        else:
            wins = [w for w in wins if needle in w.title.lower() or needle in (w.process or "").lower()]
    return wins


def _find_window(driver, pattern: str, min_width: int = 0, min_height: int = 0):
    """Resolve a window reference to a WindowInfo.

    Accepted references:

    * ``active`` / ``fg`` / ``foreground`` / ``current`` - the foreground window
      (the window the user is looking at right now)
    * ``last`` - the window the previous command resolved (cheap shorthand)
    * ``pid:1234`` - the largest visible window owned by that process id
    * ``proc:chrome.exe`` / a bare ``chrome.exe`` - that process's window
    * an HWND (all digits) or a title / process substring, best match wins
    """
    windows = _windows_for(driver, argparse.Namespace(min_width=min_width, min_height=min_height))
    if not windows:
        raise CliError("no windows visible; pass --at X,Y, --region X,Y,W,H or --screen N instead")
    needle = _text(pattern)
    lowered = needle.lower()

    if lowered in _WINDOW_ALIASES["active"]:
        active = next((w for w in windows if w.foreground), None)
        if active is None:
            raise CliError("no foreground window reported by the backend")
        _remember_window(active)
        return active

    if lowered in _WINDOW_ALIASES["last"]:
        remembered = _last_window_info()
        if remembered is None:
            raise CliError("no previous window to reuse; pass --window <title|process|HWND> once first")
        for win in windows:
            if win.handle == remembered.handle:
                return win
        raise CliError(f"the previous window (HWND {remembered.handle}, {remembered.title!r}) is gone")

    if lowered.startswith("pid:"):
        wanted = lowered[4:].strip()
        owned = [w for w in windows if str(getattr(w, "pid", "")) == wanted]
        if not owned:
            raise CliError(f"no visible window owned by pid {wanted}")
        chosen = max(owned, key=lambda w: w.width * w.height)
        _remember_window(chosen)
        return chosen

    if lowered.startswith("proc:"):
        needle = needle[5:].strip()
        lowered = needle.lower()

    if lowered.isdigit():
        # Prefer an exact title match (a window literally named "123"), then HWND.
        for win in windows:
            if win.title.strip() == needle:
                _remember_window(win)
                return win
        for win in windows:
            if win.handle == int(needle):
                _remember_window(win)
                return win

    exact = [w for w in windows if w.title.lower() == lowered or (w.process or "").lower() == lowered]
    if exact:
        exact.sort(key=lambda w: (not w.foreground, w.minimized, -w.width * w.height))
        _remember_window(exact[0])
        return exact[0]

    partial = [w for w in windows if lowered in w.title.lower() or lowered in (w.process or "").lower()]
    if not partial:
        titles = ", ".join(repr(w.title) for w in windows[:10])
        raise CliError(
            f"no window matching {pattern!r}. Visible windows: {titles}. "
            "Use 'active' for the foreground window or 'last' for the previous one."
        )
    partial.sort(key=lambda w: (not w.foreground, w.minimized, -w.width * w.height))
    _remember_window(partial[0])
    return partial[0]


def _target_window(driver, args, default_to_active: bool = False):
    """Resolve + optionally focus the window targeted by *args*.

    Returns ``(WindowInfo | None, focus_state)``.  ``--no-activate`` skips raising
    a minimised target: SendInput can still click it, and some users prefer that
    over the window stealing focus.
    """
    pattern = getattr(args, "window", None)
    if not pattern:
        if not default_to_active:
            return None, "none"
        pattern = "active"
    info = _find_window(driver, pattern, getattr(args, "min_width", 0), getattr(args, "min_height", 0))
    if getattr(args, "no_activate", False) and getattr(args, "focus", False):
        raise CliError("--focus and --no-activate contradict each other; pick one")
    if _is_window_active(driver, info):
        return info, "already-active"
    raise_it = (not getattr(args, "no_activate", False)) and (info.minimized or getattr(args, "focus", False))
    if raise_it:
        force = bool(getattr(args, "force_focus", False))
        if not driver.focus_window(info.handle, force=force):
            raise CliError(
                f"failed to focus window {info.title!r} (HWND {info.handle}); Windows refused the "
                "foreground change. Retry with --force-focus, or click the app once yourself and "
                "use --window active, or use --no-activate to act without focusing."
            )
        time.sleep(0.12)
        return info, "focused"
    return info, "targeted"


def _is_window_active(driver, info) -> bool:
    """Ask the driver live; the window list snapshot can be a few ms stale."""
    probe = getattr(driver, "is_active", None)
    if callable(probe):
        try:
            return bool(probe(info.handle))
        except Exception:
            pass
    return bool(getattr(info, "foreground", False))


def _resolve_point(point, info, what: str) -> Optional[Tuple[int, int]]:
    """Turn a point into absolute physical pixels, relative to *info* if given.

    Supports ``X,Y`` pixels and ``50%,50%`` / ``0.5,0.5`` fractions of the window.
    """
    if info is None:
        if point is None:
            return None
        return _absolute_point(point, what)
    if point is None:
        return (info.x + info.width // 2, info.y + info.height // 2)
    parts = point if isinstance(point, (list, tuple)) else _split_point(point, what)
    if _is_relative(parts):
        rx, ry = _fraction(parts[0], what), _fraction(parts[1], what)
        px = info.x + max(0, min(info.width - 1, int(round(rx * info.width))))
        py = info.y + max(0, min(info.height - 1, int(round(ry * info.height))))
        return px, py
    absolute = _absolute_point(parts, what)
    return (info.x + absolute[0], info.y + absolute[1])


def _input_driver(args):
    return driver_mod.load(
        (CAP_INPUT,),
        getattr(args, "backend", None),
        dry_run=bool(getattr(args, "dry_run", False)),
    )


def _click(args) -> Dict[str, Any]:
    point = parse_coords(args.at, "--at")
    if point is None and not args.here and not args.window:
        raise CliError(
            "say where to click: --at X,Y, '--window <title|active|last> [--at ...]', or --here"
        )
    driver = _input_driver(args)
    info, focus_state = _target_window(driver, args)
    target = _resolve_point(point, info, "--at") if not args.here else None

    before = driver.cursor_pos()
    driver.click(
        target[0] if target else None,
        target[1] if target else None,
        button=args.button,
        count=args.count,
        interval=args.interval,
        duration=args.duration,
    )
    result: Dict[str, Any] = {
        "clicked": {"button": args.button, "count": args.count},
        "cursor_before": list(before),
    }
    if target:
        result["target"] = {"x": target[0], "y": target[1]}
    if info is not None:
        result["window"] = _window_ref(info, focus_state)
        if point is not None and info is not None:
            result["relative_to_window"] = {"x": target[0] - info.x, "y": target[1] - info.y}
    if getattr(args, "dry_run", False):
        result["dry_run"] = True
        result["journal"] = getattr(driver, "journal", [])
    else:
        result["cursor_after"] = list(driver.cursor_pos())
    return result


def _type(args) -> Dict[str, Any]:
    if args.text is not None:
        text = args.text
    elif args.text_file:
        with open(os.path.expanduser(args.text_file), "r", encoding="utf-8") as fh:
            text = fh.read()
    elif args.text_stdin:
        text = sys.stdin.read()
    else:
        raise CliError("provide --text, --text-file or --text-stdin")
    if args.clear:
        text = _apply_modifiers(text, args.clear)
    driver = _input_driver(args)
    info, focus_state = _target_window(driver, args)
    if info is not None and focus_state == "targeted" and not info.foreground:
        result_note = f"window {info.title!r} was targeted but not focused; pass --focus to be sure it receives the keys"
    else:
        result_note = None
    driver.type_text(text, method=args.method, interval=args.interval)
    result: Dict[str, Any] = {
        "typed": {"length": len(text), "method": args.method},
        "preview": (text[:120] + ("..." if len(text) > 120 else "")),
    }
    if info is not None:
        result["window"] = _window_ref(info, focus_state)
    if result_note:
        result["warning"] = result_note
    if getattr(args, "dry_run", False):
        result["dry_run"] = True
        result["journal"] = getattr(driver, "journal", [])
    return result


def _apply_modifiers(text: str, spec: str) -> str:
    """Apply --clear substitutions (e.g. ``tab=\\t,enter=\\n``)."""
    for pair in str(spec).split(","):
        if "=" not in pair:
            continue
        name, _, replacement = pair.partition("=")
        text = text.replace(name, replacement.replace("\\t", "\t").replace("\\n", "\n"))
    return text


def _hotkey(args) -> Dict[str, Any]:
    keys = parse_keys(args.keys)
    driver = _input_driver(args)
    info, focus_state = _target_window(driver, args)
    if args.hold is not None:
        for key in keys:
            driver.key_down(key)
        time.sleep(max(0.0, args.hold))
        for key in reversed(keys):
            driver.key_up(key)
    else:
        for _ in range(max(1, args.repeat)):
            if hasattr(driver, "hotkey"):
                driver.hotkey(keys)
            else:  # pragma: no cover - fallback for minimal drivers
                for key in keys:
                    driver.key_down(key)
                for key in reversed(keys):
                    driver.key_up(key)
            time.sleep(max(0.0, args.interval))
    result: Dict[str, Any] = {"keys": keys, "repeat": max(1, args.repeat) if args.hold is None else 1}
    if info is not None:
        result["window"] = _window_ref(info, focus_state)
        if focus_state == "targeted" and not info.foreground:
            result["warning"] = (
                f"window {info.title!r} was targeted but not focused; keystrokes go to the focused control - pass --focus"
            )
    if getattr(args, "dry_run", False):
        result["dry_run"] = True
        result["journal"] = getattr(driver, "journal", [])
    return result


def _scroll(args) -> Dict[str, Any]:
    if args.direction == "custom":
        amount = args.amount
        horizontal = args.horizontal
    else:
        magnitude = abs(args.amount) or 1
        amount = magnitude if args.direction == "up" else -magnitude
        horizontal = 0
    point = parse_coords(args.at, "--at")
    driver = _input_driver(args)
    info, focus_state = _target_window(driver, args)
    resolved = _resolve_point(point, info, "--at")
    if resolved is None:
        raise CliError("scroll needs --at X,Y (or '--window <ref>' to scroll at that window's centre)")
    driver.scroll(amount, horizontal=horizontal, x=resolved[0], y=resolved[1])
    result: Dict[str, Any] = {
        "scroll": {"direction": args.direction, "amount": amount, "horizontal": horizontal},
        "at": {"x": resolved[0], "y": resolved[1]},
    }
    if info is not None:
        result["window"] = _window_ref(info, focus_state)
    if getattr(args, "dry_run", False):
        result["dry_run"] = True
        result["journal"] = getattr(driver, "journal", [])
    return result


def _drag(args) -> Dict[str, Any]:
    start = parse_coords(args.start, "--start")
    end = parse_coords(args.to, "--to")
    if end is None:
        raise CliError("--to X,Y is required")
    driver = _input_driver(args)
    info, focus_state = _target_window(driver, args)
    resolved_end = _resolve_point(end, info, "--to")
    if start is None:
        resolved_start = driver.cursor_pos()
    else:
        resolved_start = _resolve_point(start, info, "--start")
    driver.drag(resolved_start, resolved_end, button=args.button, duration=args.duration, steps=args.steps)
    result: Dict[str, Any] = {
        "drag": {
            "from": list(resolved_start),
            "to": list(resolved_end),
            "button": args.button,
            "duration": args.duration,
        },
    }
    if info is not None:
        result["window"] = _window_ref(info, focus_state)
    if getattr(args, "dry_run", False):
        result["dry_run"] = True
        result["journal"] = getattr(driver, "journal", [])
    return result


def _screens(args) -> Dict[str, Any]:
    driver = driver_mod.load((CAP_CAPTURE,), args.backend)
    screens = [s.as_dict() for s in driver.screens()]
    primary = next((s for s in screens if s["primary"]), screens[0] if screens else None)
    return {
        "driver": driver.name,
        "screens": screens,
        "primary": primary,
        "virtual_desktop": {
            "x": min((s["x"] for s in screens), default=0),
            "y": min((s["y"] for s in screens), default=0),
            "width": (max((s["x"] + s["width"] for s in screens), default=0) - min((s["x"] for s in screens), default=0)),
            "height": (max((s["y"] + s["height"] for s in screens), default=0) - min((s["y"] for s in screens), default=0)),
        },
    }


def _windows(args) -> Dict[str, Any]:
    driver = driver_mod.load((CAP_INPUT,), args.backend)
    windows = [w.as_dict() for w in _windows_for(driver, args)]
    windows.sort(key=lambda w: (not w["foreground"], -w["width"] * w["height"]))
    active = next((w for w in windows if w["foreground"]), None)
    return {
        "driver": driver.name,
        "count": len(windows),
        "active": active,
        "match": getattr(args, "match", None),
        "windows": windows[: args.limit],
    }


def _focus(args) -> Dict[str, Any]:
    driver = driver_mod.load((CAP_INPUT,), args.backend)
    args.no_activate = False
    args.focus = True
    info, _state = _target_window(driver, args)
    ok = _is_window_active(driver, info) or driver.focus_window(
        info.handle, force=bool(getattr(args, "force_focus", False))
    )
    return {"window": _window_ref(info, "focused" if ok else "targeted"), "focused": bool(ok)}


def _backends(args) -> Dict[str, Any]:
    supported = list(driver_mod.SUPPORTED_PLATFORMS)
    return {
        "platform": sys.platform,
        "supported_platforms": supported,
        "host_supported": sys.platform in supported,
        "python": sys.version.split()[0],
        "requirements": "Windows only, no pip packages required (ctypes + GDI + SendInput)",
        "backends": driver_mod.available(),
    }


def _selftest(args) -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []

    def check(name: str, fn):
        try:
            detail = fn()
            checks.append({"check": name, "ok": True, "detail": detail})
        except Exception as exc:
            checks.append({"check": name, "ok": False, "detail": f"{type(exc).__name__}: {exc}"})

    check("import driver", lambda: driver_mod.SCHEMA_VERSION)
    check("available backends", lambda: {k: v["usable"] for k, v in driver_mod.available().items()})

    def capture():
        driver = driver_mod.load((CAP_CAPTURE,), args.backend)
        screens = driver.screens()
        frame = driver.grab((screens[0].x, screens[0].y, min(320, screens[0].width), min(200, screens[0].height)))
        return {
            "driver": driver.name,
            "size": [frame.width, frame.height],
            "bytes": len(frame.bgra),
            "expected_bytes": frame.width * frame.height * 4,
            "screens": len(screens),
        }

    check("capture", capture)

    def encode():
        rows = list(bgra_rows_to_rgb(iter([bytes(range(256)) * 4 for _ in range(8)])))
        from .png import encode_png

        data = encode_png(64, 8, rows)
        if not data.startswith(b"\x89PNG"):
            raise AssertionError("not a PNG")
        return f"{len(data)} bytes"

    check("png encoder", encode)

    def input_probe():
        driver = _input_driver(args)
        pos = driver.cursor_pos()
        return {"driver": driver.name, "cursor": list(pos), "capabilities": list(driver.capabilities)}

    check("input driver", input_probe)

    def key_table():
        from .backends import windows_input

        sample = {k: windows_input.key_vk(k) for k in ("ctrl", "shift", "s", "enter", "f5", "win", "left")}
        if len(set(sample.values())) < 5:
            raise AssertionError(f"key table looks wrong: {sample}")
        try:
            windows_input.key_vk("no-such-key")
        except DriverError:
            pass
        else:
            raise AssertionError("unknown key names must be rejected")
        return sample

    check("key table", key_table)

    def dry_run_plan():
        driver = driver_mod.load((CAP_INPUT,), args.backend, dry_run=True)
        driver.click(10, 20, button="left", count=2)
        driver.drag((5, 5), (25, 25), duration=0.1)
        driver.scroll(-3)
        driver.type_text("hello 你好", method="unicode")
        driver.hotkey(["ctrl", "s"])
        return len(getattr(driver, "journal", []))

    check("dry-run journal", dry_run_plan)

    ok = all(c["ok"] for c in checks)
    return {"ok": ok, "checks": checks}


# ---------------------------------------------------------------------------
# argument parsing
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="visual_control",
        description="Screen observation and synthetic input for GUI automation (JSON on stdout).",
        epilog=DISCLAIMER,
    )
    parser.add_argument("--backend", help="force a backend name (see 'backends' subcommand)")
    parser.add_argument("--dry-run", action="store_true", help="validate the plan without touching input devices")
    parser.add_argument("--pretty", action="store_true", help="(always on) kept for symmetry")
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    def add_windows_opts(p, with_focus: bool = True):
        p.add_argument(
            "--window",
            help=(
                "target window: title / process (chrome.exe) / HWND / pid:1234, or the aliases "
                "'active' (foreground window) and 'last' (previous target). Coordinates become "
                "window-relative."
            ),
        )
        p.add_argument("--min-width", type=int, default=0, dest="min_width")
        p.add_argument("--min-height", type=int, default=0, dest="min_height")
        if with_focus:
            p.add_argument("--focus", action="store_true", help="activate the target window first")
            p.add_argument(
                "--force-focus",
                action="store_true",
                dest="force_focus",
                help="escalate to AttachThreadInput if Windows refuses the foreground change",
            )
            p.add_argument(
                "--no-activate",
                action="store_true",
                dest="no_activate",
                help="do not restore a minimised target (default; keeps focus where it is)",
            )

    def add_point(p, flags=("--at",), help_text="target point 'X,Y' in physical pixels (or '50%%,50%%' of a --window)"):
        for flag in flags:
            # nargs="+" lets unquoted '200,80' from PowerShell (which splits it
            # into two argv items) still parse; the tuple is joined in main().
            p.add_argument(flag, nargs="+", help=help_text)

    p = sub.add_parser("observe", help="capture the screen (optionally a region/window) to a PNG")
    p.add_argument("--region", help="region 'X,Y,W,H' in physical pixels")
    p.add_argument("--screen", type=int, help="screen index from the 'screens' command")
    p.add_argument("--grid", type=int, nargs="?", const=100, default=0, help="burn a coordinate ruler every N px (default 100)")
    p.add_argument("--scale", type=float, default=1.0, help="downscale factor 0.1-1.0 (coordinates stay physical)")
    p.add_argument("--out", help="output PNG path")
    p.add_argument("--out-dir", dest="out_dir", help="directory for the auto-generated filename")
    p.add_argument("--with-cursor", action="store_true", dest="with_cursor", help="include the current cursor position")
    p.add_argument("--with-windows", action="store_true", dest="with_windows", help="include the visible window list")
    add_windows_opts(p)
    p.set_defaults(handler=_observe)

    p = sub.add_parser("click", help="click at a point, in a window, or at the current cursor (--here)")
    add_point(p)
    p.add_argument("--here", action="store_true", help="click wherever the cursor currently is (focus follows pointer)")
    p.add_argument("--button", default="left", choices=["left", "right", "middle"], help="mouse button")
    p.add_argument("--count", type=int, default=1, help="click count (2 = double click)")
    p.add_argument("--interval", type=float, default=0.08, help="delay between clicks")
    p.add_argument("--duration", type=float, default=0.0, help="travel time to --at (0 = teleport)")
    add_windows_opts(p)
    p.set_defaults(handler=_click)

    p = sub.add_parser("type", help="type text into the focused control")
    p.add_argument("--text", help="text to type (use --text-stdin for anything with quotes/newlines)")
    p.add_argument("--text-file", dest="text_file", help="read the text from a UTF-8 file")
    p.add_argument("--text-stdin", action="store_true", dest="text_stdin", help="read the text from stdin")
    p.add_argument("--method", default="unicode", choices=["unicode", "key", "clipboard"], help="input method")
    p.add_argument("--interval", type=float, default=0.01, help="delay between characters")
    p.add_argument("--clear", help="substitutions applied first, e.g. 'tab=\\t,enter=\\n'")
    add_windows_opts(p)
    p.set_defaults(handler=_type)

    p = sub.add_parser("hotkey", help="press a key combination")
    p.add_argument("--keys", required=True, help="e.g. 'ctrl+shift+s' or 'alt+tab'")
    p.add_argument("--repeat", type=int, default=1)
    p.add_argument("--interval", type=float, default=0.05)
    p.add_argument("--hold", type=float, help="hold all keys down for N seconds instead of tapping")
    add_windows_opts(p)
    p.set_defaults(handler=_hotkey)

    p = sub.add_parser("scroll", help="scroll the wheel (positive = up/away)")
    p.add_argument("--direction", default="down", choices=["up", "down", "custom"])
    p.add_argument("--amount", type=int, default=3, help="number of wheel notches")
    p.add_argument("--horizontal", type=int, default=0, help="horizontal notches (with --direction custom)")
    add_point(p, help_text="point to scroll over (moves the cursor there first)")
    add_windows_opts(p)
    p.set_defaults(handler=_scroll)

    p = sub.add_parser("drag", help="press, move, release")
    p.add_argument("--to", required=True, help="end point 'X,Y' or '50%%,50%%' of --window")
    p.add_argument("--start", help="start point 'X,Y' (default: current cursor)")
    p.add_argument("--button", default="left", choices=["left", "right", "middle"])
    p.add_argument("--duration", type=float, default=0.5, help="drag travel time")
    p.add_argument("--steps", type=int, default=0, help="explicit step count (0 = derive from duration)")
    add_windows_opts(p)
    p.set_defaults(handler=_drag)

    p = sub.add_parser("screens", help="list displays and the virtual desktop bounds")
    p.set_defaults(handler=_screens)

    p = sub.add_parser("windows", help="list visible windows with bounds (and which one is active)")
    p.add_argument("--limit", type=int, default=40)
    p.add_argument("--match", help="only windows whose title/process contains this text, or 'active'")
    p.add_argument("--min-width", type=int, default=0, dest="min_width")
    p.add_argument("--min-height", type=int, default=0, dest="min_height")
    p.set_defaults(handler=_windows)

    p = sub.add_parser("focus", help="activate a window (title / process / HWND / active / last)")
    p.add_argument("--window", required=True)
    p.add_argument("--min-width", type=int, default=0, dest="min_width")
    p.add_argument("--min-height", type=int, default=0, dest="min_height")
    p.add_argument(
        "--force-focus",
        action="store_true",
        dest="force_focus",
        help="escalate to AttachThreadInput if Windows refuses the foreground change",
    )
    p.set_defaults(handler=_focus, focus=True, no_activate=False)

    p = sub.add_parser("backends", help="show backend availability for this machine")
    p.set_defaults(handler=_backends)

    p = sub.add_parser("selftest", help="non-destructive health check of every layer")
    p.add_argument("--include-input", action="store_true", help="(already included) ")
    p.set_defaults(handler=_selftest)

    return parser


def _join_point_args(args) -> None:
    for attr in ("at", "to", "start"):
        value = getattr(args, attr, None)
        if isinstance(value, list):
            setattr(args, attr, ",".join(str(v) for v in value))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    started = time.time()
    try:
        args = parser.parse_args(list(argv) if argv is not None else sys.argv[1:])
    except CliError as exc:
        _json_print({"ok": False, "error": "usage", "message": str(exc)})
        return EXIT_USAGE
    _join_point_args(args)

    try:
        payload = args.handler(args)
    except (CliError, DriverError) as exc:
        _json_print({"ok": False, "command": args.command, "error": type(exc).__name__, "message": str(exc)})
        return EXIT_ERROR
    except Exception as exc:  # pragma: no cover - unexpected
        if os.environ.get("VISUAL_CONTROL_DEBUG"):
            raise
        _json_print({"ok": False, "command": args.command, "error": type(exc).__name__, "message": str(exc)})
        return EXIT_ERROR

    payload.setdefault("ok", True)
    payload["command"] = args.command
    payload["elapsed_ms"] = int((time.time() - started) * 1000)
    _json_print(payload)
    return EXIT_OK if payload.get("ok") else EXIT_ERROR


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
