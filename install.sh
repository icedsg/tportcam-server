#!/usr/bin/env bash
# camgrid hub installer for Raspberry Pi OS 64-bit (Debian bookworm/trixie; also any Debian/Ubuntu on amd64/arm64).
#   sudo ./install.sh [--user CAMUSER --password CAMPASS] [--name "Hall hub"] [--dry-run] [--no-start]
# Re-running it upgrades the code and keeps /etc/camgrid/hub.env (camera login) unless --user/--password are given.
set -euo pipefail

GO2RTC_VERSION="${GO2RTC_VERSION:-1.9.15}"
PREFIX=/opt/camgrid_hub          # code + venv
DATA=/var/lib/camgrid            # generated go2rtc.yaml (has camera passwords inside RTSP URLs)
ETC=/etc/camgrid                 # hub.env: CAMGRID_USER / CAMGRID_PASSWORD / CAMGRID_NAME
SVC_USER=camgrid
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DRY=0; START=1; CAM_USER=""; CAM_PASS=""; HUB_NAME=""
while [ $# -gt 0 ]; do
  case "$1" in
    --user) CAM_USER="$2"; shift 2 ;;
    --password) CAM_PASS="$2"; shift 2 ;;
    --name) HUB_NAME="$2"; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    --no-start) START=0; shift ;;
    -h|--help) sed -n 2,4p "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

run() { if [ "$DRY" = 1 ]; then echo "+ $*"; else "$@"; fi; }
say() { echo "==> $*"; }

[ "$DRY" = 1 ] || [ "$(id -u)" = 0 ] || { echo "run as root: sudo $0 $*" >&2; exit 1; }

case "$(uname -m)" in
  aarch64|arm64) GO_ARCH=arm64 ;;
  armv7l|armv6l) GO_ARCH=arm ;;
  x86_64|amd64) GO_ARCH=amd64 ;;
  *) echo "unsupported CPU: $(uname -m)" >&2; exit 1 ;;
esac
[ "$GO_ARCH" = arm ] && echo "warning: 32-bit OS; Raspberry Pi OS 64-bit is the tested setup" >&2

say "packages (python3-venv, ffmpeg, curl)"
run apt-get update -qq
run env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3 python3-venv python3-pip ffmpeg curl ca-certificates

say "go2rtc v$GO2RTC_VERSION ($GO_ARCH)"
if [ -x /usr/local/bin/go2rtc ] && /usr/local/bin/go2rtc -version 2>/dev/null | grep -q "$GO2RTC_VERSION"; then
  echo "already installed"
else
  run curl -fsSL -o /usr/local/bin/go2rtc.new \
    "https://github.com/AlexxIT/go2rtc/releases/download/v$GO2RTC_VERSION/go2rtc_linux_$GO_ARCH"
  run chmod 755 /usr/local/bin/go2rtc.new
  run mv -f /usr/local/bin/go2rtc.new /usr/local/bin/go2rtc
fi

say "service user and folders"
id "$SVC_USER" >/dev/null 2>&1 || run useradd --system --home-dir "$DATA" --shell /usr/sbin/nologin "$SVC_USER"
run install -d -m 755 "$PREFIX"
run install -d -m 700 -o "$SVC_USER" -g "$SVC_USER" "$DATA"
run install -d -m 750 -o root -g "$SVC_USER" "$ETC"

say "hub code + venv in $PREFIX"
run cp -r "$SRC/camgrid_hub" "$SRC/pyproject.toml" "$SRC/README.md" "$PREFIX/"
run find "$PREFIX/camgrid_hub" -name __pycache__ -prune -exec rm -rf {} +
[ -x "$PREFIX/venv/bin/python" ] || run python3 -m venv "$PREFIX/venv"
run "$PREFIX/venv/bin/pip" install -q --upgrade pip
run "$PREFIX/venv/bin/pip" install -q "$PREFIX"

say "camera login in $ETC/hub.env"
if [ -n "$CAM_USER$CAM_PASS$HUB_NAME" ] || [ ! -f "$ETC/hub.env" ]; then
  if [ -z "$CAM_USER" ] && [ -t 0 ] && [ "$DRY" = 0 ]; then
    read -r -p "Camera user (blank = find cameras only, no streams): " CAM_USER
    [ -n "$CAM_USER" ] && { read -r -s -p "Camera password: " CAM_PASS; echo; }
  fi
  if [ "$DRY" = 1 ]; then
    echo "+ write $ETC/hub.env (CAMGRID_USER=${CAM_USER:-<blank>}, password hidden), mode 640 root:$SVC_USER"
  else
    umask 027
    HUB_NAME="${HUB_NAME:-camgrid hub $(hostname)}"
    # systemd EnvironmentFile format; the name is single-quoted (spaces), so no ' in it
    printf "CAMGRID_USER=%s\nCAMGRID_PASSWORD=%s\nCAMGRID_NAME='%s'\n" \
      "$CAM_USER" "$CAM_PASS" "${HUB_NAME//\'/}" > "$ETC/hub.env"
    chown root:"$SVC_USER" "$ETC/hub.env"; chmod 640 "$ETC/hub.env"
  fi
else
  echo "kept (pass --user/--password to change it)"
fi

say "systemd unit camgrid-hub.service"
run install -m 644 "$SRC/systemd/camgrid-hub.service" /etc/systemd/system/camgrid-hub.service
if [ -d /run/systemd/system ]; then
  run systemctl daemon-reload
  run systemctl enable camgrid-hub.service
  if [ "$START" = 1 ]; then run systemctl restart camgrid-hub.service; fi
else
  echo "systemd is not running here (container?): unit installed, not started"
fi

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
say "done: web grid http://${IP:-<pi-ip>}:8780/  ·  logs: journalctl -u camgrid-hub -f"
