# AutoPPT — automatic class-slide capture app (Windows)

## Context
You attend online classes where teachers either screen-share in Google Classroom/Meet or present slides live on websites like Kiteroom, and some write on a digital whiteboard. You want a desktop app that watches **one chosen window**, takes a screenshot **only when the slide/page actually changes** (not while the teacher is still writing), crops to the shared area, and when you stop, lets you review and save everything as **PPTX, DOCX or PDF** wherever you choose.

`D:\PROJECT\AutoPPT` is empty, so this is a new project. The machine has Python 3.12 (with python-pptx, python-docx and Pillow already installed) and Node 24; there is no .NET SDK.

### Decisions from the interview
| Topic | Decision |
|---|---|
| Class window | Kept open behind other apps or on a second monitor (never minimized) |
| Slide builds | Final version only: capture just before the slide changes |
| Revisited slides | Skip near-duplicates of earlier captures |
| Crop | Auto-detect the shared area, show it as a box you can drag to adjust, remember it per site |
| After Stop | Thumbnail review (delete, reorder, enlarge), then the save dialog |
| Word/PDF layout | Always 2 screenshots per portrait page (PPT: 1 per slide) |
| Extras | Capture-now global hotkey, pause/resume, timestamp captions, sensitivity slider |
| Whiteboard moves on by | A new blank page or scrolling down (a small erase must NOT trigger) |
| Webcam bubble | Sometimes, so areas with constant motion are ignored automatically |
| Image quality | Lossless PNG |
| Launch | A single `AutoPPT.exe` built with PyInstaller |

## Tech stack
- **Python 3.12** in a project `.venv`
- **PySide6-Essentials** (GUI), **numpy** and **opencv-python-headless** (frame analysis)
- **windows-capture** (Windows Graphics Capture: it captures a window even when other windows cover it). Fallback: `PrintWindow(PW_RENDERFULLCONTENT)` through **pywin32**.
- **python-pptx**, **python-docx**, **reportlab** (PDF with lossless images and captions)
- **pytest**, **PyInstaller**

## Project layout
```
autoppt/
  __main__.py          entry point (python -m autoppt); sets per-monitor DPI awareness
  settings.py          JSON in %APPDATA%\AutoPPT\settings.json (sensitivity, hotkey, crop per site, last folder, page size A4)
  winlist.py           list visible top-level windows (title, process, HWND, thumbnail); IsWindow/IsIconic checks
  capture.py           CaptureSource interface; WgcSource (windows-capture, by HWND, border off) + PrintWindowSource fallback
  detector.py          SlideChangeDetector (core logic, below)
  autocrop.py          detect_content_rect(frame), trim_uniform_border(img)
  dedupe.py            perceptual hash, near-duplicate check, blank-frame check
  session.py           session folder, PNG writes, session.json, crash recovery
  recorder.py          QThread worker: sample, crop, detect, commit, emit signals
  hotkey.py            global hotkey via Win32 RegisterHotKey + Qt native event filter (default Ctrl+Alt+S)
  exporters/pptx_export.py, docx_export.py, pdf_export.py
  ui/main_window.py    window picker, live preview, Start/Pause/Stop, sensitivity slider, capture counter, status line
  ui/crop_overlay.py   draggable/resizable crop rectangle on the preview, plus "Re-detect"
  ui/review_dialog.py  thumbnail grid (QListWidget icon mode): drag to reorder, Delete key, double-click to enlarge
  ui/save_dialog.py    format checkboxes (PPTX/DOCX/PDF, any combination), folder, filename, timestamp toggle
tests/                 test_detector.py, test_autocrop.py, test_exporters.py, test_dedupe.py
tools/class_sim.html   local fake-class page for end-to-end testing
requirements.txt, AutoPPT.spec, build.bat, README.md
```

## Core: change detection (`detector.py`)
The rule is **save the last settled frame of a page just before it gets replaced**. One rule covers slides, bullet builds and the whiteboard.

