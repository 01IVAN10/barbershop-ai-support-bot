"""
Передача розмови людині. ЄДИНЕ місце в боті, де це відбувається: картки, теми, пересилка.
Статус звернення (відкрите / закрите / прострочене) змінює лише bot/tickets.py — тут ми
кажемо йому, ЩО сталося, і повідомляємо про це клієнта й адміна.

Схема:
  клієнт ──(кнопка або AI: needs_human)──► request_handoff()
     │                                         │
     │                     адмін-група з темами: 1 клієнт = 1 тема
     │                                         │
     ◄──── бот копіює відповідь адміна ◄────── адмін пише в темі
  Поки звернення відкрите, ВСЕ, що пише клієнт, іде адміну (AI мовчить).
  Адмін пише /close у темі → звернення закрите, знову відповідає AI.

Якщо ADMIN_CHAT_ID не задано або Telegram видав помилку — бот не мовчить
і не бреше: дає клієнту телефон (запасний варіант).

Невідкладний стан (медичний режим) — окремий шлях send_emergency(): клієнт ОДРАЗУ
отримує телефон, а адмін — картку 🚨. Клієнта НЕ переводимо в режим «чекайте
адміністратора»: уночі чат може ніхто не читати, а бот має й далі відповідати.
"""
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError
from aiogram.types import Message, User

from bot import history, tickets
from bot.config import load_config
from bot.db import Ticket
from bot.keyboards import main_menu
from bot.knowledge import KB, SAFETY, UI, escape, medical_mode
from bot.reasons import Reason

log = logging.getLogger(__name__)
ADMIN_CHAT_ID = load_config().admin_chat_id

# Звернення без активності закривається автоматично (строк — tickets.IDLE_HOURS, з YAML).
# Інакше: клієнт натиснув «Адміністратор», ніхто не відповів — і бот мовчить для нього
# назавжди (усе йде адміну, AI не втручається). Клієнту про закриття кажемо прямо: він
# бачив «усе, що напишете далі, побачить адміністратор» і має знати, що це вже не так.
TICKET_EXPIRED_TEXT = (UI.get("ticket_expired_text") or (
    "⏱ Розмову з адміністратором закрито: давно не було повідомлень. "
    "Це повідомлення адміністратор уже не побачить — далі відповідаю я. "
    "Якщо потрібна людина, напишіть про це.")).strip()
DELIVERY_FAILED_TEXT = ("⚠️ Не вдалося передати це повідомлення адміністратору. "
                        "Надішліть його, будь ласка, ще раз за хвилину.")


def _safety_text(key: str) -> str:
    """Текст із розділу safety. Це звичайний текст, а не HTML, тому екрануємо: інакше
    символ «<» у ньому зламав би розмітку Telegram і повідомлення не відправилось би взагалі
    (а це телефон при невідкладному стані). Кнопка меню показує його так само — format_emergency."""
    return escape(SAFETY.get(key, "").strip())


# Що сказати клієнту — фіксований текст (код або YAML бізнесу), не від моделі.
# YAML може перевизначити будь-який рядок: ui.handoff_texts.<reason>, ui.handoff_confirm.
CLIENT_TEXT = {
    Reason.BOOKING: "📅 Записом займається адміністратор.",
    Reason.HUMAN_REQUEST: "👤 Підключаю адміністратора.",
    Reason.COMPLAINT: "🙏 Нам шкода, що так вийшло.",
    Reason.NO_INFO: "🙋 На це питання краще відповість адміністратор.",
    Reason.MEDICAL: _safety_text("medical_text"),
}
for _key, _text in (UI.get("handoff_texts") or {}).items():
    CLIENT_TEXT[Reason(_key)] = _text.strip()
HANDOFF_CONFIRM = (UI.get("handoff_confirm") or (
    "✅ Передав ваше звернення адміністратору — він відповість тут, у цьому чаті.\n"
    "Усе, що напишете далі, побачить адміністратор.")).strip()
EMERGENCY_TEXT = _safety_text("emergency_text")
if medical_mode() and not (EMERGENCY_TEXT and CLIENT_TEXT[Reason.MEDICAL]):
    raise SystemExit("❌ safety.medical: true потребує safety.emergency_text і safety.medical_text")

