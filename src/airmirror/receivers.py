"""Find AirPlay receivers, pair with them, and remember the default one."""
from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

import pyatv
from pyatv.const import Protocol
from pyatv.interface import BaseConfig
from pyatv.storage.file_storage import FileStorage

from .protocol import FEATURE_FAIRPLAY, FEATURE_HOMEKIT_PAIRING, FEATURE_SCREEN, parse_features

CONFIG_DIR = Path(os.environ.get("APPDATA", Path.home() / ".config")) / "airmirror"
CONFIG_FILE = CONFIG_DIR / "config.json"


@dataclass
class Receiver:
    name: str
    identifier: str
    address: str
    features: int
    paired: bool
    config: BaseConfig

    @property
    def supports_mirroring(self) -> bool:
        return bool(self.features & FEATURE_SCREEN)

    @property
    def needs_fairplay(self) -> bool:
        # FairPlay-gated receivers (Apple TVs, most older ones) need Apple's DRM handshake, which this
        # project does not implement. Receivers that advertise HomeKit pairing without it work.
        return bool(self.features & FEATURE_FAIRPLAY) or not self.features & FEATURE_HOMEKIT_PAIRING

    @property
    def usable(self) -> bool:
        return self.supports_mirroring and not self.needs_fairplay

    @property
    def status(self) -> str:
        if not self.supports_mirroring:
            return "no screen mirroring"
        if self.needs_fairplay:
            return "unsupported (needs FairPlay)"
        return "ready" if self.paired else "needs pairing"


async def load_storage() -> FileStorage:
    storage = FileStorage.default_storage(asyncio.get_running_loop())
    await storage.load()
    return storage


async def discover(timeout: float = 5, storage: FileStorage | None = None) -> list[Receiver]:
    storage = storage or await load_storage()
    confs = await pyatv.scan(asyncio.get_running_loop(), timeout=timeout, protocol=Protocol.AirPlay, storage=storage)
    found = []
    for conf in confs:
        service = conf.get_service(Protocol.AirPlay)
        if service is None:
            continue
        props = service.properties
        found.append(Receiver(
            name=conf.name,
            identifier=service.identifier or conf.identifier,
            address=str(conf.address),
            features=parse_features(props.get("features") or props.get("ft") or "0"),
            paired=bool(service.credentials),
            config=conf,
        ))
    return sorted(found, key=lambda r: (not r.usable, r.name.lower()))


def load_settings() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text())
    except (OSError, ValueError):
        return {}


def save_settings(**changes) -> None:
    settings = {**load_settings(), **changes}
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(settings, indent=2))


def choose(receivers: list[Receiver], wanted: str | None) -> Receiver:
    """Pick by name/identifier, else the saved default, else the only usable paired receiver."""
    if wanted:
        w = wanted.lower()
        matches = [r for r in receivers if w in (r.name.lower(), r.identifier.lower())] or \
                  [r for r in receivers if w in r.name.lower()]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise LookupError(f"No AirPlay receiver matching {wanted!r}. Run `airmirror scan`.")
        raise LookupError(f"{wanted!r} matches several receivers: {', '.join(r.name for r in matches)}")
    default = load_settings().get("default_receiver")
    for r in receivers:
        if default and r.identifier == default:
            return r
    ready = [r for r in receivers if r.usable and r.paired]
    if len(ready) == 1:
        return ready[0]
    if not ready:
        raise LookupError("No paired receiver yet. Run `airmirror pair \"<TV name>\"` first.")
    raise LookupError(f"Several paired receivers ({', '.join(r.name for r in ready)}); name one.")


async def pair(receiver: Receiver, ask_pin: Callable[[], Awaitable[str]], storage: FileStorage | None = None) -> bool:
    """Run AirPlay pairing; the receiver shows a PIN which ask_pin must return."""
    storage = storage or await load_storage()
    pairing = await pyatv.pair(receiver.config, Protocol.AirPlay, asyncio.get_running_loop(), storage=storage)
    try:
        await pairing.begin()
        pin = (await ask_pin()).strip()
        pairing.pin(int(pin))
        await pairing.finish()
        if pairing.has_paired:
            await storage.save()
            save_settings(default_receiver=receiver.identifier)
        return pairing.has_paired
    finally:
        await pairing.close()
