# ДОБАВИТЬ В НАЧАЛО ФАЙЛА, ВЫШЕ остальных импортов aiogram
'''
import os
from dotenv import load_dotenv
from pathlib import Path

# Найдем путь к текущему файлу скрипта
env_path = Path('.') / '.env'
print("Пытаюсь загрузить .env по пути:", env_path)

# Загрузим файл по конкретному пути
load_dotenv(dotenv_path=env_path)

# Теперь можно получать переменные из .env
TOKEN_API = os.getenv('BOT_TOKEN') # Или как у вас называется переменная в .env
'''

TOKEN_API = "8596662297:AAE36tvXL72kpabfjEYDUVe6KQrU4SkKSzc"


import asyncio
import logging
import os
import sqlite3
import sys
from io import BytesIO
from pathlib import Path
from typing import Any

from aiogram import Bot, Dispatcher, F, types
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramNetworkError
from aiogram.filters.command import Command, CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

BASE_DIR = Path(__file__).resolve().parent
MAIN_DB_PATH = BASE_DIR / "bot_data003.db"
SUPPORT_DB_PATH = BASE_DIR / "data_support.db"

# Подключение к основной базе данных пользователей
connection = sqlite3.connect(MAIN_DB_PATH)
cursor = connection.cursor()
cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS Users
    (
        id INTEGER PRIMARY KEY,
        owner_tg_id INTEGER,
        name TEXT,
        school TEXT,
        grade TEXT,
        subjects TEXT,
        description TEXT,
        contact TEXT,
        photo BLOB
    )
"""
)

# Проверка и добавление колонки owner_tg_id при необходимости
cursor.execute("PRAGMA table_info(Users)")
users_columns = {row[1] for row in cursor.fetchall()}
if "owner_tg_id" not in users_columns:
    cursor.execute("ALTER TABLE Users ADD COLUMN owner_tg_id INTEGER")

# Оставляем только последнюю анкету для каждого пользователя
cursor.execute(
    """
    DELETE FROM Users
    WHERE owner_tg_id IS NOT NULL
      AND id NOT IN (
          SELECT MAX(id)
          FROM Users
          WHERE owner_tg_id IS NOT NULL
          GROUP BY owner_tg_id
      )
"""
)
cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_owner_tg_id ON Users(owner_tg_id)")
connection.commit()

# Подключение к базе данных поддержки
connection2 = sqlite3.connect(SUPPORT_DB_PATH)
cursor2 = connection2.cursor()
cursor2.execute(
    """
    CREATE TABLE IF NOT EXISTS Support
    (
        id INTEGER PRIMARY KEY,
        text TEXT
    )
