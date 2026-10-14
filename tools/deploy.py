# -*- coding: utf-8 -*-
"""Deploy Pocket Mini App to CT200: code + venv + systemd + nginx.

Requires env:
  PVE_PASSWORD  — Proxmox root password
  BOT_TOKEN     — optional on first run if backend/.env already on server

Usage (from repo root):
  set PVE_PASSWORD=...
  python tools/deploy.py
"""
from __future__ import annotations

import base64
import os
import sys
import tarfile
import tempfile
import time
from pathlib import Path

import paramiko

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
PW = os.environ.get("PVE_PASSWORD", "")
HOSTS = ["100.64.245.30", "192.168.0.200"]
CTID = 200
REMOTE_APP = "/opt/pocket"
SERVICE = "pocket"
BOT_SERVICE = "pocket-bot"
PORT = 8110
DOMAIN = "pocket.melnichuk.kz"


def run(ssh, cmd, timeout=300):
    print(">>", cmd[:180].replace("\n", " "))
    chan = ssh.get_transport().open_session()
    chan.settimeout(timeout)
    chan.exec_command(cmd)
    out = b""
    err = b""
    end = time.time() + timeout
    while time.time() < end:
        if chan.recv_ready():
            out += chan.recv(65535)
        if chan.recv_stderr_ready():
            err += chan.recv_stderr(65535)
        if chan.exit_status_ready():
            break
        time.sleep(0.05)
    while chan.recv_ready():
        out += chan.recv(65535)
    while chan.recv_stderr_ready():
        err += chan.recv_stderr(65535)
    code = chan.recv_exit_status() if chan.exit_status_ready() else -1
    text = out.decode("utf-8", "replace")
    et = err.decode("utf-8", "replace")
    if text.strip():
        print(text)
    if et.strip():
        print("ERR:", et)
    return code, text, et


def main():
    if not PW:
        raise SystemExit("Set PVE_PASSWORD env var")

    tmp = tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False)
    tmp.close()
    with tarfile.open(tmp.name, "w:gz") as tar:
        for name in ("backend", "miniapp", "deploy"):
            tar.add(ROOT / name, arcname=name)
    print("archive", tmp.name, os.path.getsize(tmp.name))

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    for h in HOSTS:
        try:
            ssh.connect(
                h,
                username="root",
                password=PW,
                timeout=20,
                allow_agent=False,
                look_for_keys=False,
            )
            print("ssh", h)
            break
        except Exception as e:
            print("fail", h, e)
    else:
        raise SystemExit("no pve host reachable")

    remote_tar = "/tmp/pocket-deploy.tar.gz"
    sftp = ssh.open_sftp()
    sftp.put(tmp.name, remote_tar)
    sftp.close()
    os.unlink(tmp.name)

    unit = f"""[Unit]
Description=Pocket Mini App API
After=network.target

[Service]
Type=simple
WorkingDirectory={REMOTE_APP}/backend
EnvironmentFile={REMOTE_APP}/backend/.env
ExecStart={REMOTE_APP}/venv/bin/uvicorn app:app --host 127.0.0.1 --port {PORT} --workers 1
Restart=always
RestartSec=3
User=root

[Install]
WantedBy=multi-user.target
"""
    bot_unit = f"""[Unit]
Description=Pocket Telegram bot
After=network.target {SERVICE}.service

[Service]
Type=simple
WorkingDirectory={REMOTE_APP}/backend
EnvironmentFile={REMOTE_APP}/backend/.env
ExecStart={REMOTE_APP}/venv/bin/python bot.py
Restart=always
RestartSec=5
User=root

[Install]
WantedBy=multi-user.target
"""
    unit_b64 = base64.b64encode(unit.encode()).decode()
    bot_b64 = base64.b64encode(bot_unit.encode()).decode()
    nginx_b64 = base64.b64encode((ROOT / "deploy" / "nginx-pocket.conf").read_bytes()).decode()

    script = f"""
set -e
pct push {CTID} {remote_tar} /tmp/pocket-deploy.tar.gz
pct exec {CTID} -- bash -lc '
set -e
mkdir -p {REMOTE_APP}/data
tar xzf /tmp/pocket-deploy.tar.gz -C {REMOTE_APP}
rm -f /tmp/pocket-deploy.tar.gz
cd {REMOTE_APP}
if [ ! -f backend/.env ]; then
  cp backend/.env.example backend/.env
  echo "CREATED backend/.env from example — fill BOT_TOKEN and CREDENTIALS_ENCRYPTION_KEY"
fi
python3 -m venv venv
./venv/bin/pip install -q -U pip
./venv/bin/pip install -q -r backend/requirements.txt
echo {unit_b64} | base64 -d > /etc/systemd/system/{SERVICE}.service
echo {bot_b64} | base64 -d > /etc/systemd/system/{BOT_SERVICE}.service
systemctl daemon-reload
systemctl enable {SERVICE} {BOT_SERVICE}
systemctl restart {SERVICE}
systemctl restart {BOT_SERVICE} || true
sleep 3
systemctl --no-pager --full status {SERVICE} | head -20
echo {nginx_b64} | base64 -d > /etc/nginx/conf.d/domains/{DOMAIN}.conf
nginx -t
nginx -s reload
curl -sS -m 20 http://127.0.0.1:{PORT}/api/health || true
echo
curl -sS -m 15 -H "Host: {DOMAIN}" -o /dev/null -w "nginx=%{{http_code}}\\n" http://127.0.0.1/api/health || true
'
rm -f {remote_tar}
"""
    code, _, _ = run(ssh, script, timeout=400)
    ssh.close()
    if code != 0:
        raise SystemExit(f"deploy failed code={code}")
    print(f"OK https://{DOMAIN}/")
    print("Cloudflare: add public hostname {DOMAIN} -> http://192.168.0.203:80 (same as other apps)")
    print("Then: edit /opt/pocket/backend/.env on CT200 (BOT_TOKEN, CREDENTIALS_ENCRYPTION_KEY), restart pocket pocket-bot")


if __name__ == "__main__":
    main()
