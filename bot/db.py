"""
База даних (SQLite). Три таблиці:
- users    — хто писав боту (для статистики і, на кроці 7, лімітів);
- messages — історія діалогу з AI (контекст для моделі і картка для адміна);
- tickets  — звернення до адміністратора: яка тема належить якому клієнту.

Навіщо зберігати на диску, а не в пам'яті: бот має пам'ятати, яка тема
в адмін-групі належить якому клієнту. Після перезапуску (а він буває часто:
оновлення коду, збій, деплой) пам'ять очищається — і відповідь адміна
нікому не дійшла б. Файл bot.db переживає перезапуски.

Файл лежить у storage/, а НЕ в data/: за data/ стежить watchfiles, і кожен
запис у базу перезапускав би бота посеред роботи.

Чому SQLite: це один файл, без окремого сервера. Для одного бізнесу з
десятками звернень на день — більш ніж достатньо.
"""
import logging
from dataclasses import dataclass
from pathlib import Path

import aiosqlite

log = logging.getLogger(__name__)

_db: aiosqlite.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id    INTEGER PRIMARY KEY,         -- Telegram ID — унікальний і незмінний
    username   TEXT,                        -- може не бути або змінитися
    full_name  TEXT NOT NULL,
    first_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,  -- порядок повідомлень
    user_id    INTEGER NOT NULL REFERENCES users(user_id),
    role       TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    text       TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
-- Індекс: «останні N повідомлень клієнта» — найчастіший запит, без індексу
-- SQLite перебирала б усю таблицю.
CREATE INDEX IF NOT EXISTS idx_messages_user ON messages(user_id, id);

