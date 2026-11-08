"""The AirMirror logo: a pixel-art frog perched on a retro TV.

The TV screen doubles as the tray status light: dark when idle, amber while
connecting, blue while mirroring.
"""
from __future__ import annotations

from PIL import Image

# Left half of a 32x32 sprite; each row is mirrored to make the full width.
HALF = [
    "................",
    "................",
    ".........KKKK...",
    "........KWPPWK..",
    "........KWPPWK..",
    "........KWWWWKKK",
    ".......KGKKKKGGG",
    "......KGGGGGGGGG",
    "......KGGGGGGGGG",
    "......KGRRGGGGGG",
    "......KGGKGGGGGG",
    ".....KGGGGKKKKKK",
    "....KgGGGGGLLLLL",
    "...KgGGGGGLLLLLL",
    "...KggKGGKLLLLLL",
    "..KKKKKKKKKKKKKK",
    "..KTTTTTTTTTTTTT",
    "..KTKKKKKKKKKKKK",
    "..KTKSSSSSSSSSSS",
    "..KTKSSSSSSSSSSS",
    "..KTKSSSSSSSSSSS",
    "..KTKSSSSSSSSSSS",
    "..KTKSSSSSSSSSSS",
    "..KTKSSSSSSSSSSS",
    "..KTKSSSSSSSSSSS",
    "..KTKSSSSSSSSSSS",
    "..KTKKKKKKKKKKKK",
    "..KTTTTTTTTTTTTT",
    "..KDDDDDDDDDDDDD",
    "..KKKKKKKKKKKKKK",
    "....KK..........",
    "....KK..........",
]

# Asymmetric details drawn over the mirrored sprite: (x, y, colour key).
DETAILS = [
    (6, 19, "H"), (7, 19, "H"), (6, 20, "H"),           # screen glare
    (24, 27, "N"), (26, 27, "N"),                       # control knobs
]

BASE = {
    "K": (27, 27, 47),     # outline
    "G": (92, 200, 90),    # frog
    "g": (58, 143, 62),    # frog shade
    "L": (190, 236, 130),  # belly
    "W": (255, 255, 255),  # eye
    "P": (27, 27, 47),     # pupil
    "R": (255, 143, 171),  # cheek
    "T": (224, 160, 80),   # TV case
    "D": (156, 98, 48),    # TV case shade
    "N": (255, 214, 102),  # knob
}
SCREENS = {
    "idle": ((44, 58, 85), (84, 104, 140)),
    "busy": ((217, 160, 36), (255, 220, 120)),
    "live": ((59, 130, 246), (190, 225, 255)),
}


def sprite(state: str = "live") -> list[str]:
    rows = [list(half + half[::-1]) for half in HALF]
    for x, y, key in DETAILS:
        rows[y][x] = key
    return ["".join(r) for r in rows]


def render(state: str = "live", scale: int = 1) -> Image.Image:
    screen, glare = SCREENS[state]
    palette = {**BASE, "S": screen, "H": glare}
    rows = sprite(state)
    img = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    for y, row in enumerate(rows):
        for x, key in enumerate(row):
            if key != ".":
                img.putpixel((x, y), (*palette[key], 255))
    return img.resize((32 * scale, 32 * scale), Image.NEAREST) if scale > 1 else img
