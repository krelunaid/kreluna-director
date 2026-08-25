#!/usr/bin/env python3
"""Crea l'icona Mac (.png + .icns) e la favicon web."""
from __future__ import annotations

import io
import struct
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[2]
NAVY = (11, 18, 32, 255)
GOLD = (212, 175, 55, 255)
GOLD_2 = (240, 215, 140, 255)
INK = (244, 239, 228, 255)


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in (
        "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
        "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf",
        "/System/Library/Fonts/NewYork.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ):
        candidate = Path(path)
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    # Pillow's unscaled bitmap fallback makes the K almost invisible in a
    # 1024px macOS icon. Modern Pillow can size its bundled default font, so
    # keep the mark legible even on an unexpected build runner.
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1; release builds use a newer version.
        return ImageFont.load_default()


def draw_icon(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    pad = max(1, size // 32)
    radius = size * 22 // 100
    draw.rounded_rectangle((pad, pad, size - 1 - pad, size - 1 - pad), radius=radius, fill=NAVY)
    ring = max(2, size // 28)
    inset = size * 18 // 100
    draw.ellipse((inset, inset - size // 18, size - inset, size - inset - size // 10), outline=GOLD, width=ring)
    letter = _font(max(12, size * 42 // 100))
    text = "K"
    box = draw.textbbox((0, 0), text, font=letter)
    tw, th = box[2] - box[0], box[3] - box[1]
    x = (size - tw) / 2 - box[0]
    y = (size - th) / 2 - box[1] + size // 18
    draw.text((x, y), text, font=letter, fill=GOLD_2)
    if size >= 128:
        small = _font(max(8, size * 7 // 100))
        label = "KRELUNA"
        box = draw.textbbox((0, 0), label, font=small)
        lw = box[2] - box[0]
        draw.text(((size - lw) / 2 - box[0], size * 78 // 100), label, font=small, fill=INK)
    return img.filter(ImageFilter.SMOOTH)


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def write_icns(path: Path, master: Image.Image) -> None:
    # PNG-in-ICNS types used by modern macOS Finder.
    specs = {
        "ic04": 16,
        "ic05": 32,
        "ic07": 128,
        "ic08": 256,
        "ic09": 512,
        "ic10": 1024,
        "ic11": 32,
        "ic12": 64,
        "ic13": 256,
        "ic14": 512,
    }
    chunks: list[bytes] = []
    for ostype, size in specs.items():
        payload = _png(master.resize((size, size), Image.Resampling.LANCZOS))
        chunks.append(ostype.encode("ascii") + struct.pack(">I", 8 + len(payload)) + payload)
    body = b"".join(chunks)
    path.write_bytes(b"icns" + struct.pack(">I", 8 + len(body)) + body)


def main() -> None:
    master = draw_icon(1024)
    macos = ROOT / "packaging" / "macos"
    macos.mkdir(parents=True, exist_ok=True)
    png_path = macos / "AppIcon.png"
    icns_path = macos / "AppIcon.icns"
    master.save(png_path)
    write_icns(icns_path, master)

    public = ROOT / "apps" / "director-web" / "public"
    public.mkdir(parents=True, exist_ok=True)
    master.resize((180, 180), Image.Resampling.LANCZOS).save(public / "apple-touch-icon.png")
    master.resize((32, 32), Image.Resampling.LANCZOS).save(public / "favicon.png")
    print(png_path)
    print(icns_path)


if __name__ == "__main__":
    main()
