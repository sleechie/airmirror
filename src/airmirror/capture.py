"""Screen capture and H.264 encoding through FFmpeg, split into access units."""
from __future__ import annotations

import asyncio
import shutil
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path

NAL_SLICE, NAL_IDR, NAL_SEI, NAL_SPS, NAL_PPS, NAL_AUD = 1, 5, 6, 7, 8, 9
VCL = (NAL_SLICE, NAL_IDR)

# Low-latency settings per encoder, best first. Hardware encoders keep the CPU free.
ENCODERS = {
    "h264_nvenc": ["-preset", "p1", "-tune", "ull", "-zerolatency", "1", "-rc", "cbr", "-profile:v", "high"],
    "h264_amf": ["-usage", "ultralowlatency", "-quality", "speed", "-rc", "cbr", "-profile:v", "high"],
    "h264_qsv": ["-preset", "veryfast", "-look_ahead", "0", "-profile:v", "high"],
    # Windows' built-in Media Foundation encoder: present on every PC, used when no GPU encoder works.
    "h264_mf": ["-rate_control", "cbr", "-scenario", "display_remoting"],
    "libx264": ["-preset", "ultrafast", "-tune", "zerolatency", "-profile:v", "high"],
}

# Keep FFmpeg from flashing a console window when launched from the tray app.
NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}


class FFmpegNotFound(RuntimeError):
    pass


def find_ffmpeg() -> str:
    bundled_dirs = [Path(getattr(sys, "_MEIPASS", "")), Path(sys.executable).parent]
    for d in bundled_dirs if getattr(sys, "frozen", False) else []:
        if (d / "ffmpeg.exe").exists():
            return str(d / "ffmpeg.exe")
    path = shutil.which("ffmpeg")
    if path:
        return path
    try:
        import imageio_ffmpeg  # optional fallback

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    raise FFmpegNotFound("FFmpeg not found. Install it (winget install Gyan.FFmpeg) and open a new terminal.")


def encoder_args(encoder: str, fps: int = 30, bitrate: str = "10M") -> list[str]:
    return [
        "-c:v", encoder, *ENCODERS[encoder],
        "-b:v", bitrate, "-maxrate", bitrate, "-bufsize", bitrate,
        "-bf", "0", "-g", str(fps * 2),
    ]


def encoder_works(ffmpeg: str, encoder: str) -> bool:
    """Encode a few frames with the real settings to prove the encoder (and its GPU) is usable."""
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30",
           "-frames:v", "3", "-vf", "format=yuv420p", *encoder_args(encoder), "-f", "null", "-"]
    try:
        return subprocess.run(cmd, capture_output=True, timeout=20, **NO_WINDOW).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def pick_encoder(ffmpeg: str, preferred: str = "auto") -> str:
    if preferred != "auto":
        if preferred not in ENCODERS:
            raise ValueError(f"unknown encoder {preferred!r}; choose from {', '.join(ENCODERS)}")
        return preferred
    for name in ENCODERS:
        if encoder_works(ffmpeg, name):
            return name
    raise RuntimeError("No working H.264 encoder found in this FFmpeg build.")


def ffmpeg_command(
    ffmpeg: str,
    encoder: str,
    *,
    width: int = 1920,
    height: int = 1080,
    fps: int = 30,
    bitrate: str = "10M",
    monitor: int = 0,
    test_pattern: bool = False,
) -> list[str]:
    if test_pattern:
        source = ["-re", "-f", "lavfi", "-i", f"testsrc2=size={width}x{height}:rate={fps}"]
    else:
        # Desktop Duplication API: GPU capture, includes the mouse cursor.
        source = ["-f", "lavfi", "-i", f"ddagrab=output_idx={monitor}:framerate={fps},hwdownload,format=bgra"]
    scale = (f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
             f"pad={width}:{height}:-1:-1,format=yuv420p")
    return [
        ffmpeg, "-hide_banner", "-loglevel", "error", *source,
        "-vf", scale, *encoder_args(encoder, fps, bitrate),
        "-bsf:v", "dump_extra",  # repeat SPS/PPS before every keyframe
        "-f", "h264", "-",
    ]


def nal_type(nal: bytes) -> int:
    return nal[0] & 0x1F


class AccessUnitSplitter:
    """Turns an Annex-B byte stream into access units (one list of NAL units per frame).

    Works with or without access unit delimiters: a new frame starts at an AUD,
    at SPS/PPS/SEI that follow a slice, or at a slice whose first_mb_in_slice is 0.
    """

    def __init__(self) -> None:
        self._buf = b""
        self._au: list[bytes] = []
        self._au_has_vcl = False

    def feed(self, data: bytes) -> list[list[bytes]]:
        self._buf += data
        out: list[list[bytes]] = []
        for nal in self._complete_nals():
            self._push(nal, out)
        return out

    def flush(self) -> list[list[bytes]]:
        out: list[list[bytes]] = []
        tail = self._strip_start_code(self._buf)
        self._buf = b""
        if tail:
            self._push(tail, out)
        if self._au:
            out.append(self._au)
            self._au, self._au_has_vcl = [], False
        return out

    def _push(self, nal: bytes, out: list[list[bytes]]) -> None:
        t = nal_type(nal)
        starts_new = (
            t == NAL_AUD
            or (t in (NAL_SPS, NAL_PPS, NAL_SEI) and self._au_has_vcl)
            or (t in VCL and self._au_has_vcl and len(nal) > 1 and nal[1] & 0x80)
        )
        if starts_new and self._au:
            out.append(self._au)
            self._au, self._au_has_vcl = [], False
        if t == NAL_AUD:
            return
        self._au.append(nal)
        if t in VCL:
            self._au_has_vcl = True

    def _complete_nals(self):
        buf = self._buf
        starts = []
        i = 0
        while True:
            j = buf.find(b"\x00\x00\x01", i)
            if j < 0:
                break
            starts.append((j - 1 if j > 0 and buf[j - 1] == 0 else j, j + 3))
            i = j + 3
        if len(starts) < 2:
            return
        for (_, body), (nxt, _) in zip(starts, starts[1:], strict=False):
            nal = buf[body:nxt]
            if nal:
                yield nal
        self._buf = buf[starts[-1][0]:]

    @staticmethod
    def _strip_start_code(buf: bytes) -> bytes:
        j = buf.find(b"\x00\x00\x01")
        return buf[j + 3:] if j >= 0 else b""


async def access_units(stdout: asyncio.StreamReader) -> AsyncIterator[list[bytes]]:
    splitter = AccessUnitSplitter()
    while True:
        chunk = await stdout.read(65536)
        if not chunk:
            for au in splitter.flush():
                yield au
            return
        for au in splitter.feed(chunk):
            yield au


def find_nal(au: list[bytes], kind: int) -> bytes | None:
    return next((n for n in au if nal_type(n) == kind), None)
