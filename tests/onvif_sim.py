"""Simulated ONVIF camera for tests: WS-Discovery responder (UDP) + SOAP device/media service (HTTP).

auth="wsse": checks the WS-Security UsernameToken PasswordDigest in the SOAP header.
auth="http-digest": answers 401 with an HTTP Digest challenge (MD5, qop=auth) and checks the Authorization header.
"""
from __future__ import annotations

import base64
import hashlib
import re
import socket
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from xml.etree import ElementTree as ET

from camgrid_hub.discovery import NS as DNS
from camgrid_hub.onvif import NS, WSSE, WSU, password_digest

REALM = "camsim"
NONCE = "dcd98b7102dd2f0e8b11d0f600bfb0c093"

ENV = ('<?xml version="1.0" encoding="UTF-8"?><s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" '
       'xmlns:tds="http://www.onvif.org/ver10/device/wsdl" xmlns:trt="http://www.onvif.org/ver10/media/wsdl" '
       'xmlns:tt="http://www.onvif.org/ver10/schema"><s:Body>{}</s:Body></s:Envelope>')

FAULT = ENV.format('<s:Fault><s:Code><s:Value>s:Sender</s:Value></s:Code>'
                   '<s:Reason><s:Text xml:lang="en">Sender not Authorized</s:Text></s:Reason></s:Fault>')

PROBE_MATCH = """<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing"
 xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery" xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
 <s:Header><a:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/ProbeMatches</a:Action>
  <a:RelatesTo>{relates}</a:RelatesTo></s:Header>
 <s:Body><d:ProbeMatches><d:ProbeMatch>
  <a:EndpointReference><a:Address>urn:uuid:{uuid}</a:Address></a:EndpointReference>
  <d:Types>dn:NetworkVideoTransmitter</d:Types>
  <d:Scopes>onvif://www.onvif.org/type/video_encoder onvif://www.onvif.org/name/{name} onvif://www.onvif.org/hardware/SIM-1</d:Scopes>
  <d:XAddrs>{xaddr}</d:XAddrs><d:MetadataVersion>1</d:MetadataVersion>
 </d:ProbeMatch></d:ProbeMatches></s:Body></s:Envelope>"""


