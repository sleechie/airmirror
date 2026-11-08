"""An AirPlay screen-mirroring session: pair-verify, RTSP SETUP, then the encrypted video stream."""
from __future__ import annotations

import asyncio
import logging
import os
import random
import socket
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from pyatv.auth.hap_channel import setup_channel
from pyatv.auth.hap_pairing import parse_credentials
from pyatv.const import Protocol
from pyatv.protocols.airplay.auth import verify_connection
from pyatv.protocols.airplay.channels import EventChannel
from pyatv.protocols.raop import timing
from pyatv.protocols.raop.protocols import TimingServer
from pyatv.support.http import decode_bplist_from_body, http_connect
from pyatv.support.rtsp import RtspSession

from . import __version__, capture, protocol
from .receivers import Receiver

log = logging.getLogger(__name__)

TIMESTAMP_FIELDS = ("SubSu", "BePxT", "AfPxT", "BefEn", "EmEnc")


@dataclass
class MirrorOptions:
    width: int = 1920
    height: int = 1080
    fps: int = 30
    bitrate: str = "10M"
    monitor: int = 0
    encoder: str = "auto"
    test_pattern: bool = False
    latency_ms: int = 90


class NotPaired(RuntimeError):
    pass


class MirrorSession:
    def __init__(self, receiver: Receiver, width: int, height: int, latency_ms: int = 90) -> None:
        self.receiver = receiver
        self.width, self.height, self.latency_ms = width, height, latency_ms
        self.stream_id = random.getrandbits(63)
        self._sealer: protocol.FrameSealer | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._codec: tuple | None = None
        self._tasks: list = []
        self._closers: list = []

    async def start(self) -> None:
        service = self.receiver.config.get_service(Protocol.AirPlay)
        if not service or not service.credentials:
            raise NotPaired(f"{self.receiver.name} is not paired. Run `airmirror pair`.")
        loop = asyncio.get_running_loop()
        ip = self.receiver.address

        timing_transport, timing_server = await loop.create_datagram_endpoint(TimingServer, local_addr=("0.0.0.0", 0))
        self._closers.append(timing_transport)
        conn = await http_connect(ip, service.port or 7000)
        self._closers.append(conn)
        self._rtsp = RtspSession(conn)
        verifier = await verify_connection(parse_credentials(service.credentials), conn)

        resp = decode_bplist_from_body(await self._rtsp.setup(body={
            "deviceID": _device_id(), "macAddress": _device_id(), "sessionUUID": str(uuid.uuid4()).upper(),
            "name": socket.gethostname(), "model": "airmirror", "sourceVersion": "770.8.1",
            "osBuildVersion": __version__, "isScreenMirroringSession": True, "updateSessionRequest": False,
            "combinedGetInfoWithControlSetup": True, "timingProtocol": "NTP", "timingPort": timing_server.port,
        }))
        log.debug("session SETUP: %s", {k: v for k, v in resp.items() if k != "info"})
        events, _ = await setup_channel(EventChannel, verifier, ip, resp["eventPort"], "Events-Salt",
                                        "Events-Read-Encryption-Key", "Events-Write-Encryption-Key")
        self._closers.append(events)

        stream = decode_bplist_from_body(await self._rtsp.setup(body={"streams": [{
            "type": protocol.STREAM_TYPE_SCREEN, "streamConnectionID": self.stream_id, "latencyMs": self.latency_ms,
            "timestampInfo": [{"name": n} for n in TIMESTAMP_FIELDS],
            "shk": os.urandom(32), "shiv": os.urandom(16),
        }]}))["streams"][0]
        log.debug("stream SETUP: %s", stream)

        # pyatv keeps the pair-verify X25519 secret here; it seeds the video stream key.
        shared_secret = verifier.srp._shared
        self._sealer = protocol.FrameSealer(protocol.stream_key(shared_secret, self.stream_id))
        _, self._writer = await asyncio.open_connection(ip, stream["dataPort"])
        self._writer.get_extra_info("socket").setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        if not resp.get("skipRecord"):
            await self._rtsp.record()
        self._tasks = [asyncio.ensure_future(self._feedback()), asyncio.ensure_future(self._heartbeat())]
        log.info("Mirroring to %s (%s), data port %s", self.receiver.name, ip, stream["dataPort"])

    async def send(self, au: list) -> bool:
        """Send one access unit. Returns False if it carried no picture."""
        ts = timing.ntp_now()
        sps, pps = capture.find_nal(au, capture.NAL_SPS), capture.find_nal(au, capture.NAL_PPS)
        if sps and pps and (sps, pps) != self._codec:
            self._writer.write(protocol.codec_packet(sps, pps, self.width, self.height, ts))
            self._codec = (sps, pps)
        vcl = [n for n in au if capture.nal_type(n) not in (capture.NAL_SPS, capture.NAL_PPS)]
        if not self._codec or not any(capture.nal_type(n) in capture.VCL for n in vcl):
            return False
        idr = any(capture.nal_type(n) == capture.NAL_IDR for n in vcl)
        self._writer.write(self._sealer.seal(vcl, idr, ts))
        await self._writer.drain()
        return True

    async def _feedback(self) -> None:
        while True:
            await asyncio.sleep(2)
            try:
                await self._rtsp.exchange("POST", uri="/feedback")
            except Exception as exc:  # the data connection reports real failures
                log.debug("feedback failed: %s", exc)

    async def _heartbeat(self) -> None:
        while True:
            await asyncio.sleep(1)
            if self._codec and self._writer:
                self._writer.write(protocol.heartbeat_packet())

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        try:
            await asyncio.wait_for(self._rtsp.exchange("TEARDOWN"), 2)
        except Exception:
            pass
        for closer in [self._writer, *self._closers]:
            try:
                closer.close()
            except Exception:
                pass


