# Lectura

Lectura watches one window (your Google Meet / Classroom tab, a live-slides site such as
Kiteroom, or any other app). Every time the teacher moves to a new slide or a new whiteboard
page, it saves a screenshot. When the class ends you review the screenshots and save them as
**PowerPoint, Word or PDF**.

- **Only the window you pick is captured.** You can switch to other apps while it records,
  and the class window can stay behind other windows or on a second monitor.
- **Smart timing.**
  - **Slides:** a slide is saved just before it changes, so bullets that appear one by one
    end up in a single screenshot with all of them.
  - **Whiteboard:** nothing is saved while the teacher is still writing. The full page is
    saved when they open a new page or scroll most of the writing away. Rubbing out a small
    mistake doesn't count as a new page.
- **Auto-crop.** It finds the shared screen or slide area and shows it as a box you can drag
  or resize. The box is remembered for each site, and black letterbox bars are trimmed off.
- **No clutter.**
  - A webcam bubble or other moving video is ignored automatically.
  - Going back to a slide that was already saved doesn't save it twice.
- **Safe.** Captures are written to disk as they happen. If the app or PC crashes, Lectura
  offers to recover them the next time it opens.

## Using it

1. Open your class so it's showing in a browser window (or app).
2. Start **Lectura** and pick that window under **Class window**.
3. Check the box on the preview covers only the slides / shared screen. **Auto-detect area**
   finds it again; you can also drag the box, resize it from its corners, or draw a new one.
4. Press **Start recording**. You can now use other apps.
   - **Capture now**, or **Ctrl+Alt+S** from any app, saves the current screen straight away.
   - **Pause / Resume** is for breaks.
   - **Sensitivity**: move it to *More captures* if slides are missed, *Fewer captures* if
     you get too many near-identical ones.
5. Press **Stop & review**. You can delete screenshots you don't want (Delete key), drag to
   reorder, and double-click to enlarge.
6. Press **Save…**, tick PowerPoint, Word and/or PDF, and pick the folder and file name.
   - PowerPoint: one screenshot per slide.
   - Word and PDF: two screenshots per page.
   - Each page can show the class time it was taken.

## Tips and limits

- **Don't minimize the class window.** Windows can't capture minimized windows; Lectura pauses
  until you restore it. Leaving it *behind* other windows is fine.
- **Keep the class in its own browser window.** Only the tab that is showing in that window
  is captured, so open other tabs in a different window.
- **If Lectura says the window is hidden and not updating**, the browser may have stopped
  drawing it because it's fully covered. Leave a small part of it visible, put it on another
  monitor, or turn off the browser's "hidden window" saving:
  - **Firefox:** open `about:config` and set `widget.windows.window_occlusion_tracking.enabled`
    to `false`.
  - **Chrome / Edge:** start the browser with
    `--disable-features=CalculateNativeWinOcclusion --disable-backgrounding-occluded-windows`.
    Add this to the end of the shortcut's *Target* field.
- **Protected (DRM) video**, such as some streaming players, appears black in any screenshot
  tool.
- Captures waiting to be saved are kept in `%LOCALAPPDATA%\Lectura\sessions`. Sessions that
  were already saved are cleaned up after 14 days.

## Running from source and building the .exe

Needs Windows 10 (1903+) or 11, and Python 3.12.

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m lectura
```

`build.bat` builds a single `dist\Lectura.exe`.

Tests:

```powershell
.venv\Scripts\python.exe -m pytest -q
```

`tools/class_sim.html` is a fake class: slides with bullet builds, a fade, a webcam bubble, and
a whiteboard with a small erase, a new page and a scroll.
`tools/e2e_sim.py <folder>` records it in a separate Edge window and exports all three formats.
It should produce 7 captures.

## How it works

| File | What it does |
|---|---|
| `lectura/capture.py` | Captures the window with Windows Graphics Capture (falls back to PrintWindow). |
| `lectura/detector.py` | 2 samples per second. Learns and ignores areas that move all the time. Waits until the picture holds still for 1.5 s, then compares it with the current page: if most of the old content is gone (new slide, cleared board, a big scroll), it saves the old page; otherwise it updates the current page. |
| `lectura/autocrop.py` | Finds the slide / shared-screen rectangle and trims letterbox bars. |
| `lectura/dedupe.py` | Drops blank pages and anything already contained in an earlier capture. |
| `lectura/exporters/` | Writes PPTX (python-pptx), DOCX (python-docx) and PDF (reportlab). Images are lossless PNG. |
