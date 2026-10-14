# Pocket — Telegram Mini App + 1С OData

Бот (телефон) → Mini App → Backend → 1С OData.  
Шаринг баз: **ACL по телефонам**, единый OData-логин (только owner).

Архитектура: https://github.com/sania2007mav/telegram-1c-miniapp-architecture

## Состав

| Путь | Назначение |
|---|---|
| `backend/` | FastAPI + SQLite + Telegram bot |
| `miniapp/` | UI Mini App |
| `deploy/nginx-pocket.conf` | nginx на CT200 |
| `tools/deploy.py` | выкладка на Proxmox CT 200 |

## Целевой хостинг

- Домен: **https://pocket.melnichuk.kz**
- CT 200 (`192.168.0.203`), порт приложения `8110`
- Cloudflare tunnel → nginx → uvicorn (как falconapp)

## Локально (smoke)

```powershell
cd backend
copy .env.example .env
# заполнить BOT_TOKEN и CREDENTIALS_ENCRYPTION_KEY
python -m venv ..\.venv
..\.venv\Scripts\pip install -r requirements.txt
..\.venv\Scripts\uvicorn app:app --reload --port 8110
```

Ключ шифрования:

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Бот локально (нужен публичный API или туннель):

```powershell
cd backend
..\.venv\Scripts\python bot.py
```

## Деплой на CT200

1. **BotFather** — новый токен (старый из чата отозвать), Menu Button / Web App URL = `https://pocket.melnichuk.kz`
2. **Cloudflare** — hostname `pocket.melnichuk.kz` → `http://192.168.0.203:80` (как у других `*.melnichuk.kz`)
3. С этой машины:

```powershell
cd d:\Projects\056_ПроектноеМоделирование\telegram-1c-miniapp
pip install paramiko
$env:PVE_PASSWORD = "…"   # пароль Proxmox root
python tools/deploy.py
```

4. На CT200 дописать `/opt/pocket/backend/.env`:
   - `BOT_TOKEN`
   - `CREDENTIALS_ENCRYPTION_KEY`
5. `systemctl restart pocket pocket-bot`
6. Проверка: `https://pocket.melnichuk.kz/api/health` → `{"ok":true}`
7. В Telegram: `/start` → номер → «Открыть приложение»

## API (MVP)

| Метод | Путь | Кто |
|---|---|---|
| POST | `/api/auth/phone` | бот |
| GET | `/api/me` | Mini App (initData) |
| GET/POST | `/api/bases` | список / создать (owner) |
| GET/POST | `/api/bases/{id}/access` | ACL (только owner) |

## Безопасность

- Не коммитить `.env` и токены
- Токен, светившийся в чате — **Revoke** в BotFather
- OData-пароль шифруется Fernet на бэкенде
