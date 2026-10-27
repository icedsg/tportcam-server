import base64

import pytest

from camgrid_hub.cli import main
from camgrid_hub.onvif import OnvifClient, OnvifError, password_digest


def test_password_digest_known_value():
    # SHA1(nonce + created + password), base64; nonce/created fixed
    nonce = base64.b64decode("LKqI6G/AikKCQrN0zqZFlg==")
    assert password_digest(nonce, "2010-09-16T07:50:45Z", "userpassword") == "tuOSpGlFlIXsozq4HFNeeGeFLEI="


@pytest.mark.parametrize("fixture", ["cam", "digest_cam"])
def test_profiles_and_uris(request, fixture):
    c = request.getfixturevalue(fixture)
    with OnvifClient(c.xaddr, "admin", "secret") as cl:
        assert cl.device_information()["Manufacturer"] == "CamSim"
        profiles = cl.profiles()
        assert [(p.token, p.encoding, p.width, p.height) for p in profiles] == [
            ("main", "H264", 1920, 1080), ("sub", "H264", 640, 360)]
        assert cl.stream_uri("sub") == "rtsp://127.0.0.1:8554/sub"
        assert cl.snapshot_uri("main").endswith("/snap/main.jpg")
        assert cl.media_xaddr.endswith("/onvif/media_service")


@pytest.mark.parametrize("fixture", ["cam", "digest_cam"])
def test_wrong_password_fails(request, fixture):
    c = request.getfixturevalue(fixture)
    with OnvifClient(c.xaddr, "admin", "nope") as cl, pytest.raises(OnvifError, match="Not Authorized|40[01]"):
        cl.profiles()


def test_cli_discover(cam, capsys):
    rc = main(["discover", "--timeout", "1", "--target", f"127.0.0.1:{cam.probe_port}",
               "--user", "admin", "--password", "secret"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Sim Cam" in out and "rtsp://127.0.0.1:8554/main" in out and "1 camera(s)" in out
