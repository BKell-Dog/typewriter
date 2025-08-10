# typewriter_mvp_blocky_keydown_draw_keyup_move.py
# Printable characters are drawn & struck on KEYDOWN; horizontal blocky page move and column advance occur on KEYUP.

import pygame
import random
import sys
import os
import tkinter as tk
from tkinter import filedialog

# optional numpy sound synth fallback
try:
    import numpy as np
    HAS_NUMPY = True
except Exception:
    HAS_NUMPY = False

pygame.init()
try:
    pygame.mixer.init()
except Exception:
    pass

pygame.key.set_repeat(0)

# ---------- window / paper constants ----------
W, H = 1000, 780
screen = pygame.display.set_mode((W, H))
pygame.display.set_caption("Typewriter — Draw on KeyDown, Move on KeyUp")
clock = pygame.time.Clock()

# paper area (leave room for command bar at bottom)
PAPER_X, PAPER_Y = 60, 40
PAPER_W, PAPER_H = W - 2*PAPER_X, H - 140
PAPER_COLOR = (245, 241, 232)

FONT_NAME = "Courier New"
FONT_SIZE = 26
font = pygame.font.SysFont(FONT_NAME, FONT_SIZE, bold=False)

LINE_HEIGHT = int(FONT_SIZE * 1.6)
CHAR_WIDTH = font.size("M")[0]

LEFT_MARGIN = 20
# carriage will be displayed in the center of the paper area:
CARRIAGE_DISPLAY_X = PAPER_X + PAPER_W // 2

