# -*- coding: utf-8 -*-
"""DNS + Cloudflare tunnel for pocket.melnichuk.kz; set encryption key on CT200.

Env:
  CLOUDFLARE_API_TOKEN
  PVE_PASSWORD
  CREDENTIALS_ENCRYPTION_KEY  (Fernet)
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

import paramiko

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CF_TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN", "")
ZONE_ID = "25ec564914a8fb0febc34aaff2f37104"
TUNNEL_ID = "419be2fe-2b95-49a8-92f1-f0aebe7e1c90"
FQDN = "pocket.melnichuk.kz"
SUB = "pocket"
PW = os.environ.get("PVE_PASSWORD", "")
FERNET = os.environ.get("CREDENTIALS_ENCRYPTION_KEY", "")
HOSTS = ["100.64.245.30", "192.168.0.200"]


def cf_api(method: str, path: str, data=None) -> dict:
    req = urllib.request.Request(
        f"https://api.cloudflare.com/client/v4{path}",
        data=json.dumps(data).encode() if data else None,
        method=method,
    )
    req.add_header("Authorization", f"Bearer {CF_TOKEN}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        print(f"CF HTTP {e.code}: {body[:500]}")
        return json.loads(body) if body.startswith("{") else {"success": False}


def main() -> None:
    if not CF_TOKEN or not PW:
        raise SystemExit("Need CLOUDFLARE_API_TOKEN and PVE_PASSWORD")
    if not FERNET:
        raise SystemExit("Need CREDENTIALS_ENCRYPTION_KEY")

    print("=== DNS ===")
    tunnel_cname = f"{TUNNEL_ID}.cfargotunnel.com"
    recs = cf_api("GET", f"/zones/{ZONE_ID}/dns_records?name={FQDN}")
    payload = {
        "type": "CNAME",
        "name": SUB,
        "content": tunnel_cname,
        "proxied": True,
        "ttl": 1,
    }
    if recs.get("result"):
        res = cf_api("PUT", f"/zones/{ZONE_ID}/dns_records/{recs['result'][0]['id']}", payload)
    else:
        res = cf_api("POST", f"/zones/{ZONE_ID}/dns_records", payload)
    print(
        "DNS success=",
        res.get("success"),
        res.get("result", {}).get("name"),
        "->",
        res.get("result", {}).get("content"),
    )

    print("=== Tunnel ===")
    zone = cf_api("GET", f"/zones/{ZONE_ID}")
    account_id = (zone.get("result") or {}).get("account", {}).get("id")
    if account_id:
        config = cf_api("GET", f"/accounts/{account_id}/cfd_tunnel/{TUNNEL_ID}/configurations")
        if config.get("success"):
            cfg = config.get("result", {}).get("config", {}) or {}
            ingress = [r for r in (cfg.get("ingress") or []) if r.get("hostname") != FQDN]
            rule = {"hostname": FQDN, "service": "http://127.0.0.1:80", "originRequest": {}}
            new_ingress = []
            inserted = False
            for r in ingress:
                if not inserted and "http_status:404" in str(r.get("service", "")):
                    new_ingress.append(rule)
                    inserted = True
                new_ingress.append(r)
            if not inserted:
                new_ingress.append(rule)
                new_ingress.append({"service": "http_status:404"})
            put = cf_api(
                "PUT",
                f"/accounts/{account_id}/cfd_tunnel/{TUNNEL_ID}/configurations",
                {
                    "config": {
                        "ingress": new_ingress,
                        "warp-routing": cfg.get("warp-routing", {"enabled": True}),
                    }
                },
            )
            print("Tunnel success=", put.get("success"), put.get("errors"))
        else:
            print("Tunnel GET failed — check wildcard *.melnichuk.kz")
    else:
        print("no account id")

    print("=== CT200 .env ===")
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

    # Escape for single-quoted bash is painful; pass key via base64
    import base64

    key_b64 = base64.b64encode(FERNET.encode()).decode()
    remote = f"""
set -e
ENV=/opt/pocket/backend/.env
KEY=$(echo {key_b64} | base64 -d)
touch "$ENV"
grep -q '^CREDENTIALS_ENCRYPTION_KEY=' "$ENV" \
  && sed -i "s|^CREDENTIALS_ENCRYPTION_KEY=.*|CREDENTIALS_ENCRYPTION_KEY=$KEY|" "$ENV" \
  || echo "CREDENTIALS_ENCRYPTION_KEY=$KEY" >> "$ENV"
sed -i 's|^APP_URL=.*|APP_URL=https://pocket.melnichuk.kz|' "$ENV" || true
grep -q '^APP_URL=' "$ENV" || echo 'APP_URL=https://pocket.melnichuk.kz' >> "$ENV"
sed -i 's|^API_PUBLIC_URL=.*|API_PUBLIC_URL=https://pocket.melnichuk.kz/api|' "$ENV" || true
grep -q '^API_PUBLIC_URL=' "$ENV" || echo 'API_PUBLIC_URL=https://pocket.melnichuk.kz/api' >> "$ENV"
sed -i 's|^DATABASE_PATH=.*|DATABASE_PATH=/opt/pocket/data/app.db|' "$ENV" || true
grep -q '^DATABASE_PATH=' "$ENV" || echo 'DATABASE_PATH=/opt/pocket/data/app.db' >> "$ENV"
systemctl restart pocket
sleep 2
curl -sS http://127.0.0.1:8110/api/health; echo
grep -E '^[A-Z_]+=' "$ENV" | cut -d= -f1
"""
    cmd = "pct exec 200 -- bash -lc " + json.dumps(remote)
    _, o, e = ssh.exec_command(cmd, timeout=90)
    print(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("ERR", err[:400])
    ssh.close()
    print("DONE — set BOT_TOKEN on server, then: systemctl restart pocket pocket-bot")


if __name__ == "__main__":
    main()
