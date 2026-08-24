"""Finestra gestionale visibile: mouse, campi, testo. Stand-in di Webdesk / sito Agenzia delle Entrate."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import json
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

from kreluna_shared.crypto import sha256_hex

NAVY = (16, 24, 40)
PANEL = (236, 232, 222)
INK = (22, 28, 38)
GOLD = (196, 154, 42)
WHITE = (252, 250, 246)
CURSOR = (20, 20, 20)


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    names = (
        ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"),
        ("LiberationSans-Bold.ttf" if bold else "LiberationSans-Regular.ttf"),
    )
    roots = [
        Path("/usr/share/fonts/truetype/dejavu"),
        Path("/usr/share/fonts/truetype/liberation"),
        Path("C:/Windows/Fonts"),
    ]
    for root in roots:
        for name in names:
            path = root / name
            if path.exists():
                return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def _pointer(draw: ImageDraw.ImageDraw, x: int, y: int) -> None:
    pts = [(x, y), (x, y + 18), (x + 5, y + 14), (x + 10, y + 22), (x + 12, y + 20), (x + 6, y + 12), (x + 14, y + 12)]
    draw.polygon(pts, fill=CURSOR, outline=(255, 255, 255))


def _field(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], label: str, value: str, focus: bool) -> None:
    x1, y1, x2, y2 = box
    draw.text((x1, y1 - 22), label, fill=(90, 96, 108), font=_font(13))
    draw.rounded_rectangle(box, radius=8, fill=WHITE, outline=GOLD if focus else (186, 180, 168), width=2 if focus else 1)
    draw.text((x1 + 12, y1 + 10), value, fill=INK, font=_font(16))
    if focus and value:
        tw = draw.textlength(value, font=_font(16))
        cx = int(x1 + 14 + tw)
        draw.line((cx, y1 + 8, cx, y2 - 8), fill=GOLD, width=2)


def render_invoice_window(
    *,
    client: str,
    description: str,
    net_label: str,
    vat_label: str,
    total_label: str,
    status: str,
    typed_client: str,
    typed_desc: str,
    typed_net: str,
    focus: str,
    pointer: tuple[int, int],
    subtitle: str,
) -> bytes:
    width, height = 1100, 720
    image = Image.new("RGB", (width, height), (48, 56, 68))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((40, 36, 1060, 684), radius=16, fill=PANEL)
    draw.rounded_rectangle((40, 36, 1060, 92), radius=16, fill=NAVY)
    draw.rectangle((40, 76, 1060, 92), fill=NAVY)
    draw.text((64, 52), "Webdesk / AdE  ·  PC-FATTURE (demo)", fill=(244, 239, 228), font=_font(18, bold=True))
    draw.ellipse((1008, 54, 1024, 70), fill=(224, 90, 80))
    draw.text((64, 112), "Nuova fattura", fill=INK, font=_font(26, bold=True))
    draw.text((64, 148), subtitle, fill=(90, 96, 108), font=_font(14))

    fields = {
        "client": (64, 210, 620, 258),
        "desc": (64, 310, 1030, 358),
        "net": (64, 410, 360, 458),
        "iva": (390, 410, 620, 458),
        "total": (650, 410, 1030, 458),
    }
    _field(draw, fields["client"], "Cliente", typed_client, focus == "client")
    _field(draw, fields["desc"], "Prestazione", typed_desc, focus == "desc")
    _field(draw, fields["net"], "Imponibile", typed_net, focus == "net")
    _field(draw, fields["iva"], "IVA 22%", vat_label if typed_net else "", focus == "iva")
    _field(draw, fields["total"], "Totale", total_label if typed_net else "", focus == "total")

    save = (64, 520, 280, 572)
    emit = (300, 520, 560, 572)
    draw.rounded_rectangle(save, radius=10, fill=NAVY)
    draw.text((92, 534), "Salva bozza", fill=(244, 239, 228), font=_font(16, bold=True))
    draw.rounded_rectangle(emit, radius=10, fill=(210, 210, 210) if status != "issued" else GOLD)
    draw.text((338, 534), "Emetti (bloccato)" if status != "issued" else "Emessa", fill=INK, font=_font(16, bold=True))
    draw.text((64, 600), "Il mouse e la digitazione sono sul PC-FATTURE. Nessun invio all'Agenzia.", fill=(90, 96, 108), font=_font(13))
    _pointer(draw, pointer[0], pointer[1])
    buf = BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def show_invoice_on_this_mac(
    *,
    client_name: str,
    description: str,
    net_eur: float,
) -> bool:
    if sys.platform != "darwin":
        return False
    script = Path(__file__).resolve().parent / "mac_gestionale_ui.py"
    if not script.exists():
        return False
    payload = json.dumps(
        {"client_name": client_name, "description": description, "net_eur": net_eur},
        ensure_ascii=False,
    )
    try:
        subprocess.Popen(  # noqa: S603
            [sys.executable, str(script), payload],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except OSError:
        return False


def fill_invoice_on_pc(
    *,
    client_name: str,
    description: str,
    net_eur: float,
    vat_rate: float = 0.22,
    status: str = "draft",
) -> list[dict]:
    vat = round(net_eur * vat_rate, 2)
    total = round(net_eur + vat, 2)
    net_label = f"€ {net_eur:,.2f}"
    vat_label = f"€ {vat:,.2f}"
    total_label = f"€ {total:,.2f}"
    opened = show_invoice_on_this_mac(
        client_name=client_name,
        description=description,
        net_eur=net_eur,
    )
    frames = [
        {
            "typed_client": "",
            "typed_desc": "",
            "typed_net": "",
            "focus": "client",
            "pointer": (90, 230),
            "subtitle": "Apro Webdesk / sito AdE (demo) sul PC-FATTURE…",
        },
        {
            "typed_client": client_name[: max(1, len(client_name) // 2)],
            "typed_desc": "",
            "typed_net": "",
            "focus": "client",
            "pointer": (180, 236),
            "subtitle": "Scrivo il cliente con la tastiera.",
        },
        {
            "typed_client": client_name,
            "typed_desc": description,
            "typed_net": net_label,
            "focus": "net",
            "pointer": (140, 430),
            "subtitle": "Compilo imponibile, IVA e totale.",
        },
        {
            "typed_client": client_name,
            "typed_desc": description,
            "typed_net": net_label,
            "focus": "save",
            "pointer": (160, 540),
            "subtitle": "Bozza pronta. Aspetto la tua conferma prima di emettere.",
        },
    ]
    if status == "issued":
        frames.append(
            {
                "typed_client": client_name,
                "typed_desc": description,
                "typed_net": net_label,
                "focus": "emit",
                "pointer": (380, 540),
                "subtitle": "Hai approvato. Stato DEMO: EMESSA. Nessun invio fiscale reale.",
            }
        )
    evidence = []
    for index, frame in enumerate(frames, start=1):
        png = render_invoice_window(
            client=client_name,
            description=description,
            net_label=net_label,
            vat_label=vat_label,
            total_label=total_label,
            status=status if index == len(frames) else "draft",
            **frame,
        )
        evidence.append(
            {
                "kind": "screenshot",
                "sha256": sha256_hex(png),
                "png": png,
                "metadata": {
                    "window": "Gestionale Fatture",
                    "step": index,
                    "program": "gestionale-fatture-demo",
                    "mouse": True,
                    "typing": True,
                    "live_window": opened,
                    "status": status if index == len(frames) else "draft",
                },
            }
        )
    return evidence
