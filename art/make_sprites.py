#!/usr/bin/env python3
"""Draws the Night Kettles sprite sheets. Pure Python, no dependencies.

Every sprite is built from a few shapes, flat-shaded, and wrapped in a 1px
outline. The shapes are laid out in design units and rasterised at Z sprite
pixels per unit, so Z alone decides how fine the pixels look.

    python3 art/make_sprites.py                 # write the sheets, refresh the preview
    python3 art/make_sprites.py --sheet out.png # also write an enlarged contact sheet

Sheet layout, in design units (the engines multiply by their FINE, which
must equal Z here):

    kettle.png   4 frames, 56x48   row = colourway * 3 + tier
    dripper.png  4 frames, 56x48   row = colourway * 3 + tier
    press.png    4 frames, 56x48   row = colourway * 3 + tier
    mill.png     4 frames, 56x48   row = colourway * 3 + tier
    grinder.png  4 frames, 56x48   row = colourway * 3 + tier
    cup.png      4 frames, 40x36   row = (accent * 4 + roast) * 3 + tier
    bean.png     4 frames, 16x16   row = roast * 3 + tier
    puff.png     5 frames, 16x16   row = tier
    drop.png     5 frames, 16x16   row = tier

Tier 0 is the far, dimmed layer; tier 2 is the nearest. The engines count the
colourways (and the cup's accents) from each sheet, so adding one is just
another line here.
"""
import base64
import math
import os
import re
import struct
import sys
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESOURCES = os.path.join(ROOT, 'saver', 'Resources')
PREVIEW = os.path.join(ROOT, 'preview', 'index.html')

Z = 1.5          # sprite pixels per design unit: raise it for finer pixels
ONE = 1 / Z      # one sprite pixel, in design units


