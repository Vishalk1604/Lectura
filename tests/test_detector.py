import numpy as np
import pytest

from lectura.detector import CapturePipeline, SlideChangeDetector
from tests import synth

DT = 0.5  # 2 samples per second


class Clock:
    def __init__(self):
        self.t = 0.0


def run(pipe: CapturePipeline, frames, clock: Clock, seconds: float, fx=None):
    """Feed `frames` (a single image or a callable t -> image) for `seconds`."""
    caps = []
    steps = int(round(seconds / DT))
    for _ in range(steps):
        img = frames(clock.t) if callable(frames) else frames
        if fx:
            img = fx(img, clock.t)
        caps += pipe.feed(img, clock.t)
        clock.t += DT
    return caps


def similar(a: np.ndarray, b: np.ndarray, tol: float = 0.01) -> bool:
    if a.shape != b.shape:
        return False
    return (np.abs(a.astype(int) - b.astype(int)) > 30).mean() < tol


def test_bullet_build_gives_one_capture_with_all_bullets():
    pipe, c = CapturePipeline(), Clock()
    caps = []
    for n in (1, 2, 3):
        caps += run(pipe, synth.slide(1, n), c, 4)
    assert caps == []
    caps += run(pipe, synth.slide(2, 3), c, 4)
    assert len(caps) == 1
    assert similar(caps[0].image, synth.slide(1, 3))
    final = pipe.finish()
    assert final is not None and similar(final.image, synth.slide(2, 3))


def test_whiteboard_writing_then_page_clear():
    pipe, c = CapturePipeline(), Clock()
    st = synth.strokes(30, seed=1)
    caps = []
    # write a stroke per sample (60 samples) with pauses every 10 samples
    for i in range(30):
        caps += run(pipe, synth.board(st[: i + 1]), c, DT)
        if i % 10 == 9:
            caps += run(pipe, synth.board(st[: i + 1]), c, 3)
    assert caps == [], "nothing should be captured while writing"
    caps += run(pipe, synth.board([]), c, 4)  # new blank page
    assert len(caps) == 1
    assert similar(caps[0].image, synth.board(st))
    caps += run(pipe, synth.board(synth.strokes(4, seed=9)), c, 4)
    final = pipe.finish()
    assert final is not None  # second page has content


def test_small_erase_does_not_capture():
    pipe, c = CapturePipeline(), Clock()
    st = synth.strokes(24, seed=2)
    caps = run(pipe, synth.board(st), c, 4)
    erased = st[:10] + st[11:]  # rub out one stroke
    caps += run(pipe, synth.board(erased), c, 4)
    caps += run(pipe, synth.board(erased + synth.strokes(3, seed=5, top=400)), c, 4)
    assert caps == []
    assert pipe.finish() is not None


def test_tiny_page_erase_of_single_word_is_ignored():
    pipe, c = CapturePipeline(), Clock()
    caps = run(pipe, synth.board(synth.strokes(1, seed=3)), c, 4)
    caps += run(pipe, synth.board([]), c, 4)
    assert caps == []


def _scrolled(img: np.ndarray, dy: int, bg=250) -> np.ndarray:
    out = np.full_like(img, bg)
    out[: img.shape[0] - dy] = img[dy:]
    return out


def test_scroll_hiding_most_writing_captures_once():
    pipe, c = CapturePipeline(), Clock()
    page = synth.board(synth.strokes(36, seed=4))
    caps = run(pipe, page, c, 4)
    caps += run(pipe, _scrolled(page, int(0.7 * synth.H)), c, 4)
    assert len(caps) == 1
    assert similar(caps[0].image, page)


def test_small_scroll_of_blank_margin_does_not_capture():
    pipe, c = CapturePipeline(), Clock()
    page = synth.board(synth.strokes(12, seed=6, top=200))  # writing starts lower down
    caps = run(pipe, page, c, 4)
    caps += run(pipe, _scrolled(page, 60), c, 4)
    assert caps == []


