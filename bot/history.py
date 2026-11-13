"""
Історія діалогу з AI: обгортка над таблицею messages.

Читають її двоє:
- fallback.py — передає моделі як контекст;
- handoff.py — показує адміну, про що клієнт говорив до передачі.

Тепер історія в SQLite і переживає перезапуски бота.
"""
from bot import db

HISTORY_SIZE = 10      # скільки останніх повідомлень бачить модель — промпт (і ціна) не ростуть
CONTEXT_HOURS = 24     # старіші не беремо: питання тижневої давності лише заплутають модель
RETENTION_DAYS = 30    # довше не зберігаємо взагалі (див. purge_old)


async def get(user_id: int) -> list[dict]:
    return await db.recent_messages(user_id, HISTORY_SIZE, CONTEXT_HOURS)


async def add(user_id: int, role: str, text: str) -> None:
    """role: "user" або "assistant"."""
    await db.add_message(user_id, role, text)


async def drop_last(user_id: int) -> None:
    await db.delete_last_message(user_id)


async def purge_old() -> tuple[int, int]:
    """Листування й імена клієнтів — персональні дані. Зберігаємо стільки, скільки потрібно
    для роботи, а не «про всяк випадок». Для реального клієнта строк погоджуємо з ним.
    Повертає (видалено повідомлень, видалено клієнтів)."""
    messages = await db.purge_old_messages(RETENTION_DAYS)
    users = await db.purge_inactive_users(RETENTION_DAYS)
    return messages, users
