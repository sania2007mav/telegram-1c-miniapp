# -*- coding: utf-8 -*-
"""Set CREDENTIALS_ENCRYPTION_KEY (and optional BOT_TOKEN) on CT200."""
from __future__ import annotations

import base64
import json
import os
import sys

import paramiko

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PW = os.environ.get("PVE_PASSWORD", "")
FERNET = os.environ.get("CREDENTIALS_ENCRYPTION_KEY", "")
BOT = os.environ.get("BOT_TOKEN", "")
HOSTS = ["100.64.245.30", "192.168.0.200"]


def main() -> None:
    if not PW or not FERNET:
        raise SystemExit("Need PVE_PASSWORD and CREDENTIALS_ENCRYPTION_KEY")

    lines = [
        "set -e",
        "ENV=/opt/pocket/backend/.env",
        "touch \"$ENV\"",
        f"KEY=$(echo {base64.b64encode(FERNET.encode()).decode()} | base64 -d)",
        "if grep -q '^CREDENTIALS_ENCRYPTION_KEY=' \"$ENV\"; then",
        "  sed -i \"s|^CREDENTIALS_ENCRYPTION_KEY=.*|CREDENTIALS_ENCRYPTION_KEY=$KEY|\" \"$ENV\"",
        "else",
        "  echo \"CREDENTIALS_ENCRYPTION_KEY=$KEY\" >> \"$ENV\"",
        "fi",
    ]
    if BOT:
        lines += [
            f"BTOK=$(echo {base64.b64encode(BOT.encode()).decode()} | base64 -d)",
            "if grep -q '^BOT_TOKEN=' \"$ENV\"; then",
            "  sed -i \"s|^BOT_TOKEN=.*|BOT_TOKEN=$BTOK|\" \"$ENV\"",
            "else",
            "  echo \"BOT_TOKEN=$BTOK\" >> \"$ENV\"",
            "fi",
        ]
    lines += [
        "grep -q '^APP_URL=' \"$ENV\" || echo 'APP_URL=https://pocket.melnichuk.kz' >> \"$ENV\"",
        "sed -i 's|^APP_URL=.*|APP_URL=https://pocket.melnichuk.kz|' \"$ENV\"",
        "grep -q '^API_PUBLIC_URL=' \"$ENV\" || echo 'API_PUBLIC_URL=https://pocket.melnichuk.kz/api' >> \"$ENV\"",
        "sed -i 's|^API_PUBLIC_URL=.*|API_PUBLIC_URL=https://pocket.melnichuk.kz/api|' \"$ENV\"",
        "grep -q '^DATABASE_PATH=' \"$ENV\" || echo 'DATABASE_PATH=/opt/pocket/data/app.db' >> \"$ENV\"",
        "sed -i 's|^DATABASE_PATH=.*|DATABASE_PATH=/opt/pocket/data/app.db|' \"$ENV\"",
        "systemctl restart pocket",
        "systemctl restart pocket-bot || true",
        "sleep 2",
        "curl -sS http://127.0.0.1:8110/api/health; echo",
        "systemctl is-active pocket; systemctl is-active pocket-bot || true",
        "grep -E '^[A-Z_]+=' \"$ENV\" | cut -d= -f1",
    ]
    script = "\n".join(lines)
    b64 = base64.b64encode(script.encode()).decode()

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    for h in HOSTS:
        try:
            ssh.connect(h, username="root", password=PW, timeout=20, allow_agent=False, look_for_keys=False)
            print("ssh", h)
            break
        except Exception as e:
            print("fail", h, e)
    else:
        raise SystemExit("no pve")

    cmd = f"pct exec 200 -- bash -lc 'echo {b64} | base64 -d | bash'"
    _, o, e = ssh.exec_command(cmd, timeout=90)
    print(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("ERR", err[:500])
    ssh.close()


if __name__ == "__main__":
    main()
