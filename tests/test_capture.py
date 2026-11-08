from airmirror import capture

SC = b"\x00\x00\x00\x01"
AUD, SPS, PPS, SEI = b"\x09\xf0", b"\x67\x64\x00\x29", b"\x68\xee", b"\x06\x05"
IDR, P_FIRST, P_SECOND = b"\x65\x88\x80", b"\x41\x9a\x80", b"\x41\x1a\x80"  # first_mb bit set/clear


def annexb(*nals):
    return b"".join(SC + n for n in nals)


def run(data, chunk=None):
    s = capture.AccessUnitSplitter()
    out = []
    if chunk:
        for i in range(0, len(data), chunk):
            out += s.feed(data[i:i + chunk])
    else:
        out += s.feed(data)
    return out + s.flush()


def test_splits_on_aud():
    aus = run(annexb(AUD, SPS, PPS, IDR, AUD, P_FIRST, AUD, P_FIRST))
    assert aus == [[SPS, PPS, IDR], [P_FIRST], [P_FIRST]]


def test_splits_without_aud():
    aus = run(annexb(SPS, PPS, SEI, IDR, P_FIRST, P_SECOND, SPS, PPS, IDR))
    assert aus == [[SPS, PPS, SEI, IDR], [P_FIRST, P_SECOND], [SPS, PPS, IDR]]


def test_byte_by_byte_feeding_matches():
    data = annexb(AUD, SPS, PPS, IDR, AUD, P_FIRST, AUD, P_FIRST, P_SECOND)
    assert run(data, chunk=1) == run(data) == run(data, chunk=7)


def test_three_byte_start_codes():
    data = b"\x00\x00\x01" + SPS + b"\x00\x00\x01" + PPS + b"\x00\x00\x01" + IDR
    assert run(data) == [[SPS, PPS, IDR]]


def test_ffmpeg_command_screen_and_test_pattern():
    cmd = capture.ffmpeg_command("ffmpeg", "libx264", monitor=1, fps=60)
    joined = " ".join(cmd)
    assert "ddagrab=output_idx=1:framerate=60" in joined
    assert "-bf 0" in joined and "dump_extra" in joined and cmd[-2:] == ["h264", "-"]
    assert "testsrc2" in " ".join(capture.ffmpeg_command("ffmpeg", "h264_nvenc", test_pattern=True))


def test_find_nal():
    assert capture.find_nal([SPS, PPS, IDR], capture.NAL_PPS) == PPS
    assert capture.find_nal([P_FIRST], capture.NAL_SPS) is None
