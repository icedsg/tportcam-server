# tportcam-server

Open-source camera server for a Raspberry Pi or any computer on the same LAN as your cameras: finds every ONVIF
camera by WS-Discovery, reads their RTSP stream URIs and re-streams them through go2rtc to a web grid (React/Vite)
and the tport cam app. Optionally sends each camera to your own [tport.stream](https://tport.stream) stream so you
can watch it away from home. MIT licence ([LICENSE](LICENSE)); no keys in the repo, you paste your own.

The Python package and the Pi service keep their earlier names (`camgrid_hub`, `camgrid-hub.service`,
`/etc/camgrid`), so existing installs upgrade in place; `tportcam-server` and `camgrid_hub` are the same command.

## Setup (any computer: Linux, macOS, Windows)
Needs Python 3.11+, [go2rtc](https://github.com/AlexxIT/go2rtc) (on PATH, `GO2RTC_BIN` or `--go2rtc`) and ffmpeg
for Send to tport.stream. On a Pi, use the installer below instead.
```
python -m venv venv
venv/bin/pip install -e ".[dev]"          # Windows: venv\Scripts\pip
tportcam-server serve --user admin --password ...
```
then open http://localhost:8780/.

## Discover
```
camgrid_hub discover                              # multicast probe to 239.255.255.250:3702, 3 s
camgrid_hub discover --target 192.168.1.64        # unicast probe (multicast blocked); repeatable
camgrid_hub discover --user admin --password ...  # also GetDeviceInformation, GetProfiles, GetStreamUri
camgrid_hub discover --json
```
Credentials can come from `CAMGRID_USER` / `CAMGRID_PASSWORD` instead of flags.

ONVIF calls send a WS-Security UsernameToken (PasswordDigest); if a camera answers 401 with an HTTP Digest
challenge, the request is retried with HTTP Digest too. The camera clock must be within a few minutes of the hub's
for UsernameToken auth (ONVIF rule).

## Serve (re-stream + web app)
```
camgrid_hub serve --user admin --password ...     # needs go2rtc: on PATH, GO2RTC_BIN or --go2rtc
```
Discovers the cameras, writes `data/go2rtc.yaml` (per camera `cam_<ip>` = main stream, `cam_<ip>_sub` = sub stream,
credentials inside the RTSP URLs), starts go2rtc, serves the hub on port 8780 and announces it by mDNS as
`_camgrid._tcp` (TXT `api=/api/cameras`).

| Port | What |
|---|---|
| 8780 | hub: web app `/` + `/assets/`, `GET /api/hub`, `GET /api/cameras`, `GET /api/cameras/<id>/snapshot`, `/go2rtc/api/{webrtc,frame.jpeg,stream.m3u8,hls/...}` |
| 1984 | go2rtc API, **127.0.0.1 only** (its /api/streams would show camera passwords); clients use the /go2rtc proxy |
| 8554 | RTSP re-streams `rtsp://<hub>:8554/cam_<ip>` and `..._sub` |
| 8555 | WebRTC media (TCP/UDP) |

`/api/cameras` never returns credentials. WebRTC: POST `{"type":"offer","sdp":...}` to the camera's `webrtc` URL,
the answer comes back as `{"type":"answer","sdp":...}` (the web app does this, with reconnect on drop).

## Send to tport.stream
Hub web app → Settings → **Send to tport.stream**: per camera, paste the stream id and publish key from the tport cam
app, pick Sub (720p, the default) or Main (only if your plan allows it; the relay caps free keys at 720p), Save. The
hub then runs one `ffmpeg -c copy` per camera (video only, no re-encode) from go2rtc's local RTSP to
`rtmps://cam.tport.stream:1936/<stream id>?key=...`, restarting it after 5-60 s if it drops. Stop removes it.

- Settings are kept in `<data>/cloud.json` (mode 600). `GET /api/cloud` lists stream id, quality and status
  (`pushing` / `retrying`), never the key; `PUT /api/cloud/<camera id>` `{"stream_id", "key", "quality"}` (blank key
  keeps the saved one for the same id); `DELETE /api/cloud/<camera id>`.
- Other relay: `--relay rtmp://host:1935` or `TPORTCAM_RELAY`.
- go2rtc's own `publish` isn't used: MediaMTX can't decode go2rtc 1.9.15's RTMP output.

Try it without a camera (go2rtc + ffmpeg installed):
```
venv/bin/python scripts/sim_camera.py         # prints the probe port
camgrid_hub serve --target 127.0.0.1:<port> --user admin --password secret --go2rtc-config scripts/sim_go2rtc.yaml
```
then open http://localhost:8780/ (test pattern via ffmpeg: 640x360 in the grid, 1280x720 full screen).

## Raspberry Pi install
Tested setup: Raspberry Pi 4 or 5, **Raspberry Pi OS Lite (64-bit)**, wired Ethernet or Wi-Fi on the cameras' LAN.

1. Flash with Raspberry Pi Imager: device = your Pi, OS = Raspberry Pi OS (other) > Raspberry Pi OS Lite (64-bit).
   In "Edit settings": hostname (e.g. `camhub`), user + password, Wi-Fi (skip if wired), and on the Services tab
   enable SSH. Write, put the card in the Pi, power on, wait about a minute.
2. Copy this repo to the Pi and run the installer (as root):
   ```
   ssh <user>@camhub.local
   git clone https://github.com/icedsg/tportcam-server.git
   cd tportcam-server
   sudo ./install.sh --user <camera user> --password '<camera password>' --name "Home hub"
   ```
   Without `--user` it asks for the camera login (blank = find cameras only). `--dry-run` prints every step and
   changes nothing.
3. Open `http://camhub.local:8780/` (or the IP it prints). The tport cam app finds the hub by mDNS.

What it installs:

| Where | What |
|---|---|
| `/usr/local/bin/go2rtc` | go2rtc v1.9.15 for the CPU (arm64 / arm / amd64); `GO2RTC_VERSION=x.y.z ./install.sh` to change |
| `/opt/camgrid_hub` | hub code + venv (`/opt/camgrid_hub/venv/bin/camgrid_hub`) |
| `/etc/camgrid/hub.env` | `CAMGRID_USER`, `CAMGRID_PASSWORD`, `CAMGRID_NAME`; mode 640 root:camgrid; kept on re-runs unless `--user/--password/--name` are given |
| `/var/lib/camgrid` | generated `go2rtc.yaml` (camera passwords inside RTSP URLs), mode 700, user `camgrid` |
| `camgrid-hub.service` | systemd unit ([systemd/camgrid-hub.service](systemd/camgrid-hub.service)), runs as `camgrid`, restarts on failure, starts at boot |

Day to day: `journalctl -u camgrid-hub -f` (logs), `sudo systemctl restart camgrid-hub` (picks up new cameras: they
are found once at start), `git pull && sudo ./install.sh` (upgrade). Uninstall: `sudo systemctl disable --now
camgrid-hub; sudo rm -rf /opt/camgrid_hub /var/lib/camgrid /etc/camgrid /etc/systemd/system/camgrid-hub.service
/usr/local/bin/go2rtc; sudo userdel camgrid`.

Same steps work on any Debian/Ubuntu box (amd64/arm64). Checked in a Debian bookworm arm64 container (qemu): packages, go2rtc arm64, venv, hub.env, unit file, hub start as `camgrid` (`/api/hub`, grid page, go2rtc API
on 127.0.0.1:1984), re-run keeps hub.env. Not yet checked on real Pi hardware or with systemd actually running.

## Tests
```
venv/bin/python -m pytest
```
`tests/onvif_sim.py` is a simulated camera: a WS-Discovery responder on a local UDP port and a SOAP device/media
service (GetDeviceInformation, GetCapabilities, GetProfiles, GetStreamUri, GetSnapshotUri) with either
UsernameToken or HTTP Digest auth. Tests probe it by unicast on 127.0.0.1, so they don't need multicast.

## Web app
`web/` is a React + Vite app: Grid (1-4 columns, sub stream per tile, tap for the main stream full screen, Esc
closes), Cameras (snapshot, IP, model, RTSP URL or the camera's error), Settings (grid quality, names on tiles; kept
in the browser). The build goes into `camgrid_hub/web/` and is committed, so a Pi install needs no Node.
```
cd web && npm install && npm run build      # type check + build into ../camgrid_hub/web
npm run dev                                 # dev server; proxies /api and /go2rtc to HUB_URL (default 127.0.0.1:8780)
```
Rebuild and commit `camgrid_hub/web/` after any change under `web/src/`.

## Layout
- `camgrid_hub/discovery.py`: Probe message, ProbeMatches parser, `discover()`
- `camgrid_hub/onvif.py`: minimal SOAP client (no WSDLs)
- `camgrid_hub/cli.py`: `camgrid_hub discover`, `camgrid_hub serve`
- `camgrid_hub/hub.py`: cameras -> go2rtc config, go2rtc process
- `camgrid_hub/server.py`: FastAPI hub API, go2rtc proxy, serves the built web app
- `web/src/`: React web app (`App.tsx` tabs, `Player.tsx` WebRTC with reconnect, `settings.ts`)
- `camgrid_hub/mdns.py`: `_camgrid._tcp` announce
- `install.sh` + `systemd/camgrid-hub.service`: Raspberry Pi / Debian install

## Licence
MIT, see [LICENSE](LICENSE). Bundles nothing from go2rtc or ffmpeg; the installer downloads go2rtc (MIT) from its
GitHub releases.
