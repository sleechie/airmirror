import hashlib
import hmac
import struct

from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

from airmirror import protocol


def hkdf_sha512(ikm, salt, info, length=32):
    prk = hmac.new(salt, ikm, hashlib.sha512).digest()
    return hmac.new(prk, info + b"\x01", hashlib.sha512).digest()[:length]


def test_header_layout():
    h = protocol.header(1234, protocol.TYPE_VIDEO, flags=protocol.FLAG_IDR, timestamp=0x0102030405060708)
    assert len(h) == 128
    assert struct.unpack_from("<I", h, 0)[0] == 1234
    assert h[4] == 0 and h[5] == 0x10 and h[6:8] == b"\x00\x00"
    assert struct.unpack_from("<Q", h, 8)[0] == 0x0102030405060708
    assert h[16:] == bytes(112)


def test_codec_packet():
    sps, pps = bytes([0x67, 0x64, 0x00, 0x29, 0xAC]), bytes([0x68, 0xEE, 0x3C, 0x80])
    pkt = protocol.codec_packet(sps, pps, 1920, 1080, timestamp=42)
    h, payload = pkt[:128], pkt[128:]
    assert h[4] == 1 and h[6:8] == b"\x16\x01"
    assert struct.unpack_from("<I", h, 0)[0] == len(payload)
    for off in (16, 40, 56):
        assert struct.unpack_from("<ff", h, off) == (1920.0, 1080.0)
    assert payload[:6] == bytes([1, 0x64, 0x00, 0x29, 0xFF, 0xE1])
    assert payload[6:8] == struct.pack(">H", len(sps)) and payload[8:8 + len(sps)] == sps
    assert payload.endswith(b"\x01" + struct.pack(">H", len(pps)) + pps + b"\x02\x00\x00\x00")


def test_heartbeat():
    hb = protocol.heartbeat_packet()
    assert len(hb) == 128 and hb[4] == 2 and hb[6:8] == b"\x1e\x00" and hb[:4] == bytes(4)


def test_stream_key_matches_reference_hkdf():
    secret = bytes(range(32))
    expected = hkdf_sha512(secret, b"DataStream-Salt1234567890", b"DataStream-Output-Encryption-Key")
    assert protocol.stream_key(secret, 1234567890) == expected


def test_sealed_frames_decrypt_with_header_as_aad():
    key = bytes(32)
    sealer = protocol.FrameSealer(key)
    nals = [b"\x65" + b"\xAA" * 50, b"\x06\x01\x02"]
    for counter in range(3):
        pkt = sealer.seal(nals, idr=True, timestamp=99)
        h, body = pkt[:128], pkt[128:]
        assert struct.unpack_from("<I", h, 0)[0] == len(body) == len(protocol.avcc_payload(nals)) + 16
        assert h[5] == 0x10
        nonce = b"\x00" * 4 + struct.pack("<Q", counter)
        assert ChaCha20Poly1305(key).decrypt(nonce, body, h) == protocol.avcc_payload(nals)
    assert sealer.counter == 3


def test_parse_features():
    value = protocol.parse_features("0x7F8AD0,0x38BCB46")
    assert value == 255521305393072848
    assert value & protocol.FEATURE_SCREEN
    assert not value & protocol.FEATURE_FAIRPLAY
    assert value & protocol.FEATURE_HOMEKIT_PAIRING
    assert protocol.parse_features("0x10") == 16
