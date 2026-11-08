# AirPlay screen mirroring to HomeKit-paired receivers

This page covers what AirMirror sends. It was checked against a real receiver, an Insignia Fire TV with `AirTunes/377.40.00` and `AirPlay;3.6.0.126`. Field names follow Apple's senders where they're known.

## Is a receiver supported?

Read the `features` TXT record from `_airplay._tcp` as `0xLOW,0xHIGH` (64 bits):

| bit | meaning | needed |
| --- | --- | --- |
| 7 | screen mirroring | set |
| 14 | FairPlay authentication | **clear** (FairPlay isn't implemented) |
| 46 | HomeKit pairing and access control | set |
| 48 | CoreUtils pairing and encryption | set |

The test receiver advertises `0x7F8AD0,0x38BCB46` and `statusFlags=0x244`. Bit 9 of `statusFlags` means a one-time PIN is required.

## Pairing and the control channel

1. **Pair-setup (once).** `POST /pair-pin-start`, then SRP-6a pair-setup (TLV8 over `POST /pair-setup`) with the PIN the TV shows. The result is the receiver's long-term public key, which is stored together with our own Ed25519 identity.
2. **Pair-verify (every session).** Over `POST /pair-verify`, an X25519 exchange produces a 32-byte shared secret `S`.
3. **Control encryption.** After pair-verify, the TCP connection on port 7000 switches to ChaCha20-Poly1305 framing. The keys are `HKDF-SHA512(S, salt="Control-Salt", info="Control-Write-Encryption-Key" / "Control-Read-Encryption-Key")`.

## Session setup (RTSP over the encrypted channel)

The first `SETUP` uses a binary plist body:

```
deviceID, macAddress, sessionUUID, name, model, sourceVersion,
isScreenMirroringSession: true, updateSessionRequest: false,
combinedGetInfoWithControlSetup: true,
timingProtocol: "NTP", timingPort: <our UDP NTP responder>
```

The reply contains `eventPort` (an encrypted event channel using `Events-Salt` keys) and `timingPort`. The receiver then sends NTP timing requests to our `timingPort`.

The second `SETUP` adds the screen stream:

```
streams: [{ type: 110, streamConnectionID: <random int63>, latencyMs: 90,
            timestampInfo: [{name: SubSu}, {name: BePxT}, {name: AfPxT}, {name: BefEn}, {name: EmEnc}],
            shk: <32 random bytes>, shiv: <16 random bytes> }]
```

The reply is `streams: [{ type: 110, dataPort: N }]`. Open TCP to `dataPort`, then send `RECORD` unless the session reply set `skipRecord`. While mirroring, `POST /feedback` every 2 s.

## Data channel packets

Each packet is a 128-byte header followed by its payload. All integers are little-endian.

| bytes | field |
| --- | --- |
| 0-3 | payload length (for video, includes the 16-byte tag) |
| 4 | type: `0` video, `1` codec configuration, `2` heartbeat |
| 5 | `0x10` if the video frame is an IDR |
| 6-7 | option: `16 01` on H.264 codec packets, `1e 00` on heartbeats |
| 8-15 | NTP timestamp of the frame (`seconds << 32 \| fraction`) |
| 16-23, 40-47, 56-63 | codec packets only: width and height as `float32` |

* **Codec packet** (unencrypted): an `avcC` record (`01 profile compat level FF E1 <sps> 01 <pps>`) followed by the trailer `02 00 00 00`. It's sent first and again whenever SPS/PPS change.
* **Video packet**: an access unit in AVCC form (each NAL prefixed with a 4-byte big-endian length), sealed with ChaCha20-Poly1305:
  * key = `HKDF-SHA512(S, salt="DataStream-Salt" + str(streamConnectionID), info="DataStream-Output-Encryption-Key")`, 32 bytes
  * nonce = `00 00 00 00` followed by the 64-bit little-endian frame counter, starting at 0
  * associated data = the 128-byte header
  * the 16-byte tag is appended to the ciphertext
* **Heartbeat**: a header with type 2, no payload, about once per second.

Receivers that require FairPlay take a different path. There, the video key is `SHA-512("AirPlayStreamKey<id>" + aeskey)[:16]` with AES-128-CTR, where `aeskey` comes from the FairPlay-wrapped `ekey`. UxPlay documents that path.