def test_cursor_and_webcam_over_static_slide_never_capture():
    pipe, c = CapturePipeline(), Clock()
    base = synth.slide(3, 3)
    caps = run(pipe, lambda t: synth.with_webcam(synth.with_cursor(base, t), t), c, 30)
    assert caps == []
    assert pipe.detector.moving_fraction > 0  # webcam area learned as moving
    caps += run(pipe, lambda t: synth.with_webcam(synth.with_cursor(synth.slide(4, 3), t), t), c, 6)
    assert len(caps) == 1
    # the committed image is slide 3 (webcam corner aside)
    assert similar(caps[0].image[:400], base[:400])


def test_compression_noise_is_tolerated():
    pipe, c = CapturePipeline(), Clock()
    caps = run(pipe, synth.slide(1, 3), c, 10, fx=synth.noisy)
    assert caps == []
    caps += run(pipe, synth.slide(2, 3), c, 4, fx=synth.noisy)
    assert len(caps) == 1


def test_revisited_slide_is_deduplicated():
    pipe, c = CapturePipeline(), Clock()
    caps = []
    for sid in (1, 2, 1, 3):
        caps += run(pipe, synth.slide(sid, 3), c, 4)
    last = pipe.finish()
    caps.append(last)
    assert len(caps) == 3  # slide 1, slide 2, slide 3 (revisit of 1 dropped)
    assert similar(caps[0].image, synth.slide(1, 3))
    assert similar(caps[1].image, synth.slide(2, 3))
    assert similar(caps[2].image, synth.slide(3, 3))


def test_revisit_with_partial_build_is_deduplicated():
    pipe, c = CapturePipeline(), Clock()
    caps = run(pipe, synth.slide(1, 3), c, 4)
    caps += run(pipe, synth.slide(2, 3), c, 4)
    caps += run(pipe, synth.slide(1, 1), c, 4)  # back to slide 1, only first bullet shown
    caps += run(pipe, synth.slide(5, 3), c, 4)
    assert len(caps) == 2


def test_fade_transition_frames_are_never_saved():
    pipe, c = CapturePipeline(), Clock()
    a, b = synth.slide(1, 3), synth.slide(2, 3)
    caps = run(pipe, a, c, 4)
    for k in np.linspace(0.15, 0.85, 6):
        caps += run(pipe, synth.blend(a, b, k), c, DT)
    caps += run(pipe, b, c, 4)
    caps.append(pipe.finish())
    assert len(caps) == 2
    assert similar(caps[0].image, a) and similar(caps[1].image, b)


def test_background_colour_change_is_a_new_slide():
    pipe, c = CapturePipeline(), Clock()
    caps = run(pipe, synth.slide(1, 3), c, 4)
    caps += run(pipe, synth.slide(1, 3, bg=(40, 30, 30), fg=(240, 240, 240)), c, 4)
    assert len(caps) == 1


def test_letterboxed_frames_are_trimmed():
    pipe, c = CapturePipeline(), Clock()
    content = synth.slide(1, 3)  # 16:9
    frame = np.zeros((900, 1280, 3), np.uint8)  # black bars top/bottom
    frame[90:810] = content
    run(pipe, frame, c, 4)
    cap = pipe.finish()
    assert cap.image.shape[:2] == (720, 1280)


def test_force_capture_returns_latest_frame():
    pipe, c = CapturePipeline(), Clock()
    run(pipe, synth.slide(1, 2), c, 1)
    cap = pipe.force()
    assert cap is not None and cap.forced
    assert similar(cap.image, synth.slide(1, 2))


@pytest.mark.parametrize("s", [0.0, 1.0])
def test_extreme_sensitivities_still_separate_distinct_slides(s):
    pipe, c = CapturePipeline(sensitivity=s), Clock()
    caps = []
    for sid in (1, 2, 3):
        caps += run(pipe, synth.slide(sid, 3), c, 4)
    assert len(caps) == 2


def test_resize_of_crop_commits_previous_page():
    det = SlideChangeDetector()
    t = 0.0
    out = []
    for _ in range(8):
        out += det.feed(synth.slide(1, 3), t); t += DT
    for _ in range(8):
        out += det.feed(synth.slide(1, 3, w=1024, h=768), t); t += DT
    assert len(out) == 1
