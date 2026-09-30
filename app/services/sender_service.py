import asyncio
import logging
from datetime import datetime
from typing import Dict

from app.database import (
    get_active_advertisement,
    get_or_create_settings, update_settings, add_send_stat
)
from app.services.telethon_service import (
    SessionRevokedException, AccountBannedException,
    disconnect_client, _clear_user_session, _notify_session_lost,
    get_bot_folder_groups_live,
)

logger = logging.getLogger(__name__)

# Aktiv yuborish tasklari: {user_db_id: asyncio.Task}
_sending_tasks: Dict[int, asyncio.Task] = {}

# Guruhlar orasidagi kutish (spam himoyasi)
DELAY_BETWEEN_GROUPS = 8


async def start_sending(bot, user_db_id: int, telegram_id: int, session_string: str):
    task = _sending_tasks.get(user_db_id)
    if task and not task.done():
        return
    _sending_tasks[user_db_id] = asyncio.create_task(
        _sending_loop(bot, user_db_id, telegram_id, session_string),
        name=f"send_{user_db_id}"
    )


async def stop_sending(user_db_id: int):
    task = _sending_tasks.get(user_db_id)
    if task and not task.done():
        task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=5)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
    _sending_tasks.pop(user_db_id, None)  # ← KeyError bo'lmaydi
    await update_settings(user_db_id, is_sending=False, sending_paused=False)


async def pause_sending(user_db_id: int):
    await update_settings(user_db_id, sending_paused=True)


async def resume_sending(user_db_id: int):
    await update_settings(user_db_id, sending_paused=False)


def is_sending(user_db_id: int) -> bool:
    task = _sending_tasks.get(user_db_id)
    return task is not None and not task.done()


async def stop_all_for_user(user_db_id: int):
    await stop_sending(user_db_id)


async def _send_to_entity(client_session: str, user_db_id: int, entity, text: str, photo_path: str = None):
    """
    Guruh yoki kanalga xabar (yoki rasm+izoh) yuborish.
    Telethon send_message/send_file barcha turdagi entity larni qabul
    qiladi: guruh, supergroup, kanal — farqi yo'q.
    """
    from app.services.telethon_service import get_client
    client = await get_client(user_db_id, client_session)
    if not client:
        return False, "Mijoz ulanmagan"

    from telethon import errors
    for attempt in range(3):
        try:
            if photo_path:
                await client.send_file(entity, photo_path, caption=text)
            else:
                await client.send_message(entity, text)
            return True, ""

        except errors.FloodWaitError as e:
            wait = e.seconds
            logger.warning(f"FloodWait {wait}s — foydalanuvchi {user_db_id}, entity {entity}")
            if wait > 300:
                return False, f"FloodWait: {wait}s (juda uzoq)"
            await asyncio.sleep(wait + 3)

        except errors.ChatWriteForbiddenError:
            return False, "Yozish taqiqlangan"

        except errors.UserBannedInChannelError:
            return False, "Kanalda bloklangan"

        except errors.SlowModeWaitError as e:
            return False, f"SlowMode: {e.seconds}s"

        except errors.ChannelPrivateError:
            return False, "Kanal/guruh yopiq yoki chiqib ketilgan"

        except errors.RPCError as e:
            logger.warning(f"RPCError (urinish {attempt+1}/3): {e}")
            if attempt == 2:
                return False, str(e)
            await asyncio.sleep(5)

        except Exception as e:
            logger.error(f"Kutilmagan xato: {e}")
            return False, str(e)

    return False, "3 ta urinishdan keyin ham xato"