CREATE TABLE IF NOT EXISTS tickets (
    user_id    INTEGER PRIMARY KEY,         -- один клієнт = одна тема в адмін-групі
    thread_id  INTEGER NOT NULL,            -- ID теми (forum topic)
    status     TEXT NOT NULL DEFAULT 'open',-- open / closed
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_tickets_thread ON tickets(thread_id);
"""


@dataclass
class Ticket:
    user_id: int
    thread_id: int
    status: str
    idle_minutes: float = 0.0  # скільки хвилин у зверненні нічого не відбувалося

    @property
    def is_open(self) -> bool:
        return self.status == "open"


async def init(path: str) -> None:
    """Відкриває файл БД (створює, якщо нема) і таблиці. Викликається при старті бота."""
    global _db
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    _db = await aiosqlite.connect(path)
    _db.row_factory = aiosqlite.Row
    # SQLite за замовчуванням НЕ перевіряє REFERENCES. Вмикаємо: повідомлення
    # не може належати клієнту, якого немає в users.
    await _db.execute("PRAGMA foreign_keys = ON")
    await _db.executescript(SCHEMA)
    await _db.commit()
    log.info("База даних: %s", path)


async def close() -> None:
    if _db is not None:
        await _db.close()


# updated_at оновлюється при КОЖНІЙ активності (повідомлення клієнта, відповідь адміна).
# Різниця з поточним часом = простій. julianday — дата як число днів, тож *24*60 = хвилини.
_TICKET_COLUMNS = "*, (julianday('now') - julianday(updated_at)) * 24 * 60 AS idle_minutes"


def _row_to_ticket(row) -> Ticket | None:
    if not row:
        return None
    return Ticket(row["user_id"], row["thread_id"], row["status"], row["idle_minutes"])


async def get_ticket_by_user(user_id: int) -> Ticket | None:
    # "?" — параметр запиту. НІКОЛИ не вставляємо значення в SQL через f-рядок:
    # це відкриває дорогу SQL-ін'єкціям.
    async with _db.execute(f"SELECT {_TICKET_COLUMNS} FROM tickets WHERE user_id = ?", (user_id,)) as cur:
        return _row_to_ticket(await cur.fetchone())


async def get_ticket_by_thread(thread_id: int) -> Ticket | None:
    async with _db.execute(f"SELECT {_TICKET_COLUMNS} FROM tickets WHERE thread_id = ?", (thread_id,)) as cur:
        return _row_to_ticket(await cur.fetchone())


async def save_ticket(user_id: int, thread_id: int, status: str = "open") -> None:
    """Створює звернення або оновлює наявне (upsert)."""
    await _db.execute(
        """INSERT INTO tickets (user_id, thread_id, status) VALUES (?, ?, ?)
           ON CONFLICT(user_id) DO UPDATE SET
               thread_id = excluded.thread_id,
               status = excluded.status,
               updated_at = CURRENT_TIMESTAMP""",
        (user_id, thread_id, status),
    )
    await _db.commit()


async def touch_ticket(user_id: int) -> None:
    """Позначає активність у зверненні (скидає лічильник простою)."""
    await _db.execute("UPDATE tickets SET updated_at = CURRENT_TIMESTAMP WHERE user_id = ?", (user_id,))
    await _db.commit()


async def set_status(user_id: int, status: str) -> None:
    await _db.execute(
        "UPDATE tickets SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
        (status, user_id),
    )
    await _db.commit()


# ---------- клієнти ----------

async def upsert_user(user_id: int, username: str | None, full_name: str) -> None:
    """Новий клієнт — додаємо; відомий — оновлюємо ім'я і час останнього візиту."""
    await _db.execute(
        """INSERT INTO users (user_id, username, full_name) VALUES (?, ?, ?)
           ON CONFLICT(user_id) DO UPDATE SET
               username = excluded.username,
               full_name = excluded.full_name,
               last_seen = CURRENT_TIMESTAMP""",
        (user_id, username, full_name),
    )
    await _db.commit()


# ---------- історія діалогу ----------

async def add_message(user_id: int, role: str, text: str) -> None:
    await _db.execute(
        "INSERT INTO messages (user_id, role, text) VALUES (?, ?, ?)", (user_id, role, text)
    )
    await _db.commit()


async def recent_messages(user_id: int, limit: int, since_hours: int) -> list[dict]:
    """Останні `limit` повідомлень клієнта за `since_hours` годин, від старих до нових."""
    async with _db.execute(
        """SELECT role, text FROM messages
           WHERE user_id = ? AND created_at >= datetime('now', ?)
           ORDER BY id DESC LIMIT ?""",
        (user_id, f"-{since_hours} hours", limit),
    ) as cur:
        rows = await cur.fetchall()
    # Вибрали найновіші (DESC), а моделі потрібен хронологічний порядок — розвертаємо.
    return [{"role": r["role"], "text": r["text"]} for r in reversed(rows)]


async def delete_last_message(user_id: int) -> None:
    await _db.execute(
        "DELETE FROM messages WHERE id = (SELECT MAX(id) FROM messages WHERE user_id = ?)",
        (user_id,),
    )
    await _db.commit()


async def purge_old_messages(days: int) -> int:
    """Видаляє повідомлення, старші за `days` днів. Повертає, скільки видалено."""
    cur = await _db.execute(
        "DELETE FROM messages WHERE created_at < datetime('now', ?)", (f"-{days} days",)
    )
    await _db.commit()
    return cur.rowcount


# ---------- лічильники для лімітів ----------

async def count_questions(since_hours: int, user_id: int | None = None) -> int:
    """Скільки питань (role='user') надійшло за останні `since_hours` годин.

    user_id задано — для одного клієнта; None — для всіх разом.
    Окрема таблиця для лімітів не потрібна: питання вже лежать у messages.
    """
    sql = "SELECT COUNT(*) FROM messages WHERE role = 'user' AND created_at >= datetime('now', ?)"
    params: tuple = (f"-{since_hours} hours",)
    if user_id is not None:
        sql += " AND user_id = ?"
        params += (user_id,)
    async with _db.execute(sql, params) as cur:
        return (await cur.fetchone())[0]


# ---------- статистика ----------

async def stats() -> dict:
    """Цифри для власника бізнесу (/stats в адмін-групі). «Доба» = останні 24 години."""
    queries = {
        "users_total": "SELECT COUNT(*) FROM users",
        "users_new_24h": "SELECT COUNT(*) FROM users WHERE first_seen >= datetime('now', '-1 day')",
        "users_active_24h": "SELECT COUNT(*) FROM users WHERE last_seen >= datetime('now', '-1 day')",
        "questions_24h": "SELECT COUNT(*) FROM messages "
                         "WHERE role = 'user' AND created_at >= datetime('now', '-1 day')",
        "tickets_open": "SELECT COUNT(*) FROM tickets WHERE status = 'open'",
        "tickets_total": "SELECT COUNT(*) FROM tickets",
    }
    result = {}
    for key, sql in queries.items():
        async with _db.execute(sql) as cur:
            result[key] = (await cur.fetchone())[0]
    return result
