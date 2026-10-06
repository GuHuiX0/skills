"""Driver layer: backend registry and shared helpers for visual-control.

A *driver* is any object that implements the ``Driver`` protocol below.  Two
capability groups exist:

* ``capture`` : ``screens()`` and ``grab(region)``
* ``input``   : pointer / keyboard primitives

Backends live in ``visual_control/backends/*.py`` and expose ``build()``.
Drop a new module there to extend the skill (see references/backends.md).
"""

from __future__ import annotations

import importlib
import os
import pkgutil
import sys
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple, runtime_checkable
SCHEMA_VERSION = "1.0"

#: Environment override, e.g. ``VISUAL_CONTROL_BACKEND=windows`` or
#: ``VISUAL_CONTROL_BACKENDS=my_remote`` (comma separated, first match wins).
ENV_BACKEND = "VISUAL_CONTROL_BACKEND"
ENV_BACKENDS = "VISUAL_CONTROL_BACKENDS"

CAP_CAPTURE = "capture"
CAP_INPUT = "input"


class DriverError(RuntimeError):
    """Raised when no usable driver exists or a primitive fails."""


@dataclass
class Screen:
    index: int
    x: int
    y: int
    width: int
    height: int
    primary: bool = False
    name: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Frame:
    """A captured image in raw BGRA/BGR layout."""

    width: int
    height: int
    bgra: bytes
    origin_x: int = 0
    origin_y: int = 0

    def bgr_rows(self):
        for y in range(self.height):
            yield self.bgra[y * self.width * 4 : (y + 1) * self.width * 4]


@dataclass
class WindowInfo:
    handle: int
    title: str
    process: str
    x: int
    y: int
    width: int
    height: int
    minimized: bool = False
    foreground: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@runtime_checkable
class Driver(Protocol):
    name: str
    capabilities: Tuple[str, ...]
    platform: str

    # -- capture ---------------------------------------------------------
    def screens(self) -> List[Screen]: ...

    def grab(self, region: Tuple[int, int, int, int]) -> Frame: ...

    # -- input -----------------------------------------------------------
    def cursor_pos(self) -> Tuple[int, int]: ...

    def move(self, x: int, y: int, duration: float = 0.0) -> None: ...

    def click(
        self,
        x: Optional[int],
        y: Optional[int],
        button: str = "left",
        count: int = 1,
        interval: float = 0.08,
        duration: float = 0.0,
    ) -> None: ...

    def scroll(self, amount: int, horizontal: int = 0, x: Optional[int] = None, y: Optional[int] = None) -> None: ...

    def drag(
        self,
        from_xy: Tuple[int, int],
        to_xy: Tuple[int, int],
        button: str = "left",
        duration: float = 0.5,
        steps: int = 0,
    ) -> None: ...

    def key_down(self, key: str) -> None: ...

    def key_up(self, key: str) -> None: ...

    def type_text(self, text: str, method: str = "unicode", interval: float = 0.01) -> None: ...

    # -- optional extras (implement when the platform allows) ------------
    def windows(self) -> List[WindowInfo]: ...

    def focus_window(self, handle: int) -> bool: ...


class BaseDriver:
    """Convenience base class.  Subclasses override only what they support."""

    name = "base"
    capabilities: Tuple[str, ...] = ()
    platform = sys.platform

    def _unsupported(self, what: str):
        raise DriverError(f"driver '{self.name}' does not support {what}")

    def screens(self) -> List[Screen]:
        self._unsupported("screens()")

    def grab(self, region: Tuple[int, int, int, int]) -> Frame:
        self._unsupported("grab()")

    def cursor_pos(self) -> Tuple[int, int]:
        self._unsupported("cursor_pos()")

    def move(self, x: int, y: int, duration: float = 0.0) -> None:
        self._unsupported("move()")

    def click(self, x, y, button="left", count=1, interval=0.08, duration=0.0) -> None:
        self._unsupported("click()")

    def scroll(self, amount, horizontal=0, x=None, y=None) -> None:
        self._unsupported("scroll()")

    def drag(self, from_xy, to_xy, button="left", duration=0.5, steps=0) -> None:
        self._unsupported("drag()")

    def key_down(self, key: str) -> None:
        self._unsupported("key_down()")

    def key_up(self, key: str) -> None:
        self._unsupported("key_up()")

    def type_text(self, text: str, method: str = "unicode", interval: float = 0.01) -> None:
        self._unsupported("type_text()")

    def windows(self) -> List[WindowInfo]:
        return []

    def focus_window(self, handle: int) -> bool:
        return False

    # -- shared helpers --------------------------------------------------
    def _sleep(self, seconds: float) -> None:
        if seconds and seconds > 0:
            import time

            time.sleep(seconds)

    def _interpolate(self, a: Tuple[int, int], b: Tuple[int, int], steps: int) -> List[Tuple[int, int]]:
        if steps <= 1:
            return [b]
        out: List[Tuple[int, int]] = []
        for i in range(1, steps + 1):
            t = i / steps
            out.append((int(round(a[0] + (b[0] - a[0]) * t)), int(round(a[1] + (b[1] - a[1]) * t))))
        return out


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------