1. **Sampling:** 2 frames per second inside the crop. Analysis runs on a grayscale copy scaled down to about 480 px wide; the full-resolution frame is what gets saved.
2. **Auto-ignore moving areas (webcam bubble):** split the frame into 16×16 blocks. A block that changed in more than 60% of the last 20 samples (about 10 s) is masked out of every comparison. The mask decays once the block goes quiet.
3. **Settled:** a frame counts as settled when the unmasked area changed by less than about 0.3% for at least 1.5 s. A moving cursor stays under that limit. Fade transitions and embedded videos never settle, so they are skipped.
4. **Same page or new page:** compare each settled frame S with the current page frame P.
   - Content pixels of P are those that differ from P's background colour (the most common gray level) by more than 30.
   - `lost` is the share of P's content pixels that are gone in S.
   - `lost < L` (about 25%): same page, because ink or bullets were added or a small part was erased. P = S, so P always holds the fullest version.
   - `lost ≥ L`, or more than 40% of all pixels changed: new slide, new blank page or a scroll. **Commit P**, then P = S.
   - The sensitivity slider scales L and the settle threshold together.
5. **Commit:** skip blank frames (very low pixel spread) and near-duplicates of any earlier capture (perceptual-hash distance). Trim uniform letterbox borders, then save a PNG with its class timestamp.
6. **Stop** commits the final P. **The hotkey** force-commits the latest frame at once (only blank frames are dropped). **Pause** stops sampling; on resume, the next settled frame is compared with P as usual.
7. **Crash safety:** whenever P updates, it is also written to `pending.png`. This way a long whiteboard page is never lost.

## Auto-crop (`autocrop.py`)
- **On Start:** take one window frame, run Canny edges and contours, and keep large rectangles (>15% of the window, aspect ratio 1.2–2.1). Score them by area and how evenly their border contrasts with the surroundings, which picks the Meet presentation tile or the Kiteroom slide box over the browser toolbar and sidebars. If none qualifies, use the whole client area.
- The result appears as a box on the live preview. You can drag it or press Re-detect. The final box is saved as fractions of the window, keyed by process plus site (for example `chrome:meet.google.com`, matched from the window title), and is reused next time.
- **During capture:** if the window is resized, the box rescales automatically. Every saved image also gets its black or gray letterbox bars trimmed, which absorbs small layout shifts.

