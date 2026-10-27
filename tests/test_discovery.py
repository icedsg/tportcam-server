from camgrid_hub.discovery import discover, parse_probe_matches, probe_message


def test_probe_message_is_ws_discovery_probe():
    msg = probe_message("abc").decode()
    assert "urn:uuid:abc" in msg
    assert "dn:NetworkVideoTransmitter" in msg


def test_parse_ignores_junk():
    assert parse_probe_matches(b"not xml") == []
    assert parse_probe_matches(b"<a/>") == []


def test_discover_finds_simulated_cameras(cam, digest_cam):
    found = discover(timeout=1.0, targets=[("127.0.0.1", cam.probe_port), ("127.0.0.1", digest_cam.probe_port)])
    by_name = {d.name: d for d in found}
    assert set(by_name) == {"Sim Cam", "Digest Cam"}
    d = by_name["Sim Cam"]
    assert d.xaddrs == [cam.xaddr]
    assert d.hardware == "SIM-1"
    assert d.address == f"urn:uuid:{cam.uuid}"
    assert d.source == "127.0.0.1"


def test_discover_nothing_answers():
    assert discover(timeout=0.3, targets=[("127.0.0.1", 9)]) == []
