"""
Життєвий цикл звернення до адміністратора. ЄДИНЕ місце, де змінюється його статус.

Стани:
  (немає) ──remember_topic──► closed ──start──► open ──close / expire──► closed
  closed — тема клієнта в адмін-групі є, але розмови зараз немає: клієнту відповідає AI;
  open   — клієнт розмовляє з адміном: усе, що він пише, іде в тему, AI мовчить.

Переходи:
  remember_topic — запам'ятати тему клієнта; статус НЕ змінює (нова тема — closed);
  start          — почати або відновити розмову з адміном;
  touch          — активність у розмові: скидає відлік простою;
  close          — завершити: адмін написав /close або тема зникла;
  expire         — закрити, якщо простій довший за IDLE_HOURS.

Раніше статус писали вісім місць у двох модулях, а створення теми побічно відкривало
звернення — тому картка невідкладного стану мусила одразу закривати його назад.

Тут немає Telegram: що сказати клієнту й адміну при переході — справа handoff.py.
"""
from bot import db
from bot.db import Ticket
from bot.knowledge import UI

DEFAULT_IDLE_HOURS = 2


def _idle_hours() -> float:
    """Через скільки годин без активності розмова закривається сама (ui.ticket_idle_hours).

    Строк — у YAML бізнесу, бо залежить від того, як швидко там відповідають: якщо заявки
    обробляють лише вдень, строк має пережити ніч, інакше вечірня заявка «згорить» до ранку.
    """
    value = UI.get("ticket_idle_hours", DEFAULT_IDLE_HOURS)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise SystemExit(f"❌ ui.ticket_idle_hours має бути додатним числом годин, а зараз: {value!r}")
    return float(value)


IDLE_HOURS = _idle_hours()


def is_stale(ticket: Ticket) -> bool:
    return ticket.idle_minutes >= IDLE_HOURS * 60


async def get(user_id: int) -> Ticket | None:
    return await db.get_ticket_by_user(user_id)


async def by_thread(thread_id: int) -> Ticket | None:
    return await db.get_ticket_by_thread(thread_id)


async def active(user_id: int) -> Ticket | None:
    """Відкрите і не прострочене звернення клієнта. Нічого не змінює."""
    ticket = await get(user_id)
    if ticket is None or not ticket.is_open or is_stale(ticket):
        return None
    return ticket


async def expire(user_id: int) -> Ticket | None:
    """Прострочене відкрите звернення закриває і повертає — щоб про це можна було сказати
    клієнту й адміну. Якщо прострочувати нічого — None."""
    ticket = await get(user_id)
    if ticket is None or not ticket.is_open or not is_stale(ticket):
        return None
    await db.set_ticket_status(user_id, "closed")
    return ticket


async def remember_topic(user_id: int, thread_id: int) -> None:
    await db.set_ticket_thread(user_id, thread_id)


async def start(user_id: int) -> None:
    await db.set_ticket_status(user_id, "open")


async def touch(user_id: int) -> None:
    await db.touch_ticket(user_id)


async def close(user_id: int) -> None:
    await db.set_ticket_status(user_id, "closed")
