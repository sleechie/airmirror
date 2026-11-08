# AirMirror

**Mirror your Windows screen to an AirPlay TV. No Apple device or extra hardware needed.**

Lots of TVs now have AirPlay built in, including Fire TV smart TVs, Samsung, LG, Vizio and Roku. iPhones and Macs can mirror to them with a tap, but Windows has had no free way to join in. AirMirror fills that gap. It's a small tray icon: click it and your screen appears on the TV, click it again and the mirroring stops.

## Install

1. Download **AirMirrorSetup.exe** from the [latest release](https://github.com/sleechie/airmirror/releases/latest) and run it. You don't need admin rights.
2. An AirMirror icon appears in the system tray, next to the clock. If you don't see it, check the `^` overflow menu and drag it onto the taskbar.
3. **Click the icon.** The first time, your TV shows a 4-digit code. Type it into the box that pops up. You only do this once per TV.
4. From then on, click the icon to start mirroring and click again to stop. The icon turns blue while you're live.

Things you may see the first time:
- **"Windows protected your PC"**: the installer isn't code-signed. Click *More info* → *Run anyway*.
- **A Windows Firewall prompt**: allow AirMirror on private networks. The TV has to reach your PC to keep the video in sync.

Right-click the icon to pick another TV or to turn *Start with Windows* on or off.

## Compatibility

AirMirror works with AirPlay 2 receivers that use HomeKit-style pairing and **don't** require Apple's FairPlay DRM handshake. Most third-party "AirPlay 2" TVs are like this. Apple TVs and some older receivers require FairPlay, so `airmirror scan` lists them as unsupported.

| Receiver | Result |
| --- | --- |
| Insignia NS-42F201NA23 (Fire TV, AirTunes 377.40) | ✅ Works: 1080p30, smooth |
| Other Fire TV, Samsung, LG, TCL, Roku, Vizio AirPlay 2 TVs | Should work, untested. Please [report results](https://github.com/sleechie/airmirror/issues)! |
| Apple TV | ❌ Needs FairPlay (not implemented) |

Requirements: Windows 10 or 11 on x64. Video is encoded on the GPU when one is available (NVIDIA NVENC, AMD AMF, Intel Quick Sync). Otherwise Windows' built-in encoder is used.

**Not yet supported:** audio (the TV shows your screen but plays no sound), and capture on macOS or Linux.

## Command line (optional)

You can also install AirMirror as a Python package. This needs Python 3.10+ and [FFmpeg](https://ffmpeg.org) on your `PATH` (`winget install Gyan.FFmpeg`).

```
pip install git+https://github.com/sleechie/airmirror
airmirror scan                     # list AirPlay receivers and whether they're supported
airmirror pair "Living Room TV"    # one-time pairing; type the code shown on the TV
airmirror mirror                   # mirror to your paired TV (Ctrl+C stops)
airmirror mirror --monitor 1 --fps 60 --bitrate 20M
airmirror mirror --test            # send a test pattern instead of the screen
airmirror tray                     # the same tray app as the installer
airmirror install --startup        # add a Start Menu shortcut and start at sign-in
```

## How it works

AirMirror talks to the TV the same way an iPhone does when it mirrors:

1. **Discovery.** It finds receivers over Bonjour (`_airplay._tcp`) and reads their feature flags.
2. **Pairing.** It runs HomeKit pair-setup once, with the PIN shown on the TV, and keeps the long-term keys. [pyatv](https://github.com/postlund/pyatv) handles this part.
3. **Session.** Each time you mirror, it runs pair-verify, which encrypts the RTSP control channel with ChaCha20-Poly1305. Then it sends a `SETUP` with `isScreenMirroringSession` and a second `SETUP` for a type-110 (screen) stream. It also runs an NTP responder so the TV can sync clocks.
4. **Video.** FFmpeg captures the desktop (Desktop Duplication API) and encodes low-latency H.264. Each frame goes over TCP behind a 128-byte header, sealed with ChaCha20-Poly1305 using a key derived from the pair-verify secret.

The packet-level details are in [docs/PROTOCOL.md](docs/PROTOCOL.md).

## Credits

- [pyatv](https://github.com/postlund/pyatv) (MIT): discovery, HomeKit pairing, the encrypted RTSP channel.
- [doubletake](https://github.com/omarroth/doubletake) (LGPL-3.0): a Go AirPlay mirroring sender for Linux. Its source is where the stream-key derivation and framing for HomeKit-paired receivers were confirmed. AirMirror is an independent Python implementation and shares no code with it.
- [UxPlay](https://github.com/FDH2/UxPlay) (GPL-3.0): its receiver-side parsing documents the mirroring header layout.
- [FFmpeg](https://ffmpeg.org) (LGPL build bundled in the installer): capture and encoding.

AirPlay is a trademark of Apple Inc. This project is not affiliated with or endorsed by Apple.

## License

MIT
