"""Send to tport.stream (CR-0446): per camera, a stream id + publish key the user copied from the tport cam app.
The hub runs one `ffmpeg -c copy` per linked camera: go2rtc's local RTSP re-stream -> RTMPS on the relay
(cam.tport.stream:1936), key as `?key=` (the relay's auth hook reads it). No re-encode, video only. go2rtc's own
`publish` is not used: MediaMTX can't decode its RTMP output (go2rtc 1.9.15, "unable to decode AVCC").

Keys live only in `<data>/cloud.json` (mode 600) and the ffmpeg command line; the hub API never returns them."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import quote

RELAY = "rtmps://cam.tport.stream:1936"
STREAM_ID = re.compile(r"^[A-Za-z0-9_-]{6,64}$")
QUALITIES = ("sub", "main")     # sub = the camera's 720p-or-less stream (free plan); main only if the plan allows it


@dataclass
class CloudLink:
    stream_id: str
    key: str
    quality: str = "sub"
    enabled: bool = True

    def public(self) -> dict:
        return {"stream_id": self.stream_id, "quality": self.quality, "enabled": self.enabled, "has_key": bool(self.key)}


def validate(stream_id: str, key: str, quality: str) -> str:
    """'' when fine, else the reason (shown to the user)."""
    if not STREAM_ID.match(stream_id or ""):
        return "stream id: letters, digits, - or _ (as shown in the app)"
    if not key or len(key) > 200 or any(c.isspace() for c in key):
        return "publish key: paste it from the app (no spaces)"
    if quality not in QUALITIES:
        return "quality: sub or main"
    return ""


class CloudSettings:
    def __init__(self, path: Path, relay: str = ""):
        self.path = path
        self.relay = (relay or os.environ.get("TPORTCAM_RELAY", "") or RELAY).rstrip("/")
        self.links: dict[str, CloudLink] = {}
        if path.exists():
            raw = json.loads(path.read_text() or "{}")
            self.links = {cid: CloudLink(**v) for cid, v in raw.get("cameras", {}).items()}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump({"cameras": {cid: asdict(l) for cid, l in self.links.items()}}, f, indent=2)
        os.replace(tmp, self.path)

    def publish_url(self, link: CloudLink) -> str:
        return f"{self.relay}/{link.stream_id}?key={quote(link.key, safe='')}"

    def pushes(self, camera_ids: set[str]) -> dict[str, tuple[str, str]]:
        """camera id -> (go2rtc source stream `<id>_sub` or `<id>`, relay URL), for enabled links the hub has."""
        return {cid: (cid if l.quality == "main" else f"{cid}_sub", self.publish_url(l))
                for cid, l in self.links.items() if l.enabled and cid in camera_ids}


def ffmpeg_args(ffmpeg: str, rtsp_base: str, src: str, url: str) -> list[str]:
    return [ffmpeg, "-hide_banner", "-loglevel", "error", "-rtsp_transport", "tcp", "-i", f"{rtsp_base}/{src}",
            "-map", "0:v:0", "-c", "copy", "-f", "flv", url]


class Pushers:
    """Keeps one ffmpeg per camera in `pushes` running; a pusher that exits is started again after 5 s, 10 s, ...
    up to 60 s (relay down, key refused, camera gone). `sync()` after every settings change."""

    def __init__(self, cloud: CloudSettings, camera_ids: set[str], rtsp_base: str, ffmpeg: str = ""):
        self.cloud, self.camera_ids, self.rtsp_base = cloud, camera_ids, rtsp_base
        self.ffmpeg = ffmpeg or shutil.which("ffmpeg") or "ffmpeg"
        self.procs: dict[str, tuple[tuple[str, str], subprocess.Popen | None, float, float]] = {}
        self.lock = threading.Lock()
        self.stopped = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self) -> "Pushers":
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        return self

    def status(self) -> dict[str, str]:
        with self.lock:
            return {cid: ("pushing" if p and p.poll() is None else "retrying") for cid, (_, p, _, _) in self.procs.items()}

    def sync(self) -> None:
        want = self.cloud.pushes(self.camera_ids)
        with self.lock:
            for cid in list(self.procs):
                if self.procs[cid][0] != want.get(cid):
                    _kill(self.procs.pop(cid)[1])
            for cid, target in want.items():
                if cid not in self.procs:
                    self.procs[cid] = (target, None, 0.0, 0.0)   # started by the loop
        self._tick()

    def _tick(self) -> None:
        now = time.monotonic()
        with self.lock:
            for cid, (target, p, next_at, backoff) in list(self.procs.items()):
                if p and p.poll() is None:
                    continue
                if p:   # exited: wait before the next try; a run that lasted a minute resets the wait
                    backoff = 5.0 if now - next_at > 60 else min(max(backoff * 2, 5.0), 60.0)
                    self.procs[cid] = (target, None, now + backoff, backoff)
                    continue
                if now >= next_at:
                    p = subprocess.Popen(ffmpeg_args(self.ffmpeg, self.rtsp_base, *target),
                                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    self.procs[cid] = (target, p, now, backoff)

    def _loop(self) -> None:
        while not self.stopped.wait(1.0):
            self._tick()

    def stop(self) -> None:
        self.stopped.set()
        with self.lock:
            for _, p, _, _ in self.procs.values():
                _kill(p)
            self.procs.clear()


def _kill(p: subprocess.Popen | None) -> None:
    if p and p.poll() is None:
        p.terminate()
        try:
            p.wait(5)
        except subprocess.TimeoutExpired:
            p.kill()
