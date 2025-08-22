import json
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

TOKEN = "8474832895:AAEsdmVsuLExg6yAfRMZhzYgDaSYJFWxBVk"
ADMIN_ID = 6174110078  # твой Telegram ID

logging.basicConfig(level=logging.INFO)

bot = Bot(token=TOKEN)
dp = Dispatcher(bot)

# ================= ФАЙЛЫ =================
USERS_FILE = "users.json"
CONFIG_FILE = "config.json"


def load_users():
    try:
        with open(USERS_FILE, "r") as f:
            return json.load(f)
    except:
        return {}  # {user_id: {"username": "..."}}


def save_users():
    with open(USERS_FILE, "w") as f:
        json.dump(users, f)


def load_config():
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except:
        return {
            "welcome_text": (
                "Приветствую в боте для связи с fr1.\n"
                "—————————————\n"
                "1 - вопросы/сообщения\n"
                "—————————————\n"
                "2 - или по поводу покупок и т.д\n"
                "—————————————\n"
                "(Отвечаю не сразу)"
            )
        }


def save_config():
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f)


# ================= ДАННЫЕ =================
users = load_users()
config = load_config()


# ================= ХЕНДЛЕРЫ =================

@dp.message_handler(commands=["start"])
async def start_cmd(message: types.Message):
    global users
    if message.from_user.id == ADMIN_ID:
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(
            InlineKeyboardButton("Изменить текст", callback_data="change_text"),
            InlineKeyboardButton("Отправить всем сообщение", callback_data="broadcast")
        )
        await message.answer(
            f"Приветствую Администратор!\n"
            f"—————————————\n"
            f"Всего пользователей: {len(users)}\n"
            f"—————————————",
            reply_markup=kb
        )
    else:
        users[str(message.from_user.id)] = {
            "username": message.from_user.username or f"id{message.from_user.id}"
        }
        save_users()
        await message.answer(config["welcome_text"])


# Пересылка сообщений админу
@dp.message_handler(lambda msg: msg.from_user.id != ADMIN_ID, content_types=types.ContentTypes.TEXT)
async def forward_msg(message: types.Message):
    await message.answer("Сообщение успешно отправлено! Ожидай ответа.")
    user_info = f"Сообщение от @{message.from_user.username or 'Без username'} (ID: {message.from_user.id})"
    await bot.send_message(ADMIN_ID, user_info)
    await bot.forward_message(ADMIN_ID, message.chat.id, message.message_id)


# ================= АДМИН КНОПКИ =================

@dp.callback_query_handler(lambda c: c.data == "change_text")
async def change_text(call: types.CallbackQuery):
    await call.message.answer("Напиши новый текст приветствия:")

    @dp.message_handler(lambda msg: msg.from_user.id == ADMIN_ID)
    async def set_new_text(message: types.Message):
        config["welcome_text"] = message.text
        save_config()
        await message.answer("✅ Новый приветственный текст установлен!")
        dp.message_handlers.unregister(set_new_text)


@dp.callback_query_handler(lambda c: c.data == "broadcast")
async def broadcast_msg(call: types.CallbackQuery):
    await call.message.answer("Отправь сообщение, которое пойдёт всем пользователям:")

    @dp.message_handler(lambda msg: msg.from_user.id == ADMIN_ID)
    async def send_broadcast(message: types.Message):
        count = 0
        for user_id in list(users.keys()):
            try:
                await bot.send_message(int(user_id), message.text)
                count += 1
            except:
                pass
        await message.answer(f"✅ Сообщение отправлено {count} пользователям")
        dp.message_handlers.unregister(send_broadcast)


# ================= КОМАНДА ДЛЯ ОТВЕТА АДМИНА =================
@dp.message_handler(lambda msg: msg.from_user.id == ADMIN_ID, content_types=types.ContentTypes.TEXT)
async def reply_to_user(message: types.Message):
    text_msg = message.text.strip()

    # Проверяем, начинается ли текст с "/@"
    if not text_msg.startswith("/@"):
        return  # если нет - игнорим

    try:
        parts = text_msg.split(" ", 1)
        if len(parts) < 2:
            await message.answer("❌ Используй: /@username текст")
            return

        cmd, reply_text = parts
        username = cmd[2:]  # убираем "/@" спереди

        # ищем пользователя по username или id
        target_id = None
        for uid, data in users.items():
            if data["username"].lower() == username.lower() or f"id{uid}" == username.lower():
                target_id = int(uid)
                break

        if not target_id:
            await message.answer(f"❌ Пользователь {username} не найден в базе.")
            return

        # Отправляем сообщение пользователю
        await bot.send_message(target_id, reply_text)
        await message.answer(f"✅ Сообщение отправлено пользователю {username}")

    except Exception as e:
        await message.answer(f"⚠ Ошибка: {e}")

# ================= ЗАПУСК =================
if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
