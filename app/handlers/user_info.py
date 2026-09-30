import logging
from datetime import datetime

from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

from app.database import get_or_create_user, get_user_payments, get_active_subscription
from app.keyboards import kb_main_menu_reply

router = Router()
logger = logging.getLogger(__name__)


@router.message(F.text == "💰 Hisobingiz")
async def btn_my_account(message: Message, state: FSMContext):
    await state.clear()
    user = await get_or_create_user(message.from_user.id)
    sub = await get_active_subscription(user.id)
    payments = await get_user_payments(user.id)

    lines = ["💰 <b>Hisobingiz</b>\n"]

    now = datetime.utcnow()
    if sub and sub.expires_at and sub.expires_at > now:
        delta = sub.expires_at - now
        days_left = delta.days
        hours_left = delta.seconds // 3600
        lines.append(
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"📋 Reja: <b>{sub.plan_name}</b>\n"
            f"🟢 Holat: <b>Faol</b>\n"
            f"📅 Boshlangan: <b>{sub.activated_at.strftime('%d.%m.%Y') if sub.activated_at else '—'}</b>\n"
            f"⏰ Tugaydi: <b>{sub.expires_at.strftime('%d.%m.%Y')}</b>\n"
            f"⏳ To'lov kuniga qoldi: <b>{days_left} kun {hours_left} soat</b>\n"
            "━━━━━━━━━━━━━━━━━━━━"
        )
        if days_left <= 3:
            lines.append("\n⚠️ <i>Obuna tez orada tugaydi — '💳 Obuna uchun to'lov qilish' tugmasi orqali yangilang.</i>")
    else:
        lines.append(
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🔴 Holat: <b>Faol obuna yo'q</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "\n💳 Yangilash uchun '💳 Obuna uchun to'lov qilish' tugmasini bosing."
        )

    phone = user.phone_number or "ulanmagan"
    lines.append(f"\n\n📱 Ulangan hisob: <code>{phone}</code>")

    if payments:
        lines.append("\n\n🧾 <b>To'lovlar tarixi:</b>")
        for p in payments[:10]:
            emoji = {"approved": "✅", "rejected": "❌", "pending": "⏳"}.get(p.status, "❓")
            method = {"admin": "Admin", "card": "Karta"}.get(p.method, p.method)
            status_uz = {"approved": "Tasdiqlandi", "rejected": "Rad etildi", "pending": "Kutilmoqda"}.get(p.status, p.status)
            lines.append(
                f"\n{emoji} <b>{p.amount:,} so'm</b> — {method}\n"
                f"    📅 {p.created_at.strftime('%d.%m.%Y %H:%M')} · {status_uz}"
            )
    else:
        lines.append("\n\n🧾 <i>To'lovlar tarixi hozircha bo'sh.</i>")

    await message.answer("".join(lines), parse_mode="HTML", reply_markup=kb_main_menu_reply())


@router.message(F.text == "👥 Do'stingizni taklif qilish")
async def btn_invite_friend(message: Message, state: FSMContext):
    await state.clear()
    me = await message.bot.get_me()
    link = f"https://t.me/{me.username}"
    await message.answer(
        "👥 <b>Do'stingizni taklif qiling!</b>\n\n"
        "Quyidagi havolani do'stlaringizga yuboring:\n\n"
        f"🔗 {link}",
        parse_mode="HTML",
        reply_markup=kb_main_menu_reply()
    )
