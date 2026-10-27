"""camgrid_hub command line: `camgrid_hub discover`, `camgrid_hub serve`."""
from __future__ import annotations

import argparse
import json
import os
import socket
from pathlib import Path
from urllib.parse import urlparse

from .discovery import MULTICAST, discover
from .onvif import OnvifClient, OnvifError


def _target(s: str) -> tuple[str, int]:
    host, _, port = s.partition(":")
    return host, int(port or 3702)


def describe(device, user: str, password: str) -> dict:
    cam = {"name": device.name, "hardware": device.hardware, "ip": device.source or urlparse(device.xaddrs[0]).hostname,
           "xaddr": device.xaddrs[0], "address": device.address, "streams": []}
    if not user:
        return cam
    try:
        with OnvifClient(device.xaddrs[0], user, password) as c:
            info = c.device_information()
            cam["manufacturer"], cam["model"] = info.get("Manufacturer", ""), info.get("Model", "")
            for p in c.profiles():
                cam["streams"].append({"profile": p.token, "name": p.name, "encoding": p.encoding,
                                       "size": f"{p.width}x{p.height}", "rtsp": c.stream_uri(p.token)})
    except OnvifError as e:
        cam["error"] = str(e)
    return cam


def cmd_discover(a) -> int:
    targets = [_target(t) for t in a.target] or [MULTICAST]
    user = a.user or os.environ.get("CAMGRID_USER", "")
    password = a.password or os.environ.get("CAMGRID_PASSWORD", "")
    cams = [describe(d, user, password) for d in discover(a.timeout, targets)]
    if a.json:
        print(json.dumps(cams, indent=2))
        return 0
    if not cams:
        print("No ONVIF cameras answered.")
        return 1
    for cam in cams:
        print(f"{cam['name']}  {cam['ip']}  {cam['hardware']}  {cam['xaddr']}")
        for s in cam["streams"]:
            print(f"    {s['profile']}  {s['encoding']} {s['size']}  {s['rtsp']}")
        if "error" in cam:
            print(f"    error: {cam['error']}")
    print(f"{len(cams)} camera(s)")
    return 0


def cmd_serve(a) -> int:
    import uvicorn

    from .cloud import CloudSettings, Pushers
    from .hub import GO2RTC_RTSP, Go2rtc, find_go2rtc, from_described, go2rtc_config, write_config
    from .mdns import Announcer
    from .server import create_app

    targets = [_target(t) for t in a.target] or [MULTICAST]
    user = a.user or os.environ.get("CAMGRID_USER", "")
    password = a.password or os.environ.get("CAMGRID_PASSWORD", "")
    cams = [from_described(describe(d, user, password), user, password) for d in discover(a.timeout, targets)]
    for c in cams:
        print(f"{c.id}  {c.name}  {c.ip}  " + (c.error or "ok"))
    cfg = write_config(go2rtc_config(cams), Path(a.data) / "go2rtc.yaml")
    go2rtc = None if a.no_go2rtc else Go2rtc(find_go2rtc(a.go2rtc), [cfg, *map(Path, a.go2rtc_config)]).start()
    cloud = CloudSettings(Path(a.data) / "cloud.json", a.relay)
    pushers = Pushers(cloud, {c.id for c in cams if c.main}, f"rtsp://127.0.0.1:{GO2RTC_RTSP}").start()
    pushers.sync()
    name = a.name or f"camgrid hub {socket.gethostname()}"
    mdns = None if a.no_mdns else Announcer(name, a.port).start()
    try:
        uvicorn.run(create_app(cams, name, cloud=cloud, pushers=pushers),
                    host=a.host, port=a.port, log_level="warning")
    finally:
        pushers.stop()
        if mdns:
            mdns.stop()
        if go2rtc:
            go2rtc.stop()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="camgrid_hub")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("discover", help="find ONVIF cameras by WS-Discovery")
    d.add_argument("--timeout", type=float, default=3.0)
    d.add_argument("--target", action="append", default=[], metavar="IP[:PORT]",
                   help="unicast probe instead of multicast (repeatable)")
    d.add_argument("--user", default="", help="camera user (or CAMGRID_USER) to also read stream URIs")
    d.add_argument("--password", default="", help="camera password (or CAMGRID_PASSWORD)")
    d.add_argument("--json", action="store_true")
    d.set_defaults(func=cmd_discover)
    s = sub.add_parser("serve", help="discover cameras, run go2rtc, serve the API + web grid, announce by mDNS")
    s.add_argument("--timeout", type=float, default=3.0)
    s.add_argument("--target", action="append", default=[], metavar="IP[:PORT]")
    s.add_argument("--user", default="")
    s.add_argument("--password", default="")
    s.add_argument("--host", default="0.0.0.0")
    s.add_argument("--port", type=int, default=8780)
    s.add_argument("--name", default="", help="hub name shown in the app (default: camgrid hub <hostname>)")
    s.add_argument("--data", default="data", help="folder for the generated go2rtc.yaml")
    s.add_argument("--go2rtc", default="", help="go2rtc binary (or GO2RTC_BIN, or on PATH)")
    s.add_argument("--go2rtc-config", action="append", default=[], metavar="FILE",
                   help="extra go2rtc config merged after the generated one (repeatable)")
    s.add_argument("--relay", default="", help="tport.stream relay for Send to tport.stream (or TPORTCAM_RELAY; "
                   "default rtmps://cam.tport.stream:1936)")
    s.add_argument("--no-go2rtc", action="store_true")
    s.add_argument("--no-mdns", action="store_true")
    s.set_defaults(func=cmd_serve)
    a = ap.parse_args(argv)
    return a.func(a)
