# typewriter_mvp_nav_updown.py
# Typewriter: scrolling page, buffered animations, thunk/bell, one-key-at-time,
# up/down navigation added; horizontal cursor bar removed.

import pygame
import random
import sys

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

# Window / paper
W, H = 1000, 700
screen = pygame.display.set_mode((W, H))
pygame.display.set_caption("Typewriter — Up/Down Navigation")
clock = pygame.time.Clock()

PAPER_X, PAPER_Y = 60, 40
PAPER_W, PAPER_H = W - 2*PAPER_X, H - 2*PAPER_Y
PAPER_COLOR = (245, 241, 232)

FONT_NAME = "Courier New"
FONT_SIZE = 28
font = pygame.font.SysFont(FONT_NAME, FONT_SIZE, bold=False)

LINE_HEIGHT = int(FONT_SIZE * 1.6)
CHAR_WIDTH = font.size("M")[0]

LEFT_MARGIN = 20
CARRIAGE_LEFT_PIXEL = PAPER_X + LEFT_MARGIN

# logical cursor position
cursor_col = 0
cursor_row = 0  # absolute row number
cols_per_line = max(10, (PAPER_W - LEFT_MARGIN - 40) // CHAR_WIDTH) + 2
visible_rows = PAPER_H // LINE_HEIGHT

MAX_COL = cols_per_line - 1
OFF_COL = MAX_COL + 1

# paper scroll state
paper_scroll = 0                # how many logical rows scrolled off the top
paper_scroll_offset_px = 0.0    # animated offset (0 normally)

# animated carriage horizontal pixel (for column position)
carriage_px = CARRIAGE_LEFT_PIXEL

# glyph store (absolute rows)
glyphs = []  # dicts: 'char','row','col','offset_x','offset_y','darkness'

# sounds & volumes
KEY_VOL = 0.7
BELL_VOL = 0.9
THUNK_VOL = 0.9

def _make_click_sound():
    if not HAS_NUMPY:
        return None
    sr = 22050
    length = int(0.02 * sr)
    noise = __import__('numpy').random.uniform(-1,1,length)
    env = __import__('numpy').linspace(1.0,0.0,length)
    data = (noise * env * 0.3 * (2**15-1)).astype(__import__('numpy').int16)
    return pygame.sndarray.make_sound(__import__('numpy').column_stack([data,data]))

def _make_bell_sound():
    if not HAS_NUMPY:
        return None
    sr = 22050
    t = __import__('numpy').linspace(0, 0.14, int(0.14*sr))
    freq = 1500.0
    tone = 0.6 * __import__('numpy').sin(2*__import__('numpy').pi*freq*t) * __import__('numpy').exp(-8*t)
    data = (tone * (2**15-1)).astype(__import__('numpy').int16)
    return pygame.sndarray.make_sound(__import__('numpy').column_stack([data,data]))

def _make_thunk_sound():
    if not HAS_NUMPY:
        return None
    sr = 22050
    t = __import__('numpy').linspace(0, 0.07, int(0.07*sr))
    freq = 110.0
    tone = 0.9 * __import__('numpy').sin(2*__import__('numpy').pi*freq*t) * __import__('numpy').exp(-18*t)
    click = 0.08 * __import__('numpy').sin(2*__import__('numpy').pi*2200*t) * __import__('numpy').exp(-250*t)
    data = (tone + click) * (2**15-1)
    data = data.astype(__import__('numpy').int16)
    return pygame.sndarray.make_sound(__import__('numpy').column_stack([data,data]))

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

# bell tracking: ring once per absolute row
bell_rung_rows = set()

# small font for status
small_font = pygame.font.SysFont(FONT_NAME, 16)

# state flags
key_locked = False
locked_key = None
locked_char_display = ""
animating = False
animation_cancel = False

# modifier keys that shouldn't lock
MODIFIER_KEYS = {
    pygame.K_LSHIFT, pygame.K_RSHIFT,
    pygame.K_LCTRL, pygame.K_RCTRL,
    pygame.K_LALT, pygame.K_RALT,
    getattr(pygame, 'K_LMETA', None), getattr(pygame, 'K_RMETA', None),
    getattr(pygame, 'K_CAPSLOCK', None), getattr(pygame, 'K_NUMLOCK', None)
}
MODIFIER_KEYS = {k for k in MODIFIER_KEYS if k is not None}

def pixel_for_col(col_index):
    if col_index <= MAX_COL:
        return PAPER_X + LEFT_MARGIN + col_index * CHAR_WIDTH
    else:
        return PAPER_X + PAPER_W + 18

def row_vis_index(row_index):
    """Return the index (0..visible_rows-1) of the absolute row on the visible paper."""
    return row_index - paper_scroll

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
        frac = (now - start_time) / max(1, end_time - start_time)
        frac = 1 - (1 - frac) * (1 - frac)
        carriage_px = start_px + (end_px - start_px) * frac
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
    for ev in local_buffer:
        try:
            pygame.event.post(ev)
        except Exception:
            pass

def animate_paper_scroll_to(target_scroll, duration_ms=260):
    """
    Animate paper_scroll to target_scroll (integer). Positive target_scroll means content moves up.
    Buffers events during animation and reposts them afterwards.
    """
    global animating, paper_scroll, paper_scroll_offset_px, animation_cancel
    # clamp target_scroll >= 0
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
        frac = (now - start_time) / max(1, end_time - start_time)
        frac = 1 - (1 - frac) * (1 - frac)
        paper_scroll_offset_px = start_offset + (end_offset - start_offset) * frac
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
    # finalize
    paper_scroll_offset_px = 0.0
    paper_scroll = target_scroll
    animating = False
    animation_cancel = False
    for ev in local_buffer:
        try:
            pygame.event.post(ev)
        except Exception:
            pass

def ensure_cursor_visible(animated=True):
    """
    Ensure cursor_row is visible in the window. If it's above or below visible area,
    compute new target_scroll and either animate to it or set it instantly.
    """
    global paper_scroll
    top = paper_scroll
    bottom = paper_scroll + visible_rows - 1
    if cursor_row < top:
        target = cursor_row
    elif cursor_row > bottom:
        target = cursor_row - visible_rows + 1
    else:
        return  # already visible
    if animated:
        animate_paper_scroll_to(target, duration_ms=220)
    else:
        paper_scroll = target

def draw():
    screen.fill((30,30,30))
    pygame.draw.rect(screen, PAPER_COLOR, (PAPER_X, PAPER_Y, PAPER_W, PAPER_H))

    # draw ruled lines with current scroll offset
    for i in range(visible_rows + 1):
        y = PAPER_Y + i * LINE_HEIGHT + paper_scroll_offset_px
        if PAPER_Y <= y <= PAPER_Y + PAPER_H:
            pygame.draw.line(screen, (230,230,220), (PAPER_X + 10, y), (PAPER_X + PAPER_W - 10, y), 1)

    # draw visible glyphs only
    min_row = paper_scroll
    max_row = paper_scroll + visible_rows - 1
    for g in glyphs:
        if g['row'] < min_row or g['row'] > max_row:
            continue
        x = PAPER_X + LEFT_MARGIN + g['col'] * CHAR_WIDTH + g.get('offset_x', 0)
        y = PAPER_Y + (g['row'] - paper_scroll) * LINE_HEIGHT + g.get('offset_y', 0) + paper_scroll_offset_px
        text_surf = font.render(g['char'], True, (0,0,0))
        tmp = pygame.Surface(text_surf.get_size(), pygame.SRCALPHA)
        darkness = max(0.0, min(1.0, g.get('darkness', 1.0)))
        alpha = int(80 + 175 * darkness)
        text_surf.set_alpha(alpha)
        tmp.blit(text_surf, (0,0))
        ghost = font.render(g['char'], True, (0,0,0))
        ghost.set_alpha(int(alpha * 0.35))
        for ox, oy in [(-1,0),(1,0),(0,-1),(0,1),(-1,-1),(1,1)]:
            tmp.blit(ghost, (ox, oy))
        screen.blit(tmp, (x, y))

    # draw carriage tick limited to the current visible line
    cursor_vis = cursor_row - paper_scroll
    if 0 <= cursor_vis < visible_rows:
        # vertical short tick near the baseline of the line
        line_top = PAPER_Y + cursor_vis * LINE_HEIGHT + paper_scroll_offset_px
        tick_h = int(LINE_HEIGHT * 0.6)
        tick_top = int((line_top + line_top + LINE_HEIGHT) / 2 - tick_h/2)
        tick_bottom = tick_top + tick_h
        pygame.draw.line(screen, (90,20,20), (carriage_px, tick_top), (carriage_px, tick_bottom), 3)

    # locked-key indicator
    if key_locked:
        box_w, box_h = 220, 44
        bx = W - box_w - 20
        by = 20
        pygame.draw.rect(screen, (40,40,40), (bx, by, box_w, box_h), border_radius=6)
        label = small_font.render("Key down: " + (locked_char_display or ""), True, (220,220,220))
        screen.blit(label, (bx+12, by+10))

def count_strikes_at(row, col):
    return sum(1 for g in glyphs if g['row'] == row and g['col'] == col)

def pretty_key_name(ev):
    ch = ev.unicode
    if ch and len(ch) == 1 and ch.isprintable():
        return ch
    return pygame.key.name(ev.key)

running = True
carriage_px = pixel_for_col(cursor_col)

while running:
    for ev in pygame.event.get():
        if ev.type == pygame.QUIT:
            running = False

        if animating:
            # animations buffer events internally and repost them, so ignore processing here
            continue

        if ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_ESCAPE:
                running = False
                continue

            if ev.key in MODIFIER_KEYS:
                continue

            if key_locked:
                # still holding a key down; ignore new keydowns
                continue

            key_locked = True
            locked_key = ev.key
            locked_char_display = pretty_key_name(ev)

            # vertical navigation
            if ev.key == pygame.K_UP:
                if cursor_row > 0:
                    cursor_row -= 1
                    ensure_cursor_visible(animated=True)
                continue

            if ev.key == pygame.K_DOWN:
                cursor_row += 1
                ensure_cursor_visible(animated=True)
                continue

            # return advances row and may feed paper
            if ev.key == pygame.K_RETURN:
                play_key()
                # carriage return: animate carriage back to left, advance row
                animate_carriage_to_col(0, duration_ms=300)
                cursor_col = 0
                cursor_row += 1
                if cursor_row >= paper_scroll + visible_rows:
                    animate_paper_scroll_to(cursor_row - visible_rows + 1, duration_ms=260)
                continue

            if ev.key == pygame.K_BACKSPACE:
                if cursor_col == OFF_COL:
                    play_key()
                    animate_carriage_to_col(MAX_COL, duration_ms=140)
                    cursor_col = MAX_COL
                elif cursor_col > 0:
                    play_key()
                    cursor_col -= 1
                    animate_carriage_to_col(cursor_col, duration_ms=120)
                continue

            if ev.key == pygame.K_LEFT:
                if cursor_col > 0:
                    play_key()
                    cursor_col -= 1
                    animate_carriage_to_col(cursor_col, duration_ms=120)
                continue

            if ev.key == pygame.K_RIGHT:
                if cursor_col < OFF_COL:
                    play_key()
                    cursor_col += 1
                    if cursor_col == OFF_COL:
                        animate_carriage_to_col(OFF_COL, duration_ms=200, play_thunk_at_end=True, thunk_delay_ms=10)
                    else:
                        animate_carriage_to_col(cursor_col, duration_ms=120)
                continue

            # printable character
            ch = ev.unicode
            if not ch or len(ch) != 1:
                continue

            if cursor_col == OFF_COL:
                continue

            if cursor_col >= MAX_COL:
                strikes = count_strikes_at(cursor_row, MAX_COL)
                if cursor_row not in bell_rung_rows:
                    play_bell()
                    bell_rung_rows.add(cursor_row)
                play_key()
                base_darkness = random.uniform(0.6, 0.95)
                darkness = min(1.0, base_darkness + 0.12 * strikes)
                jitter_x = random.randint(-2, 2) if strikes > 0 else random.randint(-1, 1)
                jitter_y = random.randint(-2, 2) if strikes > 0 else random.randint(-1, 2)
                glyphs.append({
                    'char': ch,
                    'row': cursor_row,
                    'col': MAX_COL,
                    'offset_x': jitter_x,
                    'offset_y': jitter_y,
                    'darkness': darkness
                })
                cursor_col = OFF_COL
                animate_carriage_to_col(OFF_COL, duration_ms=240, play_thunk_at_end=True, thunk_delay_ms=10)
            else:
                strikes = count_strikes_at(cursor_row, cursor_col)
                if cursor_col >= cols_per_line - 2 and cursor_row not in bell_rung_rows:
                    play_bell()
                    bell_rung_rows.add(cursor_row)
                play_key()
                base_darkness = random.uniform(0.6, 0.95)
                darkness = min(1.0, base_darkness + 0.12 * strikes)
                jitter_x = random.uniform(-0.5, 0.5)
                jitter_y = random.uniform(-0.5, 0.5)
                glyphs.append({
                    'char': ch,
                    'row': cursor_row,
                    'col': cursor_col,
                    'offset_x': jitter_x,
                    'offset_y': jitter_y,
                    'darkness': darkness
                })
                cursor_col += 1
                animate_carriage_to_col(cursor_col, duration_ms=110)

        elif ev.type == pygame.KEYUP:
            if ev.key in MODIFIER_KEYS:
                continue
            if key_locked and ev.key == locked_key:
                key_locked = False
                locked_key = None
                locked_char_display = ""

    draw()
    pygame.display.flip()
    clock.tick(60)

pygame.quit()
sys.exit()
