# bot.py — отлаженная версия для aiogram 3.x
import asyncio
import logging
import random
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    ChatPermissions,
    ChatMemberUpdated,
    MessageEntity
)
from aiogram.exceptions import TelegramBadRequest

# ---------- Настройки ----------
TOKEN = "8587162546:AAHa3MeKA5071GSV4yAsXnbIRDWK2fq2tCw"  # <- вставь сюда токен
LOGFILE = "bot.log"
# -------------------------------

# Логи (файл + консоль)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOGFILE, encoding="utf-8"),
        logging.StreamHandler()
    ],
)
logger = logging.getLogger(__name__)

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Структуры в памяти
# user_stats: {user_id: {"display": str, "count": int}}
user_stats = {}
# spam_tracker: {user_id: [datetime, ...]}
spam_tracker = {}

WELCOME_TEXT = "👋 Привет, {name}!\nДобро пожаловать в нашу группу!\nНадеюсь, тебе тут понравится 🙂"


# ---------- Утилиты ----------
def format_display(user) -> str:
    """Формируем удобную строку для показа: @username или FirstName."""
    if not user:
        return "unknown"
    if getattr(user, "username", None):
        return f"@{user.username}"
    return getattr(user, "first_name", None) or str(getattr(user, "id", ""))


async def is_admin_or_owner(chat_id: int, user_id: int) -> bool:
    """Проверка, является ли пользователь админом или владельцем."""
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ("administrator", "creator")
    except Exception:
        logger.exception("is_admin_or_owner error")
        return False


async def resolve_user_id(message: Message) -> int | None:
    """
    Надёжно получить target user_id:
    1) если есть reply — берем reply_to_message.from_user.id
    2) ищем entities типа text_mention (встроенное упоминание с user)
    3) ищем @username в тексте — пробуем bot.get_chat(@username) и затем проверяем членство
    4) если в тексте есть число — считаем это user_id
    Возвращает user_id (int) или None.
    """
    # 1) ответ
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user.id

    text = (message.text or "").strip()
    # 2) text_mention (если есть entity с user)
    if message.entities:
        for ent in message.entities:
            # ent.type иногда — строка, иногда enum; приведём к str
            ent_type = getattr(ent, "type", "")
            if isinstance(ent_type, str):
                if ent_type == "text_mention" and getattr(ent, "user", None):
                    return ent.user.id
            else:
                # на всякий случай сравним имя
                try:
                    if str(ent_type).lower().endswith("text_mention") and getattr(ent, "user", None):
                        return ent.user.id
                except Exception:
                    pass

    # 3) @username
    parts = text.split()
    for p in parts:
        if p.startswith("@") and len(p) > 1:
            username = p
            try:
                # get_chat возвращает объект (User или Chat). У user.id будет id.
                chat_obj = await bot.get_chat(username)
                target_id = getattr(chat_obj, "id", None)
                if target_id is not None:
                    # Проверим, является ли он участником чата (если не публичный, может не быть)
                    try:
                        await bot.get_chat_member(message.chat.id, target_id)
                        return int(target_id)
                    except TelegramBadRequest:
                        # не участник — возвращаем id всё равно (некоторые операции работают с id)
                        return int(target_id)
            except Exception:
                logger.info("resolve_user_id: не удалось получить @%s", username)
                continue

    # 4) numeric id
    for p in parts:
        if p.lstrip("-").isdigit():
            try:
                return int(p)
            except:
                pass

    return None


def update_user_stats_from_message(message: Message):
    """Обновляем user_stats по incoming message."""
    user = message.from_user
    if not user:
        return
    uid = user.id
    display = format_display(user)
    entry = user_stats.get(uid)
    if entry:
        entry["count"] += 1
    else:
        user_stats[uid] = {"display": display, "count": 1}


def choose_random_active_user(exclude_bot_id: int = None):
    """Выбираем случайного пользователя из user_stats, исключая бота если нужно."""
    candidates = [ (uid, info) for uid, info in user_stats.items() if uid != exclude_bot_id ]
    if not candidates:
        return None
    uid, info = random.choice(candidates)
    return uid, info["display"]


