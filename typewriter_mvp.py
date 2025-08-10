# typewriter_with_commands.py
"""
Typewriter with command bar:
- Clickable buttons: CLEAR, NEW PAGE, SAVE AS..., OPEN..., EXPORT PNG..., TOGGLE EDIT MODE, QUIT
- Up/Down arrows scroll the view only (do not move the carriage/cursor)
- One-key-at-a-time, buffered animations, thunk/bell, off-paper carriage, overstrike
- Uses tkinter file dialogs for Save/Open (native dialogs)
"""

import pygame
import random
import sys
import io

# optional heavy math/sound synth
try:
    import numpy as np
    HAS_NUMPY = True
except Exception:
    HAS_NUMPY = False

# tkinter for file dialogs (import lazily when needed)
import tkinter as tk
from tkinter import filedialog

pygame.init()
try:
    pygame.mixer.init()
except Exception:
    pass

pygame.key.set_repeat(0)

# ---------- window / paper constants ----------
W, H = 1000, 780
screen = pygame.display.set_mode((W, H))
pygame.display.set_caption("Typewriter — Commands")
clock = pygame.time.Clock()

# paper area
PAPER_X, PAPER_Y = 60, 40
PAPER_W, PAPER_H = W - 2*PAPER_X, H - 140      # leave room for command bar at bottom
PAPER_COLOR = (245, 241, 232)

FONT_NAME = "Courier New"
FONT_SIZE = 26
font = pygame.font.SysFont(FONT_NAME, FONT_SIZE, bold=False)

LINE_HEIGHT = int(FONT_SIZE * 1.6)
CHAR_WIDTH = font.size("M")[0]

LEFT_MARGIN = 20
CARRIAGE_LEFT_PIXEL = PAPER_X + LEFT_MARGIN

