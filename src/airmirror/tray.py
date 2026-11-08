"""System tray app: click the icon to start or stop mirroring."""
from __future__ import annotations

import asyncio
import logging
import threading

import pystray
from PIL import Image, ImageDraw

from . import receivers, windows
from .session import MirrorOptions, NotPaired, mirror

log = logging.getLogger(__name__)

IDLE, BUSY, LIVE = "idle", "busy", "live"
COLORS = {IDLE: (235, 235, 235, 255), BUSY: (250, 204, 21, 255), LIVE: (59, 130, 246, 255)}


def draw_icon(state: str) -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    color = COLORS[state]
    filled = state != IDLE
    d.rounded_rectangle((4, 8, 60, 46), radius=6, outline=color, width=5, fill=color if filled else None)
    d.polygon([(32, 34), (14, 60), (50, 60)], fill=color)
    if filled:
        d.polygon([(26, 18), (26, 36), (42, 27)], fill=(255, 255, 255, 255))
    return img


def ask_pin_dialog(tv_name: str) -> str:
    import tkinter as tk
    from tkinter import simpledialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        return simpledialog.askstring("AirMirror", f"Enter the PIN shown on {tv_name}:", parent=root) or ""
    finally:
        root.destroy()


class TrayApp:
    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        self.found: list[receivers.Receiver] = []
        self.selected: str | None = receivers.load_settings().get("default_receiver")
        self.stop_event: asyncio.Event | None = None
        self.state = IDLE
        self.icon = pystray.Icon("airmirror", draw_icon(IDLE), "AirMirror", menu=self._menu())

    # ----- helpers -----
    def run(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def target(self) -> receivers.Receiver | None:
        return next((r for r in self.found if r.identifier == self.selected), None)

    def set_state(self, state: str, tooltip: str = "") -> None:
        self.state = state
        self.icon.icon = draw_icon(state)
        self.icon.title = tooltip or "AirMirror"
        self.icon.update_menu()

    def notify(self, message: str) -> None:
        try:
            self.icon.notify(message, "AirMirror")
        except Exception:
            log.info(message)

    # ----- actions -----
    async def refresh(self) -> None:
        self.found = await receivers.discover()
        usable = [r for r in self.found if r.usable]
        if not self.target() and usable:
            paired = [r for r in usable if r.paired]
            self.selected = (paired or usable)[0].identifier
        self.icon.update_menu()

    async def _mirror(self) -> None:
        tv = self.target()
        if tv is None:
            await self.refresh()
            tv = self.target()
        if tv is None:
            self.notify("No compatible AirPlay TV found on this network.")
            return
        if not tv.paired and not await self._pair(tv):
            return
        self.stop_event = asyncio.Event()
        self.set_state(BUSY, f"Connecting to {tv.name}…")
        try:
            await mirror(tv, MirrorOptions(), self.stop_event,
                         on_status=lambda s: s == "mirroring" and self.set_state(LIVE, f"Mirroring to {tv.name}"))
        except NotPaired:
            self.notify(f"{tv.name} forgot this PC. Pick it again to re-pair.")
        except Exception as exc:
            log.exception("mirroring failed")
            self.notify(f"Mirroring stopped: {exc}")
        finally:
            self.stop_event = None
            self.set_state(IDLE)

    async def _pair(self, tv: receivers.Receiver) -> bool:
        self.set_state(BUSY, f"Pairing with {tv.name}…")

        async def ask() -> str:
            return await asyncio.get_running_loop().run_in_executor(None, ask_pin_dialog, tv.name)

        try:
            ok = await receivers.pair(tv, ask)
        except Exception as exc:
            ok = False
            log.exception("pairing failed: %s", exc)
        self.set_state(IDLE)
        if ok:
            await self.refresh()
            self.notify(f"Paired with {tv.name}.")
        else:
            self.notify(f"Pairing with {tv.name} failed.")
        return ok

    def toggle(self, *_):
        if self.stop_event is not None:
            self.loop.call_soon_threadsafe(self.stop_event.set)
        elif self.state == IDLE:
            self.run(self._mirror())

    def choose(self, tv: receivers.Receiver):
        def handler(*_):
            self.selected = tv.identifier
            receivers.save_settings(default_receiver=tv.identifier)
            if not tv.paired:
                self.run(self._pair(tv))
            self.icon.update_menu()
        return handler

    # ----- menu -----
    def _toggle_label(self, _item) -> str:
        if self.stop_event is not None:
            return "Stop mirroring"
        tv = self.target()
        return f"Mirror to {tv.name}" if tv else "Mirror screen"

    def _tv_items(self):
        usable = [r for r in self.found if r.usable]
        if not usable:
            yield pystray.MenuItem("Searching…" if not self.found else "No compatible TVs", None, enabled=False)
        for tv in usable:
            label = tv.name if tv.paired else f"{tv.name} (pair…)"
            yield pystray.MenuItem(label, self.choose(tv), checked=lambda _i, t=tv: t.identifier == self.selected,
                                   radio=True)
        yield pystray.Menu.SEPARATOR
        yield pystray.MenuItem("Refresh", lambda *_: self.run(self.refresh()))

    def _menu(self) -> pystray.Menu:
        items = [
            pystray.MenuItem(self._toggle_label, self.toggle, default=True,
                             enabled=lambda _i: self.state != BUSY or self.stop_event is not None),
            pystray.MenuItem("TV", pystray.Menu(self._tv_items)),
            pystray.Menu.SEPARATOR,
        ]
        items.append(pystray.MenuItem(
            "Start with Windows", lambda *_: windows.set_start_with_windows(not windows.starts_with_windows()),
            checked=lambda _i: windows.starts_with_windows()))
        items.append(pystray.MenuItem("Quit", self.quit))
        return pystray.Menu(*items)

    def quit(self, *_):
        if self.stop_event is not None:
            self.loop.call_soon_threadsafe(self.stop_event.set)
        self.icon.stop()

    async def _first_refresh(self) -> None:
        await self.refresh()
        tv = self.target()
        if tv and not tv.paired:
            self.notify(f"Found {tv.name}. Click the AirMirror icon to connect (the TV will show a code).")
        elif tv:
            self.notify(f"Ready. Click the icon to mirror to {tv.name}.")
        else:
            self.notify("No AirPlay TV found yet. Make sure the TV is on and on the same Wi-Fi.")

    def start(self) -> None:
        self.icon.run(setup=self._setup)

    def _setup(self, icon) -> None:
        icon.visible = True
        self.run(self._first_refresh())


def run_tray() -> int:
    # The tray app usually runs under pythonw (no console), so log to a file.
    receivers.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", force=True,
                        filename=str(receivers.CONFIG_DIR / "airmirror.log"))
    logging.getLogger("pyatv").setLevel(logging.WARNING)
    if not windows.single_instance():
        log.info("AirMirror is already running")
        return 0
    TrayApp().start()
    return 0
