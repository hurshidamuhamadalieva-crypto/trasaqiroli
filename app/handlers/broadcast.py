"""
E'lon yuborish — doimiy (reply) menyu tugmalari orqali.

Tugmalar:
  📝 Yuboriladigan matnni kiritish     → matn yoki rasm+matn shablonini saqlaydi
  ⏰ Yuborish vaqtini kiritish va boshlash → inline interval → darhol yuborishni boshlaydi
  ⏹ Yuborishni to'xtatish              → yuborishni to'xtatadi
  🔄 Yuborishni qayta boshlash          → oxirgi e'lon va oxirgi interval bilan darhol qayta boshlaydi

Yuborish foydalanuvchining ulangan hisobi orqali, "Bot uchun" jildidagi
guruhlarga (har siklda jonli o'qiladi) amalga oshadi.
"""
import logging
import os
import time

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from app.database import (
    get_or_create_user, get_or_create_settings, update_settings,
    get_active_advertisement, save_advertisement,
)
from app.keyboards import kb_interval, kb_main_menu_reply
from app.states import BroadcastFlow
from app.services import sender_service
from config import config

router = Router()
logger = logging.getLogger(__name__)

BTN_TEXT = "📝 Yuboriladigan matnni kiritish"
BTN_TIME = "⏰ Yuborish vaqtini kiritish va boshlash"
BTN_STOP = "⏹ Yuborishni to'xtatish"
BTN_RESTART = "🔄 Yuborishni qayta boshlash"


def _check_active(user) -> bool:
    return bool(user and user.is_active and not user.is_banned)


async def _guard(message: Message, state: FSMContext = None):
    """Faol obuna + ulangan sessiya tekshiruvi. Muvaffaqiyatli bo'lsa user qaytaradi."""
    user = await get_or_create_user(message.from_user.id)
    if not _check_active(user):
        await message.answer("❌ Bu funksiya uchun faol obuna kerak. /start ni bosing.")
        return None
    if not user.session_string:
        from app.keyboards import kb_reconnect
        await message.answer(
            "⚠️ Telegram hisobingiz ulanmagan. Iltimos, avval hisobni ulang:",
            reply_markup=kb_reconnect()
        )
        return None
    return user


# ─── 1) Matn / rasm shablonini kiritish ───────────────────────────────────────

@router.message(F.text == BTN_TEXT)
async def btn_enter_text(message: Message, state: FSMContext):
    user = await _guard(message, state)
    if not user:
        return
    await state.set_state(BroadcastFlow.waiting_text)
    await message.answer(
        "✏️ <b>Yubormoqchi bo'lgan xabar matnini yoki matn bilan rasmni kiriting.</b>\n\n"
        "• Faqat matn yuborsangiz — matnli shablon saqlanadi\n"
        "• Rasm + izoh (matn) yuborsangiz — rasmli shablon saqlanadi",
        parse_mode="HTML",
        reply_markup=kb_main_menu_reply()
    )


async def _save_template(message: Message, state: FSMContext, text: str, photo_path: str = None):
    user = await get_or_create_user(message.from_user.id)
    was_sending = sender_service.is_sending(user.id)
    await save_advertisement(user.id, text, photo_path=photo_path)
    await state.clear()
    suffix = " (rasm bilan)" if photo_path else ""
    note = "\n\n🔄 Yuborilayotgan e'lon keyingi siklda yangi shablonga almashadi." if was_sending else ""
    await message.answer(
        f"✅ <b>Shablon saqlandi!</b>{suffix}{note}",
        parse_mode="HTML",
        reply_markup=kb_main_menu_reply()
    )


@router.message(BroadcastFlow.waiting_text, F.photo)
async def receive_photo_template(message: Message, state: FSMContext):
    user = await get_or_create_user(message.from_user.id)
    photo = message.photo[-1]
    path = os.path.join(config.AD_PHOTOS_DIR, f"{user.id}_{int(time.time())}.jpg")
    try:
        # Rasm Bot API orqali yuklab olinib diskka saqlanadi — chunki e'lon
        # foydalanuvchi hisobi (Telethon) orqali yuboriladi va Telethon
        # Bot API file_id'sini ishlata olmaydi.
        await message.bot.download(photo, destination=path)
    except Exception as e:
        logger.error(f"Rasmni yuklab olishda xato: {e}")
        await message.answer("❌ Rasmni saqlab bo'lmadi, qayta urinib ko'ring.", reply_markup=kb_main_menu_reply())
        return

    # Eski rasm faylini tozalaymiz (disk to'lib ketmasligi uchun)
    old_ad = await get_active_advertisement(user.id)
    if old_ad and old_ad.photo_path and old_ad.photo_path != path:
        try:
            os.remove(old_ad.photo_path)
        except OSError:
            pass

    caption = (message.caption or "").strip()
    await _save_template(message, state, caption, photo_path=path)


@router.message(BroadcastFlow.waiting_text, F.text)
async def receive_text_template(message: Message, state: FSMContext):
    # Menyu tugmalari matn sifatida shablonga tushib ketmasligi uchun
    if message.text in (BTN_TEXT, BTN_TIME, BTN_STOP, BTN_RESTART):
        await state.clear()
        return await _dispatch_menu_button(message, state)

    user = await get_or_create_user(message.from_user.id)
    old_ad = await get_active_advertisement(user.id)
    if old_ad and old_ad.photo_path:
        try:
            os.remove(old_ad.photo_path)
        except OSError:
            pass
    await _save_template(message, state, message.text, photo_path=None)


