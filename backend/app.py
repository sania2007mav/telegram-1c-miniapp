from __future__ import annotations

import hashlib
import hmac
import json
import time
from pathlib import Path
from urllib.parse import parse_qsl

import httpx
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from config import settings
from crypto import decrypt_password, encrypt_password
from db import (
    connect,
    create_fund,
    delete_fund,
    get_base_credentials,
    get_user_by_telegram,
    init_db,
    list_bases_for_phone,
    list_funds,
    normalize_phone,
    update_fund,
    upsert_user,
    user_can_access_base,
)
from odata_money import fetch_free_money

FUND_PRESETS = [
    {"name": "Зарплата", "hint": "ФОТ, авансы, оклады"},
    {"name": "Бонусы", "hint": "Премии, KPI"},
    {"name": "Налоги", "hint": "Налоги и взносы к уплате"},
    {"name": "Резерв", "hint": "Подушка безопасности"},
    {"name": "Операционный", "hint": "Текущие расходы"},
    {"name": "Проект", "hint": "Бюджет конкретного проекта — уточните название"},
]

ROOT = Path(__file__).resolve().parent.parent
MINIAPP = ROOT / "miniapp"

app = FastAPI(title="Pocket — Telegram Mini App + 1C OData")
init_db()


class PhoneBind(BaseModel):
    telegram_id: int
    phone: str


class BaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    odata_url: str = Field(min_length=8)
    login: str = Field(min_length=1)
    password: str = Field(min_length=1)


class AccessAdd(BaseModel):
    phone: str


class FundCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    amount: float = Field(ge=0)
    note: str = Field(default="", max_length=500)


class FundUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    amount: float | None = Field(default=None, ge=0)
    note: str | None = Field(default=None, max_length=500)


def verify_init_data(init_data: str) -> dict:
    if not settings.bot_token:
        raise HTTPException(503, "BOT_TOKEN not configured")
    parsed = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = parsed.pop("hash", None)
    if not received_hash:
        raise HTTPException(401, "Missing hash")
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret = hmac.new(b"WebAppData", settings.bot_token.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, received_hash):
        raise HTTPException(401, "Invalid initData")
    auth_date = int(parsed.get("auth_date", "0"))
    if abs(time.time() - auth_date) > 86400:
        raise HTTPException(401, "initData expired")
    user = json.loads(parsed.get("user", "{}"))
    return user


def require_user(x_telegram_init_data: str | None) -> dict:
    if not x_telegram_init_data:
        raise HTTPException(401, "X-Telegram-Init-Data required")
    tg_user = verify_init_data(x_telegram_init_data)
    telegram_id = int(tg_user["id"])
    row = get_user_by_telegram(telegram_id)
    if row is None:
        raise HTTPException(403, "Phone not linked — open bot and share contact")
    return {"telegram_id": telegram_id, "phone": row["phone"], "user_id": row["id"]}


def require_base(user: dict, base_id: int):
    row = user_can_access_base(user["user_id"], user["phone"], base_id)
    if row is None:
        raise HTTPException(404, "Base not found or access denied")
    return row


@app.get("/api/health")
def health():
    return {"ok": True, "app": "pocket"}


@app.get("/api/fund-presets")
def fund_presets():
    return {"items": FUND_PRESETS}


@app.post("/api/auth/phone")
def auth_phone(body: PhoneBind):
    """Called by bot after contact share."""
    row = upsert_user(body.telegram_id, body.phone)
    return {"ok": True, "user_id": row["id"], "phone": row["phone"]}


@app.get("/api/me")
def me(x_telegram_init_data: str | None = Header(default=None)):
    user = require_user(x_telegram_init_data)
    return user


@app.get("/api/bases")
def bases(x_telegram_init_data: str | None = Header(default=None)):
    user = require_user(x_telegram_init_data)
    rows = list_bases_for_phone(user["phone"])
    return {
        "items": [
            {
                "id": r["id"],
                "name": r["name"],
                "odata_url": r["odata_url"],
                "is_owner": bool(r["is_owner"]),
            }
            for r in rows
        ]
    }


async def probe_odata(url: str, login: str, password: str) -> None:
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        r = await client.get(url.rstrip("/") + "/", auth=(login, password))
        if r.status_code in (401, 403):
            raise HTTPException(400, "OData auth failed — check login/password")
        if r.status_code >= 400:
            raise HTTPException(400, f"OData probe failed: HTTP {r.status_code}")


@app.post("/api/bases")
async def create_base(
    body: BaseCreate,
    x_telegram_init_data: str | None = Header(default=None),
):
    user = require_user(x_telegram_init_data)
    await probe_odata(body.odata_url, body.login, body.password)
    enc = encrypt_password(body.password)
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO bases (owner_user_id, name, odata_url) VALUES (?, ?, ?)",
            (user["user_id"], body.name, body.odata_url.rstrip("/")),
        )
        base_id = cur.lastrowid
        conn.execute(
            "INSERT INTO odata_credentials (base_id, login, password_encrypted) VALUES (?, ?, ?)",
            (base_id, body.login, enc),
        )
        # owner always has access via ownership; also mirror phone in ACL for clarity
        conn.execute(
            "INSERT OR IGNORE INTO base_access (base_id, phone) VALUES (?, ?)",
            (base_id, user["phone"]),
        )
    return {"id": base_id, "ok": True}


