"""Render the tray glyph into a multi-size .ico for the exe and installer."""
import sys

from airmirror.tray import LIVE, draw_icon

draw_icon(LIVE).save(sys.argv[1], sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64)])