"""
)
'''
# Чтение токена бота из переменной окружения (рекомендуется для продакшена)
TOKEN_API = os.getenv("BOT_TOKEN", "").strip()
if not TOKEN_API:
    raise RuntimeError("Установите BOT_TOKEN в переменной окружения или .env файле")
'''

def detect_proxy_url() -> str | None:
    env_candidates = (
        "HTTPS_PROXY",
        "https_proxy",
        "HTTP_PROXY",
        "http_proxy",
        "ALL_PROXY",
        "all_proxy",
    )
    for key in env_candidates:
        value = os.getenv(key)
        if value and value.strip():
            return value.strip()

    if not sys.platform.startswith("win"):
        return None

    try:
        import winreg  # type: ignore

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as key:
            proxy_enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
            if not proxy_enabled:
                return None

            proxy_server, _ = winreg.QueryValueEx(key, "ProxyServer")
    except OSError:
        return None

    if not proxy_server:
        return None

    raw = str(proxy_server).strip()
    if not raw:
        return None

    selected = raw
    if "=" in raw and ";" in raw:
        mapping: dict[str, str] = {}
        for part in raw.split(";"):
            if "=" not in part:
                continue
            proto, value = part.split("=", 1)
            mapping[proto.strip().lower()] = value.strip()
        selected = mapping.get("https") or mapping.get("http") or ""

    if not selected:
        return None

    if "://" not in selected:
        selected = f"http://{selected}"

    return selected


proxy_url = detect_proxy_url()
session = AiohttpSession(proxy=proxy_url) if proxy_url else AiohttpSession()
bot = Bot(TOKEN_API, session=session)
dp = Dispatcher()

# Названия кнопок на русском языке с эмодзи
BTN_MENU = "📋 Меню"
BTN_FORM = "📝 Анкета"
BTN_PROFILE = "👤 Моя анкета"
BTN_SEARCH = "🔍 Поиск"
BTN_SUPPORT = "🆘 Поддержка"
BTN_HELP = "ℹ️ Помощь"

HELP_COMMAND = (
    "📚 Что умеет бот:\n"
    "📝 Анкета — создать/обновить анкету (/form)\n"
    "👤 Моя анкета — посмотреть свою анкету (/profile)\n"
    "🔍 Поиск — найти случайную анкету (/search)\n"
    "🆘 Поддержка — написать в поддержку (/support)\n"
    "ℹ️ Помощь — показать этот список (/help)"
)

SCHOOL_OPTIONS = ('Школа №50', 'Лицей "Дельта"', "Не из Дельты и 50-й")
GRADE_OPTIONS = ("1-4", "5-6", "7-9", "10-11", "Не учусь в этой школе")
SUBJECT_OPTIONS = (
    "Математика/физика/информатика",
    "Русский/ин.яз/литература",
    "Химия/биология",
    "История/обществознание",
    "География",
)


active_users: set[int] = set()
user_grade_cache: dict[int, str] = {}
paused_form_drafts: dict[int, dict[str, Any]] = {}


class Form(StatesGroup):
    Name = State()
    School = State()
    Grade = State()
    Subjects = State()
    Description = State()
    Contact = State()
    Photo = State()


class Sup(StatesGroup):
    Ans = State()


class Profile(StatesGroup):
    Decision = State()

class AdminStates(StatesGroup):
    """Состояния для административных команд"""
    waiting_for_user_id = State()


FORM_STATES = {
    Form.Name.state,
    Form.School.state,
    Form.Grade.state,
    Form.Subjects.state,
    Form.Description.state,
    Form.Contact.state,
    Form.Photo.state,
}


def get_keyboard1() -> InlineKeyboardMarkup:
    b1 = InlineKeyboardButton(text="1-4", callback_data="1-4")
    b2 = InlineKeyboardButton(text="5-6", callback_data="5-6")
    b3 = InlineKeyboardButton(text="7-9", callback_data="7-9")
    b4 = InlineKeyboardButton(text="10-11", callback_data="10-11")
    bw = InlineKeyboardButton(text="Не учусь в этой школе", callback_data="Не учусь в этой школе")
    return InlineKeyboardMarkup(inline_keyboard=[[b1, b2, b3, b4], [bw]])


def get_keyboard2() -> InlineKeyboardMarkup:
    a1 = InlineKeyboardButton(text="Удалить", callback_data="delete")
    a2 = InlineKeyboardButton(text="Отправить", callback_data="accept")
    return InlineKeyboardMarkup(inline_keyboard=[[a1, a2]])


def get_keyboard3() -> InlineKeyboardMarkup:
    c1 = InlineKeyboardButton(
        text="Математика/физика/информатика",
        callback_data="Математика/физика/информатика",
    )
    c2 = InlineKeyboardButton(
        text="Русский/ин.яз/литература",
        callback_data="Русский/ин.яз/литература",
    )
    c3 = InlineKeyboardButton(text="Химия/биология", callback_data="Химия/биология")
    c4 = InlineKeyboardButton(
        text="История/обществознание",
        callback_data="История/обществознание",
    )
    c5 = InlineKeyboardButton(text="География", callback_data="География")
    return InlineKeyboardMarkup(inline_keyboard=[[c1], [c2], [c3], [c4], [c5]])


def get_keyboard4() -> InlineKeyboardMarkup:
    d1 = InlineKeyboardButton(text="Школа №50", callback_data="Школа №50")
    d2 = InlineKeyboardButton(text='Лицей "Дельта"', callback_data='Лицей "Дельта"')
    dw = InlineKeyboardButton(text="Не из Дельты и 50-й", callback_data="Не из Дельты и 50-й")
    return InlineKeyboardMarkup(inline_keyboard=[[d1, d2], [dw]])


def get_keyboard5() -> InlineKeyboardMarkup:
    e1 = InlineKeyboardButton(text="Пропустить", callback_data="skip")
    e2 = InlineKeyboardButton(text="Отправить фото", callback_data="send_photo")
    return InlineKeyboardMarkup(inline_keyboard=[[e1, e2]])


def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
   return ReplyKeyboardMarkup(
       keyboard=[
           [KeyboardButton(text=BTN_MENU)],
           [KeyboardButton(text=BTN_FORM), KeyboardButton(text=BTN_PROFILE)],
           [KeyboardButton(text=BTN_SEARCH), KeyboardButton(text=BTN_SUPPORT)],
           [KeyboardButton(text=BTN_HELP)],
       ],
       resize_keyboard=True,
       input_field_placeholder="Выберите действие",
   )


async def send_form_step_prompt(message: Message, state_name: str) -> None:
   if state_name == Form.Name.state:
       await message.answer("Продолжаем заполнение анкеты.\nШаг 1/7: как тебя зовут?")
       return

   if state_name == Form.School.state:
       await message.answer("Продолжаем заполнение анкеты.\nШаг 2/7: из какой ты школы?", reply_markup=get_keyboard4())
       return

   if state_name == Form.Grade.state:
       await message.answer("Продолжаем заполнение анкеты.\nШаг 3/7: в каком ты классе?", reply_markup=get_keyboard1())
       return

   if state_name == Form.Subjects.state:
       await message.answer(
           "Продолжаем заполнение анкеты.\nШаг 4/7: какой набор предметов тебе ближе?",
           reply_markup=get_keyboard3(),
       )
       return

   if state_name == Form.Description.state:
       await message.answer("Продолжаем заполнение анкеты.\nШаг 5/7: расскажи что-нибудь о себе.")
       return

   if state_name == Form.Contact.state:
       await message.answer("Продолжаем заполнение анкеты.\nШаг 6/7: напиши номер/юз для связи.")
       return

   if state_name == Form.Photo.state:
       await message.answer(
           "Продолжаем заполнение анкеты.\nШаг 7/7: отправь фото или нажми «Пропустить».",
           reply_markup=get_keyboard5(),
       )
       return

   await message.answer("Продолжаем заполнение анкеты.")


def user_is_busy(user_id: int) -> bool:
   return user_id in active_users


def mark_user_busy(user_id: int) -> None:
   active_users.add(user_id)


def mark_user_free(user_id: int) -> None:
   active_users.discard(user_id)


def build_profile_text(data: dict, user_id: int) -> str:
   name = str(data.get("Name", "")).strip()
   school = str(data.get("School", "")).strip()
   grade = str(data.get("Grade", "")).strip()
   subjects = str(data.get("Subjects", "")).strip()
   description = str(data.get("Description", "")).strip()
   contact = str(data.get("Contact", "")).strip()

   return (
      "Ваша анкета будет выглядеть так:\n\n"
      f"Имя: {name}\n"
      "--------------------------\n"
      f"Школа: {school}\n"
      f"Класс: {grade}\n"
      f"Любимые предметы: {subjects}\n"
      f"Информация о себе: {description}\n"
      f'Контакт: <span class="tg-spoiler">{contact}</span>\n'
      "--------------------------\n"
      f"ID: {user_id}"
   )


def blob_to_bytes(photo_blob: Any) -> bytes | None:
   if isinstance(photo_blob, memoryview):
       return photo_blob.tobytes()
   if isinstance(photo_blob, (bytes, bytearray)):
       return bytes(photo_blob)
   return None


async def show_my_profile_and_ask_decision(message: Message, state: FSMContext) -> None:
   user_id = message.from_user.id
   current_state = await state.get_state()

   if current_state in FORM_STATES:
       paused_form_drafts[user_id] = {
           "state": current_state,
           "data": await state.get_data(),
       }
       await state.clear()
       await message.answer(
           "Поставил заполнение анкеты на паузу и сохранил введённые данные.\n"
           "Сейчас покажу твою текущую анкету."
       )
   elif current_state == Sup.Ans:
       await state.clear()
       mark_user_free(user_id)
       await message.answer("Диалог поддержки поставил на паузу. Сейчас покажу твою анкету.")

   cursor.execute(
      "SELECT id, name, school, grade, subjects, description, contact, photo FROM Users WHERE owner_tg_id = ?",
      (user_id,),
   )
   row = cursor.fetchone()

   if row is None:
      await message.answer(
         "У тебя пока нет сохранённой анкеты.\n"
         f"Нажми {BTN_FORM}, чтобы создать её."
      )
      return

   profile_text = (
     f"Имя: {row[1]}\n"
     "--------------------------\n"
     f"Школа: {row[2]}\n"
     f"Класс: {row[3]}\n"
     f"Любимые предметы: {row[4]}\n"
     f"Информация о себе: {row[5]}\n"
     f'Контакт: <span class="tg-spoiler">{row[6]}</span>\n'
     "--------------------------\n"
     f"ID анкеты: {row[0]}"
   )

   photo_bytes = blob_to_bytes(row[7])
   if photo_bytes:
      caption = profile_text if len(profile_text) <= 1000 else f"{profile_text[:997]}..."
      photo = BufferedInputFile(photo_bytes, filename=f"my_profile_{row[0]}.jpg")
      await message.answer_photo(photo=photo, caption=caption, parse_mode="HTML")
   else:
      await message.answer(text=profile_text, parse_mode="HTML")

   await message.answer(
     "Что делаем дальше?\n"
     "1 - Подтвердить и оставить как есть\n"
     "2 - Изменить анкету"
   )
   await state.set_state(Profile.Decision)


async def send_form_preview(message: Message, state: FSMContext, photo_bytes: bytes | None) -> None:
  data = await state.get_data()
  text = build_profile_text(data, message.from_user.id)

  if photo_bytes:
      # Telegram ограничивает размер caption, поэтому аккуратно режем длинные анкеты.
      caption = text if len(text) <= 1000 else f"{text[:997]}..."
      preview = BufferedInputFile(photo_bytes, filename=f"profile_{message.from_user.id}.jpg")
      await message.answer_photo(photo=preview, caption=caption, parse_mode="HTML", reply_markup=get_keyboard2())
      return

  await message.answer(text=text, parse_mode="HTML", reply_markup=get_keyboard2())


@dp.message(CommandStart())
async def cmd_start(message: types.Message) -> None:
  display_name = f"@{message.from_user.username}" if message.from_user.username else message.from_user.full_name
  await message.answer(
     text=(
         f"Привет, {display_name}!\n\n"
         "🤖 Это бот для знакомств среди школьников.\n"
         "Здесь ты можешь создать анкету, найти новых людей и из других школ, и написать в поддержку.\n"
         "Ниже — меню действий."
     )
  )
  await message.answer("\U0001F447 Меню команд:", reply_markup=get_main_menu_keyboard())


@dp.message(F.text == BTN_MENU)
async def menu_message(message: Message) -> None:
  await message.answer("\U0001F447 Открыл меню команд:", reply_markup=get_main_menu_keyboard())


@dp.message(Command("help"))
async def cmd_help(message: types.Message) -> None:
    await message.reply(text=HELP_COMMAND, reply_markup=get_main_menu_keyboard())

@dp.message(F.text == BTN_HELP)
async def help_button(message: Message) -> None:
    await cmd_help(message)

@dp.message(F.text == BTN_FORM)
async def form_button(message: Message, state: FSMContext) -> None:
    await cmd_form(message, state)

@dp.message(F.text == BTN_SEARCH)
async def search_button(message: Message) -> None:
    await search_command(message)

@dp.message(F.text == BTN_SUPPORT)
async def support_button(message: Message, state: FSMContext) -> None:
    await support_command(message, state)

@dp.message(F.text == BTN_PROFILE)
async def profile_button(message: Message, state: FSMContext) -> None:
    await show_my_profile_and_ask_decision(message, state)

@dp.message(Command("profile"))
async def profile_command(message: Message, state: FSMContext) -> None:
    await show_my_profile_and_ask_decision(message, state)

@dp.message(Profile.Decision, F.text.in_(("1", "2")))
async def process_profile_decision(message: Message, state: FSMContext) -> None:
    user_id = message.from_user.id
    choice = message.text.strip()

    await state.clear()

    if choice == "1":
        await message.answer("Ок, оставил анкету без изменений.")
        if user_id in paused_form_drafts:
            await message.answer(
                f"Черновик анкеты сохранён. Нажми {BTN_FORM}, и продолжим заполнение с места паузы."
            )
        return

    paused_draft = paused_form_drafts.pop(user_id, None)
    if paused_draft:
        await state.set_data(paused_draft.get("data", {}))
        await state.set_state(paused_draft["state"])
        await message.answer("Отлично, обновляем анкету. Возвращаю тебя к месту, где остановились.")
        await send_form_step_prompt(message, paused_draft["state"])
        return

    mark_user_busy(user_id)
    await message.answer("Отлично, обновляем анкету. Начинаем с первого шага.")
    await message.answer("Как тебя зовут?")
    await state.set_state(Form.Name)

@dp.message(Profile.Decision)
async def process_profile_decision_fallback(message: Message) -> None:
    await message.answer(
        "Напиши цифру:\n"
        "1 - подтвердить текущую анкету\n"
        "2 - обновить анкету"
    )

@dp.message(Command(commands="users"))
async def users_list_command(message: Message) -> None:
    if message.from_user.full_name == "Матвей Хазиев":
        cursor.execute("SELECT * FROM Users")
        users = cursor.fetchall()
        await message.answer(str(users))

@dp.message(Command(commands="zhalobi"))
async def watch_supports(message: Message) -> None:
    if message.from_user.full_name == "Матвей Хазиев":
        cursor2.execute("SELECT * FROM Support")
        supports = cursor2.fetchall()
        await message.answer(str(supports))

# --- Обработчик команды /user <id> ---
@dp.message(F.text.startswith("/user "))
async def cmd_view_user(message: Message):
    """
    Команда /user <id>.
    Пример использования: /user 3
    """
    if message.from_user.full_name == "Матвей Хазиев":
    # 1. Достаем текст сообщения
        full_text = message.text
    
    # 2. Находим позицию первого пробела после команды
    # Это нужно, чтобы отделить команду от самого ID
        space_pos = full_text.find(' ')
    
    # Если пробела нет (например, пользователь написал просто "/user"), выдаем ошибку
        if space_pos == -1:
            await message.answer("Укажи ID пользователя. Пример: /user 3")
            return

    # 3. Вырезаем из текста только ту часть, которая идет после пробела (это и есть наш ID)
        user_input = full_text[space_pos + 1:] 

    # 4. Проверяем, является ли ID числом
        if not user_input.isdigit():
            await message.answer("Ошибка: ID должен быть числом.")
            return

        user_id_to_find = int(user_input)

    # --- Запрос к базе данных (остался без изменений) ---
        cursor.execute("""
            SELECT id, name, school, grade, subjects, description, contact, photo 
            FROM Users 
            WHERE id = ?
            LIMIT 1
        """, (user_id_to_find,))

        user_data = cursor.fetchone()

        if user_data:
            '''
            profile_text = (
                f"🆔 *ID в базе:* {user_data[0]}\n"
                f"📛 *Имя:* {user_data[1]}\n"
                f"🏫 *Школа:* {user_data[2]}\n"
                f"🎒 *Класс:* {user_data[3]}\n"
                f"📚 *Предметы:* {user_data[4]}\n"
                f"📝 *О себе:* {user_data[5]}\n"
                f"📞 *Контакт:* ||{user_data[6]}||\n"
            )   
            await message.answer(profile_text, parse_mode="Markdown")
            '''
            profile_text = (
                f"Имя: {user_data[1]}\n"
                "--------------------------\n"
                f"Школа: {user_data[2]}\n"
                f"Класс: {user_data[3]}\n"
                f"Любимые предметы: {user_data[4]}\n"
                f"Информация о себе: {user_data[5]}\n"
                f'Контакт: <span class="tg-spoiler">{user_data[6]}</span>\n'
                "--------------------------\n"
                f"ID анкеты: {user_data[0]}"
                )

            photo_bytes = blob_to_bytes(user_data[7])
            if photo_bytes:
                caption = profile_text if len(profile_text) <= 1000 else f"{profile_text[:997]}..."
                photo = BufferedInputFile(photo_bytes, filename=f"my_profile_{user_data[0]}.jpg")
                await message.answer_photo(photo=photo, caption=caption, parse_mode="HTML")
            else:
                await message.answer(text=profile_text, parse_mode="HTML")
        else:
            await message.answer(f"Пользователя с ID {user_id_to_find} не найдено в базе.")

@dp.message(F.text.startswith("/delete "))
async def cmd_delete_user(message: Message):
    """
    Команда /delete <id>.
    Пример использования: /delete 1
    """
    if message.from_user.full_name == "Матвей Хазиев":
        full_text = message.text
        space_pos = full_text.find(' ')

    # Проверка на наличие пробела и ID
        if space_pos == -1:
            await message.answer("Укажи ID пользователя для удаления. Пример: /delete 1")
            return

        user_input = full_text[space_pos + 1:]

        if not user_input.isdigit():
            await message.answer("Ошибка: ID должен быть числом.")
            return

        user_id_to_delete = int(user_input)

    # --- Запрос к базе данных на удаление ---
        cursor.execute("""
            DELETE FROM Users 
            WHERE id = ?
        """, (user_id_to_delete,))
    
    # Сохраняем изменения в базе данных
        connection.commit()

    # Проверяем, была ли строка действительно удалена
        if cursor.rowcount > 0:
            await message.answer(f"Пользователь с ID {user_id_to_delete} успешно удален.", parse_mode="Markdown")
        else:
            await message.answer(f"Пользователя с ID {user_id_to_delete} не найдено.", parse_mode="Markdown")

@dp.message(Command("form"))
async def cmd_form(message: Message, state: FSMContext) -> None:
    user_id = message.from_user.id
    current_state = await state.get_state()

    if current_state in FORM_STATES:
        await message.answer("Нашёл твою незавершённую анкету. Продолжаем с того же места.")
        await send_form_step_prompt(message, current_state)
        return

    paused_draft = paused_form_drafts.pop(user_id, None)
    if paused_draft:
        await state.set_data(paused_draft.get("data", {}))
        await state.set_state(paused_draft["state"])
        await message.answer("Вернул твою анкету из паузы. Продолжаем сбор данных.")
        await send_form_step_prompt(message, paused_draft["state"])
        return

    mark_user_busy(user_id)
    await state.clear()
    await message.answer("Начинаем новую анкету.")
    await message.answer(text="Как тебя зовут?")
    await state.set_state(Form.Name)

@dp.message(Form.Name, F.text)
async def process_name(message: Message, state: FSMContext) -> None:
    await state.update_data(Name=message.text.strip())
    await message.answer("Из какой ты школы?", reply_markup=get_keyboard4())
    await state.set_state(Form.School)

@dp.message(Form.Name)
async def process_name_fallback(message: Message) -> None:
    await message.answer("Напиши имя текстом, пожалуйста.")

@dp.callback_query(Form.School, F.data.in_(SCHOOL_OPTIONS))
async def process_school(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.update_data(School=callback.data)
    await callback.message.answer(text="В каком ты классе?", reply_markup=get_keyboard1())
    await state.set_state(Form.Grade)

@dp.callback_query(Form.Grade, F.data.in_(GRADE_OPTIONS))
async def process_grade(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.update_data(Grade=callback.data)
    await callback.message.answer(
        text="Какой набор предметов тебе больше всего нравится?",
        reply_markup=get_keyboard3(),
    )
    await state.set_state(Form.Subjects)

@dp.callback_query(Form.Subjects, F.data.in_(SUBJECT_OPTIONS))
async def process_subjects(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.update_data(Subjects=callback.data)
    await callback.message.answer(text="Расскажи что-нибудь о себе")
    await state.set_state(Form.Description)

@dp.message(Form.Description, F.text)
async def process_description(message: Message, state: FSMContext) -> None:
    await state.update_data(Description=message.text.strip())
    await message.answer("Напиши номер/юз, чтобы можно было связаться с тобой")
    await state.set_state(Form.Contact)

@dp.message(Form.Contact, F.text)
async def process_contact(message: Message, state: FSMContext) -> None:
    await state.update_data(Contact=message.text.strip())
    await message.answer("Можно прикрепить к анкете фото", reply_markup=get_keyboard5())
    await state.set_state(Form.Photo)

@dp.message(Form.Description)
async def process_description_fallback(message: Message) -> None:
    await message.answer("Опиши себя текстом, пожалуйста.")

@dp.message(Form.Contact)
async def process_contact_fallback(message: Message) -> None:
    await message.answer("Отправь контакт текстом: номер телефона или @username.")

@dp.callback_query(Form.Photo, F.data == "send_photo")
async def ask_photo(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.answer(text="Отправь фото")

@dp.callback_query(Form.Photo, F.data == "skip")
async def skip_photo(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.update_data(PhotoBytes=None)
    await send_form_preview(callback.message, state, None)

@dp.message(Form.Photo, F.photo)
async def process_photo(message: Message, state: FSMContext) -> None:
    photo = message.photo[-1]
    tg_bot = message.bot
    file_info = await tg_bot.get_file(photo.file_id)
    buffer = BytesIO()
    await tg_bot.download_file(file_info.file_path, destination=buffer)
    photo_bytes = buffer.getvalue()

    await state.update_data(PhotoBytes=photo_bytes)
    await send_form_preview(message, state, photo_bytes)

@dp.message(Form.Photo)
async def process_photo_fallback(message: Message) -> None:
    await message.answer("Пришли фото как изображение или нажми «Пропустить».")

@dp.callback_query(F.data == "accept")
async def accept_form(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    
    if not data:
        await callback.answer("Нет данных анкеты", show_alert=True)
        return

    # Получаем данные из состояния
    name = str(data.get("Name", "")).strip()
    school = str(data.get("School", "")).strip()
    grade = str(data.get("Grade", "")).strip()
    subjects = str(data.get("Subjects", "")).strip()
    description = str(data.get("Description", "")).strip()
    contact = str(data.get("Contact", "")).strip()
    photo_bytes = data.get("PhotoBytes")
    
    owner_tg_id = callback.from_user.id

    # --- НАЧАЛО ИЗМЕНЕННОЙ ЛОГИКИ ---
    
    # 1. Ищем, есть ли у этого пользователя (owner_tg_id) уже анкета?
    cursor.execute("SELECT id, photo FROM Users WHERE owner_tg_id = ?", (owner_tg_id,))
    existing_profile = cursor.fetchone()

    if existing_profile:
        # Если анкета ЕСТЬ, мы будем делать UPDATE (обновление)

        # Проверяем фото. Если в новой анкете фото нет (None), 
        # то мы сохраняем старое фото из базы, чтобы оно не пропало.
        if photo_bytes is None:
            old_photo = existing_profile[1]
            if old_photo is not None:
                # Приводим старое фото к нужному формату (bytes)
                if isinstance(old_photo, memoryview):
                    photo_bytes = old_photo.tobytes()
                elif isinstance(old_photo, (bytes, bytearray)):
                    photo_bytes = bytes(old_photo)

        # Выполняем команду UPDATE
        cursor.execute(
            """
            UPDATE Users 
            SET name = ?, school = ?, grade = ?, subjects = ?, description = ?, contact = ?, photo = ? 
            WHERE owner_tg_id = ?
            """,
            (name, school, grade, subjects, description, contact, photo_bytes, owner_tg_id),
        )
        save_result_text = "Анкета обновлена"

    else:
        # Если анкеты НЕТ, мы делаем INSERT (создание новой)
        cursor.execute(
            """
            INSERT INTO Users (owner_tg_id, name, school, grade, subjects, description, contact, photo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (owner_tg_id, name, school, grade, subjects, description, contact, photo_bytes),
        )
        save_result_text = "Анкета сохранена"

    # --- КОНЕЦ ИЗМЕНЕННОЙ ЛОГИКИ ---

    connection.commit()

    user_grade_cache[callback.from_user.id] = grade
    await state.clear()
    mark_user_free(callback.from_user.id)
    paused_form_drafts.pop(callback.from_user.id, None)

    await callback.answer(save_result_text)
    await callback.message.delete()
    await callback.message.answer("Теперь ваша анкета в общем доступе!")

