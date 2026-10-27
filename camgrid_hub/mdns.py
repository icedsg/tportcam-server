"""Announces the hub on the LAN as `_camgrid._tcp` so the app can find it."""
from __future__ import annotations

import socket

from zeroconf import ServiceInfo, Zeroconf

SERVICE = "_camgrid._tcp.local."


def lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.0.2.1", 9))   # no packet is sent; picks the interface with the default route
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def service_info(name: str, port: int, ip: str) -> ServiceInfo:
    return ServiceInfo(SERVICE, f"{name}.{SERVICE}", addresses=[socket.inet_aton(ip)], port=port,
                       properties={"api": "/api/cameras", "v": "1"}, server=f"{socket.gethostname()}.local.")


class Announcer:
    def __init__(self, name: str, port: int, ip: str = ""):
        self.info = service_info(name, port, ip or lan_ip())
        self.zc: Zeroconf | None = None

    def start(self) -> "Announcer":
        self.zc = Zeroconf()
        self.zc.register_service(self.info, allow_name_change=True)
        return self

    def stop(self) -> None:
        if self.zc:
            self.zc.unregister_service(self.info)
            self.zc.close()
            self.zc = None
