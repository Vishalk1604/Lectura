import numpy as np
import pytest

from lectura.autocrop import (detect_content_rect, find_letterbox, from_fraction,
                              to_fraction, trim_uniform_border)
from lectura.dedupe import Deduper, is_blank
from tests import synth


def close(a, b, tol=6):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def test_detects_presentation_in_meet_layout_16_9():
    frame, expected = synth.meet_layout(synth.slide(1, 3))
    got = detect_content_rect(frame)
    assert close(got, expected), (got, expected)


def test_detects_presentation_in_meet_layout_4_3():
    frame, expected = synth.meet_layout(synth.slide(2, 3, w=1024, h=768))
    got = detect_content_rect(frame)
    assert close(got, expected), (got, expected)


def test_detects_whiteboard_in_meet_layout():
    frame, expected = synth.meet_layout(synth.board(synth.strokes(10, seed=1)))
    got = detect_content_rect(frame)
    assert close(got, expected), (got, expected)


def test_slide_box_on_light_web_page():
    page = np.full((1000, 1600, 3), 245, np.uint8)
    page[:90] = 225  # browser toolbar
    page[90:150] = 255  # site header
    page[150:152] = 200
    s = synth.slide(3, 3, w=1120, h=630, bg=(255, 255, 255))
    page[220:850, 60:1180] = s
    page[218:220, 58:1182] = 120  # slide border
    page[850:852, 58:1182] = 120
    page[218:852, 58:60] = 120
    page[218:852, 1180:1182] = 120
    page[220:850, 1220:1560] = 230  # chat sidebar
    got = detect_content_rect(page)
    assert close(got, (60, 220, 1120, 630), tol=8), got


def test_small_presentation_tile_beats_whole_page():
    """Narrow presentation tile with tall letterbox bars, participant tiles beside it."""
    frame = np.full((943, 1586, 3), (36, 33, 32), np.uint8)
    frame[:76] = (45, 45, 45)
    frame[76:79] = (229, 70, 79)  # coloured line under the toolbar
    frame[96:937, 21:566] = 0     # black tile
    s = synth.slide(1, 3, w=545, h=306)
    frame[363:669, 21:566] = s    # centred in the tile, like real letterboxing
    rng = np.random.default_rng(1)
    for top in (96, 292, 488):
        tile = rng.integers(40, 200, (180, 320, 3), dtype=np.uint8)
        frame[top:top + 180, 590:910] = tile
    got = detect_content_rect(frame)
    assert close(got, (21, 363, 545, 306), tol=8), got


@pytest.mark.parametrize("dim", [1.0, 0.55])
def test_slide_with_coloured_footer_keeps_the_footer(dim):
    """A slide whose bottom band is a different colour (theme footer) must not be cut off."""
    import cv2
    s = synth.slide(1, 3)
    s[-26:] = (229, 70, 79)  # purple footer bar
    frame, expected = synth.meet_layout(s)
    frame = (frame.astype(np.float32) * dim).astype(np.uint8)
    got = detect_content_rect(frame)
    assert close(got, expected), (got, expected)


@pytest.mark.parametrize("dim", [1.0, 0.55, 0.4])
def test_real_simulator_window_is_cropped_exactly(dim):
    """Captured Edge window of tools/class_sim.html: slide with a purple footer bar,
    letterboxed in a dark Meet-like page with participant tiles beside it."""
    from pathlib import Path

    import cv2
    f = cv2.imread(str(Path(__file__).parent / "fixtures" / "sim_window_slide1.png"))
    f = (f.astype(np.float32) * dim).astype(np.uint8)
    assert close(detect_content_rect(f), (17, 137, 1208, 681), tol=2)


def test_no_rectangle_returns_full_frame():
    flat = np.full((600, 800, 3), 128, np.uint8)
    assert detect_content_rect(flat) == (0, 0, 800, 600)


def test_letterbox_trim_symmetric_black_bars():
    content = synth.slide(1, 3)
    frame = np.zeros((720, 1280 + 2 * 160, 3), np.uint8)
    frame[:, 160:1440] = content
    assert find_letterbox(frame) == (160, 0, 1280, 720)


def test_letterbox_trim_leaves_whiteboard_alone():
    wb = synth.board(synth.strokes(5, seed=2))  # lots of white margin
    assert trim_uniform_border(wb).shape == wb.shape


def test_letterbox_trim_leaves_blackboard_alone():
    bb = synth.board(synth.strokes(5, seed=2), bg=(20, 20, 20), ink=(240, 240, 240))
    assert trim_uniform_border(bb).shape == bb.shape


def test_fraction_roundtrip():
    r = (100, 50, 640, 360)
    assert from_fraction(to_fraction(r, 1600, 1000), 1600, 1000) == r
    # rescales with the window
    assert from_fraction(to_fraction(r, 1600, 1000), 800, 500) == (50, 25, 320, 180)


def test_blank_detection():
    assert is_blank(np.full((720, 1280, 3), 255, np.uint8))
    assert is_blank(synth.noisy(np.full((720, 1280, 3), 30, np.uint8), 1.0, amp=4))
    assert not is_blank(synth.slide(1, 1))
    assert not is_blank(synth.board(synth.strokes(3)))


def _thin_board(n=12, dim=1.0, w=1920, h=1080):
    """Full-HD whiteboard with thin (2 px) pen strokes, optionally dimmed."""
    import cv2
    img = np.full((h, w, 3), 250, np.uint8)
    for s in synth.strokes(n, seed=7, w=w, h=h, top=400):
        cv2.polylines(img, [s], False, (40, 20, 20), 2, cv2.LINE_AA)
    return (img.astype(np.float32) * dim).astype(np.uint8)


def test_thin_pen_strokes_are_not_blank():
    assert not is_blank(_thin_board())


def test_thin_dimmed_pen_strokes_are_not_blank():
    assert not is_blank(_thin_board(dim=0.55))


def test_thin_whiteboard_pages_are_not_duplicates_of_each_other():
    d = Deduper()
    d.add(_thin_board(12))
    import cv2
    other = np.full((1080, 1920, 3), 250, np.uint8)
    for s in synth.strokes(12, seed=99, w=1920, h=1080, top=100):
        cv2.polylines(other, [s], False, (40, 20, 20), 2, cv2.LINE_AA)
    assert not d.is_redundant(other)


def test_deduper_identical_and_different():
    d = Deduper()
    d.add(synth.slide(1, 3))
    assert d.is_redundant(synth.noisy(synth.slide(1, 3), 2.0))
    assert d.is_redundant(synth.slide(1, 2))      # subset of an earlier capture
    assert not d.is_redundant(synth.slide(2, 3))
    assert not d.is_redundant(synth.slide(1, 4))  # adds a bullet
