"""PowerPoint: one capture per slide, full width, timestamp strip underneath."""

from __future__ import annotations

from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Emu, Inches, Pt

from . import Page

SLIDE_W_IN = 13.333
STRIP_IN = 0.32


def export_pptx(pages: list[Page], out: Path, title: str = "", progress=None) -> Path:
    prs = Presentation()
    w0, h0 = pages[0].size()
    aspect = w0 / h0
    has_caption = any(p.caption for p in pages)
    slide_w = Inches(SLIDE_W_IN)
    img_h = int(slide_w / aspect)
    slide_h = img_h + (Inches(STRIP_IN) if has_caption else 0)
    prs.slide_width, prs.slide_height = slide_w, Emu(slide_h)
    prs.core_properties.title = title
    blank = prs.slide_layouts[6]

    for i, page in enumerate(pages):
        slide = prs.slides.add_slide(blank)
        bg = slide.background.fill
        bg.solid()
        bg.fore_color.rgb = RGBColor(0, 0, 0)
        pw, ph = page.size()
        # fit inside the image area, centred (pages from a resized crop may differ)
        scale = min(slide_w / pw, img_h / ph)
        w, h = int(pw * scale), int(ph * scale)
        slide.shapes.add_picture(str(page.path), (slide_w - w) // 2, (img_h - h) // 2, w, h)
        if has_caption and page.caption:
            box = slide.shapes.add_textbox(0, img_h, slide_w, Inches(STRIP_IN))
            tf = box.text_frame
            tf.margin_top = tf.margin_bottom = Inches(0.03)
            tf.margin_right = Inches(0.15)
            para = tf.paragraphs[0]
            para.alignment = PP_ALIGN.RIGHT
            run = para.add_run()
            run.text = f"{i + 1}  ·  {page.caption}"
            run.font.size = Pt(11)
            run.font.color.rgb = RGBColor(0xC8, 0xC8, 0xC8)
        if progress:
            progress(i + 1, len(pages))
    prs.save(str(out))
    return out
