import math
import re
import zipfile

import cv2
import pytest
from docx import Document
from pptx import Presentation

from lectura.exporters import Page, unique_path
from lectura.exporters.docx_export import export_docx
from lectura.exporters.pdf_export import export_pdf
from lectura.exporters.pptx_export import export_pptx
from tests import synth


@pytest.fixture
def pages(tmp_path):
    out = []
    for i in range(5):
        img = synth.slide(i + 1, 3) if i % 2 == 0 else synth.board(synth.strokes(8, seed=i))
        p = tmp_path / f"{i + 1:04d}.png"
        cv2.imwrite(str(p), img)
        out.append(Page(p, f"10:{i:02d} AM  ·  00:0{i}:00 into class"))
    return out


def test_pptx_one_slide_per_capture(pages, tmp_path):
    out = export_pptx(pages, tmp_path / "c.pptx", title="Class")
    prs = Presentation(str(out))
    assert len(prs.slides) == 5
    for s in prs.slides:
        pics = [sh for sh in s.shapes if sh.shape_type == 13]
        assert len(pics) == 1
    # 16:9 image area + caption strip
    assert prs.slide_width > prs.slide_height


def test_pptx_without_captions_is_exact_aspect(pages, tmp_path):
    for p in pages:
        p.caption = ""
    prs = Presentation(str(export_pptx(pages, tmp_path / "c.pptx")))
    assert abs(prs.slide_width / prs.slide_height - 16 / 9) < 0.01


def test_docx_two_per_page(pages, tmp_path):
    out = export_docx(pages, tmp_path / "c.docx", title="Class")
    doc = Document(str(out))
    assert len(doc.inline_shapes) == 5
    with zipfile.ZipFile(out) as z:
        xml = z.read("word/document.xml").decode()
    assert xml.count('w:type="page"') == math.ceil(5 / 2) - 1
    sec = doc.sections[0]
    assert sec.page_height > sec.page_width  # portrait


def test_pdf_two_per_page(pages, tmp_path):
    out = export_pdf(pages, tmp_path / "c.pdf", title="Class")
    data = out.read_bytes()
    n_pages = len(re.findall(rb"/Type\s*/Page[^s]", data))
    assert n_pages == math.ceil(5 / 2)
    assert data.count(b"/Subtype /Image") == 5


def test_unique_path(tmp_path):
    p = tmp_path / "Class.pdf"
    assert unique_path(p) == p
    p.write_text("x")
    assert unique_path(p).name == "Class (2).pdf"
