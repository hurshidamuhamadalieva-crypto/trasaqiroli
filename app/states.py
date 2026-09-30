from aiogram.fsm.state import State, StatesGroup


class PaymentFlow(StatesGroup):
    choosing_plan = State()
    choosing_method = State()
    waiting_screenshot = State()
    waiting_click_confirm = State()


class PhoneFlow(StatesGroup):
    agreeing = State()
    entering_phone = State()
    entering_code = State()
    entering_password = State()


class BroadcastFlow(StatesGroup):
    """
    E'lon matni (yoki matn+rasm) shablonini kiritish uchun kutish holati.
    Interval tanlash endi alohida tasdiqlash bosqichisiz, to'g'ridan-to'g'ri
    inline tugma bosilishi bilan yuborishni boshlaydi.
    """
    waiting_text = State()


class AdminFlow(StatesGroup):
    panel = State()
    viewing_users = State()
    user_detail = State()
    broadcast = State()
    ban_input = State()
    edit_sub = State()