# ---------- Основной единый хэндлер ----------
@dp.message(F.text)
async def main_handler(message: Message):
    # Лог входящего сообщения
    logger.info("Incoming | chat: %s | from: %s (%s) | text: %s",
                message.chat.id,
                (message.from_user.full_name if message.from_user else "None"),
                (message.from_user.id if message.from_user else "None"),
                (message.text[:200] + ("..." if message.text and len(message.text) > 200 else "")))

    # Обновляем статистику и антиспам
    try:
        update_user_stats_from_message(message)

        # антиспам: 5 сообщений за 5 секунд -> авто-мут 30 сек
        user = message.from_user
        if user:
            now = datetime.now()
            lst = spam_tracker.get(user.id, [])
            lst = [t for t in lst if (now - t).total_seconds() < 5]
            lst.append(now)
            spam_tracker[user.id] = lst
            if len(lst) >= 5:
                until = now + timedelta(seconds=30)
                try:
                    await bot.restrict_chat_member(
                        chat_id=message.chat.id,
                        user_id=user.id,
                        permissions=ChatPermissions(can_send_messages=False),
                        until_date=until
                    )
                    await message.reply(f"⚠️ {format_display(user)} получил(а) авто-мут за спам (30 сек).")
                    logger.info("Auto-mute applied to %s in chat %s", user.id, message.chat.id)
                except Exception:
                    logger.exception("Auto-mute error")
                spam_tracker[user.id] = []
    except Exception:
        logger.exception("Stats/antispam error")

    txt = (message.text or "").strip()
    txt_lower = txt.lower()

    # ----- Админские команды -----
    try:
        # МУТ
        if txt_lower.startswith("мут"):
            if not await is_admin_or_owner(message.chat.id, message.from_user.id):
                await message.reply("⛔ Только админ или владелец может выдавать мут.")
                return

            target_id = await resolve_user_id(message)
            if not target_id:
                await message.reply("Не удалось найти пользователя. Используй ответ на сообщение или @username или id.")
                return

            parts = txt.split()
            if len(parts) < 3:
                await message.reply("Формат: мут <число> <минут/часов> причина: ...")
                return

            try:
                amount = int(parts[1])
            except:
                await message.reply("Укажи число, например: мут 30 минут причина: ...")
                return

            unit = parts[2].lower()
            if "мин" in unit:
                duration = timedelta(minutes=amount)
            elif "час" in unit:
                duration = timedelta(hours=amount)
            else:
                await message.reply("Используй 'минут' или 'часов'.")
                return

            reason = "не указана"
            if "причина:" in txt_lower:
                reason = txt.split("причина:", 1)[1].strip()

            until = datetime.now() + duration
            try:
                await bot.restrict_chat_member(
                    chat_id=message.chat.id,
                    user_id=target_id,
                    permissions=ChatPermissions(can_send_messages=False),
                    until_date=until
                )
                await message.reply(f"🔇 Пользователь (id={target_id}) получил мут на {amount} {unit}.\nПричина: {reason}")
                logger.info("Mute applied by %s to %s in chat %s for %s %s", message.from_user.id, target_id, message.chat.id, amount, unit)
            except TelegramBadRequest as e:
                await message.reply(f"Ошибка при муте: {e}")
                logger.exception("Mute error")
            return

        # РАЗМУТ
        if txt_lower.startswith("размут"):
            if not await is_admin_or_owner(message.chat.id, message.from_user.id):
                await message.reply("⛔ Только админ или владелец может размутить.")
                return

            target_id = await resolve_user_id(message)
            if not target_id:
                await message.reply("Не удалось найти пользователя. Используй ответ или @username.")
                return

            try:
                await bot.restrict_chat_member(
                    chat_id=message.chat.id,
                    user_id=target_id,
                    permissions=ChatPermissions(
                        can_send_messages=True,
                        can_send_media_messages=True,
                        can_send_polls=True,
                        can_send_other_messages=True,
                        can_add_web_page_previews=True,
                        can_change_info=False,
                        can_invite_users=True,
                        can_pin_messages=False
                    )
                )
                await message.reply(f"✅ Пользователь (id={target_id}) размучен.")
                logger.info("Unmute applied by %s to %s in chat %s", message.from_user.id, target_id, message.chat.id)
            except TelegramBadRequest as e:
                await message.reply(f"Ошибка при размуте: {e}")
                logger.exception("Unmute error")
            return

        # БАН
        if txt_lower.startswith("бан"):
            if not await is_admin_or_owner(message.chat.id, message.from_user.id):
                await message.reply("⛔ Только админ или владелец может забанить.")
                return

            target_id = await resolve_user_id(message)
            if not target_id:
                await message.reply("Не удалось найти пользователя. Используй ответ или @username.")
                return

            reason = "не указана"
            if "причина:" in txt_lower:
                reason = txt.split("причина:", 1)[1].strip()

            try:
                await bot.ban_chat_member(message.chat.id, target_id)
                await message.reply(f"🔨 Пользователь (id={target_id}) забанен.\nПричина: {reason}")
                logger.info("Ban applied by %s to %s in chat %s", message.from_user.id, target_id, message.chat.id)
            except TelegramBadRequest as e:
                await message.reply(f"Ошибка при бане: {e}")
                logger.exception("Ban error")
            return

        # РАЗБАН
        if txt_lower.startswith("разбан"):
            if not await is_admin_or_owner(message.chat.id, message.from_user.id):
                await message.reply("⛔ Только админ или владелец может разбанить.")
                return

            target_id = await resolve_user_id(message)
            if not target_id:
                await message.reply("Не удалось найти пользователя. Используй ответ или @username.")
                return

            try:
                await bot.unban_chat_member(message.chat.id, target_id)
                await message.reply(f"✅ Пользователь (id={target_id}) разбанен.")
                logger.info("Unban applied by %s to %s in chat %s", message.from_user.id, target_id, message.chat.id)
            except TelegramBadRequest as e:
                await message.reply(f"Ошибка при разбане: {e}")
                logger.exception("Unban error")
            return

    except Exception:
        logger.exception("Ошибка при выполнении админской команды")
        await message.reply("Произошла ошибка при выполнении админской команды (см. bot.log).")
        return

    # ----- Мини-игра: "фри, кто ..." -----
    try:
        if txt_lower.startswith("фри, кто"):
            after = txt.split("кто", 1)[1].strip()
            # выбираем рандомного активного пользователя, исключая бота
            chosen = choose_random_active_user(exclude_bot_id=(await bot.get_me()).id)
            if chosen:
                uid, display = chosen
                await message.reply(f"я думаю что {display} {after}")
            else:
                # если никто не активен — выбираем автора
                await message.reply(f"я думаю что {format_display(message.from_user)} {after}")
            return
    except Exception:
        logger.exception("Ошибка в мини-игре")
        await message.reply("Ошибка мини-игры (см. bot.log).")
        return

    # ----- /admins и /stats -----
    try:
        if txt_lower.startswith("/admins"):
            admins = await bot.get_chat_administrators(message.chat.id)
            text = "👮 Администраторы:\n"
            for admin in admins:
                name = admin.user.username or admin.user.first_name
                if admin.status == "creator":
                    text += f"• @{name} (владелец)\n"
                else:
                    text += f"• @{name}\n"
            await message.reply(text)
            return

        if txt_lower.startswith("/stats"):
            if not user_stats:
                await message.reply("Статистика пока пуста.")
                return
            total = sum(info["count"] for info in user_stats.values())
            most_active_id = max(user_stats.items(), key=lambda kv: kv[1]["count"])[0]
            most_active_display = user_stats[most_active_id]["display"]
            await message.reply(
                f"📊 Статистика чата:\n"
                f"Сообщений: {total}\n"
                f"Уникальных участников: {len(user_stats)}\n"
                f"Самый активный: {most_active_display} ({user_stats[most_active_id]['count']} сообщений)"
            )
            return
    except Exception:
        logger.exception("Ошибка /admins или /stats")
        await message.reply("Ошибка команды (см. bot.log).")
        return

    # Обычное сообщение — бот не отвечает
    return


# ----- Приветствие нового участника -----
@dp.chat_member()
async def welcome_new_member(event: ChatMemberUpdated):
    try:
        old = event.old_chat_member
        new = event.new_chat_member
        if old.status in ("left", "kicked") and new.status == "member":
            user = new.user
            name = getattr(user, "first_name", "") or ""
            text = WELCOME_TEXT.replace("{name}", name)
            await bot.send_message(event.chat.id, text)
            logger.info("Welcomed new member %s in chat %s", user.id, event.chat.id)
    except Exception:
        logger.exception("welcome_new_member error")


# ----- Запуск -----
async def main():
    logger.info("Bot starting...")
    try:
        await dp.start_polling(bot)
    except Exception:
        logger.exception("Fatal polling error")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
