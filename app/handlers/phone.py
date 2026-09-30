import asyncio
import logging
import re
import time
from datetime import datetime

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from app.database import get_or_create_user, update_user
from app.keyboards import kb_share_phone, kb_cancel_inline, kb_main_menu_reply, kb_onboarding_connect, remove_kb
from app.states import PhoneFlow
from app.services import telethon_service
from config import config

router = Router()
logger = logging.getLogger(__name__)

# user_tg_id -> {client, phone, phone_code_hash, created_at}
# MUHIM: "created_at" — foydalanuvchi jarayonni tashlab ketsa (bekor qilmasdan),
# bu yerda "osilib qolgan" Telethon ulanishi cheksiz ochiq turib qolmasligi
# uchun. Vaqti-vaqti bilan _cleanup_stale_logins() shularni tozalaydi.
_pending_logins = {}
PENDING_LOGIN_TTL = 600  # 10 daqiqa


def _check_active(user) -> bool:
    return user and user.is_active and not user.is_banned


async def _disconnect_pending(user_tg_id: int):
    pending = _pending_logins.pop(user_tg_id, None)
    if pending:
        try:
            await pending["client"].disconnect()
        except Exception:
            pass


async def cleanup_stale_logins():
    """
    Fon vazifasi: uzoq vaqt yakunlanmagan (bekor ham qilinmagan, tasdiqlanmagan
    ham) login urinishlarining Telethon ulanishini yopib, resurslarni bo'shatadi.
    Buni ishlatmasak, har bir yangi ulanish urinishi ochiq qoladigan
    ulanishlar to'planib boradi va vaqt o'tishi bilan (masalan, Railway'da
    bir necha kundan keyin) serverning ulanish/resurs limiti tugab, yangi
    foydalanuvchilarga tasdiqlash kodi umuman kelmay qo'yishi mumkin edi.
    """
    while True:
        try:
            now = time.time()
            stale = [
                uid for uid, p in list(_pending_logins.items())
                if now - p.get("created_at", now) > PENDING_LOGIN_TTL
            ]
            for uid in stale:
                logger.info(f"Eskirgan login urinishi tozalanmoqda: {uid}")
                await _disconnect_pending(uid)
        except Exception as e:
            logger.error(f"cleanup_stale_logins xatosi: {e}")
        await asyncio.sleep(120)


# ─── Hisobni ulash (to'lov tasdiqlangach yoki sessiya uzilgach avtomatik) ─────

@router.callback_query(F.data == "phone:agree")
async def cb_phone_agree(call: CallbackQuery, state: FSMContext):
    user = await get_or_create_user(call.from_user.id)
    if not _check_active(user):
        await call.answer("❌ Bu funksiyadan foydalanish uchun faol obuna kerak.", show_alert=True)
        return
    await state.set_state(PhoneFlow.entering_phone)
    await call.message.edit_text(
        "📱 <b>Telefon raqamingizni kiriting</b>\n\n"
        "Xalqaro formatda yuboring:\n"
        "<code>+998901234567</code>\n\n"
        "Yoki pastdagi tugma orqali kontaktingizni ulashing:",
        parse_mode="HTML"
    )
    await call.message.answer("👇 Kontakt ulashing yoki raqam kiriting:", reply_markup=kb_share_phone())
    await call.answer()


@router.callback_query(F.data == "phone:cancel")
async def cb_phone_cancel(call: CallbackQuery, state: FSMContext):
    await _disconnect_pending(call.from_user.id)
    await state.clear()
    try:
        await call.message.edit_text("❌ Bekor qilindi.")
    except Exception:
        pass
    await call.message.answer(
        "Hisobingizni ulash uchun quyidagi tugmani bosing:",
        reply_markup=kb_onboarding_connect()
    )
    await call.answer()


@router.message(PhoneFlow.entering_phone, F.text == "✏️ Qo'lda kiritish")
async def hint_manual_phone(message: Message, state: FSMContext):
    await message.answer(
        "✏️ Raqamingizni xalqaro formatda yozib yuboring:\n<code>+998901234567</code>",
        parse_mode="HTML"
    )


@router.message(PhoneFlow.entering_phone, F.contact)
async def receive_contact(message: Message, state: FSMContext):
    phone = message.contact.phone_number
    if not phone.startswith("+"):
        phone = "+" + phone
    await _process_phone(message, state, phone)