## Recording flow and window handling
- **Main window:** pick from the list of open windows (with thumbnails) → preview with crop box → Start.
- **While recording:** a status line shows "Recording · 12 captured · 00:42:10". The window can be minimized to the tray, and the hotkey works from any app.
- **If the class window is minimized:** the status shows "Paused – class window minimized" and capture resumes on its own when the window is restored.
- **If the window closes:** recording auto-stops and goes to review.
- **Session data** goes to `%LOCALAPPDATA%\AutoPPT\sessions\<date-time>\`: `0001.png` and onward, `session.json` (order, timestamps, deletions) and `pending.png`. If the app finds an unfinished session on launch, it offers "Recover last session", which opens the review screen.

## Review and save
- **Review grid:** delete, reorder by drag, enlarge, Continue.
- **Save dialog:** tick any of PPTX, DOCX and PDF. Choose the folder (remembered) and the file name (default `Class 2026-11-23 10-05`). The timestamp toggle defaults to on.
- **PPTX:** 1 image per slide, full-bleed. The slide size matches the crop's aspect ratio. The timestamp is a small text box in the bottom-right corner.
- **DOCX:** A4 portrait, 2 images per page. Each image is sized to fit both the width and half the usable height. Timestamp captions go under each image.
- **PDF:** the same 2-per-page layout through reportlab, with lossless PNGs and text captions.

## Build steps (in order)
1. Create the venv, write `requirements.txt` and install.
2. **Spike `capture.py`:** confirm that windows-capture can target an HWND, capture Chrome or Edge while another window covers it, and turn off the yellow border. If not, use PrintWindow.
3. Write `detector.py`, `dedupe.py` and `autocrop.py` with unit tests on synthetic numpy frames.
4. Write `session.py`, `recorder.py` and `hotkey.py`.
5. Build the UI: the main window, crop overlay, review and save dialogs.
6. Write the three exporters with tests.
7. Package with `AutoPPT.spec` and `build.bat` into `dist\AutoPPT.exe` (one file; it takes a few seconds to start).
8. Write a README covering usage and limits: don't minimize the class window, keep the class in its own browser window (only the visible tab is captured), and some DRM video players show black.

## Verification
- **Unit tests (`pytest`), synthetic sequences that must give exact capture counts:**
  - a 3-step bullet build, then a slide change: 1 capture with all bullets
  - whiteboard strokes over 60 samples, then a page clear: 1 capture with all strokes
  - a small erase in the middle of writing: no extra capture
  - scrolling 70%: 1 capture
  - a moving cursor and an animated webcam corner over a static slide: no captures
  - going back to slide 1 unchanged: deduped
  - fade transition frames: never saved
- **Auto-crop tests:** a synthetic Meet-like layout (dark background, presentation tile and participant tiles) must return the tile within a few px. The letterbox trim is tested as well.
- **Exporter tests:** reopen the PPTX and DOCX with python-pptx and python-docx to check image and page counts. Check the PDF page count is ceil(n/2).
- **End to end:** `tools/class_sim.html` has auto-advancing slides with bullet builds, an animated webcam bubble, a canvas whiteboard that draws strokes, does a small erase, then a new page and a scroll. Open it in its own Edge window with other windows on top, record with the app, and check that the captured count matches the script's expected count. Then export all three formats and open them.
- **Final check:** build `AutoPPT.exe`, run it from `dist\`, then you test it on a real Meet or Kiteroom class.

---

## Progress (session 1, 2026-11-23) and plan for the next session

The app is named **Lectura** (package `lectura/`, repo github.com/Vishalk1604/Lectura). Commits use your git identity with no Claude co-author line.

### Done
- `.venv` (Python 3.12) with every dependency installed. `opencv-python` replaced headless, because windows-capture needs it.
- Capture spike passed: windows-capture 2.0.1 by HWND (`draw_border=False`) and PrintWindow both captured an Edge window sitting behind other windows. WGC also captures your Firefox Meet window.
- `winlist.py`, `capture.py`, `detector.py`, `dedupe.py`, `autocrop.py`, `settings.py`, `session.py`, `hotkey.py` and `recorder.py` are written.
- UI is written (`ui/main_window.py`, `crop_view.py`, `review_dialog.py`, `save_dialog.py`, `style.py`) and the modules import, but it has never been launched.
- The PPTX, DOCX and PDF exporters are written.
- `tools/class_sim.html` (fake class) and `tools/e2e_sim.py` (headless recording plus export) exist.
- The app icon is generated by `tools/make_icon.py` into `assets/lectura.ico`.
- Tests: 33 of 34 pass. These cover the detector scenarios, Meet-layout auto-crop, letterbox trim, dedupe and the exporters.

### Known problems found
1. **Auto-crop on a narrow presentation tile:** `test_small_presentation_tile_beats_whole_page` fails because it returns the full frame. The black tile plus slide forms one tall component (aspect about 0.65), which the aspect filter rejects before letterbox trimming. **Fix:** in `detect_content_rect`, run `find_letterbox` on every candidate first, then score the inner rectangle. Keep the new "touches 3+ window edges → ×0.3" penalty.
2. **First E2E run gave 2 of 7 captures:**
   - The simulator window got minimized during the run (it popped up over your class), so the recorder paused.
   - Auto-crop ran before the page had finished re-laying out after the resize.
   - **Fix in `e2e_sim.py`:** launch an isolated Edge (`--user-data-dir=<scratch> --no-first-run --no-default-browser-check --new-window`), wait about 3 s after resizing before auto-crop, and never run it while you are in a class.

## Progress (session 2, 2026-11-23)

### Done
- **Auto-crop fixed.** Every candidate is letterbox-trimmed before the shape check, blended 1–2 px edges are ignored, and the "whole web page" area gets a ×0.12 penalty. In the real simulator window it now finds the exact 16:9 slide (1199×672).
- **Detector rebuilt around fine detail.**
  - "Content" now means text and ink strokes (morphological top-hats), so black bars and page background don't count. A loose crop still works.
  - Brightness is matched before comparing (a line fit, used only when it explains the frames better). A dimming popup or a brightness change is therefore neither a new page nor a missed duplicate.
  - Dedupe uses the same comparison.
- **Fully covered browsers confirmed.**
  - Edge stops drawing a fully covered window: both painting and JS timers freeze.
  - With `--disable-features=CalculateNativeWinOcclusion --disable-backgrounding-occluded-windows` it kept drawing for 30 of 30 covered seconds.
  - The recorder now shows a "window hidden" warning when the window is fully covered and no frame has arrived for 10 s (`winlist.covered_fraction`).
  - The README explains the browser settings. The Firefox setting has **not** been tested yet.
- **Debug tooling.** `LECTURA_DEBUG=1` writes every page decision to `<session>/debug.log`. `LECTURA_DUMP_FRAMES=<dir>` saves the sampled frames, and `tools/replay.py <dir>` replays them offline.
- **Packaging.**
  - `Lectura.spec`, `build.bat` and `run_lectura.py` added.
  - `dist\Lectura.exe` (107 MB, one file) starts in about 4–8 s, shows the UI, registers Ctrl+Alt+S, and closes cleanly.
  - The window picker has a hint text and a chevron arrow.
- **README.md** written.
- **Tests: 41 of 41 pass.** These include loose crops, dimming, thin-pen whiteboards, and narrow letterboxed tiles.
- **E2E fake class: 7 of 7 captures (PASS).** Replaying its 228 saved frames also gives 7 of 7 at sensitivity 0.2, 0.5 and 0.8, with dimming, and at 1 sample per second.

## Progress (session 3, 2026-11-23): UI walkthrough

### Done
- **`tools/ui_smoke.py`** drives the real Lectura window against the fake class. Settings, sessions and saved files all go to the out folder. It has three phases: `main`, `crash` and `recover`. These all **pass**:
  - picking the window, auto-detect, dragging a crop corner;
  - Start, Pause/Resume, the global Ctrl+Alt+S hotkey, Stop;
  - in review: Delete key, reorder plus renumbering, double-click viewer with arrow keys;
  - the save dialog saving all three formats, with your choices remembered;
  - the session marked as saved, with the review order kept.
- **Crash recovery passes.** Killing the app mid-class with 2 captures and a page in progress gave a relaunch prompt for "3 unsaved captures", then review, then save as PDF.
- **Exports checked visually** (PDF via pypdfium2; DOCX and PPTX rendered through Word and PowerPoint):
  - PDF and Word: A4, two per page, header and captions.
  - PowerPoint: one per slide with a caption strip below.
  - PDF captions now use "·" like the other formats.
- **Auto-crop fixed:**
  - When one candidate encloses another of nearly the same size, the outer one wins, so a slide's coloured footer is no longer cut off.
  - Edges snap to the sharpest boundary at full resolution.
  - On a real captured simulator frame the result is pixel-exact (test fixture `tests/fixtures/sim_window_slide1.png`).
- **Tests: 46 of 46 pass.**

### Still open (next session)
1. **The throwaway Edge test profile sometimes dims the whole window and renders sluggishly** (first-run UI?). In that state one walkthrough run missed slide 1 and saved a half-faded frame. Clean recordings and replays (with dimming) are fine.
   - Make the tests stable: try `--app=<url>` or a reused profile.
   - For real classes, consider a longer settle time or a check for blended ("ghost") frames.
   - `ui_smoke.py` now saves frames, so any repeat can be replayed with `tools/replay.py`.
2. **Real mouse-drag reorder in the review grid is untested.** Reorder was tested through the list API.
3. **The Firefox `about:config` occlusion setting is untested.** The Edge/Chrome flags are verified.
4. **Test on a real class,** only when you say so, with `LECTURA_DEBUG=1`.
