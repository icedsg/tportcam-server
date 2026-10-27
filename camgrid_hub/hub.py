"""Hub state: cameras from discovery, the go2rtc config built from them, and the go2rtc process."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

GO2RTC_API = 1984
GO2RTC_RTSP = 8554
GO2RTC_WEBRTC = 8555


@dataclass
class HubCamera:
    id: str
    name: str
    ip: str
    manufacturer: str = ""
    model: str = ""
    main: str = ""          # camera RTSP URI with credentials (never sent to clients)
    sub: str = ""
    error: str = ""
    streams: list[dict] = field(default_factory=list)

    def public(self) -> dict:
        return {"id": self.id, "name": self.name, "ip": self.ip, "manufacturer": self.manufacturer,
                "model": self.model, "error": self.error, "has_sub": bool(self.sub)}


def camera_id(ip: str) -> str:
    return "cam_" + re.sub(r"[^0-9A-Za-z]+", "_", ip).strip("_")


def with_credentials(uri: str, user: str, password: str) -> str:
    if not uri or not user:
        return uri
    p = urlsplit(uri)
    if p.username:
        return uri
    netloc = f"{quote(user, safe='')}:{quote(password, safe='')}@{p.hostname}" + (f":{p.port}" if p.port else "")
    return urlunsplit((p.scheme, netloc, p.path, p.query, p.fragment))


def from_described(cam: dict, user: str, password: str) -> HubCamera:
    """Builds a HubCamera from cli.describe() output: main = widest profile, sub = narrowest (if different)."""
    streams = sorted((s for s in cam.get("streams", []) if s.get("rtsp")),
                     key=lambda s: int(s["size"].split("x")[0] or 0), reverse=True)
    main = with_credentials(streams[0]["rtsp"], user, password) if streams else ""
    sub = with_credentials(streams[-1]["rtsp"], user, password) if len(streams) > 1 else ""
    return HubCamera(id=camera_id(cam["ip"]), name=cam["name"] or cam["ip"], ip=cam["ip"],
                     manufacturer=cam.get("manufacturer", ""), model=cam.get("model", ""), main=main, sub=sub,
                     error=cam.get("error", "") or ("" if main else "no stream URI (credentials?)"),
                     streams=[{k: s[k] for k in ("profile", "encoding", "size")} for s in streams])


def go2rtc_config(cameras: list[HubCamera], api_listen: str = f"127.0.0.1:{GO2RTC_API}") -> dict:
    """go2rtc config: `<id>` = main stream, `<id>_sub` = sub stream. The API stays on localhost (it would show the
    camera passwords in /api/streams); clients reach it through the hub's /go2rtc proxy."""
    streams: dict[str, list[str]] = {}
    for c in cameras:
        if c.main:
            streams[c.id] = [c.main]
            streams[f"{c.id}_sub"] = [c.sub or c.main]
    return {"api": {"listen": api_listen, "origin": "*"},
            "rtsp": {"listen": f":{GO2RTC_RTSP}"},
            "webrtc": {"listen": f":{GO2RTC_WEBRTC}"},
            "streams": streams}


def write_config(cfg: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2))   # JSON is valid YAML; go2rtc reads it as go2rtc.yaml
    path.chmod(0o600)                             # camera passwords inside
    return path


def find_go2rtc(explicit: str = "") -> str:
    for c in (explicit, os.environ.get("GO2RTC_BIN", ""), shutil.which("go2rtc") or "", "/usr/local/bin/go2rtc"):
        if c and Path(c).exists():
            return c
    raise FileNotFoundError("go2rtc not found: set --go2rtc or GO2RTC_BIN")


class Go2rtc:
    def __init__(self, binary: str, configs: list[Path]):
        self.binary, self.configs = binary, configs
        self.proc: subprocess.Popen | None = None

    def start(self) -> "Go2rtc":
        args = [self.binary]
        for c in self.configs:
            args += ["-config", str(c)]
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        return self

    def restart(self) -> None:
        self.stop()
        self.start()

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None
