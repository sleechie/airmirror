"""Wire format for AirPlay screen mirroring (stream type 110).

Targets AirPlay 2 receivers that use HomeKit-style pairing and do not require
FairPlay (features bit 14 clear): most third-party "AirPlay 2" TVs.

Every packet on the mirroring data connection is a 128-byte header followed by
a payload:

    bytes 0-3    payload size, uint32 LE (includes the 16-byte Poly1305 tag)
    byte  4      payload type: 0 video, 1 codec config, 2 heartbeat
    byte  5      0x10 when the video payload is an IDR frame
    bytes 6-7    option: 0x16 0x01 for H.264 codec packets, 0x1e 0x00 heartbeats
    bytes 8-15   NTP timestamp, uint64 LE (seconds << 32 | fraction)
    bytes 16-63  codec packets only: source/destination size as float32 LE

Video payloads are AVCC (4-byte big-endian length per NAL unit) sealed with
ChaCha20-Poly1305. The header is the associated data, and the nonce is four
zero bytes followed by a little-endian 64-bit frame counter. The key is
HKDF-SHA512 of the pair-verify X25519 shared secret with salt
"DataStream-Salt<streamConnectionID>" and info "DataStream-Output-Encryption-Key".
"""
from __future__ import annotations

import struct
from collections.abc import Iterable

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

HEADER_SIZE = 128
TAG_SIZE = 16

TYPE_VIDEO = 0
TYPE_CODEC = 1
TYPE_HEARTBEAT = 2

FLAG_IDR = 0x10
OPTION_H264_CODEC = 0x0116  # bytes 6-7 = 16 01
OPTION_HEARTBEAT = 0x001E  # bytes 6-7 = 1e 00

STREAM_TYPE_SCREEN = 110


def header(size: int, ptype: int, *, flags: int = 0, option: int = 0, timestamp: int = 0) -> bytearray:
    h = bytearray(HEADER_SIZE)
    struct.pack_into("<IBBHQ", h, 0, size, ptype, flags, option, timestamp)
    return h


def avcc_config(sps: bytes, pps: bytes) -> bytes:
    """AVCDecoderConfigurationRecord plus the 4-byte trailer receivers expect."""
    return (
        bytes([1, sps[1], sps[2], sps[3], 0xFF, 0xE1])
        + struct.pack(">H", len(sps)) + sps
        + b"\x01" + struct.pack(">H", len(pps)) + pps
        + b"\x02\x00\x00\x00"
    )


def codec_packet(sps: bytes, pps: bytes, width: int, height: int, timestamp: int) -> bytes:
    payload = avcc_config(sps, pps)
    h = header(len(payload), TYPE_CODEC, option=OPTION_H264_CODEC, timestamp=timestamp)
    for offset in (16, 40, 56):
        struct.pack_into("<ff", h, offset, float(width), float(height))
    return bytes(h) + payload


def heartbeat_packet() -> bytes:
    return bytes(header(0, TYPE_HEARTBEAT, option=OPTION_HEARTBEAT))


def avcc_payload(nals: Iterable[bytes]) -> bytes:
    return b"".join(struct.pack(">I", len(n)) + n for n in nals)


def stream_key(shared_secret: bytes, stream_connection_id: int) -> bytes:
    return HKDF(
        algorithm=hashes.SHA512(),
        length=32,
        salt=f"DataStream-Salt{stream_connection_id}".encode(),
        info=b"DataStream-Output-Encryption-Key",
    ).derive(shared_secret)


def nonce(counter: int) -> bytes:
    return b"\x00" * 4 + struct.pack("<Q", counter)


class FrameSealer:
    """Encrypts video access units into mirroring packets."""

    def __init__(self, key: bytes) -> None:
        self._aead = ChaCha20Poly1305(key)
        self.counter = 0

    def seal(self, nals: Iterable[bytes], idr: bool, timestamp: int) -> bytes:
        payload = avcc_payload(nals)
        h = bytes(header(len(payload) + TAG_SIZE, TYPE_VIDEO, flags=FLAG_IDR if idr else 0, timestamp=timestamp))
        sealed = self._aead.encrypt(nonce(self.counter), payload, h)
        self.counter += 1
        return h + sealed


def parse_features(value: str) -> int:
    """Parse an AirPlay features TXT value ("0x5A7FFFF7,0x1E" or a plain int)."""
    parts = [p.strip() for p in value.split(",") if p.strip()]
    low = int(parts[0], 0) if parts else 0
    high = int(parts[1], 0) if len(parts) > 1 else 0
    return low | (high << 32)


FEATURE_SCREEN = 1 << 7
FEATURE_FAIRPLAY = 1 << 14
FEATURE_HOMEKIT_PAIRING = 1 << 46