# Як причина виглядає для адміна
ADMIN_LABEL = {
    Reason.BOOKING: "📅 Запис",
    Reason.HUMAN_REQUEST: "👤 Просить адміністратора",
    Reason.COMPLAINT: "⚠️ Скарга",
    Reason.NO_INFO: "❓ Бот не знає відповіді",
    Reason.EMERGENCY: "🚨 НЕВІДКЛАДНИЙ СТАН (клієнту одразу дано телефон)",
    Reason.MEDICAL: "🩺 Медичне питання (бот порад не давав)",
}


def with_emergency_hint(text: str) -> str:
    """Медичний режим: до відмови (напр. «ліміт вичерпано») додаємо телефон для
    невідкладних випадків. Клієнт, якому бот не відповів, не має лишитися без номера."""
    if not medical_mode():
        return text
    return f"{text}\n\n{EMERGENCY_TEXT}"


def client_notice(reason: Reason) -> str:
    """Фіксований текст, який клієнт бачить при передачі (звичайний шлях, нове звернення).

    Окрема функція, бо її використовує і тест-набір: перевіряємо те, що бачить клієнт.
    """
    if reason == Reason.EMERGENCY:
        return EMERGENCY_TEXT
    return f"{CLIENT_TEXT[reason]}\n{HANDOFF_CONFIRM}"


async def request_handoff(message: Message, reason: Reason, question: str) -> None:
    if reason == Reason.EMERGENCY:
        await send_emergency(message, question)
        return
    user = message.from_user
    log.info("HANDOFF | user=%s | reason=%s", user.id, reason.value)

    if ADMIN_CHAT_ID is None:  # адмін-група не налаштована → телефон
        await _fallback_phone(message, reason)
        return

    ticket = await _active_ticket(message.bot, user.id)
    already_open = ticket is not None
    try:
        if already_open:
            # Клієнт уже на зв'язку — просто додаємо в його тему, що він ще хоче.
            text = f"➕ {ADMIN_LABEL[reason]}: «{escape(question)}»"
        else:
            text = await _admin_card(user, reason, question)
        await _send_to_topic(message.bot, user, text)
        await tickets.start(user.id)  # розмова з адміном відкрита (або триває)
    except TelegramAPIError:
        log.exception("Не вдалося передати звернення в адмін-групу")
        await _fallback_phone(message, reason)
        return

    if already_open:
        await message.answer("Ви вже на зв'язку з адміністратором — він побачить це повідомлення.")
    else:
        await message.answer(client_notice(reason), reply_markup=main_menu)


async def send_emergency(message: Message, question: str) -> None:
    """Невідкладний стан: СПЕРШУ телефон клієнту, потім (тихо) картка адміну.

    Звернення НЕ відкриваємо: бот і далі відповідає клієнту сам, а не «мовчить і чекає»
    адміністратора, якого вночі може не бути. Якщо адмін напише в тему — розмова
    відкриється (див. handlers/admin.py).
    """
    user = message.from_user
    log.warning("EMERGENCY | user=%s", user.id)
    await message.answer(EMERGENCY_TEXT, reply_markup=main_menu)
    if ADMIN_CHAT_ID is None:
        return
    try:
        ticket = await _active_ticket(message.bot, user.id)
        if ticket is not None:  # клієнт уже в розмові з адміном — додаємо в його тему
            await _send_to_topic(message.bot, user, f"➕ {ADMIN_LABEL[Reason.EMERGENCY]}: «{escape(question)}»")
            await tickets.touch(user.id)
        else:  # лише картка в тему клієнта; статус не чіпаємо — бот не замовкає
            card = await _admin_card(user, Reason.EMERGENCY, question)
            await _send_to_topic(message.bot, user, card)
    except TelegramAPIError:
        log.exception("Не вдалося надіслати адміну картку невідкладного стану")