@app.post("/api/bases/{base_id}/access")
def add_access(
    base_id: int,
    body: AccessAdd,
    x_telegram_init_data: str | None = Header(default=None),
):
    user = require_user(x_telegram_init_data)
    phone = normalize_phone(body.phone)
    with connect() as conn:
        base = conn.execute("SELECT * FROM bases WHERE id = ?", (base_id,)).fetchone()
        if base is None:
            raise HTTPException(404, "Base not found")
        if base["owner_user_id"] != user["user_id"]:
            raise HTTPException(403, "Only owner can manage ACL")
        conn.execute(
            "INSERT OR IGNORE INTO base_access (base_id, phone) VALUES (?, ?)",
            (base_id, phone),
        )
    return {"ok": True, "phone": phone}


@app.get("/api/bases/{base_id}/access")
def list_access(
    base_id: int,
    x_telegram_init_data: str | None = Header(default=None),
):
    user = require_user(x_telegram_init_data)
    with connect() as conn:
        base = conn.execute("SELECT * FROM bases WHERE id = ?", (base_id,)).fetchone()
        if base is None:
            raise HTTPException(404, "Base not found")
        if base["owner_user_id"] != user["user_id"]:
            raise HTTPException(403, "Only owner can view ACL")
        rows = conn.execute(
            "SELECT phone, created_at FROM base_access WHERE base_id = ? ORDER BY phone",
            (base_id,),
        ).fetchall()
    return {"items": [{"phone": r["phone"], "created_at": r["created_at"]} for r in rows]}


@app.get("/api/bases/{base_id}/money")
def base_money(
    base_id: int,
    x_telegram_init_data: str | None = Header(default=None),
):
    user = require_user(x_telegram_init_data)
    require_base(user, base_id)
    creds = get_base_credentials(base_id)
    if creds is None:
        raise HTTPException(400, "OData credentials missing")
    odata_url, login, password_encrypted = creds
    password = decrypt_password(password_encrypted)
    money = fetch_free_money(odata_url, login, password)
    funds = list_funds(base_id)
    allocated = sum(float(f["amount"]) for f in funds)
    free_total = float(money["free_total"])
    return {
        **money,
        "allocated_total": allocated,
        "unallocated": free_total - allocated,
        "funds": [
            {
                "id": f["id"],
                "name": f["name"],
                "amount": f["amount"],
                "note": f["note"],
                "updated_at": f["updated_at"],
            }
            for f in funds
        ],
    }


@app.get("/api/bases/{base_id}/funds")
def get_funds(
    base_id: int,
    x_telegram_init_data: str | None = Header(default=None),
):
    user = require_user(x_telegram_init_data)
    require_base(user, base_id)
    funds = list_funds(base_id)
    return {
        "items": [
            {
                "id": f["id"],
                "name": f["name"],
                "amount": f["amount"],
                "note": f["note"],
                "updated_at": f["updated_at"],
            }
            for f in funds
        ]
    }


@app.post("/api/bases/{base_id}/funds")
def post_fund(
    base_id: int,
    body: FundCreate,
    x_telegram_init_data: str | None = Header(default=None),
):
    user = require_user(x_telegram_init_data)
    require_base(user, base_id)
    fund = create_fund(base_id, body.name, body.amount, body.note, user["user_id"])
    return {
        "id": fund["id"],
        "name": fund["name"],
        "amount": fund["amount"],
        "note": fund["note"],
    }


@app.patch("/api/bases/{base_id}/funds/{fund_id}")
def patch_fund(
    base_id: int,
    fund_id: int,
    body: FundUpdate,
    x_telegram_init_data: str | None = Header(default=None),
):
    user = require_user(x_telegram_init_data)
    require_base(user, base_id)
    fund = update_fund(
        fund_id,
        base_id,
        name=body.name,
        amount=body.amount,
        note=body.note,
    )
    if fund is None:
        raise HTTPException(404, "Fund not found")
    return {
        "id": fund["id"],
        "name": fund["name"],
        "amount": fund["amount"],
        "note": fund["note"],
    }


@app.delete("/api/bases/{base_id}/funds/{fund_id}")
def remove_fund(
    base_id: int,
    fund_id: int,
    x_telegram_init_data: str | None = Header(default=None),
):
    user = require_user(x_telegram_init_data)
    require_base(user, base_id)
    if not delete_fund(fund_id, base_id):
        raise HTTPException(404, "Fund not found")
    return {"ok": True}


if MINIAPP.is_dir():
    app.mount("/assets", StaticFiles(directory=MINIAPP), name="assets")

    @app.get("/")
    def miniapp_index():
        return FileResponse(MINIAPP / "index.html")
