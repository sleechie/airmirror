import sys
import time

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="tray app is Windows-only")


class FakeIcon:
    def __init__(self, *args, menu=None, **kwargs):
        self.menu, self.icon, self.title = menu, None, ""

    def update_menu(self):
        pass

    def notify(self, *args):
        pass


@pytest.fixture
def app(monkeypatch, tmp_path):
    from airmirror import receivers, tray

    monkeypatch.setattr(receivers, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(tray.pystray, "Icon", FakeIcon)
    a = tray.TrayApp()
    a.scheduled = []

    def fake_run(coro):
        a.scheduled.append(coro.__qualname__)
        coro.close()

    monkeypatch.setattr(a, "run", fake_run)
    return a


def test_click_starts_mirroring(app):
    app.toggle()
    assert app.scheduled == ["TrayApp._mirror"]


def test_double_click_does_not_stop_what_it_started(app):
    import asyncio

    app.toggle()
    app.stop_event = asyncio.Event()  # mirroring has begun
    app.toggle()                      # second click of a double-click
    time.sleep(0.05)
    assert not app.stop_event.is_set()
    assert app.scheduled == ["TrayApp._mirror"]


def test_later_click_stops_mirroring(app):
    import asyncio

    from airmirror import tray

    app.toggle()
    app.stop_event = asyncio.Event()
    app.started_at -= tray.DOUBLE_CLICK_GUARD + 0.1
    app.toggle()
    deadline = time.time() + 2
    while not app.stop_event.is_set() and time.time() < deadline:
        time.sleep(0.01)
    assert app.stop_event.is_set()


def test_menu_labels_render(app):
    labels = [item.text for item in app.icon.menu.items if item.text]
    assert labels[0] == "Mirror screen"
