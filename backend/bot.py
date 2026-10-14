from __future__ import annotations

import logging

import httpx
from telegram import KeyboardButton, ReplyKeyboardMarkup, Update, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from config import settings

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("pocket-bot")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    kb = ReplyKeyboardMarkup(
        [[KeyboardButton("Отправить номер", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await update.effective_message.reply_text(
        "Для входа нужен номер телефона. Нажмите кнопку ниже.",
        reply_markup=kb,
    )


async def on_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    contact = update.effective_message.contact
    if contact is None:
        return
    if contact.user_id != update.effective_user.id:
        await update.effective_message.reply_text("Нужен ваш собственный контакт.")
        return

    api = settings.api_public_url.rstrip("/")
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.post(
            f"{api}/auth/phone",
            json={"telegram_id": update.effective_user.id, "phone": contact.phone_number},
        )
        if r.status_code >= 400:
            log.error("auth/phone failed: %s %s", r.status_code, r.text)
            await update.effective_message.reply_text("Не удалось сохранить номер. Попробуйте позже.")
            return

    kb = ReplyKeyboardMarkup(
        [[KeyboardButton("Открыть приложение", web_app=WebAppInfo(url=settings.app_url))]],
        resize_keyboard=True,
    )
    await update.effective_message.reply_text(
        "Номер принят. Откройте приложение:",
        reply_markup=kb,
    )


def main() -> None:
    if not settings.bot_token:
        raise SystemExit("BOT_TOKEN is empty")
    app = Application.builder().token(settings.bot_token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.CONTACT, on_contact))
    log.info("bot starting, app_url=%s", settings.app_url)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