def rgb(h):
    h = h.lstrip('#')
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def mix(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def unit(t):
    return max(0.0, min(1.0, t))


def px(v):
    """The sprite pixel a design coordinate falls in, for one-pixel patterns."""
    return int(v * Z)


NIGHT = rgb('#070917')
TIER_DIM = (0.52, 0.26, 0.0)  # how far each tier's colours sink into the night


# ---------------------------------------------------------------- raster ----

class Grid:
    """A small RGB image; None is transparent."""

    def __init__(self, w, h):
        self.w, self.h = w, h
        self.px = [[None] * w for _ in range(h)]

    def set(self, x, y, c):
        if 0 <= x < self.w and 0 <= y < self.h:
            self.px[y][x] = c

    def blit(self, src, ox, oy, dim=0.0):
        for y in range(src.h):
            for x in range(src.w):
                c = src.px[y][x]
                if c is not None:
                    self.set(ox + x, oy + y, mix(c, NIGHT, dim) if dim else c)

    def crop(self, x, y, w, h):
        out = Grid(w, h)
        out.px = [row[x:x + w] for row in self.px[y:y + h]]
        return out


def cell(w, h):
    """An empty sprite cell, w x h design units."""
    assert (w * Z).is_integer() and (h * Z).is_integer(), 'cells must be whole pixels'
    return Grid(int(w * Z), int(h * Z))


def part(g, inside, shade, outline=None):
    """Composite one shape onto g: a 1px outline, then the shaded fill.

    inside and shade are given design coordinates, sampled at pixel centres.
    """
    xs = [(i + 0.5) / Z for i in range(g.w)]
    ys = [(j + 0.5) / Z for j in range(g.h)]
    mask = [[inside(x, y) for x in xs] for y in ys]

    def filled(i, j):
        return 0 <= i < g.w and 0 <= j < g.h and mask[j][i]

    for j in range(g.h):
        for i in range(g.w):
            if mask[j][i]:
                g.px[j][i] = shade(xs[i], ys[j])
            elif outline and (filled(i + 1, j) or filled(i - 1, j)
                              or filled(i, j + 1) or filled(i, j - 1)):
                g.px[j][i] = outline


def ellipse(cx, cy, rx, ry):
    return lambda x, y: ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1


def box(x0, y0, x1, y1):
    return lambda x, y: x0 <= x <= x1 and y0 <= y <= y1


def capsule(x0, y0, x1, y1, r0, r1):
    """A fat line from (x0,y0) to (x1,y1) whose radius tapers r0 -> r1."""
    dx, dy = x1 - x0, y1 - y0
    len2 = dx * dx + dy * dy

    def inside(x, y):
        t = unit(((x - x0) * dx + (y - y0) * dy) / len2)
        r = r0 + (r1 - r0) * t
        return (x - x0 - dx * t) ** 2 + (y - y0 - dy * t) ** 2 <= r * r

    return inside


def chain(points, r0, r1):
    """A bent tube through the points, tapering r0 -> r1 along its length."""
    n = len(points) - 1
    links = [capsule(*points[i], *points[i + 1],
                     r0 + (r1 - r0) * i / n, r0 + (r1 - r0) * (i + 1) / n) for i in range(n)]
    return lambda x, y: any(link(x, y) for link in links)


def tones(colours):
    return tuple(rgb(c) for c in colours)


# ----------------------------------------------------------------- wings ----

BW, BH = 56, 48      # everything with wings shares this cell
FLAP = (62, 28, -8, -42)   # leading edge per frame, degrees above straight-back
WING = tones(('#f6f8ff', '#bcc7e8', '#5d6a99'))       # fill, shade, outline
FAR_WING = tones(('#a9b4d8', '#8591bb', '#4a557f'))


def draw_wing(g, jx, jy, angle, pal, size=1.0):
    """A fan of four feathers from the shoulder joint, longest on the leading edge.

    The trailing feathers sit in the leading ones' shadow, which is what gives
    the fan its form; the outlines pick out the individual feathers.
    """
    fill, shade, line = pal
    spread = max(9.0, abs(angle) * 0.32)
    toward_back = 1 if angle >= 0 else -1
    feather_tones = (fill, fill, mix(fill, shade, 0.5), shade)
    for i, length in reversed(list(enumerate((16, 14, 11.5, 9)))):
        a = math.radians(angle - toward_back * spread * i)
        length *= size
        feather = capsule(jx, jy, jx - math.cos(a) * length, jy - math.sin(a) * length,
                          2.7 * size, 2.0 * size)
        part(g, feather, lambda x, y, tone=feather_tones[i]: tone, line)
    part(g, ellipse(jx - 0.5, jy, 3.4 * size, 3.0 * size), lambda x, y: fill, line)


def far_wing(g, jx, jy, frame):
    if FLAP[frame] > 0:   # it only shows while it is raised above the body
        draw_wing(g, jx, jy, FLAP[frame] + 14, FAR_WING, 0.85)


def near_wing(g, jx, jy, frame):
    draw_wing(g, jx, jy, FLAP[frame], WING)


# ------------------------------------------------- the pour-over kettle ----

K_CX, K_TOP, K_BOT = 27, 21, 41
GOOSENECK = ((K_CX + 11, 37.5), (K_CX + 17, 36), (K_CX + 20, 31),
             (K_CX + 19.5, 26), (K_CX + 21.5, 22.5), (K_CX + 25.5, 21.5))
GRIP, GRIP_LIGHT, GRIP_LINE = tones(('#5a6185', '#9aa3c8', '#1e2138'))

KETTLES = (  # mid, light, dark, outline
    ('#c8743a', '#f0aa72', '#8f4a24', '#472213'),   # copper
    ('#a9b4c9', '#e6ebf5', '#6d7892', '#343c55'),   # steel
    ('#6fa98a', '#b4dcc0', '#457a62', '#213f38'),   # sage
    ('#d9442f', '#f58a6b', '#9a2732', '#4a1626'),   # tomato
    ('#e5aa2b', '#f9d978', '#b0731f', '#5b3516'),   # mustard
    ('#1fa39b', '#72dcc9', '#14707a', '#0b3848'),   # teal
    ('#eadfc6', '#fffaf0', '#b9a888', '#5e5340'),   # cream
    ('#e58aa6', '#f9c3d2', '#b0577a', '#5c2440'),   # blush
    ('#6c84e0', '#a9bcf8', '#4453ad', '#232a63'),   # periwinkle
)
SPEC = rgb('#fff6ea')


def kettle_hw(y):
    """Half-width of the kettle body: a straight-sided taper."""
    return 9.5 + 4.5 * unit((y - K_TOP) / (K_BOT - K_TOP)) - (1.0 if y > K_BOT - 1 else 0.0)


def draw_kettle(frame, colours):
    mid, light, dark, line = tones(colours)
    g = cell(BW, BH)
    far_wing(g, K_CX - 7, 25, frame)

    # The handle hangs off the back.
    top_bar = capsule(K_CX - 9, 23.5, K_CX - 15.5, 23.5, 1.5, 1.5)
    drop_bar = capsule(K_CX - 15.5, 23.5, K_CX - 16.5, 34, 1.5, 1.5)
    part(g, lambda x, y: top_bar(x, y) or drop_bar(x, y),
         lambda x, y: GRIP_LIGHT if y < 23 else GRIP, GRIP_LINE)

    neck = chain(GOOSENECK, 1.9, 1.3)
    part(g, neck, lambda x, y: mid if neck(x, y - ONE) else light, line)

    def metal(x, y):
        u = (x - K_CX) / kettle_hw(y)
        v = (y - K_TOP) / (K_BOT - K_TOP)
        if v > 0.92 or u < -0.45:
            return dark
        if 0.2 < u < 0.52 and v > 0.14:
            return SPEC if v < 0.34 else light
        return mid
    part(g, lambda x, y: K_TOP <= y <= K_BOT and abs(x - K_CX) <= kettle_hw(y), metal, line)

    part(g, ellipse(K_CX, K_TOP, 9.5, 2.4), lambda x, y: light if x > K_CX - 3 else mid, line)
    part(g, ellipse(K_CX, K_TOP - 3.4, 2.0, 1.9),
         lambda x, y: GRIP_LIGHT if x >= K_CX and y < K_TOP - 3 else GRIP, GRIP_LINE)

    near_wing(g, K_CX - 3, 30, frame)
    return g


# ------------------------------------------------------ the cone dripper ----

D_CX, D_RIM, D_TIP = 30, 18, 33
PAPER, PAPER_SHADE, PAPER_LINE = tones(('#f7f3e8', '#cfc9c4', '#6a6577'))
GROUNDS, GROUNDS_LIGHT = tones(('#4a2410', '#7a4520'))

DRIPPERS = (  # mid, light, dark, outline
    ('#d43a2f', '#f47e68', '#96242c', '#481424'),   # red
    ('#e9e5dc', '#ffffff', '#b3aeb8', '#55546a'),   # white ceramic
    ('#c8743a', '#f0aa72', '#8f4a24', '#472213'),   # copper
    ('#86b6d6', '#cfe8f6', '#4f7fa3', '#243f5c'),   # glass
)


def cone_hw(y):
    return max(3.5, 12 - 8.5 * unit((y - D_RIM) / (D_TIP - D_RIM)))


def draw_dripper(frame, colours):
    mid, light, dark, line = tones(colours)
    g = cell(BW, BH)
    far_wing(g, D_CX - 9, 22, frame)

    ring_outer, ring_inner = ellipse(D_CX - 12.5, 25, 3.8, 3.8), ellipse(D_CX - 12.5, 25, 1.8, 1.8)
    part(g, lambda x, y: ring_outer(x, y) and not ring_inner(x, y), lambda x, y: mid, line)

    # The plate it would stand on, were it standing on anything.
    part(g, ellipse(D_CX, 35.5, 10.5, 2.8), lambda x, y: dark if y >= 36 else mid, line)

    # A paper filter stands proud of the rim, with the coffee bed inside it.
    mouth = ellipse(D_CX, 14, 13, 3.2)
    part(g, lambda x, y: mouth(x, y) or (14 <= y <= 19 and abs(x - D_CX) <= 13 - (y - 14) * 0.2),
         lambda x, y: PAPER_SHADE if x < D_CX - 7 else PAPER, PAPER_LINE)
    part(g, ellipse(D_CX, 14.3, 10.6, 2.0),
         lambda x, y: GROUNDS_LIGHT if (px(x) * 3 + px(y) * 5) % 7 == 0 else GROUNDS)

    def cone(x, y):
        u = (x - D_CX) / cone_hw(y)
        if y < D_RIM + 1:
            return light                                    # the rim
        if u < -0.5:
            return dark
        if (px(x) + px(y)) % round(6 * Z) == 0 and u < 0.8:
            return light                                    # the spiral ribs
        return mid
    part(g, lambda x, y: D_RIM <= y <= D_TIP + 2 and abs(x - D_CX) <= cone_hw(y), cone, line)

    near_wing(g, D_CX - 5, 26, frame)
    return g


# ---------------------------------------------------------- the plunger ----

P_CX, P_TOP, P_BOT = 31, 19, 38
PLUNGE = (0, 2, 4, 6)     # the plunger pumps in time with the wings
SEAL, SEAL_LIGHT = tones(('#2a2d3d', '#5b6078'))
MARK = rgb('#eef1fb')     # the measure marks printed down the chamber
MARK_ROWS = {px(23.5), px(28.5), px(33.5)}
CAP, CAP_LIGHT, CAP_LINE = tones(('#3a3e52', '#666c88', '#16182a'))
COFFEE, COFFEE_LIGHT = tones(('#6a3414', '#a8642e'))

PRESSES = (  # mid, light, dark, outline
    ('#8d95a8', '#c7cdda', '#5d6478', '#2b3040'),   # smoke
    ('#5f93dd', '#a8c8f4', '#3a62a6', '#1c2f5a'),   # blue
    ('#6fbf85', '#b4e6bf', '#438a5a', '#1e4530'),   # green
    ('#dba63f', '#f5d58a', '#a3721f', '#523610'),   # amber
)


def draw_press(frame, colours):
    mid, light, dark, line = tones(colours)
    g = cell(BW, BH)
    depth = PLUNGE[frame]
    far_wing(g, P_CX - 7, 24, frame)

    part(g, box(P_CX - 4.5, 7 + depth, P_CX + 4.5, P_TOP + 1),
         lambda x, y: light if x >= P_CX + 1 else mid, line)
    part(g, box(P_CX - 7.5, 5 + depth, P_CX + 7.5, 7.6 + depth),
         lambda x, y: dark if x < P_CX - 4 else mid, line)

    seal = 25 + depth

    def chamber(x, y):
        streak = P_CX + 1 <= x < P_CX + 4
        if x >= P_CX + 4.4 and px(y) in MARK_ROWS:
            return MARK
        if seal <= y < seal + 3:
            return SEAL_LIGHT if x >= P_CX + 2 else SEAL
        if y >= seal + 3:                                   # the coffee being pressed
            return COFFEE_LIGHT if streak else COFFEE
        if x < P_CX - 3:
            return dark
        return light if streak else mid
    part(g, box(P_CX - 6.5, P_TOP, P_CX + 6.5, P_BOT), chamber, line)

    part(g, box(P_CX - 8.5, P_TOP - 1, P_CX + 8.5, P_TOP + 1.6),
         lambda x, y: dark if x < P_CX - 4 else mid, line)
    part(g, box(P_CX - 8.5, P_BOT - 0.4, P_CX + 8.5, P_BOT + 4),
         lambda x, y: CAP_LIGHT if px(x) % 2 == 0 and y > P_BOT + 0.7 else CAP, CAP_LINE)

    near_wing(g, P_CX - 4, 28, frame)
    return g


# ----------------------------------------------------- the hand grinder ----
# A box mill: a wooden box with a drawer for the grounds, a metal dome for
# the beans, and a crank that goes round as it flies.

M_CX = 30
CRANK = (1.0, 0.5, -0.5, -1.0)    # how far round the crank is, seen side-on

MILLS = (  # wood, then metal: each mid, light, dark, outline
    (('#8a5a34', '#b98452', '#5e3a20', '#2e1a0e'), ('#d9a441', '#f7d98a', '#9a6f22', '#4d3510')),   # walnut and brass
    (('#d2a56c', '#efcf9c', '#a3773f', '#553a1c'), ('#a9b4c9', '#e6ebf5', '#6d7892', '#343c55')),   # beech and steel
    (('#b8392f', '#e06a58', '#7e2226', '#3f1118'), ('#a9b4c9', '#e6ebf5', '#6d7892', '#343c55')),   # painted red and steel
    (('#56617e', '#8894b4', '#394260', '#1b2036'), ('#c8743a', '#f0aa72', '#8f4a24', '#472213')),   # slate and copper
)


def draw_mill(frame, colours):
    (wood, wood_light, wood_dark, wood_line), (metal, metal_light, metal_dark, metal_line) = (
        tones(c) for c in colours)
    g = cell(BW, BH)
    far_wing(g, M_CX - 10, 27, frame)

    # The crank: an arm out from the spindle, with an upright wooden grip.
    tip = M_CX + 11 * CRANK[frame]
    part(g, capsule(tip, 19.2, tip, 14.6, 1.5, 1.8),
         lambda x, y: wood_light if x > tip else wood, wood_line)
    part(g, capsule(M_CX, 19.8, tip, 19.8, 0.9, 0.9),
         lambda x, y: metal_light if y < 19.8 else metal, metal_line)
    part(g, box(M_CX - 1.4, 18.6, M_CX + 1.4, 22), lambda x, y: metal, metal_line)

    dome = ellipse(M_CX, 27.5, 7.6, 6.4)

    def dome_shade(x, y):
        u = (x - M_CX) / 7.6
        if u < -0.45:
            return metal_dark
        if 0.2 < u < 0.55:
            return SPEC if y < 24 else metal_light
        return metal
    part(g, lambda x, y: y <= 27.5 and dome(x, y), dome_shade, metal_line)

    def box_shade(x, y):
        if y < 28.3:
            return wood_light                                   # the top edge
        if x < M_CX - 5.5:
            return wood_dark
        if px(y) % 5 == 2 and (px(x) * 3 + px(y) * 7) % 13 < 5:
            return mix(wood, wood_dark, 0.45)                   # a little grain
        return wood
    part(g, box(M_CX - 9, 27, M_CX + 9, 41), box_shade, wood_line)
    part(g, box(M_CX - 10.2, 40.2, M_CX + 10.2, 42.2), lambda x, y: wood_dark, wood_line)

    # The drawer the grounds fall into.
    part(g, box(M_CX - 5.5, 31.5, M_CX + 5.5, 37.5),
         lambda x, y: wood_light if y < 32.6 else wood, wood_line)
    part(g, ellipse(M_CX, 34.6, 1.3, 1.3),
         lambda x, y: metal_light if x > M_CX and y < 34.6 else metal, metal_line)

    near_wing(g, M_CX - 6, 31, frame)
    return g


# ------------------------------------------------- the electric grinder ----
# A burr grinder: a hopper of beans on top, a dial, a bin for the grounds,
# and its flex trailing behind with the plug still on.

G_CX = 31
SWAY = (-0.8, -0.3, 0.3, 0.8)     # the flex wags as it flies
GLASS, GLASS_LIGHT, GLASS_LINE = tones(('#9fbcd6', '#d9eaf7', '#3e587a'))
HOPPER_BEANS = tones(('#9a6230', '#5e3818'))
BIN, BIN_LIGHT, BIN_LINE = tones(('#3a4258', '#6f7b98', '#171b2c'))
PRONG = rgb('#e6ebf5')
LAMP = rgb('#7cf29a')

GRINDERS = (  # mid, light, dark, outline
    ('#aab3c6', '#e3e8f2', '#6f7a94', '#353d56'),   # silver
    ('#eadfc6', '#fffaf0', '#b9a888', '#5e5340'),   # cream
    ('#d9442f', '#f58a6b', '#9a2732', '#4a1626'),   # tomato
    ('#5c79b8', '#9bb4e6', '#3c5288', '#1c2a4e'),   # slate blue
)


def hopper_hw(y):
    return 8.5 - 2.5 * unit((y - 12) / 11)


def draw_grinder(frame, colours):
    mid, light, dark, line = tones(colours)
    g = cell(BW, BH)
    far_wing(g, G_CX - 9, 26, frame)

    sway = SWAY[frame]
    flex = chain(((G_CX - 8, 40), (G_CX - 12, 42.6), (G_CX - 16, 41.2 + sway),
                  (G_CX - 19.6, 43 + sway)), 0.75, 0.75)
    for prong in (42.2, 43.8):
        part(g, box(G_CX - 25.4, prong + sway - 0.34, G_CX - 22.6, prong + sway + 0.34),
             lambda x, y: PRONG)
    part(g, flex, lambda x, y: GRIP, GRIP_LINE)
    part(g, box(G_CX - 23, 41.3 + sway, G_CX - 19.6, 44.7 + sway),
         lambda x, y: GRIP_LIGHT if y < 42.4 + sway else GRIP, GRIP_LINE)

    def hopper(x, y):
        if G_CX + 2.4 <= x < G_CX + 4:
            return GLASS_LIGHT                                  # light on the glass
        if y >= 15.5:                                           # the beans, jiggling
            return HOPPER_BEANS[0 if (px(x) * 5 + px(y) * 3 + frame * 2) % 7 < 3 else 1]
        return GLASS
    part(g, lambda x, y: 12 <= y <= 23.5 and abs(x - G_CX) <= hopper_hw(y), hopper, GLASS_LINE)
    part(g, box(G_CX - 9, 10.4, G_CX + 9, 12.4), lambda x, y: light if x > G_CX + 2 else mid, line)

    def body_shade(x, y):
        if x < G_CX - 4.5:
            return dark
        return light if G_CX + 5 <= x < G_CX + 6.6 else mid
    part(g, lambda x, y: 24 <= y <= 42 and abs(x - G_CX) <= 8 - max(0.0, 25.6 - y) ** 2 * 0.5,
         body_shade, line)
    part(g, box(G_CX - 6.5, 22.6, G_CX + 6.5, 24.6), lambda x, y: dark, line)
    part(g, box(G_CX - 9, 41.2, G_CX + 9, 43), lambda x, y: dark, line)

    # The grind dial, a power lamp, and the bin of grounds.
    part(g, ellipse(G_CX + 3, 28.5, 2.1, 2.1),
         lambda x, y: dark if abs(x - (G_CX + 3)) < 0.45 and y < 28.5 else light, line)
    part(g, box(G_CX - 0.9, 27.9, G_CX + 0.3, 29.1), lambda x, y: LAMP)

    def bin_shade(x, y):
        if y > 36.2:
            return GROUNDS_LIGHT if (px(x) * 3 + px(y) * 5) % 7 == 0 else GROUNDS
        return BIN_LIGHT if G_CX + 2 <= x < G_CX + 3.4 else BIN
    part(g, box(G_CX - 5.5, 32.4, G_CX + 5.5, 40), bin_shade, BIN_LINE)

    near_wing(g, G_CX - 5, 30, frame)
    return g


# ------------------------------------------------------------------- cup ----

CW, CH = 40, 36
CUP_X = 20
PORCELAIN, PORCELAIN_SHADE, PORCELAIN_LINE = tones(('#f4f1ea', '#c6c3d8', '#55577a'))
GLOW = tones(('#8fefff', '#3fa9e6', '#2a5fb4'))
STEAM = tones(('#c3cae6', '#7f89b3'))
ACCENTS = (  # the stripe round the cup and its saucer
    '#2f9a72',   # green
    '#3d5fd6',   # cobalt
    '#d9442f',   # tomato
    '#e5aa2b',   # mustard
    '#1fa39b',   # teal
    '#c9558f',   # plum
)
ROASTS = (  # coffee, crema
    ('#8a4a1e', '#d49a5a'),   # light
    ('#6a3414', '#bd7f45'),   # medium
    ('#4a2410', '#9c6436'),   # dark
    ('#30170c', '#7a4c2a'),   # french
)
CUPS = tuple((accent, roast) for accent in ACCENTS for roast in ROASTS)


def draw_cup(frame, look):
    stripe, (coffee, crema) = rgb(look[0]), tones(look[1])
    g = cell(CW, CH)

    # The saucer is a flying saucer: a shimmer of lift underneath.
    for j in range(px(32), px(35)):
        t = (j / Z - 32) / 3
        half = (7.5 - 5 * t) * Z
        for i in range(int(CUP_X * Z - half), int(CUP_X * Z + half) + 1):
            if (i + j + frame) % 2 == 0:
                g.set(i, j, GLOW[min(2, int(t * 3))])

    plate, lip = ellipse(CUP_X, 26, 15.5, 4.6), ellipse(CUP_X, 27.3, 15.5, 4.6)

    def saucer_shade(x, y):
        r = math.hypot((x - CUP_X) / 15.5, (y - 26) / 4.6)
        if r > 1:
            return PORCELAIN_SHADE
        return stripe if 0.72 < r < 0.9 else PORCELAIN
    part(g, lambda x, y: plate(x, y) or lip(x, y), saucer_shade, PORCELAIN_LINE)

    ring_outer, ring_inner = ellipse(10.5, 18.5, 3.9, 3.9), ellipse(10.5, 18.5, 1.8, 1.8)
    part(g, lambda x, y: ring_outer(x, y) and not ring_inner(x, y),
         lambda x, y: PORCELAIN, PORCELAIN_LINE)

    rim, surface, middle = ellipse(CUP_X, 14, 9.5, 3.0), ellipse(CUP_X, 14.3, 7.8, 1.9), ellipse(CUP_X, 14.4, 6.7, 1.35)

    def bowl_hw(y):
        t = unit((y - 14) / 11.5)
        return 4.5 + 5.0 * math.sqrt(1 - t * t)

    def cup_shade(x, y):
        if rim(x, y):
            if surface(x, y):
                return coffee if middle(x, y) else mix(coffee, crema, 0.7)
            return PORCELAIN_SHADE if y < 14 else PORCELAIN
        u = (x - CUP_X) / bowl_hw(y)
        if abs(y - (17.2 + 1.5 * math.sqrt(max(0.0, 1 - u * u)))) < 1.0:
            return stripe
        return PORCELAIN_SHADE if u < -0.45 or y > 24.5 else PORCELAIN
    part(g, lambda x, y: rim(x, y) or (14 <= y <= 25.5 and abs(x - CUP_X) <= bowl_hw(y)),
         cup_shade, PORCELAIN_LINE)

    steps = px(8)
    for k in range(steps):   # a wisp of steam, wriggling upward
        if k >= steps * 0.6 and (k + frame) % 2:
            continue
        i = round(CUP_X * Z + 1.6 * Z * math.sin(k * 0.9 / Z + frame * math.pi / 2))
        g.set(i, px(9.6) - k, STEAM[0] if k < steps / 2 else STEAM[1])
    return g


# ------------------------------------------------------------------ bean ----

NW, NH = 16, 16
BEANS = (  # body, light, crease, outline
    ('#c08a4a', '#ecc48a', '#7a5226', '#3d2712'),   # light
    ('#9a6230', '#cf9a60', '#5e3818', '#2e1a0c'),   # medium
    ('#74431f', '#b07846', '#44240f', '#221108'),   # dark
    ('#553019', '#946238', '#2f180c', '#180b06'),   # french
)


def draw_bean(frame, colours):
    """One bean, an eighth of a turn further round each frame."""
    body, light, crease, line = tones(colours)
    g = cell(NW, NH)
    angle = frame * math.pi / 4
    ca, sa = math.cos(angle), math.sin(angle)

    def along_across(x, y):
        dx, dy = x - 8, y - 8
        return dx * ca + dy * sa, -dx * sa + dy * ca

    def inside(x, y):
        u, v = along_across(x, y)
        return (u / 5.6) ** 2 + (v / 3.9) ** 2 <= 1

    def shade(x, y):
        u, v = along_across(x, y)
        if abs(u) < 4.3 and abs(v + 0.8 * math.sin(u * 0.75)) < 0.55:
            return crease
        return light if (x - 8) * 0.5 - (y - 8) * 0.85 > 1.7 else body
    part(g, inside, shade, line)
    return g


# ------------------------------------------------------------- particles ----

PW, PH = 16, 16
PUFF, PUFF_SHADE = tones(('#eef1fb', '#aeb8d8'))
PUFF_BLOBS = (
    ((8, 9, 1.9),),
    ((6, 9.5, 2.6), (9, 8, 3.0), (11.5, 10, 2.0)),
    ((5, 9.5, 3.0), (8.5, 7.5, 3.6), (11.5, 9.5, 3.0)),
)
DROP, DROP_LIGHT = tones(('#b8702e', '#f0b878'))
FADE = (0, 0, 0, 0.3, 0.55)   # how far each particle frame has faded


def draw_puff(frame):
    g = cell(PW, PH)
    blobs = [ellipse(bx, by, r, r) for bx, by, r in PUFF_BLOBS[min(frame, 2)]]
    for j in range(g.h):
        for i in range(g.w):
            x, y = (i + 0.5) / Z, (j + 0.5) / Z
            if not any(blob(x, y) for blob in blobs):
                continue
            if frame == 3 and (i + j) % 2:          # thinning
                continue
            if frame == 4 and (i + 2 * j) % 4:      # nearly gone
                continue
            g.set(i, j, mix(PUFF_SHADE if y >= 10 else PUFF, NIGHT, FADE[frame]))
    return g


def draw_drop(frame):
    """A drip of coffee: it beads, stretches into a teardrop, and thins out."""
    g = cell(PW, PH)
    if frame == 0:
        shape = ellipse(8, 8, 1.3, 1.3)
    elif frame == 4:
        shape = ellipse(8, 9.3, 0.8, 0.8)
    else:
        small = frame == 3
        bulb = ellipse(8, 9.5, 1.2 if small else 1.6, 1.5 if small else 1.9)
        tail = capsule(8, 6.8 if small else 6.0, 8, 9, 0.3, 1.0 if small else 1.3)
        shape = lambda x, y: bulb(x, y) or tail(x, y)

    def shade(x, y):
        lit = frame in (1, 2) and abs(x - 7.3) < 0.4 and abs(y - 9.2) < 0.7
        return mix(DROP_LIGHT if lit else DROP, NIGHT, FADE[frame])
    part(g, shape, shade)
    return g


# ---------------------------------------------------------------- output ----

def png_bytes(g, background=None):
    raw = bytearray()
    for row in g.px:
        raw.append(0)
        for c in row:
            if c is None:
                raw.extend(background + (255,) if background else (0, 0, 0, 0))
            else:
                raw.extend(c + (255,))

    def chunk(tag, data):
        return (struct.pack('>I', len(data)) + tag + data
                + struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff))

    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', struct.pack('>IIBBBBB', g.w, g.h, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(bytes(raw), 9))
            + chunk(b'IEND', b''))