async def forward_to_admin(message: Message) -> bool:
    """Якщо в клієнта відкрите звернення — копіює його повідомлення в тему адміна.

    Повертає True, якщо переслано (тоді AI відповідати НЕ повинен).
    """
    if ADMIN_CHAT_ID is None:
        return False
    # tell_client: якщо звернення щойно прострочилось, клієнт має про це дізнатися —
    # він пише адміну, а повідомлення вже піде до AI.
    ticket = await _active_ticket(message.bot, message.from_user.id, tell_client=message)
    if ticket is None:
        return False
    try:
        # copy_message, а не forward: працює з будь-яким типом (фото, голосові...)
        # і не залежить від налаштувань приватності клієнта.
        await message.bot.copy_message(
            chat_id=ADMIN_CHAT_ID, from_chat_id=message.chat.id,
            message_id=message.message_id, message_thread_id=ticket.thread_id,
        )
        await tickets.touch(message.from_user.id)
        return True
    except (TelegramBadRequest, TelegramForbiddenError):
        # Тему видалили або бота прибрали з групи — закриваємо звернення,
        # щоб клієнт не писав "у порожнечу". Далі знову відповідає AI.
        log.exception("Тема клієнта недоступна — закриваю звернення")
        await tickets.close(message.from_user.id)
        return False
    except TelegramAPIError:
        # Мережа, ліміт запитів (429), збій Telegram — це тимчасове. Звернення НЕ закриваємо:
        # інакше одна мережева помилка мовчки перевела б розмову з адміна на AI.
        log.exception("Тимчасова помилка Telegram: повідомлення клієнта адміну не доставлено")
        await message.answer(DELIVERY_FAILED_TEXT)
        return True


async def check_admin_chat(bot: Bot) -> bool:
    """Перевірка при запуску: чи працюватиме передача адміну.

    Без неї помилка в ADMIN_CHAT_ID чи правах бота проявиться лише тоді, коли
    клієнт уже чекає відповіді. Бот НЕ зупиняємо (на питання він відповідає і без
    адмін-групи, клієнт отримає телефон), але пишемо в лог гучну зрозумілу помилку.
    """
    if ADMIN_CHAT_ID is None:
        return False
    problems = []
    try:
        chat = await bot.get_chat(ADMIN_CHAT_ID)
        if not chat.is_forum:
            problems.append("у групі вимкнені теми (налаштування групи → Теми/Topics)")
        me = await bot.get_me()
        member = await bot.get_chat_member(ADMIN_CHAT_ID, me.id)
        if member.status != "administrator":
            problems.append(f"бот не адміністратор групи (статус: {member.status})")
        elif not getattr(member, "can_manage_topics", False):
            problems.append("у бота немає права «Керування темами» (Manage Topics)")
    except TelegramAPIError as e:
        problems.append(f"Telegram: {e} — перевір ADMIN_CHAT_ID (напиши /chatid у групі) "
                        "і чи бот доданий у групу")
    if problems:
        log.error("❌ АДМІН-ГРУПА НЕ ПРАЦЮЄ (ADMIN_CHAT_ID=%s): %s. "
                  "Клієнти отримуватимуть телефон замість передачі адміну.",
                  ADMIN_CHAT_ID, "; ".join(problems))
        return False
    log.info("✅ Адмін-група «%s» доступна, теми й права бота в порядку", chat.title)
    return True


# ---------- внутрішні функції ----------

async def _active_ticket(bot: Bot, user_id: int, tell_client: Message | None = None) -> Ticket | None:
    """Відкрите і «живе» звернення клієнта. Прострочене закривається (tickets.expire),
    а ми повідомляємо про це адміна і — якщо передано tell_client — клієнта."""
    expired = await tickets.expire(user_id)
    if expired is None:
        return await tickets.active(user_id)
    log.info("Автозакриття звернення %s: простій %.0f хв", user_id, expired.idle_minutes)
    try:  # адміну — пояснення, щоб не дивувався, чому тема закрилась сама
        await bot.send_message(
            ADMIN_CHAT_ID,
            f"⏱ Звернення закрито автоматично: {tickets.IDLE_HOURS:g} год без активності. "
            "Клієнту знову відповідає бот. Напишіть у тему — розмова відновиться.",
            message_thread_id=expired.thread_id,
        )
        await bot.close_forum_topic(ADMIN_CHAT_ID, expired.thread_id)
    except TelegramAPIError:
        pass  # не критично
    if tell_client is not None:
        await tell_client.answer(TICKET_EXPIRED_TEXT)
    return None


async def _send_to_topic(bot: Bot, user: User, text: str) -> None:
    """Надсилає текст у тему клієнта. Створює/відкриває тему, якщо треба."""
    thread_id = await _ensure_topic(bot, user)
    try:
        await bot.send_message(ADMIN_CHAT_ID, text, message_thread_id=thread_id)
    except TelegramBadRequest as e:
        # Адмін міг видалити тему вручну → створюємо нову і пробуємо ще раз.
        if "thread" not in str(e).lower():
            raise
        log.warning("Тема %s зникла, створюю нову", thread_id)
        thread_id = await _create_topic(bot, user)
        await bot.send_message(ADMIN_CHAT_ID, text, message_thread_id=thread_id)


