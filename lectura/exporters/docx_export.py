"""Word: two captures per portrait page, caption under each."""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.shared import Cm, Pt, RGBColor

from . import PAGE_SIZES_CM, Page, two_up_layout

MARGIN_CM = 1.5
CAPTION_CM = 0.8
GAP_CM = 0.9


def export_docx(pages: list[Page], out: Path, title: str = "", page_size: str = "A4",
                progress=None) -> Path:
    doc = Document()
    pw, ph = PAGE_SIZES_CM.get(page_size, PAGE_SIZES_CM["A4"])
    sec = doc.sections[0]
    sec.orientation = WD_ORIENT.PORTRAIT
    sec.page_width, sec.page_height = Cm(pw), Cm(ph)
    for side in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(sec, side, Cm(MARGIN_CM))
    sec.header_distance = Cm(0.6)
    sec.footer_distance = Cm(0.6)
    doc.core_properties.title = title

    if title:
        hp = sec.header.paragraphs[0]
        hp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = hp.add_run(title)
        r.font.size = Pt(8)
        r.font.color.rgb = RGBColor(0x80, 0x80, 0x80)

    normal = doc.styles["Normal"]
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.space_after = Pt(0)

    has_caption = any(p.caption for p in pages)
    body = doc.paragraphs[0] if doc.paragraphs else None
    first = True
    for i, page in enumerate(pages):
        w_px, h_px = page.size()
        img_w, img_h = two_up_layout(pw, ph, w_px / h_px, MARGIN_CM,
                                     CAPTION_CM if has_caption else 0.0, GAP_CM)
        p = body if (first and body is not None) else doc.add_paragraph()
        first = False
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        if i % 2 == 1:
            p.paragraph_format.space_before = Cm(GAP_CM)
        p.paragraph_format.keep_with_next = True
        p.add_run().add_picture(str(page.path), width=Cm(img_w), height=Cm(img_h))
        last_on_page = (i % 2 == 1) or (i == len(pages) - 1)
        target = p
        if has_caption:
            cp = doc.add_paragraph()
            cp.alignment = WD_ALIGN_PARAGRAPH.CENTER
            cp.paragraph_format.space_before = Pt(3)
            r = cp.add_run(f"{i + 1}  ·  {page.caption}" if page.caption else f"{i + 1}")
            r.font.size = Pt(8.5)
            r.italic = True
            r.font.color.rgb = RGBColor(0x60, 0x60, 0x60)
            target = cp
        if last_on_page and i != len(pages) - 1:
            target.add_run().add_break(WD_BREAK.PAGE)
        if progress:
            progress(i + 1, len(pages))
    doc.save(str(out))
    return out