@dp.callback_query(F.data == "delete")
async def delete_form(callback: CallbackQuery, state: FSMContext) -> None:
     # Исправлено сообщение на русском без HTML и эмодзи
     await callback.answer("Анкета удалена")
     # Исправлено сообщение на русском без HTML и эмодзи
     await callback.message.delete()
     # Исправлено сообщение на русском без HTML и эмодзи
     await callback.message.answer(
         "Вы удалили анкету!"
     )
     # Очистка состояния и снятие метки занятости происходит выше в коде

@dp.message(Command("search"))
async def search_command(message: Message) -> None:
     cursor.execute(
         "SELECT id, name, school, grade, subjects, description, contact, photo FROM Users ORDER BY RANDOM() LIMIT 1"
     )
     random_user = cursor.fetchone()
     if random_user is None:
         # Исправлено сообщение на русском без HTML и эмодзи
         await message.answer(
             "Пока нет анкет для поиска."
         )
         return

     profile_text = (
         f"Имя: {random_user[1]}\n"
         "--------------------------\n"
         f"Школа: {random_user[2]}\n"
         f"Класс: {random_user[3]}\n"
         f"Любимые предметы: {random_user[4]}\n"
         f"Информация о себе: {random_user[5]}\n"
         f'Контакт: <span class="tg-spoiler">{random_user[6]}</span>\n'  # Использован Markdown для скрытия текста в Telegram
         "--------------------------\n"
         f"ID: {random_user[0]}"
     )

     photo_blob = random_user[7]
     photo_bytes: bytes | None = None
     if isinstance(photo_blob, memoryview):
         photo_bytes = photo_blob.tobytes()
     elif isinstance(photo_blob, (bytes, bytearray)):
         photo_bytes = bytes(photo_blob)

     if photo_bytes:
         profile_image = BufferedInputFile(photo_bytes, filename=f"search_{random_user[0]}.jpg")
         # Убран parse_mode="HTML" для корректного отображения русских букв и Markdown-разметки || ||
         await message.answer_photo(photo=profile_image, caption=profile_text, parse_mode="HTML")
     else:
         # Убран parse_mode="HTML" для корректного отображения русских букв и Markdown-разметки || ||
         await message.answer(text=profile_text, parse_mode="HTML")
     '''
     current_user_grade = user_grade_cache.get(message.from_user.id)
     if current_user_grade and current_user_grade == random_user[3]:
         # Исправлено сообщение на русском без HTML и эмодзи
         await message.answer(
             text="Класс совпадает"
         ) '''

