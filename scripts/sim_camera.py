"""Runs the simulated ONVIF camera from tests/ until Ctrl+C, for trying `camgrid_hub serve` without a camera.

    python scripts/sim_camera.py            # prints the WS-Discovery port
    camgrid_hub serve --target 127.0.0.1:<port> --user admin --password secret --go2rtc-config scripts/sim_go2rtc.yaml

sim_go2rtc.yaml makes go2rtc itself serve the camera's rtsp://127.0.0.1:8554/main and /sub from an ffmpeg test pattern.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.onvif_sim import Camera  # noqa: E402

cam = Camera().start()
print(f"simulated camera: probe 127.0.0.1:{cam.probe_port}  xaddr {cam.xaddr}  user admin / secret", flush=True)
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    cam.stop()