class Camera:
    def __init__(self, user="admin", password="secret", auth="wsse", name="Sim%20Cam", rtsp_host="127.0.0.1"):
        self.user, self.password, self.auth, self.name = user, password, auth, name
        self.uuid = str(uuid.uuid4())
        self.rtsp_host = rtsp_host
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp.bind(("127.0.0.1", 0))
        self.udp.settimeout(0.2)
        self._stop = threading.Event()

    @property
    def xaddr(self) -> str:
        return f"http://127.0.0.1:{self.http.server_port}/onvif/device_service"

    @property
    def probe_port(self) -> int:
        return self.udp.getsockname()[1]

    def start(self) -> "Camera":
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        threading.Thread(target=self._udp_loop, daemon=True).start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self.http.shutdown()
        self.http.server_close()
        self.udp.close()

    def _udp_loop(self) -> None:
        while not self._stop.is_set():
            try:
                data, peer = self.udp.recvfrom(65535)
            except (socket.timeout, ConnectionResetError):
                continue
            except OSError:
                return
            try:
                root = ET.fromstring(data)
            except ET.ParseError:
                continue
            if root.find(".//d:Probe", DNS) is None:
                continue
            relates = root.findtext(".//a:MessageID", "", DNS)
            self.udp.sendto(PROBE_MATCH.format(relates=relates, uuid=self.uuid, name=self.name,
                                               xaddr=self.xaddr).encode(), peer)

    # SOAP
    def answer(self, body: ET.Element) -> str:
        op = body[0].tag.split("}")[1]
        media = self.xaddr.replace("device_service", "media_service")
        if op == "GetDeviceInformation":
            return ENV.format("<tds:GetDeviceInformationResponse><tds:Manufacturer>CamSim</tds:Manufacturer>"
                              "<tds:Model>SIM-1</tds:Model><tds:FirmwareVersion>1.0</tds:FirmwareVersion>"
                              "<tds:SerialNumber>0001</tds:SerialNumber><tds:HardwareId>SIM-1</tds:HardwareId>"
                              "</tds:GetDeviceInformationResponse>")
        if op == "GetCapabilities":
            return ENV.format(f"<tds:GetCapabilitiesResponse><tds:Capabilities><tt:Media><tt:XAddr>{media}</tt:XAddr>"
                              "</tt:Media></tds:Capabilities></tds:GetCapabilitiesResponse>")
        if op == "GetProfiles":
            profs = "".join(
                f'<trt:Profiles token="{t}" fixed="true"><tt:Name>{n}</tt:Name><tt:VideoEncoderConfiguration>'
                f"<tt:Name>{n}</tt:Name><tt:Encoding>H264</tt:Encoding><tt:Resolution><tt:Width>{w}</tt:Width>"
                f"<tt:Height>{h}</tt:Height></tt:Resolution></tt:VideoEncoderConfiguration></trt:Profiles>"
                for t, n, w, h in (("main", "MainStream", 1920, 1080), ("sub", "SubStream", 640, 360)))
            return ENV.format(f"<trt:GetProfilesResponse>{profs}</trt:GetProfilesResponse>")
        token = body[0].findtext("trt:ProfileToken", "", NS)
        if op == "GetStreamUri":
            return ENV.format(f"<trt:GetStreamUriResponse><trt:MediaUri><tt:Uri>rtsp://{self.rtsp_host}:8554/{token}"
                              "</tt:Uri></trt:MediaUri></trt:GetStreamUriResponse>")
        if op == "GetSnapshotUri":
            return ENV.format(f"<trt:GetSnapshotUriResponse><trt:MediaUri><tt:Uri>http://127.0.0.1:"
                              f"{self.http.server_port}/snap/{token}.jpg</tt:Uri></trt:MediaUri>"
                              "</trt:GetSnapshotUriResponse>")
        return ENV.format("<s:Fault><s:Code><s:Value>s:Receiver</s:Value></s:Code>"
                          f"<s:Reason><s:Text>{op} not supported</s:Text></s:Reason></s:Fault>")

    def wsse_ok(self, root: ET.Element) -> bool:
        tok = root.find(f".//{{{WSSE}}}UsernameToken")
        if tok is None:
            return False
        user = tok.findtext(f"{{{WSSE}}}Username", "")
        pw = tok.findtext(f"{{{WSSE}}}Password", "")
        nonce = base64.b64decode(tok.findtext(f"{{{WSSE}}}Nonce", ""))
        created = tok.findtext(f"{{{WSU}}}Created", "")
        return user == self.user and pw == password_digest(nonce, created, self.password)

    def digest_ok(self, header: str, method: str) -> bool:
        if not header.startswith("Digest "):
            return False
        f = dict(re.findall(r'(\w+)="?([^",]*)"?', header[7:]))
        md5 = lambda s: hashlib.md5(s.encode()).hexdigest()  # noqa: E731
        ha1 = md5(f"{self.user}:{REALM}:{self.password}")
        ha2 = md5(f"{method}:{f.get('uri', '')}")
        want = md5(f"{ha1}:{f.get('nonce')}:{f.get('nc')}:{f.get('cnonce')}:{f.get('qop')}:{ha2}")
        return f.get("username") == self.user and f.get("nonce") == NONCE and f.get("response") == want

    def _handler(self):
        cam = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def send(self, code, text, extra=None):
                data = text.encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/soap+xml; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                root = ET.fromstring(raw)
                if cam.auth == "http-digest":
                    if not cam.digest_ok(self.headers.get("Authorization", ""), "POST"):
                        return self.send(401, FAULT, {"WWW-Authenticate":
                                                      f'Digest realm="{REALM}", qop="auth", nonce="{NONCE}"'})
                elif not cam.wsse_ok(root):
                    return self.send(400, FAULT)
                self.send(200, cam.answer(root.find("s:Body", NS)))

        return H