#: This distribution is Windows-only.  Backends are still discovered from
#: ``backends/`` so a port can be dropped in, but every shipped backend is Windows.
SUPPORTED_PLATFORMS = ("win32",)

#: Preferred load order when several backends declare the same platform.
_BACKEND_MODULES = ("windows",)

_cache: Dict[str, BaseDriver] = {}


def _iter_backend_modules():
    """Yield ``(module_name, module)`` for every module in ``backends/``."""
    package = importlib.import_module("visual_control.backends")
    discovered = {m.name for m in pkgutil.iter_modules(package.__path__)}
    ordered = [n for n in _BACKEND_MODULES if n in discovered]
    ordered += sorted(discovered - set(ordered))
    for name in ordered:
        if name.startswith("_"):
            continue
        yield name, importlib.import_module(f"visual_control.backends.{name}")


def available() -> Dict[str, Dict[str, Any]]:
    """Describe every backend that could load on this machine."""
    report: Dict[str, Dict[str, Any]] = {}
    for name, module in _iter_backend_modules():
        info = dict(getattr(module, "BACKEND_INFO", {}) or {})
        reason = ""
        try:
            probe = getattr(module, "probe", None)
            if callable(probe):
                ok, reason = probe()
            else:
                ok = True
        except Exception as exc:  # pragma: no cover - defensive
            ok, reason = False, f"{type(exc).__name__}: {exc}"
        info.update({"module": name, "usable": bool(ok), "reason": reason})
        report[info.get("name", name)] = info
    return report


def _env_chain() -> List[str]:
    chain: List[str] = []
    single = os.environ.get(ENV_BACKEND, "").strip()
    if single:
        chain.append(single)
    multi = os.environ.get(ENV_BACKENDS, "").strip()
    if multi:
        chain.extend(p.strip() for p in multi.split(",") if p.strip())
    return chain


def load(required: Sequence[str], name: Optional[str] = None, **build_kwargs) -> BaseDriver:
    """Return a driver providing every capability in *required*.

    Selection order: explicit *name* / env override, then platform default,
    then any other usable backend.  ``build_kwargs`` (e.g. ``dry_run=True``) are
    forwarded to the backend's ``build()`` when it accepts them.
    """
    required = tuple(required)
    key = "|".join(required) + "#" + (name or "") + "#" + repr(sorted(build_kwargs.items()))
    if key in _cache:
        return _cache[key]

    errors: List[str] = []
    if sys.platform not in SUPPORTED_PLATFORMS:
        raise DriverError(
            f"visual-control supports {', '.join(SUPPORTED_PLATFORMS)} only; "
            f"this host reports {sys.platform!r}. A port would be a new module in "
            "visual_control/backends/ (see references/backends.md)."
        )
    pinned: List[str] = []
    for requested in list(_env_chain()) + ([name] if name else []):
        if requested not in pinned:
            pinned.append(requested)

    # Rank every discovered backend: pinned first, then ones whose declared
    # capabilities cover the request, then platform defaults, then the rest.
    ranked: List[Tuple[int, str, Any]] = []
    for module_name, module in _iter_backend_modules():
        info = dict(getattr(module, "BACKEND_INFO", {}) or {})
        backend_name = info.get("name", module_name)
        declared = set(info.get("capabilities") or ())
        if backend_name in pinned or module_name in pinned:
            rank = 0
        elif all(cap in declared for cap in required):
            rank = 1
        elif info.get("default_for") == sys.platform or info.get("platform") == sys.platform:
            rank = 3
        else:
            rank = 2
        ranked.append((rank, backend_name, module))
    ranked.sort(key=lambda item: item[0])

    for _rank, candidate, module in ranked:
        if pinned and candidate not in pinned:
            continue
        try:
            probe = getattr(module, "probe", None)
            if callable(probe):
                ok, reason = probe()
                if not ok:
                    errors.append(f"{candidate}: {reason}")
                    continue
            build = module.build
            try:
                driver = build(**build_kwargs)
            except TypeError:
                if build_kwargs:
                    driver = build()
                else:
                    raise
        except Exception as exc:
            errors.append(f"{candidate}: {type(exc).__name__}: {exc}")
            continue
        missing = [cap for cap in required if cap not in tuple(driver.capabilities)]
        if missing:
            errors.append(f"{candidate}: missing capabilities {missing}")
            continue
        _cache[key] = driver
        return driver

    detail = "; ".join(errors) if errors else "no backends discovered"
    hint = (
        "This skill is Windows-only and needs no extra package: capture uses GDI "
        "and input uses SendInput, both through ctypes. Run "
        "'python scripts/visual_control.py backends' to see what failed."
    )
    raise DriverError(f"no driver provides {list(required)} ({detail}). {hint}")