@router.message(PhoneFlow.entering_phone, F.text)
async def receive_phone_text(message: Message, state: FSMContext):
    text = message.text.strip()
    if text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("❌ Bekor qilindi.", reply_markup=remove_kb)
        await message.answer(
            "Hisobingizni ulash uchun quyidagi tugmani bosing:",
            reply_markup=kb_onboarding_connect()
        )
        return

    phone = re.sub(r"[^\d+]", "", text)
    if not phone.startswith("+"):
        phone = "+" + phone

    if len(phone) < 10:
        await message.answer(
            "❌ Noto'g'ri raqam. Xalqaro formatda kiriting:\n<code>+998901234567</code>",
            parse_mode="HTML"
        )
        return

    await _process_phone(message, state, phone)


async def _finish_onboarding(message: Message, loading_msg, user, phone: str, extra_line: str = ""):
    """
    Hisob muvaffaqiyatli ulangandan keyin asosiy (doimiy) menyuni ko'rsatadi.

    MUHIM: "Bot uchun" jildi BU YERDA DARHOL yaratilmaydi! Yangi ulangan
    hisobda, autentifikatsiyadan bir necha soniya o'tar-o'tmas yana bir
    Telegram so'rovi (hatto yengil bo'lsa ham) yuborish — Telegramning
    xavfsizlik tizimiga "avtomatlashtirilgan, shubhali harakat" signalini
    berib, hisobni chiqarib yuborishiga sabab bo'lgan edi (buni ilgari
    aynan shu loyihada amaliy kuzatuv orqali tasdiqlaganmiz). Shu sabab
    jild yaratish WARMUP_MINUTES daqiqa kechiktirilib, alohida fon
    vazifasida amalga oshiriladi — foydalanuvchi bu orada botdan bemalol
    foydalanaveradi, jild esa orqa fonda, hisobga "sezilmaydigan" tarzda
    tayyorlanadi.
    """
    await loading_msg.edit_text(
        "✅ <b>Hisob muvaffaqiyatli ulandi!</b>\n\n"
        f"📱 Raqam: <code>{phone}</code>" + extra_line +
        f"\n\n📁 <b>'Bot uchun'</b> jildi xavfsizlik uchun {config.WARMUP_MINUTES} daqiqadan "
        "so'ng avtomatik tayyorlanadi (yoki avvalgisi topiladi). Tayyor bo'lgach xabar beramiz.",
        parse_mode="HTML"
    )
    await message.answer(
        "📋 Asosiy menyu pastda 👇",
        reply_markup=kb_main_menu_reply()
    )
    asyncio.create_task(_delayed_create_folder(message.bot, user.id, message.from_user.id))


async def _delayed_create_folder(bot, user_db_id: int, user_tg_id: int):
    """WARMUP_MINUTES kutib, shundan keyingina 'Bot uchun' jildini yaratadi/topadi."""
    await asyncio.sleep(config.WARMUP_MINUTES * 60)
    try:
        from app.database import get_user_by_db_id
        user = await get_user_by_db_id(user_db_id)
        if not user or not user.session_string:
            return  # bu orada uzilib qolgan bo'lishi mumkin

        groups, created = await telethon_service.get_or_create_bot_folder(user_db_id, user.session_string)
        if created:
            text = (
                "📁 <b>'Bot uchun' jildi tayyor bo'ldi!</b>\n\n"
                "Telegram ilovangizni oching — Sozlamalar → Chat jildlari "
                "bo'limida (yoki suhbatlar ro'yxati tepasidagi yorliqlar orasida) "
                "<b>'Bot uchun'</b> nomli jildni ko'rasiz.\n\n"
                "Endi shu jildga e'lon yuboriladigan guruh yoki kanallarni qo'shing "
                "— bot ularni o'zi avtomatik taniydi. Kanal qo'shsangiz, hisobingiz "
                "o'sha kanalda <b>admin</b> bo'lishi kerak, aks holda bot unga yoza olmaydi."
            )
        else:
            text = (
                f"📁 <b>'Bot uchun' jildi topildi</b> ({len(groups)} ta guruh/kanal bilan).\n\n"
                "Yangi guruh yoki (admin bo'lgan) kanal qo'shsangiz, bot keyingi "
                "yuborish siklida o'zi avtomatik taniydi."
            )
        await bot.send_message(user_tg_id, text, parse_mode="HTML")
    except (telethon_service.SessionRevokedException, telethon_service.AccountBannedException):
        pass  # health-checker allaqachon xabar beradi
    except Exception as e:
        logger.error(f"_delayed_create_folder xatosi ({user_db_id}): {e}")