@dp.message(Command("support"))
async def support_command(message: Message, state: FSMContext) -> None:
    user_id = message.from_user.id

    current_state = await state.get_state()
    if current_state in FORM_STATES:
        paused_form_drafts[user_id] = {
            "state": current_state,
            "data": await state.get_data(),
        }
        await state.clear()
        await message.answer(
            "Поставил анкету на паузу и сохранил введённые данные.\n"
            "Опиши проблему, а потом вернись в 📝 Анкета и продолжим."
        )
    elif current_state == Sup.Ans:
        await message.answer("Жду текст обращения в поддержку.")
        return
    else:
        await message.answer(text="Напишите проблему")

    mark_user_busy(user_id)
    await state.set_state(Sup.Ans)


@dp.message(Sup.Ans, F.text)
async def process_support(message: Message, state: FSMContext) -> None:
    support_text = message.text.strip()
    cursor2.execute("INSERT INTO Support (text) VALUES (?)", (support_text,))
    connection2.commit()

    await state.clear()
    mark_user_free(message.from_user.id)
    if message.from_user.id in paused_form_drafts:
        await message.answer(
            "Жалоба принята, мы её рассмотрим в ближайшее время.\n"
            "Твоя анкета сохранена. Нажми 📝 Анкета, и я продолжу заполнение с места паузы."
        )
    else:
        await message.answer(text="Жалоба принята, мы её рассмотрим в ближайшее время и попытаемся исправиться")


