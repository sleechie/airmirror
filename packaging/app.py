"""Entry point for the installed (PyInstaller) build: AirMirror.exe is the tray app."""
import sys

from airmirror.tray import run_tray

sys.exit(run_tray())
