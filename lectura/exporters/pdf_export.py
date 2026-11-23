"""PDF: two captures per portrait page with captions; images embedded losslessly."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.colors import Color
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas

from . import PAGE_SIZES_CM, Page, two_up_layout

MARGIN_CM = 1.5
CAPTION_CM = 0.8
GAP_CM = 0.9


def export_pdf(pages: list[Page], out: Path, title: str = "", page_size: str = "A4",
               progress=None) -> Path:
    pw, ph = PAGE_SIZES_CM.get(page_size, PAGE_SIZES_CM["A4"])
    c = canvas.Canvas(str(out), pagesize=(pw * cm, ph * cm), pageCompression=1)
    c.setTitle(title or "Class captures")
    c.setCreator("Lectura")
    has_caption = any(p.caption for p in pages)
    cap_h = CAPTION_CM if has_caption else 0.0
    slot_h = (ph - 2 * MARGIN_CM - GAP_CM) / 2  # each half of the page, incl. caption

    for i, page in enumerate(pages):
        slot = i % 2
        if slot == 0 and i > 0:
            c.showPage()
        if slot == 0 and title:
            c.setFont("Helvetica", 7.5)
            c.setFillColor(Color(0.5, 0.5, 0.5))
            c.drawCentredString(pw * cm / 2, (ph - 0.9) * cm, title)
        w_px, h_px = page.size()
        img_w, img_h = two_up_layout(pw, ph, w_px / h_px, MARGIN_CM, cap_h, GAP_CM)
        top = ph - MARGIN_CM - slot * (slot_h + GAP_CM)  # top of this slot (cm from bottom)
        x = (pw - img_w) / 2
        y = top - img_h
        c.drawImage(str(page.path), x * cm, y * cm, img_w * cm, img_h * cm)
        c.setStrokeColor(Color(0.82, 0.82, 0.82))
        c.setLineWidth(0.5)
        c.rect(x * cm, y * cm, img_w * cm, img_h * cm, stroke=1, fill=0)
        if has_caption:
            c.setFont("Helvetica-Oblique", 8.5)
            c.setFillColor(Color(0.38, 0.38, 0.38))
            text = f"{i + 1}  ·  {page.caption}" if page.caption else f"{i + 1}"
            c.drawCentredString(pw * cm / 2, (y - 0.5) * cm, text)  # "·" is in WinAnsi
        if progress:
            progress(i + 1, len(pages))
    c.save()
    return out
