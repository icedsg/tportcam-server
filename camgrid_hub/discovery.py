"""WS-Discovery probe for ONVIF devices (NetworkVideoTransmitter)."""
from __future__ import annotations

import socket
import time
import uuid
from dataclasses import dataclass, field
from urllib.parse import unquote
from xml.etree import ElementTree as ET

MULTICAST = ("239.255.255.250", 3702)

NS = {
    "s": "http://www.w3.org/2003/05/soap-envelope",
    "a": "http://schemas.xmlsoap.org/ws/2004/08/addressing",
    "d": "http://schemas.xmlsoap.org/ws/2005/04/discovery",
}

PROBE = """<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
 xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing"
 xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"
 xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
 <s:Header>
  <a:Action s:mustUnderstand="1">http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</a:Action>
  <a:MessageID>urn:uuid:{msg_id}</a:MessageID>
  <a:ReplyTo><a:Address>http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous</a:Address></a:ReplyTo>
  <a:To s:mustUnderstand="1">urn:schemas-xmlsoap-org:ws:2005:04:discovery</a:To>
 </s:Header>
 <s:Body><d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types></d:Probe></s:Body>
</s:Envelope>"""


@dataclass
class Device:
    address: str  # endpoint reference, usually urn:uuid:...
    xaddrs: list[str]
    scopes: list[str] = field(default_factory=list)
    source: str = ""  # IP the reply came from

    @property
    def name(self) -> str:
        return self._scope("name") or self.source

    @property
    def hardware(self) -> str:
        return self._scope("hardware")

    def _scope(self, key: str) -> str:
        prefix = f"onvif://www.onvif.org/{key}/"
        for s in self.scopes:
            if s.startswith(prefix):
                return unquote(s[len(prefix):])
        return ""


def probe_message(msg_id: str | None = None) -> bytes:
    return PROBE.format(msg_id=msg_id or uuid.uuid4()).encode()


def parse_probe_matches(data: bytes, source: str = "") -> list[Device]:
    """Devices in a ProbeMatches reply; [] for anything else."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return []
    out = []
    for m in root.iterfind(".//d:ProbeMatch", NS):
        addr = m.findtext("a:EndpointReference/a:Address", "", NS).strip()
        xaddrs = m.findtext("d:XAddrs", "", NS).split()
        scopes = m.findtext("d:Scopes", "", NS).split()
        if xaddrs:
            out.append(Device(addr, xaddrs, scopes, source))
    return out


def discover(timeout: float = 3.0, targets: list[tuple[str, int]] | None = None) -> list[Device]:
    """Send a Probe to each target (default: the multicast group) and collect replies until timeout.

    Unicast targets (ip, 3702) work too, for networks where multicast is blocked.
    """
    targets = targets or [MULTICAST]
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    sock.bind(("", 0))
    msg = probe_message()
    for t in targets:
        sock.sendto(msg, t)
    found: dict[str, Device] = {}
    end = time.monotonic() + timeout
    try:
        while (left := end - time.monotonic()) > 0:
            sock.settimeout(left)
            try:
                data, (ip, _port) = sock.recvfrom(65535)
            except socket.timeout:
                break
            except ConnectionResetError:  # Windows: ICMP port unreachable from a unicast target
                continue
            for d in parse_probe_matches(data, ip):
                found.setdefault(d.address or d.xaddrs[0], d)
    finally:
        sock.close()
    return list(found.values())