def sheet(variants, frames, draw):
    """rows = variant * 3 + tier, columns = frames."""
    cells = [[draw(f, variant) for f in range(frames)] for variant in variants]
    w, h = cells[0][0].w, cells[0][0].h
    out = Grid(w * frames, h * len(variants) * 3)
    for v, row in enumerate(cells):
        for f, sprite in enumerate(row):
            for tier, dim in enumerate(TIER_DIM):
                out.blit(sprite, f * w, (v * 3 + tier) * h, dim)
    return out


def enlarge(g, n):
    out = Grid(g.w * n, g.h * n)
    for y in range(out.h):
        src = g.px[y // n]
        out.px[y] = [src[x // n] for x in range(out.w)]
    return out


def contact_sheet(sheets, path, scale=3):
    """Everything at a glance, enlarged on the night sky, for eyeballing."""
    bw, bh = int(BW * Z), int(BH * Z)
    cw, ch = int(CW * Z), int(CH * Z)
    n = int(NW * Z)
    out = Grid(max(bw * 8, len(ACCENTS) * cw + 16 + 13 * n), bh * 7 + ch + 4)

    def near(name, frame, variant, col, row):
        out.blit(sheets[name].crop(frame * bw, (variant * 3 + 2) * bh, bw, bh), col * bw, row * bh)

    others = {'dripper': 3, 'press': 4, 'mill': 5, 'grinder': 6}    # name -> row
    for f in range(4):                              # the flap
        near('kettle', f, 0, f, 0)
    for v in range(len(KETTLES)):                   # every kettle colourway
        near('kettle', 1 + v % 2, v, v % 8, 1 + v // 8)
    out.blit(sheets['kettle'].crop(bw, 0, bw, bh), 7 * bw, 0)
    for name, row in others.items():
        for f in range(4):
            near(name, f, 0, f, row)
        for v in range(1, 4):                       # its other colourways
            near(name, v, v, 3 + v, row)
        out.blit(sheets[name].crop(bw, 0, bw, bh), 7 * bw, row * bh)    # and a far-tier sample

    y = bh * 7 + 2
    for a in range(len(ACCENTS)):                   # every accent, working through the roasts
        out.blit(sheets['cup'].crop((a % 4) * cw, ((a * 4 + a % 4) * 3 + 2) * ch, cw, ch), a * cw, y)
    beans_x = len(ACCENTS) * cw + 8
    for v in range(4):
        for f in range(4):
            out.blit(sheets['bean'].crop(f * n, (v * 3 + 2) * n, n, n),
                     beans_x + (v % 2 * 4 + f) * n, y + (v // 2) * n)
    for f in range(5):
        out.blit(sheets['puff'].crop(f * n, 2 * n, n, n), beans_x + 8 + 8 * n + f * n, y)
        out.blit(sheets['drop'].crop(f * n, 2 * n, n, n), beans_x + 8 + 8 * n + f * n, y + n)
    with open(path, 'wb') as fh:
        fh.write(png_bytes(enlarge(out, scale), NIGHT))


def main():
    sheets = {
        'kettle': sheet(KETTLES, 4, draw_kettle),
        'dripper': sheet(DRIPPERS, 4, draw_dripper),
        'press': sheet(PRESSES, 4, draw_press),
        'mill': sheet(MILLS, 4, draw_mill),
        'grinder': sheet(GRINDERS, 4, draw_grinder),
        'cup': sheet(CUPS, 4, draw_cup),
        'bean': sheet(BEANS, 4, draw_bean),
        'puff': sheet((None,), 5, lambda f, _: draw_puff(f)),
        'drop': sheet((None,), 5, lambda f, _: draw_drop(f)),
    }
    os.makedirs(RESOURCES, exist_ok=True)
    encoded = {}
    for name, g in sheets.items():
        data = png_bytes(g)
        with open(os.path.join(RESOURCES, name + '.png'), 'wb') as fh:
            fh.write(data)
        encoded[name] = 'data:image/png;base64,' + base64.b64encode(data).decode()
        print(f'{name}.png  {g.w}x{g.h}  {len(data)} bytes')

    if os.path.exists(PREVIEW):   # keep the self-contained preview in step
        with open(PREVIEW) as fh:
            html = fh.read()
        block = ('/*SPRITES*/const SPRITES = {'
                 + ', '.join(f'{k}: "{v}"' for k, v in encoded.items()) + '};/*END*/')
        html, n = re.subn(r'/\*SPRITES\*/.*?/\*END\*/', lambda _: block, html, flags=re.S)
        if n:
            with open(PREVIEW, 'w') as fh:
                fh.write(html)
            print('preview/index.html  sprites refreshed')

    if '--sheet' in sys.argv:
        path = sys.argv[sys.argv.index('--sheet') + 1]
        contact_sheet(sheets, path)
        print('contact sheet ->', path)


if __name__ == '__main__':
    main()