@dp.message(Sup.Ans)
async def process_support_fallback(message: Message) -> None:
    await message.answer("Опиши проблему текстом, чтобы я передал её в поддержку.")


@dp.message()
async def handle_any_message(message: Message, state: FSMContext) -> None:
    current_state = await state.get_state()
    if current_state:
        await message.answer(
            "ℹ️ Я получил сообщение.\n"
            "Заверши текущий шаг формы или отправь данные в нужном формате."
        )
        return

    await message.answer(
        "ℹ️ Используй кнопки меню ниже или нажми "
        f"{BTN_MENU}."
    )


async def main() -> None:
    reconnect_delay = 5
    max_reconnect_delay = 60

    if proxy_url:
        logging.info("Telegram proxy enabled: %s", proxy_url)
    else:
        logging.info("Telegram proxy disabled: direct connection")

    try:
        while True:
            try:
                await dp.start_polling(
                    bot,
                    allowed_updates=dp.resolve_used_update_types(),
                    close_bot_session=False,
                )
                return
            except TelegramNetworkError as error:
                logging.warning(
                    "Network error while polling: %s. Retry in %s sec.",
                    error,
                    reconnect_delay,
                )
            except Exception:
                logging.exception(
                    "Unexpected polling error. Retry in %s sec.",
                    reconnect_delay,
                )

            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(main())