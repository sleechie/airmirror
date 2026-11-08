"""Windows integration: Start Menu shortcut and start-at-sign-in."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "AirMirror"


def tray_command() -> tuple:
    if getattr(sys, "frozen", False):  # installed app: AirMirror.exe is the tray app
        return sys.executable, ""
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    exe = pythonw if pythonw.exists() else Path(sys.executable)
    return str(exe), "-m airmirror tray"


def set_start_with_windows(enabled: bool) -> None:
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            exe, args = tray_command()
            winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, f'"{exe}" {args}'.strip())
        else:
            try:
                winreg.DeleteValue(key, RUN_VALUE)
            except FileNotFoundError:
                pass


def starts_with_windows() -> bool:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, RUN_VALUE)
            return True
    except FileNotFoundError:
        return False


def install_start_menu_shortcut() -> Path:
    programs = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    link = programs / "AirMirror.lnk"
    exe, args = tray_command()
    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:AM_LINK);"
        "$s.TargetPath = $env:AM_EXE; $s.Arguments = $env:AM_ARGS;"
        "$s.Description = 'Mirror your screen to an AirPlay TV'; $s.Save()"
    )
    env = {**os.environ, "AM_LINK": str(link), "AM_EXE": exe, "AM_ARGS": args}
    subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True, env=env)
    return link


def single_instance(name: str = "Local\\AirMirrorTray") -> bool:
    """Return False if another tray instance already holds the named mutex."""
    import ctypes

    kernel32 = ctypes.windll.kernel32
    single_instance.handle = kernel32.CreateMutexW(None, False, name)  # keep a reference for process lifetime
    return kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS
