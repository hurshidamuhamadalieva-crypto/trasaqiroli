from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

from config import config

# ─────────────────────────────────────────────────────────────────────────────
# To'lov bosqichi INLINE tugmalar bilan ishlaydi (o'zgarmadi).
# To'lovdan keyingi asosiy menyu esa endi doimiy REPLY klaviatura —
# xabar yozadigan joyning tepasida turadi va bo'lim ichiga kirilganda ham
# yopilib qolmaydi.
# ─────────────────────────────────────────────────────────────────────────────


def kb_plans() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for key, plan in config.PLANS.items():
        builder.button(text=plan["label"], callback_data=f"plan:{key}")
    builder.adjust(1)
    return builder.as_markup()


def kb_payment_methods() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="👨‍💼 Admin orqali to'lash", callback_data="pay:admin")
    builder.button(text="🏦 Karta o'tkazma + Screenshot", callback_data="pay:card")
    builder.button(text="🔙 Orqaga", callback_data="pay:back")
    builder.adjust(1)
    return builder.as_markup()


def kb_share_phone() -> ReplyKeyboardMarkup:
    """
    MUHIM: Telegram request_contact tugmasini faqat oddiy (reply)
    klaviaturada ishlatishga ruxsat beradi — shu sababli bu yerda
    istisno qilib qoldirilgan.
    """
    builder = ReplyKeyboardBuilder()
    builder.button(text="📱 Kontaktni ulashish", request_contact=True)
    builder.button(text="✏️ Qo'lda kiritish")
    builder.button(text="❌ Bekor qilish")
    builder.adjust(2, 1)
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


def kb_cancel_inline(callback: str = "generic:cancel") -> InlineKeyboardMarkup:
    """Matn/kod kutilayotgan bosqichlarda xabar ostida chiqadigan bekor qilish tugmasi."""
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Bekor qilish", callback_data=callback)
    return builder.as_markup()


def kb_back_inline(callback: str = "back") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Orqaga", callback_data=callback)
    return builder.as_markup()


# ─── Asosiy menyu (endi DOIMIY reply klaviatura, to'lovdan keyin) ─────────────

def kb_main_menu_reply() -> ReplyKeyboardMarkup:
    """
    To'lovdan keyingi asosiy menyu. Doimiy (persistent) klaviatura —
    biror bo'limga kirilganda ham yopilib qolmaydi, xabar pastida
    doim shu tugmalar ko'rinib turadi.
    """
    builder = ReplyKeyboardBuilder()
    builder.button(text="📝 Yuboriladigan matnni kiritish")
    builder.button(text="⏰ Yuborish vaqtini kiritish va boshlash")
    builder.button(text="⏹ Yuborishni to'xtatish")
    builder.button(text="🔄 Yuborishni qayta boshlash")
    builder.button(text="💳 Obuna uchun to'lov qilish")
    builder.button(text="👥 Do'stingizni taklif qilish")
    builder.button(text="💰 Hisobingiz")
    builder.adjust(1, 1, 2, 1, 2)
    return builder.as_markup(resize_keyboard=True)


def kb_onboarding_connect() -> InlineKeyboardMarkup:
    """To'lov tasdiqlangach, hisobni ulashni boshlash tugmasi."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📱 Hisobni ulash", callback_data="phone:agree")
    return builder.as_markup()


def kb_reconnect() -> InlineKeyboardMarkup:
    """Sessiya uzilib qolganda, qayta ulash uchun tugma."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Qayta ulash", callback_data="phone:agree")
    return builder.as_markup()


def kb_interval() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for mins in config.BROADCAST_INTERVALS:
        builder.button(text=f"⏱ {mins} daqiqa", callback_data=f"bc_interval:{mins}")
    builder.button(text="❌ Bekor qilish", callback_data="bc_cancel_interval")
    builder.adjust(2, 2, 2, 1, 1)
    return builder.as_markup()


def kb_admin_panel() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="👥 Foydalanuvchilar", callback_data="admin:users")
    builder.button(text="💰 To'lovlar", callback_data="admin:payments")
    builder.button(text="📊 Statistika", callback_data="admin:stats")
    builder.button(text="🌐 Proksilar holati", callback_data="admin:proxies")
    builder.button(text="📢 Xabar yuborish", callback_data="admin:broadcast")
    builder.button(text="🚫 Bloklash", callback_data="admin:ban")
    builder.button(text="✅ Foydalanuvchini tasdiqlash", callback_data="admin:approve")
    builder.button(text="⏹ Yuborishni to'xtatish", callback_data="admin:stop_sending")
    builder.adjust(2)
    return builder.as_markup()


def kb_approve_payment(payment_id: int, user_tg_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Tasdiqlash", callback_data=f"admin_pay:approve:{payment_id}:{user_tg_id}")
    builder.button(text="❌ Rad etish", callback_data=f"admin_pay:reject:{payment_id}:{user_tg_id}")
    builder.adjust(2)
    return builder.as_markup()


remove_kb = ReplyKeyboardRemove()