async def _sending_loop(bot, user_db_id: int, telegram_id: int, session_string: str):
    """
    Asosiy yuborish sikli:
    1. Barcha guruh/kanallarga ketma-ket yuborish (8s pauza)
    2. Hammaga yuborib bo'lgach → interval kutish
    3. Takrorlash ♻️
    """
    logger.info(f"Yuborish sikli boshlandi: foydalanuvchi {user_db_id}")
    await update_settings(user_db_id, is_sending=True, sending_paused=False)
    warned_empty = False

    try:
        while True:
            # ── Sozlamalarni olish ────────────────────────────────────────────
            settings = await get_or_create_settings(user_db_id)

            if settings.sending_paused:
                await asyncio.sleep(3)
                continue

            # ── E'lonni olish ─────────────────────────────────────────────────
            ad = await get_active_advertisement(user_db_id)
            if not ad:
                logger.warning(f"[{user_db_id}] E'lon topilmadi, 30s kutilmoqda")
                await asyncio.sleep(30)
                continue

            # ── Guruh/kanallarni JONLI o'qish (keshlanmagan, har doim yangi) ────
            # MUHIM: bu yerda foydalanuvchining "Bot uchun" jildidagi guruhlar
            # ro'yxati har safar to'g'ridan-to'g'ri Telegram'dan o'qiladi —
            # oldindan saqlangan (bazadagi) ro'yxatga tayanmaydi. Shu orqali
            # foydalanuvchi jildga yangi guruh qo'shsa, buni "yangilash"
            # tugmasini bosmasdan, KEYINGI siklda o'zi payqaydi.
            try:
                groups = await get_bot_folder_groups_live(user_db_id, session_string)
            except (SessionRevokedException, AccountBannedException) as e:
                banned = isinstance(e, AccountBannedException)
                logger.warning(f"[{user_db_id}] Sessiya yo'qoldi (guruhlarni o'qishda): {e}")
                await disconnect_client(user_db_id)
                await _clear_user_session(telegram_id)
                await _notify_session_lost(bot, telegram_id, banned)
                return

            if not groups:
                logger.warning(f"[{user_db_id}] 'Bot uchun' jildida guruh topilmadi, 30s kutilmoqda")
                if not warned_empty:
                    warned_empty = True
                    try:
                        await bot.send_message(
                            telegram_id,
                            "⚠️ <b>'Bot uchun' jildida hozircha guruh yoki kanal yo'q.</b>\n\n"
                            "Telegram ilovasini oching va e'lon yuboriladigan guruh yoki "
                            "(hisobingiz admin bo'lgan) kanallarni <b>'Bot uchun'</b> jildiga "
                            "qo'shing — bot ularni o'zi taniydi va yuborishni avtomatik boshlaydi.",
                            parse_mode="HTML"
                        )
                    except Exception:
                        pass
                await asyncio.sleep(30)
                continue
            warned_empty = False

            interval_minutes = settings.interval_minutes or 10
            total = len(groups)
            sent_count = 0
            failed_count = 0

            logger.info(
                f"[{user_db_id}] {total} ta guruh/kanalga yuborilmoqda | "
                f"interval={interval_minutes}daq | orasida {DELAY_BETWEEN_GROUPS}s"
            )

            # ── Hammaga ketma-ket yuborish ────────────────────────────────────
            for idx, group in enumerate(groups, 1):

                # Pauza tekshiruvi
                settings = await get_or_create_settings(user_db_id)
                if settings.sending_paused:
                    logger.info(f"[{user_db_id}] Pauza ({idx}/{total})")
                    while True:
                        await asyncio.sleep(3)
                        settings = await get_or_create_settings(user_db_id)
                        if not settings.sending_paused:
                            logger.info(f"[{user_db_id}] Davom ettirildi")
                            break

                # E'lon yangilangan bo'lishi mumkin
                ad = await get_active_advertisement(user_db_id)
                if not ad:
                    logger.warning(f"[{user_db_id}] E'lon o'chirildi, sikl to'xtatildi")
                    break

                # Entity aniqlash: username bo'lsa ishlatamiz, bo'lmasa ID
                entity = group["username"] if group.get("username") else int(group["id"])

                try:
                    success, error_msg = await _send_to_entity(
                        client_session=session_string,
                        user_db_id=user_db_id,
                        entity=entity,
                        text=ad.text,
                        photo_path=ad.photo_path,
                    )
                except (SessionRevokedException, AccountBannedException) as e:
                    banned = isinstance(e, AccountBannedException)
                    logger.warning(f"[{user_db_id}] Sessiya yo'qoldi (yuborish paytida): {e}")
                    await disconnect_client(user_db_id)
                    await _clear_user_session(telegram_id)
                    await _notify_session_lost(bot, telegram_id, banned)
                    return
                await add_send_stat(
                    user_db_id=user_db_id,
                    group_id=group["id"],
                    group_title=group.get("title") or "",
                    success=success,
                    error_msg=error_msg if not success else None,
                )

                mark = "📢" if group.get("is_channel") else "👥"
                if success:
                    sent_count += 1
                    logger.info(f"✅ [{idx}/{total}] {mark} {group.get('title')}")
                else:
                    failed_count += 1
                    logger.warning(f"❌ [{idx}/{total}] {mark} {group.get('title')}: {error_msg}")

                # Oxirgi guruhdan keyin kutmaslik
                if idx < total:
                    await asyncio.sleep(DELAY_BETWEEN_GROUPS)

            # ── Sikl tugadi ───────────────────────────────────────────────────
            logger.info(
                f"[{user_db_id}] Sikl tugadi → ✅{sent_count} ❌{failed_count} | "
                f"Keyingisi {interval_minutes} daqiqadan keyin"
            )

            await asyncio.sleep(interval_minutes * 60)

    except asyncio.CancelledError:
        logger.info(f"[{user_db_id}] Yuborish bekor qilindi")
        raise
    except Exception as e:
        logger.error(f"[{user_db_id}] Yuborish xatosi: {e}", exc_info=True)
    finally:
        # MUHIM: faqat O'ZINING yozuvini o'chiramiz. To'xtatib, darhol qayta
        # boshlanganda eski sikl kech tugab, YANGI siklning yozuvini yoki
        # holatini o'chirib yubormasligi uchun.
        me = asyncio.current_task()
        if _sending_tasks.get(user_db_id) is me or user_db_id not in _sending_tasks:
            _sending_tasks.pop(user_db_id, None)
            await update_settings(user_db_id, is_sending=False, sending_paused=False)
        logger.info(f"[{user_db_id}] Yuborish sikli tugatildi")