def _device_id() -> str:
    node = uuid.getnode()
    return ":".join(f"{(node >> s) & 0xFF:02X}" for s in range(40, -1, -8))


async def mirror(
    receiver: Receiver,
    options: MirrorOptions,
    stop: asyncio.Event | None = None,
    on_status: Callable[[str], None] = lambda s: None,
    duration: float = 0,
) -> None:
    """Capture the screen and mirror it until `stop` is set, `duration` passes, or the receiver hangs up."""
    ffmpeg = capture.find_ffmpeg()
    encoder = capture.pick_encoder(ffmpeg, options.encoder)
    log.info("Encoder: %s", encoder)
    session = MirrorSession(receiver, options.width, options.height, options.latency_ms)
    await session.start()
    cmd = capture.ffmpeg_command(ffmpeg, encoder, width=options.width, height=options.height, fps=options.fps,
                                 bitrate=options.bitrate, monitor=options.monitor, test_pattern=options.test_pattern)
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                                                **capture.NO_WINDOW)
    stop = stop or asyncio.Event()
    deadline = time.monotonic() + duration if duration else None
    frames, started = 0, time.monotonic()
    on_status("mirroring")

    async def pump() -> None:
        nonlocal frames
        async for au in capture.access_units(proc.stdout):
            if await session.send(au):
                frames += 1
                if frames % 300 == 0:
                    log.info("%d frames, %.1f fps", frames, frames / (time.monotonic() - started))
            if deadline and time.monotonic() > deadline:
                return

    pump_task = asyncio.ensure_future(pump())
    stop_task = asyncio.ensure_future(stop.wait())
    try:
        await asyncio.wait({pump_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
        if pump_task.done() and pump_task.exception():
            exc = pump_task.exception()
            if isinstance(exc, (ConnectionError, OSError)):
                log.info("Receiver closed the connection")
            else:
                raise exc
        elif pump_task.done() and not (deadline and time.monotonic() > deadline):
            if await proc.wait() != 0:
                err = (await proc.stderr.read()).decode(errors="replace").strip()
                raise RuntimeError(f"FFmpeg stopped: {err or proc.returncode}")
    finally:
        for task in (pump_task, stop_task):
            task.cancel()
        if proc.returncode is None:
            proc.kill()
        await proc.wait()
        await session.stop()
        on_status("stopped")
        log.info("Stopped after %d frames", frames)
