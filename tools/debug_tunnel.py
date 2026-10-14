# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import sys
import urllib.request

import paramiko

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PW = os.environ.get("PVE_PASSWORD", "")


def main() -> None:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(
        "100.64.245.30",
        username="root",
        password=PW,
        timeout=20,
        allow_agent=False,
        look_for_keys=False,
    )

    cmds = [
        "pct exec 200 -- bash -lc 'ls -la /etc/cloudflared 2>/dev/null; systemctl is-active cloudflared 2>/dev/null || true'",
        "pct exec 200 -- bash -lc 'grep -R hostname /etc/cloudflared 2>/dev/null | head -50 || true'",
        "ls /etc/cloudflared 2>/dev/null; systemctl is-active cloudflared 2>/dev/null || true",
        "grep -R hostname /etc/cloudflared 2>/dev/null | head -50 || true",
        "pct exec 200 -- bash -lc 'curl -sS -m 10 -H Host:pocket.melnichuk.kz http://127.0.0.1/api/health; echo'",
    ]
    for c in cmds:
        print(">>", c[:100])
        _, o, e = ssh.exec_command(c, timeout=60)
        print(o.read().decode("utf-8", "replace"))
        err = e.read().decode("utf-8", "replace")
        if err.strip():
            print("ERR", err[:300])
    ssh.close()

    for url in [
        "https://pocket.melnichuk.kz/api/health",
        "https://falconapp.melnichuk.kz/api/health",
        "https://dialed.melnichuk.kz/",
    ]:
        try:
            r = urllib.request.urlopen(url, timeout=25)
            body = r.read()[:100]
            print(url, r.status, body)
        except Exception as ex:
            print(url, type(ex).__name__, ex)


if __name__ == "__main__":
    main()
