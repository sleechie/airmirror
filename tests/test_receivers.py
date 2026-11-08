import pytest

from airmirror import protocol, receivers

TV_FEATURES = protocol.parse_features("0x7F8AD0,0x38BCB46")
APPLE_TV_FEATURES = protocol.FEATURE_SCREEN | protocol.FEATURE_FAIRPLAY | protocol.FEATURE_HOMEKIT_PAIRING


def rx(name, ident, features=TV_FEATURES, paired=True):
    return receivers.Receiver(name, ident, "192.0.2.1", features, paired, config=None)


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(receivers, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(receivers, "CONFIG_FILE", tmp_path / "config.json")


def test_status():
    assert rx("TV", "a").status == "ready"
    assert rx("TV", "a", paired=False).status == "needs pairing"
    assert rx("ATV", "b", APPLE_TV_FEATURES).status == "unsupported (needs FairPlay)"
    assert rx("Speaker", "c", protocol.FEATURE_HOMEKIT_PAIRING).status == "no screen mirroring"


def test_choose_by_name_and_partial_name():
    tvs = [rx("Living Room TV", "aa"), rx("Bedroom TV", "bb")]
    assert receivers.choose(tvs, "bedroom tv").identifier == "bb"
    assert receivers.choose(tvs, "living").identifier == "aa"
    with pytest.raises(LookupError):
        receivers.choose(tvs, "tv")
    with pytest.raises(LookupError):
        receivers.choose(tvs, "kitchen")


def test_choose_default_then_only_paired():
    tvs = [rx("Living Room TV", "aa"), rx("Bedroom TV", "bb", paired=False)]
    assert receivers.choose(tvs, None).identifier == "aa"
    receivers.save_settings(default_receiver="bb")
    assert receivers.choose(tvs, None).identifier == "bb"


def test_choose_requires_pairing():
    with pytest.raises(LookupError, match="pair"):
        receivers.choose([rx("TV", "a", paired=False)], None)