async def _process_phone(message: Message, state: FSMContext, phone: str):
    # Agar shu foydalanuvchi uchun avval ochilib, yakunlanmagan urinish bo'lsa —
    # yangisini boshlashdan oldin uni tozalaymiz (ulanishlar to'planib qolmasin).
    await _disconnect_pending(message.from_user.id)

    await message.answer(
        "⏳ <b>Tasdiqlash kodi yuborilmoqda...</b>\n\n<i>Iltimos kuting...</i>",
        parse_mode="HTML",
        reply_markup=remove_kb
    )

    try:
        client, result, proxy_key, device = await telethon_service.send_code(phone)
        _pending_logins[message.from_user.id] = {
            "client": client,
            "phone": phone,
            "phone_code_hash": result.phone_code_hash,
            "created_at": time.time(),
            "proxy_key": proxy_key,
            "device": device,
        }
        await state.update_data(phone=phone)
        await state.set_state(PhoneFlow.entering_code)

        await message.answer(
            "✅ <b>Tasdiqlash kodi yuborildi!</b>\n\n"
            f"📱 Raqam: <code>{phone}</code>\n\n"
            "📝 Kodni quyidagi formatda kiriting:\n"
            "<b>1 2 . 3 4 5</b>  →  <code>12.345</code>\n\n"
            "⚠️ Nuqta birinchi 2 va oxirgi 3 raqamni ajratadi.\n\n"
            "🔒 <i>Bu kodni hech kimga bermang!</i>",
            parse_mode="HTML",
            reply_markup=kb_cancel_inline("phone:cancel")
        )

    except telethon_service.FloodWaitException as e:
        minutes = max(1, e.seconds // 60)
        logger.warning(f"FloodWait {e.seconds}s — {phone} uchun")
        await message.answer(
            "⏳ <b>Telegram vaqtincha yangi kod so'rovlarini cheklab qo'ydi.</b>\n\n"
            f"Iltimos, taxminan <b>{minutes} daqiqadan</b> so'ng qayta urinib ko'ring.\n\n"
            "💡 Bu — bitta IP manzildan ko'p urinish qilinganda Telegram tomonidan "
            "qo'yiladigan vaqtinchalik cheklov, xatolik emas.",
            parse_mode="HTML",
            reply_markup=kb_cancel_inline("phone:cancel")
        )
        await state.set_state(PhoneFlow.entering_phone)

    except Exception as e:
        logger.error(f"Kod yuborishda xato {phone}: {e}")
        await message.answer(
            f"❌ <b>Kod yuborib bo'lmadi</b>\n\n"
            f"Xato: <code>{str(e)[:200]}</code>\n\n"
            "Raqamni tekshirib qayta urinib ko'ring.",
            parse_mode="HTML",
            reply_markup=kb_cancel_inline("phone:cancel")
        )
        await state.set_state(PhoneFlow.entering_phone)


@router.message(PhoneFlow.entering_code, F.text)
async def receive_code(message: Message, state: FSMContext):
    text = message.text.strip()

    code = text.replace(".", "").replace(" ", "").strip()
    if not code.isdigit() or len(code) < 4:
        await message.answer(
            "❌ Noto'g'ri format. Kodni shunday kiriting:\n<code>12.345</code>",
            parse_mode="HTML",
            reply_markup=kb_cancel_inline("phone:cancel")
        )
        return

    pending = _pending_logins.get(message.from_user.id)
    if not pending:
        await message.answer("❌ Sessiya muddati o'tdi. /start dan qayta boshlang.")
        await state.clear()
        return

    loading_msg = await message.answer("⏳ <b>Kod tekshirilmoqda...</b>", parse_mode="HTML")

    try:
        session_string = await telethon_service.sign_in(
            client=pending["client"],
            phone=pending["phone"],
            code=code,
            phone_code_hash=pending["phone_code_hash"],
        )

        user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
        device = pending.get("device") or (None, None, None)
        await update_user(
            message.from_user.id,
            session_string=session_string,
            phone_number=pending["phone"],
            proxy_key=pending.get("proxy_key"),
            device_model=device[0],
            device_system_version=device[1],
            device_app_version=device[2],
            session_connected_at=datetime.utcnow(),
        )

        # Muvaqqat login klientini yopamiz — doimiy ulanish keyinchalik
        # telethon_service.get_client() orqali alohida, boshqariladigan pool'da
        # qayta ochiladi. Buni yopmasak, har bir muvaffaqiyatli ulanishdan keyin
        # ham ortiqcha, boshqarilmaydigan bitta ulanish serverda "osilib" qolar
        # va vaqt o'tishi bilan (bir necha soat/kundan keyin) resurs yetishmay,
        # YANGI foydalanuvchilarga tasdiqlash kodi kelmay qolishiga sabab bo'lardi.
        try:
            await pending["client"].disconnect()
        except Exception:
            pass
        _pending_logins.pop(message.from_user.id, None)
        await state.clear()

        user = await get_or_create_user(message.from_user.id)
        await _finish_onboarding(message, loading_msg, user, pending["phone"])

    except Exception as e:
        err_str = str(e)
        if "SessionPasswordNeeded" in err_str or "password" in err_str.lower():
            await state.set_state(PhoneFlow.entering_password)
            await state.update_data(code=code)
            await loading_msg.edit_text(
                "🔐 <b>Ikki bosqichli tasdiqlash</b>\n\n"
                "Hisobingizda 2FA yoqilgan.\n"
                "<b>Bulut parolingizni</b> kiriting:",
                parse_mode="HTML",
                reply_markup=kb_cancel_inline("phone:cancel")
            )
        elif "PhoneCodeInvalid" in err_str:
            await loading_msg.edit_text(
                "❌ <b>Noto'g'ri kod!</b>\n\nTo'g'ri kodni kiriting:",
                parse_mode="HTML",
                reply_markup=kb_cancel_inline("phone:cancel")
            )
        elif "PhoneCodeExpired" in err_str:
            await loading_msg.edit_text(
                "❌ <b>Kod muddati o'tdi!</b>\n\n/start dan qayta boshlang.",
                parse_mode="HTML"
            )
            await _disconnect_pending(message.from_user.id)
            await state.clear()
        else:
            logger.error(f"Kirish xatosi {message.from_user.id}: {e}")
            await loading_msg.edit_text(
                f"❌ <b>Xato:</b> <code>{err_str[:200]}</code>\n\nQayta urinib ko'ring.",
                parse_mode="HTML",
                reply_markup=kb_cancel_inline("phone:cancel")
            )


@router.message(PhoneFlow.entering_password, F.text)
async def receive_2fa_password(message: Message, state: FSMContext):
    pending = _pending_logins.get(message.from_user.id)
    if not pending:
        await message.answer("❌ Sessiya muddati o'tdi. Qayta boshlang.")
        await state.clear()
        return

    text = message.text.strip()
    data = await state.get_data()
    loading_msg = await message.answer("⏳ <b>Parol tekshirilmoqda...</b>", parse_mode="HTML")

    try:
        session_string = await telethon_service.sign_in(
            client=pending["client"],
            phone=pending["phone"],
            code=data.get("code", ""),
            phone_code_hash=pending["phone_code_hash"],
            password=text,
        )

        user = await get_or_create_user(message.from_user.id)
        device = pending.get("device") or (None, None, None)
        await update_user(
            message.from_user.id,
            session_string=session_string,
            phone_number=pending["phone"],
            proxy_key=pending.get("proxy_key"),
            device_model=device[0],
            device_system_version=device[1],
            device_app_version=device[2],
            session_connected_at=datetime.utcnow(),
        )

        try:
            await pending["client"].disconnect()
        except Exception:
            pass
        _pending_logins.pop(message.from_user.id, None)
        await state.clear()

        user = await get_or_create_user(message.from_user.id)
        await _finish_onboarding(
            message, loading_msg, user, pending["phone"],
            extra_line="\n🔐 Ikki bosqichli tasdiqlash muvaffaqiyatli o'tdi."
        )

    except Exception as e:
        logger.error(f"2FA xatosi {message.from_user.id}: {e}")
        await loading_msg.edit_text(
            "❌ <b>Noto'g'ri parol!</b>\n\nQayta kiriting:",
            parse_mode="HTML",
            reply_markup=kb_cancel_inline("phone:cancel")
        )