cols_per_line = max(10, (PAPER_W - LEFT_MARGIN - 40) // CHAR_WIDTH) + 2
visible_rows = PAPER_H // LINE_HEIGHT
MAX_COL = cols_per_line - 1
OFF_COL = MAX_COL + 1

# ---------- runtime state ----------
cursor_col = 0            # carriage logical column
cursor_row = 0            # absolute row index where the carriage would type
paper_scroll = 0          # how many absolute rows scrolled off the top
paper_scroll_offset_px = 0.0  # during animate
carriage_px = CARRIAGE_LEFT_PIXEL  # animated pixel

glyphs = []  # list of glyph dicts: {'char','row','col','offset_x','offset_y','darkness'}

# pages history (for NEW PAGE)
saved_pages = []  # list of glyph lists

# UI state
key_locked = False
locked_key = None
locked_char_display = ""
animating = False
animation_cancel = False

# bell state
bell_rung_rows = set()

# edit/authentic mode
authentic_mode = True  # when True: backspace does not remove ink (moves carriage only). When False: backspace deletes the top glyph at cell.

# volumes
KEY_VOL = 0.7
BELL_VOL = 0.9
THUNK_VOL = 0.9

# small UI font
ui_font = pygame.font.SysFont(FONT_NAME, 16)

# modifier keys that should NOT lock (so Shift works)
MODIFIER_KEYS = {
    pygame.K_LSHIFT, pygame.K_RSHIFT,
    pygame.K_LCTRL, pygame.K_RCTRL,
    pygame.K_LALT, pygame.K_RALT,
    getattr(pygame, 'K_LMETA', None), getattr(pygame, 'K_RMETA', None),
    getattr(pygame, 'K_CAPSLOCK', None), getattr(pygame, 'K_NUMLOCK', None)
}
MODIFIER_KEYS = {k for k in MODIFIER_KEYS if k is not None}

# ---------- synth sounds (numpy optional) ----------
def _make_click_sound():
    if not HAS_NUMPY:
        return None
    sr = 22050
    length = int(0.02 * sr)
    noise = np.random.uniform(-1, 1, length)
    env = np.linspace(1.0, 0.0, length)
    data = (noise * env * 0.3 * (2**15-1)).astype(np.int16)
    stereo = np.column_stack([data, data])
    try:
        return pygame.sndarray.make_sound(stereo)
    except Exception:
        return None

def _make_bell_sound():
    if not HAS_NUMPY:
        return None
    sr = 22050
    t = np.linspace(0, 0.14, int(0.14*sr))
    freq = 1500.0
    tone = 0.6 * np.sin(2*np.pi*freq*t) * np.exp(-8*t)
    data = (tone * (2**15-1)).astype(np.int16)
    stereo = np.column_stack([data, data])
    try:
        return pygame.sndarray.make_sound(stereo)
    except Exception:
        return None

def _make_thunk_sound():
    if not HAS_NUMPY:
        return None
    sr = 22050
    t = np.linspace(0, 0.07, int(0.07*sr))
    freq = 110.0
    tone = 0.9 * np.sin(2*np.pi*freq*t) * np.exp(-18*t)
    click = 0.08 * np.sin(2*np.pi*2200*t) * np.exp(-250*t)
    data = (tone + click) * (2**15-1)
    data = data.astype(np.int16)
    stereo = np.column_stack([data, data])
    try:
        return pygame.sndarray.make_sound(stereo)
    except Exception:
        return None

key_sound = _make_click_sound()
bell_sound = _make_bell_sound()
thunk_sound = _make_thunk_sound()

def play_sound(snd, vol=1.0):
    if snd:
        try:
            snd.set_volume(vol)
            snd.play()
        except Exception:
            pass

def play_key():
    play_sound(key_sound, KEY_VOL)

def play_bell():
    if bell_sound:
        play_sound(bell_sound, BELL_VOL)
    else:
        play_key()

def play_thunk():
    if thunk_sound:
        play_sound(thunk_sound, THUNK_VOL)
    else:
        play_key()

# ---------- utilities for animation and coordinate mapping ----------
def pixel_for_col(col_index):
    if col_index <= MAX_COL:
        return PAPER_X + LEFT_MARGIN + col_index * CHAR_WIDTH
    else:
        return PAPER_X + PAPER_W + 18

def row_vis_index(row_index):
    return row_index - paper_scroll

def count_strikes_at(row, col):
    return sum(1 for g in glyphs if g['row'] == row and g['col'] == col)

# ---------- animations: buffer events during animation and repost them ----------
def animate_carriage_to_col(target_col, duration_ms=140, play_thunk_at_end=False, thunk_delay_ms=0):
    global animating, carriage_px, animation_cancel
    animating = True
    animation_cancel = False
    local_buffer = []
    start_px = carriage_px
    end_px = pixel_for_col(target_col)
    start_time = pygame.time.get_ticks()
    end_time = start_time + duration_ms
    while True:
        now = pygame.time.get_ticks()
        if now >= end_time or animation_cancel:
            carriage_px = end_px
            draw()
            pygame.display.flip()
            break
        frac = (now - start_time) / max(1, (end_time - start_time))
        frac = 1 - (1 - frac) * (1 - frac)
        carriage_px = start_px + (end_px - start_px) * frac
        # collect events
        for iev in pygame.event.get():
            if iev.type == pygame.QUIT:
                animation_cancel = True
                pygame.event.post(iev)
            else:
                local_buffer.append(iev)
        draw()
        pygame.display.flip()
        clock.tick(60)
    if play_thunk_at_end and not animation_cancel:
        if thunk_delay_ms:
            pygame.time.delay(thunk_delay_ms)
        play_thunk()
    animating = False
    animation_cancel = False
    # repost buffered events
    for ev in local_buffer:
        try:
            pygame.event.post(ev)
        except Exception:
            pass

def animate_paper_scroll_to(target_scroll, duration_ms=260):
    global animating, paper_scroll, paper_scroll_offset_px, animation_cancel
    if target_scroll < 0:
        target_scroll = 0
    animating = True
    animation_cancel = False
    local_buffer = []
    start_scroll = paper_scroll
    delta_rows = target_scroll - start_scroll
    start_offset = 0.0
    end_offset = -delta_rows * LINE_HEIGHT
    start_time = pygame.time.get_ticks()
    end_time = start_time + duration_ms
    while True:
        now = pygame.time.get_ticks()
        if now >= end_time or animation_cancel:
            paper_scroll_offset_px = 0.0
            paper_scroll = target_scroll
            draw()
            pygame.display.flip()
            break
        frac = (now - start_time) / max(1, (end_time - start_time))
        frac = 1 - (1 - frac) * (1 - frac)
        paper_scroll_offset_px = start_offset + (end_offset - start_offset) * frac
        for iev in pygame.event.get():
            if iev.type == pygame.QUIT:
                animation_cancel = True
                pygame.event.post(iev)
            else:
                local_buffer.append(iev)
        draw()
        pygame.display.flip()
        clock.tick(60)
    paper_scroll_offset_px = 0.0
    paper_scroll = target_scroll
    animating = False
    animation_cancel = False
    for ev in local_buffer:
        try:
            pygame.event.post(ev)
        except Exception:
            pass

# ---------- drawing ----------
COMMAND_BAR_H = 96
COMMAND_BAR_Y = H - COMMAND_BAR_H

# define buttons: label, action name (we'll map to functions)
# order matters for display
buttons = [
    {"label": "CLEAR", "id": "clear"},
    {"label": "NEW PAGE", "id": "new_page"},
    {"label": "SAVE AS...", "id": "save_as"},
    {"label": "OPEN...", "id": "open"},
    {"label": "EXPORT PNG...", "id": "export_png"},
    {"label": "TOGGLE EDIT MODE", "id": "toggle_edit"},
    {"label": "QUIT", "id": "quit"}
]

# button layout computed at runtime
button_rects = []  # list of pygame.Rect for clickable areas in same order as buttons

def draw():
    screen.fill((30, 30, 30))
    # paper rectangle
    pygame.draw.rect(screen, PAPER_COLOR, (PAPER_X, PAPER_Y, PAPER_W, PAPER_H))

    # ruled lines
    for i in range(visible_rows + 1):
        y = PAPER_Y + i * LINE_HEIGHT + paper_scroll_offset_px
        if PAPER_Y <= y <= PAPER_Y + PAPER_H:
            pygame.draw.line(screen, (230, 230, 220), (PAPER_X + 10, y), (PAPER_X + PAPER_W - 10, y), 1)

    # draw visible glyphs
    min_row = paper_scroll
    max_row = paper_scroll + visible_rows - 1
    for g in glyphs:
        if g['row'] < min_row or g['row'] > max_row:
            continue
        x = PAPER_X + LEFT_MARGIN + g['col'] * CHAR_WIDTH + g.get('offset_x', 0)
        y = PAPER_Y + (g['row'] - paper_scroll) * LINE_HEIGHT + g.get('offset_y', 0) + paper_scroll_offset_px
        text_surf = font.render(g['char'], True, (0, 0, 0))
        tmp = pygame.Surface(text_surf.get_size(), pygame.SRCALPHA)
        darkness = max(0.0, min(1.0, g.get('darkness', 1.0)))
        alpha = int(80 + 175 * darkness)
        text_surf.set_alpha(alpha)
        tmp.blit(text_surf, (0, 0))
        ghost = font.render(g['char'], True, (0,0,0))
        ghost.set_alpha(int(alpha * 0.35))
        for ox, oy in [(-1,0),(1,0),(0,-1),(0,1),(-1,-1),(1,1)]:
            tmp.blit(ghost, (ox, oy))
        screen.blit(tmp, (x, y))

    # carriage tick (short vertical) for visible cursor row
    cursor_vis = cursor_row - paper_scroll
    if 0 <= cursor_vis < visible_rows:
        line_top = PAPER_Y + cursor_vis * LINE_HEIGHT + paper_scroll_offset_px
        tick_h = int(LINE_HEIGHT * 0.6)
        tick_top = int(line_top + (LINE_HEIGHT - tick_h) / 2)
        tick_bottom = tick_top + tick_h
        pygame.draw.line(screen, (90,20,20), (carriage_px, tick_top), (carriage_px, tick_bottom), 3)

    # command bar background
    pygame.draw.rect(screen, (45,45,45), (0, COMMAND_BAR_Y, W, COMMAND_BAR_H))
    # draw buttons
    gap = 12
    pad = 12
    x = pad
    y = COMMAND_BAR_Y + 10
    button_h = COMMAND_BAR_H - 24
    button_rects.clear()
    for b in buttons:
        label = b["label"]
        # variable width by label length
        text_surf = ui_font.render(label, True, (240,240,240))
        w = max(120, text_surf.get_width() + 28)
        rect = pygame.Rect(x, y, w, button_h)
        pygame.draw.rect(screen, (70,70,70), rect, border_radius=8)
        pygame.draw.rect(screen, (90,90,90), rect, 2, border_radius=8)
        tx = x + (w - text_surf.get_width()) // 2
        ty = y + (button_h - text_surf.get_height()) // 2
        screen.blit(text_surf, (tx, ty))
        button_rects.append((rect, b["id"]))
        x += w + gap

    # small status text
    status = f"Mode: {'AUTHENTIC' if authentic_mode else 'EDITOR'}   Cursor: col {cursor_col} row {cursor_row}   Pages saved: {len(saved_pages)}"
    s_surf = ui_font.render(status, True, (200,200,200))
    screen.blit(s_surf, (x + 8, COMMAND_BAR_Y + 14))

    # locked-key indicator
    if key_locked:
        label = ui_font.render("Key down: " + (locked_char_display or ""), True, (220,220,220))
        screen.blit(label, (x + 8, COMMAND_BAR_Y + 40))

# ---------- document/text helpers ----------
def build_text_from_glyphs():
    """Return document text as string using latest glyph per cell.
    We'll include all rows from 0..max_row where max_row is the max row in glyphs or cursor_row."""
    if not glyphs:
        max_row = max(0, cursor_row)
    else:
        max_row = max(max(g['row'] for g in glyphs), cursor_row)
    lines = []
    for r in range(0, max_row + 1):
        # build row with default spaces up to cols_per_line
        row_chars = [" "] * cols_per_line
        # pick last glyph for each col
        for g in glyphs:
            if g['row'] == r:
                row_chars[g['col']] = g['char']
        # trim trailing spaces
        line = "".join(row_chars).rstrip()
        lines.append(line)
    return "\n".join(lines)

def load_text_into_glyphs(text):
    """Clear current glyphs and load provided text (plain text) into glyphs structure."""
    global glyphs, cursor_row, cursor_col, paper_scroll, bell_rung_rows
    glyphs = []
    lines = text.splitlines()
    for r, line in enumerate(lines):
        for c, ch in enumerate(line):
            if c >= cols_per_line:
                break
            glyphs.append({'char': ch, 'row': r, 'col': c, 'offset_x': random.randint(-1,1), 'offset_y': random.randint(-1,1), 'darkness': random.uniform(0.75, 1.0)})
    cursor_row = len(lines) - 1 if lines else 0
    cursor_col = len(lines[-1]) if lines else 0
    if cursor_col > MAX_COL:
        cursor_col = MAX_COL
    paper_scroll = max(0, cursor_row - visible_rows + 1)
    bell_rung_rows = set()

# ---------- file dialog helpers ----------
def ask_save_text_and_write(default_ext=".txt"):
    # use tkinter filedialog
    root = tk.Tk()
    root.withdraw()
    fname = filedialog.asksaveasfilename(defaultextension=default_ext, filetypes=[("Text files","*.txt"),("All files","*.*")])
    root.destroy()
    if not fname:
        return None
    try:
        txt = build_text_from_glyphs()
        with open(fname, "w", encoding="utf-8") as f:
            f.write(txt)
        return fname
    except Exception as e:
        print("Save failed:", e)
        return None

def ask_open_file_and_load():
    root = tk.Tk()
    root.withdraw()
    fname = filedialog.askopenfilename(filetypes=[("Text files","*.txt"),("All files","*.*")])
    root.destroy()
    if not fname:
        return None
    try:
        with open(fname, "r", encoding="utf-8") as f:
            txt = f.read()
        load_text_into_glyphs(txt)
        return fname
    except Exception as e:
        print("Open failed:", e)
        return None

def ask_save_png_and_write(surface):
    root = tk.Tk()
    root.withdraw()
    fname = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG image","*.png"),("All files","*.*")])
    root.destroy()
    if not fname:
        return None
    try:
        pygame.image.save(surface, fname)
        return fname
    except Exception as e:
        print("Export PNG failed:", e)
        return None

# ---------- actions invoked by buttons ----------
def action_clear():
    global glyphs, cursor_col, cursor_row, paper_scroll, bell_rung_rows
    glyphs = []
    cursor_col = 0
    cursor_row = 0
    paper_scroll = 0
    bell_rung_rows.clear()
    animate_carriage_to_col(0)

def action_new_page():
    global glyphs, cursor_col, cursor_row, paper_scroll, saved_pages, bell_rung_rows
    # push a deep copy of the current page
    saved_pages.append([dict(g) for g in glyphs])
    glyphs = []
    cursor_col = 0
    cursor_row = 0
    paper_scroll = 0
    bell_rung_rows.clear()
    animate_carriage_to_col(0)

def action_save_as():
    fname = ask_save_text_and_write()
    if fname:
        print("Saved to", fname)

def action_open():
    fname = ask_open_file_and_load()
    if fname:
        print("Loaded", fname)

def action_export_png():
    # create an offscreen surface of just the paper area and draw page into it
    surf = pygame.Surface((PAPER_W, PAPER_H))
    surf.fill(PAPER_COLOR)
    # draw ruled lines on surf
    for i in range(visible_rows + 1):
        y = i * LINE_HEIGHT + int(paper_scroll_offset_px)
        pygame.draw.line(surf, (230,230,220), (10, y), (PAPER_W - 10, y), 1)
    # draw visible glyphs
    min_row = paper_scroll
    max_row = paper_scroll + visible_rows - 1
    for g in glyphs:
        if g['row'] < min_row or g['row'] > max_row:
            continue
        x = LEFT_MARGIN + g['col'] * CHAR_WIDTH + g.get('offset_x', 0)
        y = (g['row'] - paper_scroll) * LINE_HEIGHT + g.get('offset_y', 0) + int(paper_scroll_offset_px)
        txt = font.render(g['char'], True, (0,0,0))
        tmp = pygame.Surface(txt.get_size(), pygame.SRCALPHA)
        darkness = max(0.0, min(1.0, g.get('darkness', 1.0)))
        alpha = int(80 + 175 * darkness)
        txt.set_alpha(alpha)
        tmp.blit(txt, (0,0))
        ghost = font.render(g['char'], True, (0,0,0))
        ghost.set_alpha(int(alpha * 0.35))
        for ox, oy in [(-1,0),(1,0),(0,-1),(0,1),(-1,-1),(1,1)]:
            tmp.blit(ghost, (ox, oy))
        surf.blit(tmp, (x, y))
    # ask to save surf
    fname = ask_save_png_and_write(surf)
    if fname:
        print("Exported PNG to", fname)

def action_toggle_edit():
    global authentic_mode
    authentic_mode = not authentic_mode

def action_quit():
    pygame.event.post(pygame.event.Event(pygame.QUIT))

action_map = {
    "clear": action_clear,
    "new_page": action_new_page,
    "save_as": action_save_as,
    "open": action_open,
    "export_png": action_export_png,
    "toggle_edit": action_toggle_edit,
    "quit": action_quit
}

# ---------- main loop ----------
running = True
carriage_px = pixel_for_col(cursor_col)

while running:
    for ev in pygame.event.get():
        if ev.type == pygame.QUIT:
            running = False

        # if animating, animation functions buffer events; ignore further handling here
        if animating:
            continue

        # Mouse clicks -> buttons
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            mx, my = ev.pos
            if my >= COMMAND_BAR_Y:
                # check buttons
                for rect, bid in button_rects:
                    if rect.collidepoint(mx, my):
                        # call action
                        fn = action_map.get(bid)
                        if fn:
                            fn()
                        break
                continue
            # else clicks on paper could be used later (e.g., place cursor) - ignore for now

        if ev.type == pygame.KEYDOWN:
            # quit
            if ev.key == pygame.K_ESCAPE:
                running = False
                continue

            # Up/Down arrows: move view (paper_scroll) only — do not lock or move cursor
            if ev.key == pygame.K_UP:
                # scroll up one row if possible
                target = max(0, paper_scroll - 1)
                if target != paper_scroll:
                    animate_paper_scroll_to(target, duration_ms=180)
                continue
            if ev.key == pygame.K_DOWN:
                # compute max scroll: ensure we don't scroll past last content; allow scrolling into empty area up to cursor_row
                max_row = max(cursor_row, max([g['row'] for g in glyphs], default=0))
                max_scroll = max(0, max_row - visible_rows + 1)
                target = min(max_scroll, paper_scroll + 1)
                if target != paper_scroll:
                    animate_paper_scroll_to(target, duration_ms=180)
                continue

            # treat pure modifiers as not locking (so Shift works for capitals)
            if ev.key in MODIFIER_KEYS:
                continue

            # Left/Right still move carriage and animate; these should lock (simulate mechanical key)
            if ev.key in (pygame.K_LEFT, pygame.K_RIGHT):
                # respect one-key-at-a-time locking for movement keys
                if key_locked:
                    continue
                key_locked = True
                locked_key = ev.key
                locked_char_display = pygame.key.name(ev.key)
                if ev.key == pygame.K_LEFT:
                    if cursor_col > 0:
                        play_key()
                        cursor_col -= 1
                        animate_carriage_to_col(cursor_col, duration_ms=120)
                else:
                    if cursor_col < OFF_COL:
                        play_key()
                        cursor_col += 1
                        if cursor_col == OFF_COL:
                            animate_carriage_to_col(OFF_COL, duration_ms=200, play_thunk_at_end=True, thunk_delay_ms=10)
                        else:
                            animate_carriage_to_col(cursor_col, duration_ms=120)
                continue

            # Backspace behaviour depends on mode
            if ev.key == pygame.K_BACKSPACE:
                if key_locked:
                    continue
                key_locked = True
                locked_key = ev.key
                locked_char_display = "BS"
                # if off-paper, move back to MAX_COL
                if cursor_col == OFF_COL:
                    play_key()
                    animate_carriage_to_col(MAX_COL, duration_ms=140)
                    cursor_col = MAX_COL
                elif cursor_col > 0:
                    if authentic_mode:
                        # move carriage left without deleting
                        play_key()
                        cursor_col -= 1
                        animate_carriage_to_col(cursor_col, duration_ms=120)
                    else:
                        # editor mode: delete top glyph at that cell (if any)
                        # find last glyph at current row and previous col
                        remove_col = cursor_col - 1
                        removed = False
                        for i in range(len(glyphs)-1, -1, -1):
                            g = glyphs[i]
                            if g['row'] == cursor_row and g['col'] == remove_col:
                                glyphs.pop(i)
                                removed = True
                                break
                        if removed:
                            # keep cursor in place (like modern editor) or move left? we'll move left
                            cursor_col -= 1
                            animate_carriage_to_col(cursor_col, duration_ms=100)
                        else:
                            # nothing to delete: still move left
                            cursor_col -= 1
                            animate_carriage_to_col(cursor_col, duration_ms=100)
                continue

            # Enter: carriage return and paper feed if needed
            if ev.key == pygame.K_RETURN:
                if key_locked:
                    continue
                key_locked = True
                locked_key = ev.key
                locked_char_display = "RET"
                play_key()
                # animate carriage back to left
                animate_carriage_to_col(0, duration_ms=300)
                cursor_col = 0
                cursor_row += 1
                # if cursor beyond visible area, feed paper
                if cursor_row >= paper_scroll + visible_rows:
                    animate_paper_scroll_to(cursor_row - visible_rows + 1, duration_ms=260)
                continue

            # Printable characters / typing
            if ev.unicode and len(ev.unicode) == 1 and ev.key not in MODIFIER_KEYS:
                # if key already locked, ignore
                if key_locked:
                    continue
                # lock
                key_locked = True
                locked_key = ev.key
                ch = ev.unicode
                locked_char_display = ch
                # if carriage off-paper, ignore typing
                if cursor_col == OFF_COL:
                    continue
                # typing into last printable column causes overstrike and slide off
                if cursor_col >= MAX_COL:
                    strikes = count_strikes_at(cursor_row, MAX_COL)
                    if cursor_row not in bell_rung_rows:
                        play_bell()
                        bell_rung_rows.add(cursor_row)
                    play_key()
                    base_dark = random.uniform(0.6, 0.95)
                    darkness = min(1.0, base_dark + 0.12 * strikes)
                    jitter_x = random.uniform(-1, 1) if strikes > 0 else random.uniform(-0.5, 0.5)
                    jitter_y = random.uniform(-1, 1) if strikes > 0 else random.uniform(-0.5, 0.5)
                    glyphs.append({'char': ch, 'row': cursor_row, 'col': MAX_COL, 'offset_x': jitter_x, 'offset_y': jitter_y, 'darkness': darkness})
                    cursor_col = OFF_COL
                    animate_carriage_to_col(OFF_COL, duration_ms=240, play_thunk_at_end=True, thunk_delay_ms=10)
                else:
                    strikes = count_strikes_at(cursor_row, cursor_col)
                    # near-margin bell once
                    if cursor_col >= cols_per_line - 2 and cursor_row not in bell_rung_rows:
                        play_bell()
                        bell_rung_rows.add(cursor_row)
                    play_key()
                    base_dark = random.uniform(0.6, 0.95)
                    darkness = min(1.0, base_dark + 0.12 * strikes)
                    jitter_x = random.randint(-1, 1)
                    jitter_y = random.randint(-1, 2)
                    glyphs.append({'char': ch, 'row': cursor_row, 'col': cursor_col, 'offset_x': jitter_x, 'offset_y': jitter_y, 'darkness': darkness})
                    cursor_col += 1
                    animate_carriage_to_col(cursor_col, duration_ms=110)
                continue

        # KEYUP: release lock if same key
        if ev.type == pygame.KEYUP:
            # ignore modifiers
            if ev.key in MODIFIER_KEYS:
                continue
            if key_locked and ev.key == locked_key:
                key_locked = False
                locked_key = None
                locked_char_display = ""

    # draw & flip
    draw()
    pygame.display.flip()
    clock.tick(60)

pygame.quit()
sys.exit()
