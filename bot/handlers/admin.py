"""
Адмін-група: відповіді адміністратора клієнтам.

Адмін пише у темі клієнта → бот копіює повідомлення клієнту.
/close у темі → звернення закрите, клієнту знову відповідає AI.
/chatid у будь-якій групі → показує ID (щоб заповнити ADMIN_CHAT_ID).

Важливо: бот має бути АДМІНІСТРАТОРОМ групи — інакше Telegram не надсилає
йому звичайні повідомлення з групи (лише команди), і не дасть створювати теми.
"""
import logging

from aiogram import F, Router
from aiogram.enums import ContentType
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from aiogram.filters import Command
from aiogram.types import ChatMemberUpdated, Message

from bot import db
from bot.config import load_config

log = logging.getLogger(__name__)
router = Router(name="admin")
ADMIN_CHAT_ID = load_config().admin_chat_id

# Що можна переслати клієнту. Службові повідомлення ("тему створено" тощо) — ні.
FORWARDABLE = {
    ContentType.TEXT, ContentType.PHOTO, ContentType.VIDEO, ContentType.DOCUMENT,
    ContentType.VOICE, ContentType.AUDIO, ContentType.STICKER, ContentType.ANIMATION,
    ContentType.VIDEO_NOTE, ContentType.LOCATION, ContentType.CONTACT,
}

# Фільтр "повідомлення в темі адмін-групи". Якщо ADMIN_CHAT_ID не задано — не спрацює ніколи.
in_admin_topic = (F.chat.id == ADMIN_CHAT_ID) & F.message_thread_id


@router.message(Command("chatid"), F.chat.type.in_({"group", "supergroup"}))
async def show_chat_id(message: Message) -> None:
    await message.reply(f"ID цього чату: <code>{message.chat.id}</code>\n"
                        "Встав його в .env як ADMIN_CHAT_ID і перезапусти бота.")


@router.message(Command("stats"), F.chat.id == ADMIN_CHAT_ID)
async def show_stats(message: Message) -> None:
    """Цифри для власника: скільки людей пише боту і скільки доходить до адміна."""
    st = await db.stats()
    await message.reply(
        "📊 <b>Статистика бота</b>\n\n"
        f"👥 Клієнтів усього: {st['users_total']}\n"
        f"🆕 Нових за добу: {st['users_new_24h']}\n"
        f"💬 Активних за добу: {st['users_active_24h']}\n"
        f"❓ Питань за добу: {st['questions_24h']}\n\n"
        f"📨 Звернень до адміна: {st['tickets_total']} (відкритих: {st['tickets_open']})"
    )


@router.message(Command("close"), in_admin_topic)
async def close_ticket(message: Message) -> None:
    ticket = await db.get_ticket_by_thread(message.message_thread_id)
    if ticket is None:
        await message.reply("Ця тема не пов'язана з клієнтом.")
        return
    await db.set_status(ticket.user_id, "closed")
    try:
        await message.bot.send_message(
            ticket.user_id,
            "✅ Адміністратор завершив розмову. Якщо будуть ще питання — пишіть, я на зв'язку 🤖",
        )
    except TelegramAPIError:
        log.warning("Не вдалося повідомити клієнта %s про закриття", ticket.user_id)
    await message.reply("Звернення закрито. Клієнту знову відповідає бот.")
    try:
        await message.bot.close_forum_topic(ADMIN_CHAT_ID, ticket.thread_id)
    except TelegramAPIError:
        pass  # не критично: закрита тема — лише зручність для адміна


@router.message(in_admin_topic, F.content_type.in_(FORWARDABLE), ~F.text.startswith("/"))
async def admin_reply(message: Message) -> None:
    ticket = await db.get_ticket_by_thread(message.message_thread_id)
    if ticket is None:
        return  # тема не наша (наприклад, адміни створили її для себе)
    try:
        await message.bot.copy_message(
            chat_id=ticket.user_id, from_chat_id=message.chat.id, message_id=message.message_id,
        )
    except TelegramForbiddenError:
        await message.reply("⚠️ Клієнт заблокував бота — повідомлення не доставлено.")
        return
    except TelegramAPIError:
        log.exception("Не вдалося надіслати відповідь адміна клієнту")
        await message.reply("⚠️ Не вдалося доставити повідомлення клієнту.")
        return
    if not ticket.is_open:
        # Адмін написав у закриту тему — значить, продовжує розмову. Відкриваємо.
        await db.set_status(ticket.user_id, "open")
    else:
        await db.touch_ticket(ticket.user_id)  # активність: скидаємо таймер автозакриття


# ---------- діагностика ----------

@router.my_chat_member()
async def bot_status_changed(event: ChatMemberUpdated) -> None:
    """Бота додали в групу / зробили адміном / видалили — пишемо в лог разом з ID чату.

    Так ID групи видно в терміналі одразу, навіть без /chatid.
    """
    status = event.new_chat_member.status
    can_topics = getattr(event.new_chat_member, "can_manage_topics", None)
    log.info("Статус бота в «%s» (id %s): %s | керування темами: %s",
             event.chat.title, event.chat.id, status, can_topics)
    if event.chat.id == ADMIN_CHAT_ID and status != "administrator":
        log.warning("⚠️ Бот НЕ адміністратор адмін-групи — передача звернень не працюватиме!")


@router.message(F.chat.type.in_({"group", "supergroup"}))
async def group_message_debug(message: Message) -> None:
    """Будь-яке інше повідомлення з групи: нічого не робимо, лише лог.

    Стоїть ОСТАННІМ у роутері admin, тож нічого корисного не перехоплює.
    """
    log.debug("Група %s, тема %s: повідомлення не для бота", message.chat.id, message.message_thread_id)
