"""Minimal ONVIF SOAP client: device info, media profiles, stream and snapshot URIs.

Auth: every request carries a WS-Security UsernameToken (PasswordDigest); if the camera answers 401 with an HTTP
Digest challenge (common on Hikvision/Dahua firmware), httpx retries with HTTP Digest as well.
"""
from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

import httpx

NS = {
    "s": "http://www.w3.org/2003/05/soap-envelope",
    "tds": "http://www.onvif.org/ver10/device/wsdl",
    "trt": "http://www.onvif.org/ver10/media/wsdl",
    "tt": "http://www.onvif.org/ver10/schema",
}
WSSE = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"
WSU = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd"
PW_DIGEST = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest"
NONCE_B64 = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary"


class OnvifError(Exception):
    pass


@dataclass
class Profile:
    token: str
    name: str
    encoding: str = ""
    width: int = 0
    height: int = 0


def password_digest(nonce: bytes, created: str, password: str) -> str:
    return base64.b64encode(hashlib.sha1(nonce + created.encode() + password.encode()).digest()).decode()


def security_header(user: str, password: str, nonce: bytes | None = None, created: str | None = None) -> str:
    nonce = nonce or os.urandom(16)
    created = created or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return (
        f'<wsse:Security s:mustUnderstand="1" xmlns:wsse="{WSSE}" xmlns:wsu="{WSU}">'
        f"<wsse:UsernameToken><wsse:Username>{_esc(user)}</wsse:Username>"
        f'<wsse:Password Type="{PW_DIGEST}">{password_digest(nonce, created, password)}</wsse:Password>'
        f'<wsse:Nonce EncodingType="{NONCE_B64}">{base64.b64encode(nonce).decode()}</wsse:Nonce>'
        f"<wsu:Created>{created}</wsu:Created></wsse:UsernameToken></wsse:Security>"
    )


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class OnvifClient:
    def __init__(self, xaddr: str, user: str = "", password: str = "", timeout: float = 5.0):
        self.xaddr = xaddr
        self.user = user
        self.password = password
        self.media_xaddr = ""
        self.http = httpx.Client(timeout=timeout, auth=httpx.DigestAuth(user, password) if user else None)

    def close(self) -> None:
        self.http.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def call(self, url: str, body: str) -> ET.Element:
        header = f"<s:Header>{security_header(self.user, self.password)}</s:Header>" if self.user else ""
        env = (
            f'<?xml version="1.0" encoding="UTF-8"?><s:Envelope xmlns:s="{NS["s"]}" xmlns:tds="{NS["tds"]}" '
            f'xmlns:trt="{NS["trt"]}" xmlns:tt="{NS["tt"]}">{header}<s:Body>{body}</s:Body></s:Envelope>'
        )
        try:
            r = self.http.post(url, content=env.encode(),
                               headers={"Content-Type": "application/soap+xml; charset=utf-8"})
        except httpx.HTTPError as e:
            raise OnvifError(f"{url}: {e}") from e
        try:
            root = ET.fromstring(r.content)
        except ET.ParseError:
            raise OnvifError(f"{url}: HTTP {r.status_code}, not SOAP") from None
        fault = root.find(".//s:Fault", NS)
        if fault is not None or r.status_code >= 400:
            reason = fault.findtext(".//s:Reason/s:Text", "", NS) if fault is not None else ""
            raise OnvifError(f"{url}: HTTP {r.status_code} {reason}".strip())
        return root.find("s:Body", NS)

    def device_information(self) -> dict[str, str]:
        b = self.call(self.xaddr, "<tds:GetDeviceInformation/>")
        info = b.find("tds:GetDeviceInformationResponse", NS)
        return {el.tag.split("}")[1]: (el.text or "") for el in info} if info is not None else {}

    def media_service(self) -> str:
        if not self.media_xaddr:
            b = self.call(self.xaddr, "<tds:GetCapabilities><tds:Category>Media</tds:Category></tds:GetCapabilities>")
            self.media_xaddr = b.findtext(".//tt:Media/tt:XAddr", "", NS).strip() or self.xaddr
        return self.media_xaddr

    def profiles(self) -> list[Profile]:
        b = self.call(self.media_service(), "<trt:GetProfiles/>")
        out = []
        for p in b.iterfind(".//trt:Profiles", NS):
            vec = p.find("tt:VideoEncoderConfiguration", NS)
            res = vec.find("tt:Resolution", NS) if vec is not None else None
            out.append(Profile(
                token=p.get("token", ""),
                name=p.findtext("tt:Name", "", NS),
                encoding=vec.findtext("tt:Encoding", "", NS) if vec is not None else "",
                width=int(res.findtext("tt:Width", "0", NS)) if res is not None else 0,
                height=int(res.findtext("tt:Height", "0", NS)) if res is not None else 0,
            ))
        return out

    def stream_uri(self, profile_token: str) -> str:
        b = self.call(self.media_service(), (
            "<trt:GetStreamUri><trt:StreamSetup><tt:Stream>RTP-Unicast</tt:Stream>"
            "<tt:Transport><tt:Protocol>RTSP</tt:Protocol></tt:Transport></trt:StreamSetup>"
            f"<trt:ProfileToken>{_esc(profile_token)}</trt:ProfileToken></trt:GetStreamUri>"
        ))
        return b.findtext(".//trt:MediaUri/tt:Uri", "", NS).strip()

    def snapshot_uri(self, profile_token: str) -> str:
        b = self.call(self.media_service(),
                      f"<trt:GetSnapshotUri><trt:ProfileToken>{_esc(profile_token)}</trt:ProfileToken></trt:GetSnapshotUri>")
        return b.findtext(".//trt:MediaUri/tt:Uri", "", NS).strip()