cols_per_line = max(10, (PAPER_W - LEFT_MARGIN - 40) // CHAR_WIDTH) + 2
visible_rows = PAPER_H // LINE_HEIGHT
MAX_COL = cols_per_line - 1
OFF_COL = MAX_COL + 1

# ---------- runtime state ----------
cursor_col = 0            # logical column index
cursor_row = 0            # absolute row index
paper_scroll = 0          # how many rows scrolled off top
paper_scroll_offset_px = 0.0  # during vertical animation

# view_offset_px represents the paper's horizontal translation: paper is drawn at PAPER_X + view_offset_px
view_offset_px = 0.0

glyphs = []  # list of dicts: {'char','row','col','offset_x','offset_y','darkness', 'pending':bool}

# pages history
saved_pages = []

# UI state
key_locked = False
locked_key = None
locked_char_display = ""
pending_keydown = None   # store the pygame.Event for the keydown that is pending (strike on KEYDOWN, move on KEYUP)
animating = False
animation_cancel = False

# bell state (once per row)
bell_rung_rows = set()

# edit/authentic mode
authentic_mode = True

# volumes
KEY_VOL = 0.7
BELL_VOL = 0.9
THUNK_VOL = 0.9

# small UI font
ui_font = pygame.font.SysFont(FONT_NAME, 16)

# how many spaces for a tab if you want to expand tabs (optional, we map tabs -> single space for simplicity)
TAB_SIZE = 4


# modifier keys that should NOT lock (so Shift works)
MODIFIER_KEYS = {
    pygame.K_LSHIFT, pygame.K_RSHIFT,
    pygame.K_LCTRL, pygame.K_RCTRL,
    pygame.K_LALT, pygame.K_RALT,
    getattr(pygame, 'K_LMETA', None), getattr(pygame, 'K_RMETA', None),
    getattr(pygame, 'K_CAPSLOCK', None), getattr(pygame, 'K_NUMLOCK', None)
}
MODIFIER_KEYS = {k for k in MODIFIER_KEYS if k is not None}

# ---------- sound setup ----------
strike_sound = None
try:
    base_dir = os.path.dirname(os.path.abspath(__file__))
except Exception:
    base_dir = os.getcwd()
strike_path = os.path.join(base_dir, "typewriter_click.wav")
if os.path.isfile(strike_path):
    try:
        strike_sound = pygame.mixer.Sound(strike_path)
    except Exception as e:
        print("Failed to load typewriter_click.wav:", e)
        strike_sound = None

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

click_fallback = _make_click_sound()
bell_sound = _make_bell_sound()
thunk_sound = _make_thunk_sound()

def play_key():
    """Play the strike WAV if available, else fallback sound."""
    global strike_sound
    if strike_sound:
        try:
            strike_sound.set_volume(KEY_VOL)
            strike_sound.play()
            return
        except Exception:
            pass
    if click_fallback:
        try:
            click_fallback.set_volume(KEY_VOL)
            click_fallback.play()
        except Exception:
            pass

def play_bell():
    if bell_sound:
        try:
            bell_sound.set_volume(BELL_VOL)
            bell_sound.play()
            return
        except Exception:
            pass
    play_key()

def play_thunk():
    if thunk_sound:
        try:
            thunk_sound.set_volume(THUNK_VOL)
            thunk_sound.play()
            return
        except Exception:
            pass
    play_key()
    pygame.time.delay(30)
    play_key()

# ---------- utilities ----------
def count_strikes_at(row, col):
    return sum(1 for g in glyphs if g['row'] == row and g['col'] == col)

def pixel_for_col(col_index):
    # column pixel position relative to the paper origin
    return LEFT_MARGIN + col_index * CHAR_WIDTH

# ---------- blocky/stepped view animation ----------
def animate_view_to_col_blocky(target_col, steps=4, step_ms=10, play_thunk_at_end=False, thunk_delay_ms=0):
    """
    Blocky/stepped animation to move view_offset_px so that target_col aligns with the fixed carriage center.
    steps: number of discrete jumps
    step_ms: milliseconds pause per step
    Buffer events while animating and repost them afterward.
    """
    global animating, view_offset_px, animation_cancel
    animating = True
    animation_cancel = False
    local_buffer = []

    target_offset = CARRIAGE_DISPLAY_X - PAPER_X - pixel_for_col(target_col)
    start_offset = view_offset_px
    delta = target_offset - start_offset

    for s in range(1, steps + 1):
        if animation_cancel:
            break
        frac = s / steps
        new_offset = start_offset + delta * frac
        view_offset_px = new_offset

        draw()
        pygame.display.flip()

        wait_until = pygame.time.get_ticks() + step_ms
        while pygame.time.get_ticks() < wait_until:
            for iev in pygame.event.get():
                if iev.type == pygame.QUIT:
                    animation_cancel = True
                    pygame.event.post(iev)
                else:
                    local_buffer.append(iev)
            clock.tick(120)

    # ensure final position
    if not animation_cancel:
        view_offset_px = target_offset
        draw()
        pygame.display.flip()

    if play_thunk_at_end and not animation_cancel:
        if thunk_delay_ms:
            pygame.time.delay(thunk_delay_ms)
        play_thunk()

    animating = False
    animation_cancel = False

    for ev in local_buffer:
        try:
            pygame.event.post(ev)
        except Exception:
            pass

def animate_view_to_col_smooth(target_col, duration_ms=1000, play_thunk_at_end=False, thunk_delay_ms=0):
    """
    Smooth animation to move view_offset_px so that target_col aligns with the fixed carriage center.
    Uses ease-out interpolation and buffers events while animating.
    """
    global animating, view_offset_px, animation_cancel
    animating = True
    animation_cancel = False
    local_buffer = []

    target_offset = CARRIAGE_DISPLAY_X - PAPER_X - pixel_for_col(target_col)
    start_offset = view_offset_px
    start_time = pygame.time.get_ticks()
    end_time = start_time + duration_ms

    while True:
        now = pygame.time.get_ticks()
        if now >= end_time or animation_cancel:
            view_offset_px = target_offset
            draw()
            pygame.display.flip()
            break

        frac = (now - start_time) / max(1, (end_time - start_time))
        # ease-out
        frac = 1 - (1 - frac) * (1 - frac)
        view_offset_px = start_offset + (target_offset - start_offset) * frac

        # buffer events so UI remains responsive
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

# Smooth vertical feed (unchanged)
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

buttons = [
    {"label": "CLEAR", "id": "clear"},
    {"label": "NEW PAGE", "id": "new_page"},
    {"label": "SAVE AS...", "id": "save_as"},
    {"label": "OPEN...", "id": "open"},
    {"label": "EXPORT PNG...", "id": "export_png"},
    {"label": "TOGGLE EDIT MODE", "id": "toggle_edit"},
    {"label": "QUIT", "id": "quit"}
]
button_rects = []

def draw():
    screen.fill((30, 30, 30))

    # Draw paper rectangle shifted by view_offset_px
    paper_draw_x = int(PAPER_X + view_offset_px)
    pygame.draw.rect(screen, PAPER_COLOR, (paper_draw_x, PAPER_Y, PAPER_W, PAPER_H))

    # ruled lines (shifted with paper)
    for i in range(visible_rows + 1):
        y = PAPER_Y + i * LINE_HEIGHT + paper_scroll_offset_px
        x1 = paper_draw_x + 10
        x2 = paper_draw_x + PAPER_W - 10
        if PAPER_Y <= y <= PAPER_Y + PAPER_H:
            pygame.draw.line(screen, (230, 230, 220), (x1, y), (x2, y), 1)

    # draw visible glyphs; position relative to paper_draw_x + LEFT_MARGIN
    min_row = paper_scroll
    max_row = paper_scroll + visible_rows - 1
    for g in glyphs:
        if g['row'] < min_row or g['row'] > max_row:
            continue

        ch = g.get('char', '')
        # Skip non-single-printable characters
        if not (isinstance(ch, str) and len(ch) == 1 and (ch == ' ' or ch.isprintable())):
            continue

        x = paper_draw_x + LEFT_MARGIN + g['col'] * CHAR_WIDTH + g.get('offset_x', 0)
        y = PAPER_Y + (g['row'] - paper_scroll) * LINE_HEIGHT + g.get('offset_y', 0) + paper_scroll_offset_px
        if x + CHAR_WIDTH < paper_draw_x or x > paper_draw_x + PAPER_W:
            continue
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

    # draw carriage underline at fixed center X
    cursor_vis = cursor_row - paper_scroll
    if 0 <= cursor_vis < visible_rows:
        line_top = PAPER_Y + cursor_vis * LINE_HEIGHT + paper_scroll_offset_px
        underline_y = line_top + LINE_HEIGHT - 10  # 3 px above the bottom of the line
        underline_half_width = CHAR_WIDTH // 2
        start_x = CARRIAGE_DISPLAY_X - underline_half_width + 7
        end_x = CARRIAGE_DISPLAY_X + underline_half_width + 5
        pygame.draw.line(screen, (220, 20, 20), (start_x, underline_y), (end_x, underline_y), 2)

    # command bar
    pygame.draw.rect(screen, (45,45,45), (0, COMMAND_BAR_Y, W, COMMAND_BAR_H))
    gap = 12; pad = 12; x = pad; y = COMMAND_BAR_Y + 10; button_h = COMMAND_BAR_H - 24
    button_rects.clear()
    for b in buttons:
        label = b["label"]
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

    status = f"Mode: {'AUTHENTIC' if authentic_mode else 'EDITOR'}   Cursor: col {cursor_col} row {cursor_row}   Pages saved: {len(saved_pages)}"
    s_surf = ui_font.render(status, True, (200,200,200))
    screen.blit(s_surf, (x + 8, COMMAND_BAR_Y + 14))

    if key_locked:
        label = ui_font.render("Key down: " + (locked_char_display or ""), True, (220,220,220))
        screen.blit(label, (x + 8, COMMAND_BAR_Y + 40))

# ---------- document/text helpers & actions ----------
def build_text_from_glyphs():
    if not glyphs:
        max_row = max(0, cursor_row)
    else:
        max_row = max(max(g['row'] for g in glyphs), cursor_row)
    lines = []
    for r in range(0, max_row + 1):
        row_chars = [" "] * cols_per_line
        for g in glyphs:
            if g['row'] == r:
                if 0 <= g['col'] < cols_per_line:
                    row_chars[g['col']] = g['char']
        line = "".join(row_chars).rstrip()
        lines.append(line)
    return "\n".join(lines)

def load_text_into_glyphs(text):
    global glyphs, cursor_row, cursor_col, paper_scroll, bell_rung_rows, view_offset_px
    glyphs = []
    lines = text.splitlines()
    for r, line in enumerate(lines):
        for c, ch in enumerate(line):
            if c >= cols_per_line:
                break
            # convert tabs and other non-space whitespace to a simple space
            if ch.isspace():
                ch = ' '

            glyphs.append({'char': ch, 'row': r, 'col': c, 'offset_x': random.randint(-1,1), 'offset_y': random.randint(-1,1), 'darkness': random.uniform(0.75, 1.0)})
    cursor_row = len(lines) - 1 if lines else 0
    cursor_col = len(lines[-1]) if lines else 0
    if cursor_col > MAX_COL:
        cursor_col = MAX_COL
    paper_scroll = max(0, cursor_row - visible_rows + 1)
    bell_rung_rows = set()
    view_offset_px = CARRIAGE_DISPLAY_X - PAPER_X - pixel_for_col(cursor_col)

def ask_save_text_and_write(default_ext=".txt"):
    root = tk.Tk(); root.withdraw()
    fname = filedialog.asksaveasfilename(defaultextension=default_ext, filetypes=[("Text files","*.txt"),("All files","*.*")])
    root.destroy()
    if not fname: return None
    try:
        txt = build_text_from_glyphs()
        with open(fname, "w", encoding="utf-8") as f:
            f.write(txt)
        return fname
    except Exception as e:
        print("Save failed:", e)
        return None

def ask_open_file_and_load():
    root = tk.Tk(); root.withdraw()
    fname = filedialog.askopenfilename(filetypes=[("Text files","*.txt"),("All files","*.*")])
    root.destroy()
    if not fname: return None
    try:
        with open(fname, "r", encoding="utf-8") as f:
            txt = f.read()
        load_text_into_glyphs(txt)
        return fname
    except Exception as e:
        print("Open failed:", e)
        return None

def ask_save_png_and_write(surface):
    root = tk.Tk(); root.withdraw()
    fname = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG image","*.png"),("All files","*.*")])
    root.destroy()
    if not fname: return None
    try:
        pygame.image.save(surface, fname)
        return fname
    except Exception as e:
        print("Export PNG failed:", e)
        return None

def action_clear():
    global glyphs, cursor_col, cursor_row, paper_scroll, bell_rung_rows, view_offset_px
    glyphs = []
    cursor_col = 0
    cursor_row = 0
    paper_scroll = 0
    bell_rung_rows.clear()
    view_offset_px = CARRIAGE_DISPLAY_X - PAPER_X - pixel_for_col(cursor_col)

def action_new_page():
    global glyphs, cursor_col, cursor_row, paper_scroll, saved_pages, bell_rung_rows, view_offset_px
    saved_pages.append([dict(g) for g in glyphs])
    glyphs = []
    cursor_col = 0
    cursor_row = 0
    paper_scroll = 0
    bell_rung_rows.clear()
    view_offset_px = CARRIAGE_DISPLAY_X - PAPER_X - pixel_for_col(cursor_col)

def action_save_as():
    fname = ask_save_text_and_write()
    if fname:
        print("Saved to", fname)

def action_open():
    fname = ask_open_file_and_load()
    if fname:
        print("Loaded", fname)

def action_export_png():
    surf = pygame.Surface((PAPER_W, PAPER_H))
    surf.fill(PAPER_COLOR)
    for i in range(visible_rows + 1):
        y = i * LINE_HEIGHT + int(paper_scroll_offset_px)
        pygame.draw.line(surf, (230,230,220), (10, y), (PAPER_W - 10, y), 1)
    min_row = paper_scroll
    max_row = paper_scroll + visible_rows - 1
    base_x = LEFT_MARGIN + int(view_offset_px)
    for g in glyphs:
        if g['row'] < min_row or g['row'] > max_row:
            continue
        x = base_x + (g['col'] * CHAR_WIDTH) + g.get('offset_x', 0)
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

# initialize view offset so initial cursor is centered
view_offset_px = CARRIAGE_DISPLAY_X - PAPER_X - pixel_for_col(cursor_col)

# ---------- helper that performs the action when a pending key is released ----------
def perform_key_action_from_event(pd):
    global cursor_col, cursor_row, paper_scroll, view_offset_px

    k = pd.key
    ch = pd.unicode

    # LEFT key: move left
    if k == pygame.K_LEFT:
        if cursor_col > 0:
            cursor_col -= 1
            animate_view_to_col_blocky(cursor_col, steps=3, step_ms=10)
        return

    # RIGHT key: move right
    if k == pygame.K_RIGHT:
        if cursor_col < OFF_COL:
            cursor_col += 1
            if cursor_col == OFF_COL:
                animate_view_to_col_blocky(OFF_COL, steps=4, step_ms=36, play_thunk_at_end=True, thunk_delay_ms=8)
            else:
                animate_view_to_col_blocky(cursor_col, steps=3, step_ms=10)
        return

    # BACKSPACE
    if k == pygame.K_BACKSPACE:
        if cursor_col == OFF_COL:
            animate_view_to_col_blocky(MAX_COL, steps=3, step_ms=10)
            cursor_col = MAX_COL
        elif cursor_col > 0:
            if authentic_mode:
                cursor_col -= 1
                animate_view_to_col_blocky(cursor_col, steps=3, step_ms=10)
            else:
                remove_col = cursor_col - 1
                # remove ALL glyphs at this (row, col) to fully clear the cell
                new_glyphs = [gg for gg in glyphs if not (gg['row'] == cursor_row and gg['col'] == remove_col)]
                removed = len(new_glyphs) != len(glyphs)
                glyphs[:] = new_glyphs  # update in-place
                # move left (whether or not anything was removed)
                cursor_col = max(0, cursor_col - 1)
                animate_view_to_col_blocky(cursor_col, steps=3, step_ms=36)
        return

    # RETURN / ENTER: snap vertically, then smooth horizontal slide
    if k == pygame.K_RETURN:
        # snap down to next line (immediate)
        cursor_distance = cursor_col # Used for calculating animation duration
        cursor_row += 1
        cursor_col = 0

        # if we've moved past visible area, snap the paper_scroll immediately
        if cursor_row >= paper_scroll + visible_rows:
            paper_scroll = cursor_row - visible_rows + 1
            paper_scroll_offset_px = 0.0

        # redraw once so the vertical snap is visible immediately
        draw()
        pygame.display.flip()

        # then smoothly slide the page so column 0 lines up under the carriage
        print(cursor_col)
        animate_view_to_col_smooth(0, duration_ms=cursor_distance * 25)

        # if the new cursor_row is beyond visible area (already snapped), optionally animate vertical feed
        # (we used snap behavior per your request; if you'd rather animate vertical feed, call animate_paper_scroll_to instead)
        return

    # Printable: for printable keys, the glyph was already appended on KEYDOWN with pending=True.
    # Here we finalize that glyph (clear pending flag), then advance cursor_col and animate view.
    if ch and len(ch) == 1 and k not in MODIFIER_KEYS:
        # find the last pending glyph (should exist)
        for i in range(len(glyphs)-1, -1, -1):
            g = glyphs[i]
            if g.get('pending', False) and g['row'] == cursor_row:
                # finalize it
                g['pending'] = False
                break
        # Now advance cursor_col and animate (do not re-play strike here; it already played on KEYDOWN)
        if cursor_col >= MAX_COL:
            # move off-paper
            cursor_col = OFF_COL
            animate_view_to_col_blocky(OFF_COL, steps=4, step_ms=10, play_thunk_at_end=True, thunk_delay_ms=8)
        else:
            cursor_col += 1
            animate_view_to_col_blocky(cursor_col, steps=3, step_ms=10)
        return

# ---------- main event loop ----------
COMMAND_BAR_H = 96
COMMAND_BAR_Y = H - COMMAND_BAR_H

running = True
while running:
    for ev in pygame.event.get():
        if ev.type == pygame.QUIT:
            running = False

        # animations buffer and repost events internally; ignore processing here while animating
        if animating:
            continue

        # mouse -> command bar
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            mx, my = ev.pos
            if my >= COMMAND_BAR_Y:
                for rect, bid in button_rects:
                    if rect.collidepoint(mx, my):
                        fn = action_map.get(bid)
                        if fn:
                            fn()
                        break
                continue

        # KEYDOWN: for printable keys, draw + strike now; for others, lock pending and wait for KEYUP to act
        if ev.type == pygame.KEYDOWN:
            # Special-case: if the carriage is off-paper, allow movement/backspace/return immediately
            if ev.key in (pygame.K_BACKSPACE, pygame.K_RETURN, pygame.K_LEFT, pygame.K_RIGHT) and cursor_col == OFF_COL:
                # perform immediately (bypass pending lock) so user can come back from off-paper
                # We call the same handler used on KEYUP to keep behavior consistent.
                # Temporarily set a lock indicator for UX, perform action, then clear lock.
                key_locked = True
                locked_key = ev.key
                locked_char_display = pygame.key.name(ev.key)
                # call the same function that performs actions on KEYUP (use the event directly)
                perform_key_action_from_event(ev)
                # release lock (perform_key_action_from_event does animations)
                key_locked = False
                locked_key = None
                locked_char_display = ""
                continue

            # quit
            if ev.key == pygame.K_ESCAPE:
                running = False
                continue

            # Up/Down: immediate view-only
            if ev.key == pygame.K_UP:
                target = max(0, paper_scroll - 1)
                if target != paper_scroll:
                    animate_paper_scroll_to(target, duration_ms=180)
                continue
            if ev.key == pygame.K_DOWN:
                max_row = max(cursor_row, max([g['row'] for g in glyphs], default=0))
                max_scroll = max(0, max_row - visible_rows + 1)
                target = min(max_scroll, paper_scroll + 1)
                if target != paper_scroll:
                    animate_paper_scroll_to(target, duration_ms=180)
                continue

            if ev.key in MODIFIER_KEYS:
                continue

            # If a key is already locked, ignore
            if key_locked:
                continue

            # Printable character: draw immediately and play strike, but do NOT advance cursor or move view until KEYUP.
            if ev.unicode and len(ev.unicode) == 1 and ev.key not in MODIFIER_KEYS:
                # if off-paper, ignore (no strike)
                if cursor_col == OFF_COL:
                    continue

                # normalize whitespace characters so the font doesn't get a control char
                raw_ch = ev.unicode

                # Handle tabs
                if raw_ch == '\t':
                    # Compute spaces needed to next tab stop
                    spaces_needed = TAB_SIZE - (cursor_col % TAB_SIZE)
                    for _ in range(spaces_needed):
                        if cursor_col >= MAX_COL:
                            break  # stop if we run out of room in line
                        strikes = count_strikes_at(cursor_row, cursor_col)
                        base_darkness = random.uniform(0.6, 0.95)
                        darkness = min(1.0, base_darkness + 0.12 * strikes)
                        jitter_x = random.uniform(-0.5, 0.5)
                        jitter_y = random.uniform(-0.5, 0.5)
                        glyphs.append({
                            'char': ' ',
                            'row': cursor_row,
                            'col': cursor_col,
                            'offset_x': jitter_x,
                            'offset_y': jitter_y,
                            'darkness': darkness,
                            'pending': True
                        })
                        cursor_col += 1
                    continue

                # if it's a tab or other whitespace, turn it into a space character.
                if raw_ch.isspace():
                    ch_to_draw = ' '
                else:
                    ch_to_draw = raw_ch

                # Lock and store pending event
                key_locked = True
                locked_key = ev.key
                pending_keydown = ev
                if ev.unicode.isprintable():
                    locked_char_display = ev.unicode
                else:
                    locked_char_display = pygame.key.name(ev.key)

                # compute strike properties at current column
                if cursor_col >= MAX_COL:
                    strikes = count_strikes_at(cursor_row, MAX_COL)
                    if cursor_row not in bell_rung_rows:
                        # ring bell on first contact
                        play_bell()
                        bell_rung_rows.add(cursor_row)
                else:
                    strikes = count_strikes_at(cursor_row, cursor_col)
                    if cursor_col >= cols_per_line - 2 and cursor_row not in bell_rung_rows:
                        play_bell()
                        bell_rung_rows.add(cursor_row)

                # play strike now (on KEYDOWN)
                play_key()

                # append glyph with pending=True so KEYUP can finalize & advance
                base_dark = random.uniform(0.6, 0.95)
                darkness = min(1.0, base_dark + 0.12 * strikes)
                if cursor_col >= MAX_COL:
                    jitter_x = random.randint(-2, 2) if strikes > 0 else random.randint(-1, 1)
                    jitter_y = random.randint(-2, 2) if strikes > 0 else random.randint(-1, 2)
                    col_for_glyph = MAX_COL
                else:
                    jitter_x = random.uniform(-0.5, 0.5)
                    jitter_y = random.uniform(-0.5, 0.5)
                    col_for_glyph = cursor_col

                glyphs.append({
                    'char': ch_to_draw,
                    'row': cursor_row,
                    'col': col_for_glyph,
                    'offset_x': jitter_x,
                    'offset_y': jitter_y,
                    'darkness': darkness,
                    'pending': True
                })
                # do NOT advance cursor_col or move view here
                continue

            # Non-printable keys: accept as pending (lock) and wait for KEYUP to act
            # (Left/Right/Backspace/Return)
            key_locked = True
            locked_key = ev.key
            pending_keydown = ev
            if ev.unicode and len(ev.unicode) == 1 and ev.unicode.isprintable():
                locked_char_display = ev.unicode
            else:
                locked_char_display = pygame.key.name(ev.key)
            # don't perform the action yet
            continue

        # KEYUP: if it's the same locked key, perform its action now
        if ev.type == pygame.KEYUP:
            if ev.key in MODIFIER_KEYS:
                continue
            if key_locked and ev.key == locked_key and pending_keydown is not None:
                pd = pending_keydown
                pending_keydown = None
                # perform the action (this will do animations and play sounds for non-printables;
                # printable case will not replay the strike sound because we already did on KEYDOWN)
                perform_key_action_from_event(pd)
                # release lock after action finishes
                key_locked = False
                locked_key = None
                locked_char_display = ""
            # otherwise ignore unmatched keyup
            continue

    draw()
    pygame.display.flip()
    clock.tick(60)

pygame.quit()
sys.exit()
