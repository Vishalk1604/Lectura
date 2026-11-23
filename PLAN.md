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

### Next session: steps in order
1. Fix the auto-crop candidate handling (problem 1) and get all unit tests green.
2. Re-run the E2E simulator (tell you before the Edge window opens). Expect 7 captures: slide 1 (all bullets), slide 2, slide 3, whiteboard page 1, whiteboard page 2 before the scroll, after the scroll, and slide 4. The revisit of slide 1 should be dropped.
3. **Check browser occlusion throttling:** Chrome, Edge and Firefox may stop painting a window that is fully covered.
   - With the simulator window fully covered, confirm that frames keep updating (`WgcSource.frame_age`).
   - If they don't, the app warns when frames go stale while the window isn't minimized.
   - The README then explains the fixes: Chrome/Edge `--disable-features=CalculateNativeWinOcclusion` and `--disable-backgrounding-occluded-windows`; Firefox `widget.windows.window_occlusion_tracking.enabled = false` in about:config.
4. **Launch the UI** (`.venv\Scripts\python.exe -m lectura`) and walk through: pick window → auto-detect and drag crop → Start → Pause/Resume → Capture now (Ctrl+Alt+S) → Stop → review (delete, reorder, enlarge) → save all three formats. Also check crash recovery: kill the app mid-recording and relaunch.
5. **Render the exported PDF/DOCX/PPTX** and check the 2-per-page layout and captions visually.
6. **Package:** `Lectura.spec` and `build.bat` (PyInstaller one-file, windowed, `assets/lectura.ico` bundled), then run `dist\Lectura.exe`.
7. **Write `README.md`:** usage, the hotkey, and the limits (don't minimize the class window, keep the class in its own browser window, DRM video may be black, occlusion settings).
8. **Commit and push** to github.com/Vishalk1604/Lectura.
9. **Test on a real class,** but only when you say so. Don't capture a live class or open test windows during a class without asking first.
