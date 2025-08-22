# Typewriter — A Mechanical Typewriter Simulation

A focused, tactile typewriter emulator implemented in Python using Pygame that behaves like a real mechanical machine in as many ways as possible (still improving). Intended as a creative-writing text editor that makes you more intentional with your typing.

---

## Features (what it simulates)

* Mechanical single-key locking (prevents key-chording).
* Strike sound per keystroke (use `typewriter_strike.wav` or fallback synth).
* Glyph jitter, ink darkness variance, and overstrike rendering (multiple glyphs drawn in a cell).
* Tab expansion to tab stops (configurable `TAB_SIZE`). Tabs insert the required number of space glyphs and stamps.
* Carriage off-page behavior: when you type past the rightmost printable column the carriage can slide off the paper (bell / thunk).
* Bell rung once per row when approaching margin.
* Blocky/stepped horizontal nudges on key release, tuned for mechanical "snap" feeling.
* Smooth horizontal slide option (used for carriage-return final alignment).
* Paper feed / vertical scrolling and animated page slide-down when you hit Enter near the bottom of the visible paper.
* Command bar with clickable buttons (CLEAR, NEW PAGE, SAVE AS..., OPEN..., EXPORT PNG..., TOGGLE EDIT MODE, QUIT).
* `EXPORT PNG` exports the visible paper area as an image.
* Stamp history: every struck glyph is recorded for saving/export; backspace does NOT remove stamps. Saved `.txt` uses `□` for cells that were struck more than once.

---

## Requirements

* Python 3.8+
* `pygame` (`pip install pygame`)
* `tkinter` (usually bundled; required for native file dialogs)
* `numpy` (optional — `pip install numpy`) for higher-quality synthesized sounds; if absent a minimal fallback is used.
* Optional: `typewriter_strike.wav` placed in the same directory to use as primary strike sound.

---

## Installation

1. Clone or copy the repository into a directory.
2. Create a virtual environment (recommended) and install dependencies:

```bash
python -m venv venv
source venv/bin/activate      # or venv\Scripts\activate on Windows
pip install pygame
pip install numpy             # optional
```

3. Put `typewriter_strike.wav` in the same folder as `typewriter_mvp.py` for authentic sound, or rely on the built-in fallback.

---

## Run

From the project directory:

```bash
python typewriter_mvp.py
```

Close the window or use the `QUIT` button to exit. 

---

## Controls / Interaction

### Typing behavior

* **Printable char**: press key → the glyph appears & strike sound plays immediately (KEYDOWN). Release key → the mechanical page nudge and carriage advance occurs (KEYUP).
* **Hold key**: nothing repeats while held. Release and press again to type again.
* **Backspace**:

  * **AUTHENTIC mode**: moves carriage left without removing ink.
  * **EDITOR mode**: removes the top glyph (the most recent) at that cell.
  * Note: saving uses stamp history; even if editor-mode removed a glyph visually, the original stamp remains recorded for the TXT output unless you switch behavior.
* **Enter / Return**: snaps the carriage vertically to the next row immediately, then smoothly slides the paper so column 0 is under the carriage. If the cursor goes past the bottom of the visible paper, the paper will feed (scroll) up.
* **Left / Right**: move the carriage left/right.
* **Up / Down**: scroll the visible page up/down (view only; doesn't move the carriage).
* **Tab**: expands to next tab stop (configurable `TAB_SIZE`). Each space is struck as normal (optionally could be configured to play a single sound: see customization section).

### UI / Command bar (mouse-clickable)

* **CLEAR** — clear the current page (resets glyphs and cursor to configured top margin).
* **NEW PAGE** — pushes the current page into `saved_pages` (in-memory) and starts a fresh page.
* **SAVE AS...** — choose a filename and save TXT (uses stamp history: blank → space; single stamp → character; multiple stamps → `□`).
* **OPEN...** — open a `.txt` file (tabs expanded).
* **EXPORT PNG...** — saves visible paper as a PNG image.
* **TOGGLE EDIT MODE** — toggle AUTHENTIC / EDITOR backspace behavior.
* **QUIT** — exits.

---

## File format & saving behavior

* `SAVE AS...` writes a plain text file built from the **stamp history**, not the current on-screen glyph list. That list is rendered as:
    * 0 stamps → space
    * 1 stamp → that character
    * \>1 stamp → `□` (U+25A1) to indicate an overstrike / overwritten ink
* Trailing spaces on each line are trimmed.
* `EXPORT PNG...` captures the visible paper area as rendered (glyph jitter, darkness, and stacked glyphs are preserved).

This preserves the *paper’s ink history*, honoring the typewriter simulation. Ink can never be removed, only overwritten.

---

## Troubleshooting & Known Behaviors

* **Letters rendering as squares**: Some characters may render as a square `□`. I've tried to capture and filter most occurrences of these missing letters, but may not have caught all possible, especially if you use strange unicode.
* **Fast typing issues**: Animations buffer events and repost them — there’s a tradeoff between responsiveness and animation fidelity. If you need more aggressive responsiveness, reduce animation durations or steps.
* **Saving shows `□` on overwritten cells**: This is by design to reflect ink overstrike. If you prefer a different marker, edit the `build_text_from_stamps()` function.

---

## Credits & license

* Author: BKell-Dog on GitHub
* Uses: [`pygame`](http://www.pygame.org/), optional `numpy`.
* License: This code is in the public domain.