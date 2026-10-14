from __future__ import annotations

from typing import Any

import httpx
from fastapi import HTTPException


def _client(url: str, login: str, password: str) -> httpx.Client:
    return httpx.Client(
        base_url=url.rstrip("/") + "/",
        auth=(login, password),
        timeout=httpx.Timeout(45.0, connect=15.0),
        headers={"Accept": "application/json"},
        follow_redirects=True,
    )


def _get_json(client: httpx.Client, path: str) -> Any:
    r = client.get(path)
    if r.status_code in (401, 403):
        raise HTTPException(
            403,
            "OData: доступ запрещён к денежным данным. Проверьте права пользователя 1С.",
        )
    if r.status_code >= 400:
        detail = r.text[:300]
        try:
            detail = (
                r.json().get("odata.error", {}).get("message", {}).get("value") or detail
            )
        except Exception:
            pass
        raise HTTPException(502, f"OData error {r.status_code}: {detail}")
    if not r.content:
        return {"value": []}
    return r.json()


def _catalog_map(client: httpx.Client, entity: str) -> dict[str, str]:
    data = _get_json(client, f"{entity}?$select=Ref_Key,Description&$format=json")
    return {
        str(row.get("Ref_Key")): str(row.get("Description") or row.get("Ref_Key"))
        for row in data.get("value") or []
    }


def fetch_free_money(odata_url: str, login: str, password: str) -> dict[str, Any]:
    with _client(odata_url, login, password) as client:
        cash_rows = _get_json(
            client, "AccumulationRegister_ДенежныеСредстваНаличные/Balance?$format=json"
        ).get("value") or []
        bank_rows = _get_json(
            client,
            "AccumulationRegister_ДенежныеСредстваБезналичные/Balance?$format=json",
        ).get("value") or []

        kassy = _catalog_map(client, "Catalog_Кассы")
        try:
            accounts = _catalog_map(client, "Catalog_БанковскиеСчетаОрганизаций")
        except HTTPException:
            accounts = {}

        cash_items = []
        cash_total = 0.0
        for row in cash_rows:
            amount = float(row.get("СуммаBalance") or 0)
            cash_total += amount
            key = str(row.get("Касса_Key") or "")
            cash_items.append(
                {
                    "kind": "cash",
                    "key": key,
                    "name": kassy.get(key, key),
                    "amount": amount,
                }
            )

        bank_items = []
        bank_total = 0.0
        for row in bank_rows:
            amount = float(row.get("СуммаBalance") or 0)
            to_write_off = float(row.get("КСписаниюBalance") or 0)
            to_credit = float(row.get("КЗачислениюBalance") or 0)
            bank_total += amount
            key = str(row.get("БанковскийСчет_Key") or "")
            bank_items.append(
                {
                    "kind": "bank",
                    "key": key,
                    "name": accounts.get(key, key),
                    "amount": amount,
                    "to_write_off": to_write_off,
                    "to_credit": to_credit,
                }
            )

        free = cash_total + bank_total
        return {
            "cash_total": cash_total,
            "bank_total": bank_total,
            "free_total": free,
            "cash": cash_items,
            "bank": bank_items,
            "currency_note": "Суммы как в 1С (СуммаBalance), без пересчёта валют",
        }
