import json
import os

from fastapi.testclient import TestClient

from camgrid_hub.cloud import CloudLink, CloudSettings, Pushers, ffmpeg_args, validate
from camgrid_hub.server import create_app
from tests.test_hub import fake_go2rtc, sim_cameras


def test_validate():
    assert validate("Ab12cd34Ef56", "k-123", "sub") == ""
    assert "stream id" in validate("bad id!", "k", "sub")
    assert "key" in validate("Ab12cd34Ef56", "", "sub")
    assert "key" in validate("Ab12cd34Ef56", "a b", "sub")
    assert "quality" in validate("Ab12cd34Ef56", "k", "4k")


def test_publish_sub_by_default_main_when_chosen(tmp_path):
    s = CloudSettings(tmp_path / "cloud.json", "rtmps://relay.test:1936/")
    s.links = {"cam_a": CloudLink("Ab12cd34Ef56", "k/+=1"), "cam_b": CloudLink("Zz12cd34Ef56", "k2", "main"),
               "cam_off": CloudLink("Off2cd34Ef56", "k3", enabled=False), "cam_gone": CloudLink("Gone2d34Ef56", "k4")}
    assert s.pushes({"cam_a", "cam_b", "cam_off"}) == {
        "cam_a": ("cam_a_sub", "rtmps://relay.test:1936/Ab12cd34Ef56?key=k%2F%2B%3D1"),
        "cam_b": ("cam_b", "rtmps://relay.test:1936/Zz12cd34Ef56?key=k2")}
    args = ffmpeg_args("ffmpeg", "rtsp://127.0.0.1:8554", "cam_a_sub", "rtmps://r/x?key=k")
    assert args[args.index("-i") + 1] == "rtsp://127.0.0.1:8554/cam_a_sub"
    assert args[-3:] == ["-f", "flv", "rtmps://r/x?key=k"]
    assert ["-c", "copy"] == args[args.index("-c"):args.index("-c") + 2]
    s.save()
    assert os.stat(s.path).st_mode & 0o777 == 0o600
    again = CloudSettings(s.path)
    assert again.links["cam_b"] == s.links["cam_b"] and again.relay == "rtmps://cam.tport.stream:1936"


def test_pushers_start_restart_and_stop(tmp_path):
    s = CloudSettings(tmp_path / "cloud.json", "rtmps://relay.test:1936")
    s.links = {"cam_a": CloudLink("Ab12cd34Ef56", "k")}
    fake = tmp_path / "ffmpeg"
    fake.write_text("#!/bin/sh\nexec sleep 30\n")
    fake.chmod(0o755)
    p = Pushers(s, {"cam_a"}, "rtsp://127.0.0.1:8554", str(fake))
    p.sync()
    assert p.status() == {"cam_a": "pushing"}
    first = p.procs["cam_a"][1]
    s.links["cam_a"].quality = "main"      # new target: old pusher killed, new one started
    p.sync()
    assert first.poll() is not None and p.procs["cam_a"][0][0] == "cam_a"
    p.procs["cam_a"][1].kill()
    p.procs["cam_a"][1].wait()
    p._tick()
    assert p.status() == {"cam_a": "retrying"} and p.procs["cam_a"][3] == 5.0
    del s.links["cam_a"]
    p.sync()
    assert p.status() == {}
    p.stop()


def test_cloud_api_never_returns_keys(cam, tmp_path):
    transport, _ = fake_go2rtc()
    cloud = CloudSettings(tmp_path / "cloud.json", "rtmps://relay.test:1936")
    class FakePushers:
        syncs = 0

        def sync(self):
            self.syncs += 1

        def status(self):
            return {"cam_127_0_0_1": "pushing"}
    pushers = FakePushers()
    app = create_app(sim_cameras(cam), "t", transport=transport, cloud=cloud, pushers=pushers)
    with TestClient(app) as http:
        assert http.get("/api/cloud").json() == {"relay": "rtmps://relay.test:1936", "cameras": {}}
        r = http.put("/api/cloud/cam_127_0_0_1", json={"stream_id": "Ab12cd34Ef56", "key": "secret-key-1"})
        assert r.status_code == 200 and r.json() == {"stream_id": "Ab12cd34Ef56", "quality": "sub", "enabled": True,
                                                     "has_key": True}
        # blank key keeps the saved one for the same stream id
        r = http.put("/api/cloud/cam_127_0_0_1", json={"stream_id": "Ab12cd34Ef56", "quality": "main"})
        assert r.status_code == 200 and cloud.links["cam_127_0_0_1"].key == "secret-key-1"
        # a new stream id needs its own key
        assert http.put("/api/cloud/cam_127_0_0_1", json={"stream_id": "New2cd34Ef56"}).status_code == 400
        assert http.put("/api/cloud/nope", json={"stream_id": "Ab12cd34Ef56", "key": "k"}).status_code == 404
        listed = http.get("/api/cloud").json()
        assert listed["cameras"]["cam_127_0_0_1"]["status"] == "pushing"
        assert "secret-key-1" not in json.dumps(listed)
        assert "secret-key-1" not in json.dumps(http.get("/api/cameras").json())
        assert http.get("/go2rtc/api/config").status_code == 404
        assert json.loads(cloud.path.read_text())["cameras"]["cam_127_0_0_1"]["quality"] == "main"
        assert http.delete("/api/cloud/cam_127_0_0_1").json() == {"ok": True}
        assert cloud.links == {} and pushers.syncs == 3
