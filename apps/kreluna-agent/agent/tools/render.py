from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw, ImageFont


def render_card(title: str, lines: list[str], accent: tuple[int, int, int] = (212, 175, 55)) -> bytes:
    width, height = 1100, 700
    image = Image.new("RGB", (width, height), (11, 18, 32))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width, 88), fill=(16, 27, 48))
    draw.rectangle((0, 88, width, 92), fill=accent)
    font_title = ImageFont.load_default()
    font = ImageFont.load_default()
    draw.text((36, 32), title, fill=(245, 237, 214), font=font_title)
    y = 130
    for line in lines:
        draw.text((40, y), line, fill=(226, 220, 204), font=font)
        y += 28
        if y > height - 40:
            break
    buf = BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()
