import json
import re

import httpx
from fastapi.testclient import TestClient

from camgrid_hub.cli import describe
from camgrid_hub.discovery import discover
from camgrid_hub.hub import camera_id, from_described, go2rtc_config, with_credentials, write_config
from camgrid_hub.mdns import SERVICE, service_info
from camgrid_hub.server import create_app


def sim_cameras(cam):
    devices = discover(1.0, [("127.0.0.1", cam.probe_port)])
    return [from_described(describe(d, "admin", "secret"), "admin", "secret") for d in devices]


def test_with_credentials_quotes_and_keeps_existing():
    assert with_credentials("rtsp://10.0.0.5:554/s1", "ad@min", "p:w/d") == "rtsp://ad%40min:p%3Aw%2Fd@10.0.0.5:554/s1"
    assert with_credentials("rtsp://u:p@10.0.0.5/s1", "x", "y") == "rtsp://u:p@10.0.0.5/s1"
    assert with_credentials("rtsp://10.0.0.5/s1", "", "") == "rtsp://10.0.0.5/s1"


def test_go2rtc_config_from_simulator(cam, tmp_path):
    cams = sim_cameras(cam)
    assert len(cams) == 1
    c = cams[0]
    assert c.id == camera_id("127.0.0.1") == "cam_127_0_0_1"
    assert c.main == "rtsp://admin:secret@127.0.0.1:8554/main"
    assert c.sub == "rtsp://admin:secret@127.0.0.1:8554/sub"
    cfg = go2rtc_config(cams)
    assert cfg["streams"] == {"cam_127_0_0_1": [c.main], "cam_127_0_0_1_sub": [c.sub]}
    assert cfg["api"]["listen"].startswith("127.0.0.1:")
    assert json.loads(write_config(cfg, tmp_path / "go2rtc.yaml").read_text()) == cfg


def test_camera_without_credentials_has_no_stream(cam):
    d = discover(1.0, [("127.0.0.1", cam.probe_port)])[0]
    c = from_described(describe(d, "", ""), "", "")
    assert not c.main and c.error
    assert go2rtc_config([c])["streams"] == {}


def fake_go2rtc():
    seen = []

    def handler(req: httpx.Request):
        seen.append((req.method, req.url.path, req.url.params.get("src")))
        if req.url.path == "/api/frame.jpeg":
            return httpx.Response(200, content=b"\xff\xd8jpeg", headers={"content-type": "image/jpeg"})
        if req.url.path == "/api/webrtc":
            return httpx.Response(200, json={"type": "answer", "sdp": "v=0"})
        return httpx.Response(200, json={"leak": "rtsp://admin:secret@..."})
    return httpx.MockTransport(handler), seen


def test_api_lists_cameras_without_passwords(cam):
    transport, seen = fake_go2rtc()
    with TestClient(create_app(sim_cameras(cam), "test hub", transport=transport)) as http:
        data = http.get("/api/cameras").json()
        assert data["hub"] == "test hub"
        c = data["cameras"][0]
        assert c["id"] == "cam_127_0_0_1" and c["has_sub"]
        assert c["sub"]["webrtc"] == "http://testserver/go2rtc/api/webrtc?src=cam_127_0_0_1_sub"
        assert c["main"]["rtsp"] == "rtsp://testserver:8554/cam_127_0_0_1"
        assert "secret" not in json.dumps(data)

        r = http.get("/api/cameras/cam_127_0_0_1/snapshot")
        assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
        assert ("GET", "/api/frame.jpeg", "cam_127_0_0_1_sub") in seen
        assert http.get("/api/cameras/nope/snapshot").status_code == 404

        r = http.post("/go2rtc/api/webrtc?src=cam_127_0_0_1", json={"type": "offer", "sdp": "v=0"})
        assert r.json()["type"] == "answer"
        for path in ("/go2rtc/api/streams", "/go2rtc/api/config", "/go2rtc/api/webrtc/../streams"):
            assert http.get(path).status_code == 404
        page = http.get("/")
        assert page.status_code == 200 and '<div id="root">' in page.text
        js = re.search(r'src="(/assets/[^"]+\.js)"', page.text).group(1)
        r = http.get(js)
        assert r.status_code == 200 and "RTCPeerConnection" in r.text


def test_mdns_service_info():
    info = service_info("test hub", 8780, "192.168.1.20")
    assert info.type == SERVICE == "_camgrid._tcp.local."
    assert info.port == 8780 and info.parsed_addresses() == ["192.168.1.20"]
    assert info.properties[b"api"] == b"/api/cameras"
