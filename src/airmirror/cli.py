"""Command line: airmirror scan | pair | mirror | tray | install."""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from . import __version__, receivers
from .session import MirrorOptions, mirror


def _receiver_table(found) -> str:
    if not found:
        return "No AirPlay receivers found. Is this PC on the same Wi-Fi as the TV?"
    width = max(len(r.name) for r in found)
    lines = [f"{'NAME'.ljust(width)}  {'ADDRESS':15}  STATUS"]
    lines += [f"{r.name.ljust(width)}  {r.address:15}  {r.status}" for r in found]
    return "\n".join(lines)


async def cmd_scan(args) -> int:
    print(_receiver_table(await receivers.discover(args.timeout)))
    return 0


async def cmd_pair(args) -> int:
    found = await receivers.discover(args.timeout)
    usable = [r for r in found if r.usable]
    if args.receiver:
        target = receivers.choose(found, args.receiver)
    elif len(usable) == 1:
        target = usable[0]
    else:
        print(_receiver_table(found))
        print('\nName the TV to pair with: airmirror pair "<name>"')
        return 1
    if not target.usable:
        print(f"{target.name}: {target.status}")
        return 1

    async def ask_pin() -> str:
        return await asyncio.get_running_loop().run_in_executor(
            None, lambda: input(f"Enter the PIN shown on {target.name}: "))

    print(f"Pairing with {target.name}. A PIN should appear on the TV.")
    if await receivers.pair(target, ask_pin):
        print(f"Paired. {target.name} is now your default; run `airmirror mirror` or `airmirror tray`.")
        return 0
    print("Pairing failed. Check the PIN and try again.")
    return 1


async def cmd_mirror(args) -> int:
    target = receivers.choose(await receivers.discover(args.timeout), args.receiver)
    options = MirrorOptions(width=args.width, height=args.height, fps=args.fps, bitrate=args.bitrate,
                            monitor=args.monitor, encoder=args.encoder, test_pattern=args.test)
    print(f"Mirroring to {target.name}. Press Ctrl+C to stop.")
    await mirror(target, options, duration=args.seconds)
    return 0


def cmd_tray(args) -> int:
    from .tray import run_tray
    return run_tray()


def cmd_install(args) -> int:
    from .windows import install_start_menu_shortcut, set_start_with_windows
    path = install_start_menu_shortcut()
    print(f"Start Menu shortcut created: {path}")
    if args.startup:
        set_start_with_windows(True)
        print("AirMirror will start in the tray when you sign in.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="airmirror", description="Mirror your Windows screen to AirPlay 2 TVs.")
    p.add_argument("--version", action="version", version=f"airmirror {__version__}")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    p.add_argument("--timeout", type=float, default=5, help="seconds to search the network (default 5)")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("scan", help="list AirPlay receivers on the network").set_defaults(func=cmd_scan)

    pr = sub.add_parser("pair", help="pair with a TV (it shows a PIN)")
    pr.add_argument("receiver", nargs="?", help="TV name (default: the only compatible one)")
    pr.set_defaults(func=cmd_pair)

    m = sub.add_parser("mirror", help="mirror the screen")
    m.add_argument("receiver", nargs="?", help="TV name (default: your paired TV)")
    m.add_argument("--monitor", type=int, default=0, help="monitor index to capture (default 0)")
    m.add_argument("--fps", type=int, default=30)
    m.add_argument("--width", type=int, default=1920)
    m.add_argument("--height", type=int, default=1080)
    m.add_argument("--bitrate", default="10M")
    m.add_argument("--encoder", default="auto", help="auto, h264_nvenc, h264_amf, h264_qsv or libx264")
    m.add_argument("--seconds", type=float, default=0, help="stop after N seconds")
    m.add_argument("--test", action="store_true", help="send a test pattern instead of the screen")
    m.set_defaults(func=cmd_mirror)

    sub.add_parser("tray", help="run the tray icon (click to start/stop)").set_defaults(func=cmd_tray)

    i = sub.add_parser("install", help="add a Start Menu shortcut for the tray app")
    i.add_argument("--startup", action="store_true", help="also start the tray app when you sign in")
    i.set_defaults(func=cmd_install)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    if not args.verbose:
        logging.getLogger("pyatv").setLevel(logging.WARNING)
    try:
        if asyncio.iscoroutinefunction(args.func):
            return asyncio.run(args.func(args))
        return args.func(args)
    except KeyboardInterrupt:
        return 0
    except (LookupError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