async def _ensure_topic(bot: Bot, user: User) -> int:
    """Повертає ID теми клієнта в адмін-групі; створює її, якщо ще немає.

    Статус звернення тут НЕ змінюється: тема — це місце для повідомлень, а чи відкрита
    розмова, вирішує той, хто пише в тему (request_handoff — так, send_emergency — ні).
    """
    ticket = await tickets.get(user.id)
    if ticket is None:
        return await _create_topic(bot, user)
    if not ticket.is_open:
        try:  # одна тема на клієнта: старе листування лишається перед очима адміна
            await bot.reopen_forum_topic(ADMIN_CHAT_ID, ticket.thread_id)
        except TelegramBadRequest:
            pass  # тема вже відкрита або зникла — це обробить _send_to_topic
    return ticket.thread_id


async def _create_topic(bot: Bot, user: User) -> int:
    name = f"{user.full_name} · {user.id}"[:128]  # ліміт Telegram — 128 символів
    topic = await bot.create_forum_topic(ADMIN_CHAT_ID, name)
    await tickets.remember_topic(user.id, topic.message_thread_id)
    return topic.message_thread_id


async def _admin_card(user: User, reason: Reason, question: str) -> str:
    """Картка звернення для адміна: хто, чому, що питав, про що говорив з ботом."""
    username = f"@{user.username}" if user.username else "без username"
    lines = [
        f"🆕 <b>Нове звернення</b> · {ADMIN_LABEL[reason]}",
        f"👤 {escape(user.full_name)} ({username}) · id <code>{user.id}</code>",
        # Кнопку показуємо як дію, а не як текст, що його «написав» клієнт.
        f"🔘 {escape(question)}" if question.startswith(BUTTON_PREFIX) else f"💬 «{escape(question)}»",
    ]
    recent, bot_answer = await _history_before(user.id, question)
    if bot_answer:  # що бот уже відповів на ЦЕ питання — щоб адмін не повторював
        lines.append(f"🤖 Бот відповів: {escape(bot_answer[:300])}")
    if recent:
        lines += ["", "<b>Розмова з ботом до цього:</b>"]
        for m in recent:
            if m["text"] == HANDOFF_MARK:  # попередні передачі показуємо як подію
                lines.append("↪️ <i>передано адміністратору</i>")
                continue
            icon = "👤" if m["role"] == "user" else "🤖"
            lines.append(f"{icon} {escape(m['text'][:200])}")
    lines += ["", "↩️ Пишіть у цій темі — бот перешле клієнту. /close — завершити розмову."]
    return "\n".join(lines)


BUTTON_PREFIX = "Натиснув кнопку"  # так menu.py позначає звернення через кнопку
HANDOFF_MARK = "(передано адміністратору)"  # так fallback.py позначає в історії передачу


async def _history_before(user_id: int, question: str, limit: int = 6) -> tuple[list[dict], str | None]:
    """(розмова ДО поточного питання, відповідь бота на поточне питання або None).

    Історію поповнює лише AI-шлях; для кнопки «Адміністратор» поточного питання там немає.
    На AI-шляху в кінці історії лежить поточний обмін: питання клієнта і те, що він на нього
    побачив (текст бота або позначка передачі). Раніше відрізалась лише позначка — тож при
    no_info питання в картці дублювалось, а відповідь бота на нього стояла під «розмова до цього».
    """
    msgs = await history.get(user_id)
    answer = None
    for i in range(len(msgs) - 1, max(len(msgs) - 3, -1), -1):  # поточний обмін — останні 1–2 записи
        if msgs[i]["role"] == "user" and msgs[i]["text"] == question:
            shown = [m["text"] for m in msgs[i + 1:] if m["role"] == "assistant" and m["text"] != HANDOFF_MARK]
            answer = shown[0] if shown else None
            msgs = msgs[:i]
            break
    return msgs[-limit:], answer


async def _fallback_phone(message: Message, reason: Reason) -> None:
    await message.answer(
        f"{CLIENT_TEXT.get(reason, CLIENT_TEXT[Reason.NO_INFO])}\n"
        f"Зв'язатися з адміністратором можна за телефоном: {KB['business']['phone']}",
        reply_markup=main_menu,
    )
