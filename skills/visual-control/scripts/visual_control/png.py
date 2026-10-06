"""Dependency-free PNG writer and optional Pillow bridge.

The Windows backend produces raw BGRA frames from GDI.  Encoding those to PNG
with ``zlib`` + ``struct`` keeps the whole skill runnable on a stock Python
install (no pip, no Pillow).  If Pillow *is* present it is used for non-PNG
formats such as ``.jpg``/``.webp``.
"""

from __future__ import annotations

import os
import struct
import zlib


def _chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def encode_png(width: int, height: int, rgb_rows, level: int = 6) -> bytes:
    """Encode 8-bit RGB rows (iterable of bytes, 3 bytes per pixel) to PNG."""
    raw = bytearray()
    for row in rgb_rows:
        raw.append(0)  # filter type 0 (None)
        raw += row

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(bytes(raw), level))
        + _chunk(b"IEND", b"")
    )


def bgra_rows_to_rgb(rows):
    """Convert BGRA rows to RGB rows (slice assignment keeps this fast)."""
    for row in rows:
        out = bytearray(len(row) // 4 * 3)
        out[0::3] = row[2::4]
        out[1::3] = row[1::4]
        out[2::3] = row[0::4]
        yield bytes(out)


def scale_rgb_rows(rows, width: int, height: int, factor: float):
    """Nearest-neighbour downscale of RGB rows.  Returns (rows, w, h)."""
    if factor >= 1.0:
        return rows, width, height
    nw = max(1, int(round(width * factor)))
    nh = max(1, int(round(height * factor)))
    sampled = []
    src = list(rows)
    for y in range(nh):
        sy = min(height - 1, int(y / factor))
        row = src[sy]
        out = bytearray(nw * 3)
        for x in range(nw):
            sx = min(width - 1, int(x / factor)) * 3
            out[x * 3 : x * 3 + 3] = row[sx : sx + 3]
        sampled.append(bytes(out))
    return sampled, nw, nh


def write_image(path: str, width: int, height: int, bgra: bytes, scale: float = 1.0, quality: int = 85):
    """Write a BGRA buffer to *path*; returns (out_width, out_height, bytes_written).

    ``scale`` < 1 downscales the image (handy for model token budgets) while the
    reported coordinate space stays in physical pixels.
    """
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)

    rows = list(bgra_rows_to_rgb(_iter_bgra_rows(bgra, width, height)))
    out_w, out_h = width, height
    if scale and scale < 1.0:
        rows, out_w, out_h = scale_rgb_rows(rows, width, height, scale)

    ext = os.path.splitext(path)[1].lower()
    if ext == ".png":
        data = encode_png(out_w, out_h, rows)
        with open(path, "wb") as fh:
            fh.write(data)
        return out_w, out_h, len(data)

    try:  # pragma: no cover - depends on optional Pillow
        from PIL import Image  # type: ignore

        img = Image.frombytes("RGB", (out_w, out_h), b"".join(rows))
        save_kwargs = {}
        if ext in (".jpg", ".jpeg"):
            save_kwargs = {"quality": quality}
        img.save(path, **save_kwargs)
        return out_w, out_h, os.path.getsize(path)
    except Exception:
        # Fall back to PNG bytes even if the extension disagrees.
        data = encode_png(out_w, out_h, rows)
        with open(path, "wb") as fh:
            fh.write(data)
        return out_w, out_h, len(data)


def _iter_bgra_rows(bgra: bytes, width: int, height: int):
    stride = width * 4
    for y in range(height):
        yield bgra[y * stride : (y + 1) * stride]
