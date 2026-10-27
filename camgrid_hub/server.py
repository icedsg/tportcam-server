"""Hub HTTP API (port 8780): camera list, snapshots, a go2rtc proxy for WebRTC/HLS, and the web app (web/ built from web/src by Vite)."""
from __future__ import annotations

from contextlib import asynccontextmanager
from importlib.resources import files

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .cloud import CloudLink, CloudSettings, Pushers, validate
from .hub import GO2RTC_API, GO2RTC_RTSP, HubCamera

HUB_PORT = 8780
# go2rtc endpoints clients may use; /api/streams and /api/config stay hidden (they hold camera passwords)
PROXY_ALLOWED = ("webrtc", "frame.jpeg", "stream.m3u8", "hls/")
WEB = files("camgrid_hub").joinpath("web")


class CloudIn(BaseModel):
    stream_id: str
    key: str = ""           # blank = keep the saved key (changing quality or turning it off)
    quality: str = "sub"
    enabled: bool = True


def create_app(cameras: list[HubCamera], hub_name: str = "camgrid hub",
               go2rtc_url: str = f"http://127.0.0.1:{GO2RTC_API}",
               transport: httpx.AsyncBaseTransport | None = None,
               cloud: CloudSettings | None = None, pushers: Pushers | None = None) -> FastAPI:
    client = httpx.AsyncClient(base_url=go2rtc_url, timeout=15, transport=transport)

    @asynccontextmanager
    async def lifespan(_app):
        yield
        await client.aclose()

    app = FastAPI(title="camgrid hub", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.cameras = cameras

    def find(cam_id: str) -> HubCamera:
        for c in app.state.cameras:
            if c.id == cam_id:
                return c
        raise HTTPException(404, "no such camera")

    def urls(request: Request, src: str) -> dict:
        host = request.url.hostname
        base = str(request.base_url).rstrip("/")
        return {"webrtc": f"{base}/go2rtc/api/webrtc?src={src}",
                "hls": f"{base}/go2rtc/api/stream.m3u8?src={src}",
                "rtsp": f"rtsp://{host}:{GO2RTC_RTSP}/{src}"}

    @app.get("/api/hub")
    def hub():
        return {"name": hub_name, "cameras": len(app.state.cameras), "api": 1}

    @app.get("/api/cameras")
    def cameras_list(request: Request):
        out = []
        for c in app.state.cameras:
            item = c.public()
            if c.main:
                item["snapshot"] = f"{str(request.base_url).rstrip('/')}/api/cameras/{c.id}/snapshot"
                item["main"] = urls(request, c.id)
                item["sub"] = urls(request, f"{c.id}_sub")
            out.append(item)
        return {"hub": hub_name, "cameras": out}

    @app.get("/api/cameras/{cam_id}/snapshot")
    async def snapshot(cam_id: str):
        c = find(cam_id)
        r = await client.get("/api/frame.jpeg", params={"src": f"{c.id}_sub"})
        if r.status_code != 200:
            raise HTTPException(502, "no frame from camera")
        return Response(r.content, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.api_route("/go2rtc/api/{path:path}", methods=["GET", "POST"])
    async def go2rtc_proxy(path: str, request: Request):
        if not path.startswith(PROXY_ALLOWED) or ".." in path:
            raise HTTPException(404)
        r = await client.request(request.method, f"/api/{path}", params=request.query_params,
                                 content=await request.body(),
                                 headers={k: v for k, v in request.headers.items() if k.lower() == "content-type"})
        keep = {k: v for k, v in r.headers.items() if k.lower() in ("content-type", "cache-control")}
        return Response(r.content, status_code=r.status_code, headers=keep)

    # Send to tport.stream: keys go in, never come back out; each change restarts that camera's pusher
    @app.get("/api/cloud")
    def cloud_list():
        if not cloud:
            return {"relay": "", "cameras": {}}
        status = pushers.status() if pushers else {}
        return {"relay": cloud.relay, "cameras": {cid: {**l.public(), "status": status.get(cid, "off")}
                                                  for cid, l in cloud.links.items()}}

    @app.put("/api/cloud/{cam_id}")
    def cloud_set(cam_id: str, body: CloudIn):
        if not cloud:
            raise HTTPException(404, "cloud settings off")
        find(cam_id)
        old = cloud.links.get(cam_id)
        key = body.key.strip() or (old.key if old and old.stream_id == body.stream_id.strip() else "")
        err = validate(body.stream_id.strip(), key, body.quality)
        if err:
            raise HTTPException(400, err)
        cloud.links[cam_id] = CloudLink(body.stream_id.strip(), key, body.quality, body.enabled)
        cloud.save()
        if pushers:
            pushers.sync()
        return cloud.links[cam_id].public()

    @app.delete("/api/cloud/{cam_id}")
    def cloud_delete(cam_id: str):
        if not cloud:
            raise HTTPException(404, "cloud settings off")
        if cloud.links.pop(cam_id, None):
            cloud.save()
            if pushers:
                pushers.sync()
        return {"ok": True}

    # hashed file names, so assets can be cached; index.html is small and always fresh
    app.mount("/assets", StaticFiles(directory=str(WEB.joinpath("assets"))), name="assets")

    @app.get("/", response_class=HTMLResponse)
    def web():
        return HTMLResponse(WEB.joinpath("index.html").read_text(encoding="utf-8"), headers={"Cache-Control": "no-cache"})

    return app