async def _dispatch_menu_button(message: Message, state: FSMContext):
    t = message.text
    if t == BTN_TEXT:
        return await btn_enter_text(message, state)
    if t == BTN_TIME:
        return await btn_choose_time(message, state)
    if t == BTN_STOP:
        return await btn_stop(message, state)
    if t == BTN_RESTART:
        return await btn_restart(message, state)


# ─── 2) Vaqtni tanlash va boshlash ────────────────────────────────────────────

@router.message(F.text == BTN_TIME)
async def btn_choose_time(message: Message, state: FSMContext):
    await state.clear()
    user = await _guard(message, state)
    if not user:
        return
    ad = await get_active_advertisement(user.id)
    if not ad:
        await message.answer(
            "❌ Avval yuboriladigan matnni kiriting: <b>📝 Yuboriladigan matnni kiritish</b> tugmasini bosing.",
            parse_mode="HTML",
            reply_markup=kb_main_menu_reply()
        )
        return
    await message.answer(
        "⏰ <b>Vaqtni tanlang (minutlarda):</b>\n\nE'lon necha daqiqada bir marta yuborilsin?",
        parse_mode="HTML",
        reply_markup=kb_interval()
    )


@router.callback_query(F.data.startswith("bc_interval:"))
async def cb_choose_interval(call: CallbackQuery, state: FSMContext):
    minutes = int(call.data.split(":")[1])
    user = await get_or_create_user(call.from_user.id)
    if not _check_active(user) or not user.session_string:
        await call.answer("❌ Avval hisobingiz ulangan va obuna faol bo'lishi kerak.", show_alert=True)
        return
    ad = await get_active_advertisement(user.id)
    if not ad:
        await call.answer("❌ Avval matnni kiriting.", show_alert=True)
        return

    # Agar allaqachon yuborilayotgan bo'lsa — avval to'xtatib, yangi interval bilan qayta boshlaymiz
    if sender_service.is_sending(user.id):
        await sender_service.stop_sending(user.id)

    await update_settings(user.id, interval_minutes=minutes)
    await sender_service.start_sending(call.bot, user.id, call.from_user.id, user.session_string)

    await call.message.edit_text(
        f"✅ <b>Vaqt tanlandi: {minutes} daqiqa</b>\n\n🚀 E'lon yuborish boshlandi!",
        parse_mode="HTML"
    )
    await call.answer("🚀 Yuborish boshlandi!")


@router.callback_query(F.data == "bc_cancel_interval")
async def cb_cancel_interval(call: CallbackQuery, state: FSMContext):
    try:
        await call.message.edit_text("❌ Bekor qilindi.")
    except Exception:
        pass
    await call.answer()


# ─── 3) To'xtatish ────────────────────────────────────────────────────────────

@router.message(F.text == BTN_STOP)
async def btn_stop(message: Message, state: FSMContext):
    await state.clear()
    user = await get_or_create_user(message.from_user.id)
    if not _check_active(user):
        await message.answer("❌ Faol obuna yo'q. /start ni bosing.")
        return

    if not sender_service.is_sending(user.id):
        # Baribir holatni tozalab qo'yamiz (nomuvofiqlik bo'lsa)
        await update_settings(user.id, is_sending=False, sending_paused=False)
        await message.answer("ℹ️ Hozir yuborish yoqilmagan.", reply_markup=kb_main_menu_reply())
        return

    await sender_service.stop_sending(user.id)
    settings = await get_or_create_settings(user.id)
    await message.answer(
        f"⏹ <b>Yuborish to'xtatildi.</b>\n\n📊 Jami yuborilgan xabarlar: <b>{settings.messages_sent}</b>",
        parse_mode="HTML",
        reply_markup=kb_main_menu_reply()
    )


# ─── 4) Qayta boshlash ────────────────────────────────────────────────────────

@router.message(F.text == BTN_RESTART)
async def btn_restart(message: Message, state: FSMContext):
    await state.clear()
    user = await _guard(message, state)
    if not user:
        return
    ad = await get_active_advertisement(user.id)
    if not ad:
        await message.answer(
            "❌ Saqlangan e'lon topilmadi. Avval <b>📝 Yuboriladigan matnni kiritish</b> tugmasini bosing.",
            parse_mode="HTML",
            reply_markup=kb_main_menu_reply()
        )
        return

    if sender_service.is_sending(user.id):
        await message.answer("ℹ️ Yuborish allaqachon davom etmoqda.", reply_markup=kb_main_menu_reply())
        return

    settings = await get_or_create_settings(user.id)
    minutes = settings.interval_minutes or 10
    await sender_service.start_sending(message.bot, user.id, message.from_user.id, user.session_string)
    await message.answer(
        f"🚀 <b>Yuborish qayta boshlandi!</b>\n\n⏱ Interval: <b>{minutes} daqiqa</b> (oxirgi tanlangan)",
        parse_mode="HTML",
        reply_markup=kb_main_menu_reply()
    )
