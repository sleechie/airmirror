"""Render the frog logo into a multi-size .ico for the exe and installer."""
import sys

from airmirror.logo import render

big = render("live", scale=8)  # 256 px, nearest-neighbour keeps the pixels crisp
big.save(sys.argv[1], sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
