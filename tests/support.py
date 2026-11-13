"""Спільне для юніт-тестів, яким потрібна база: справжня SQLite в пам'яті, несправжній Telegram."""
import logging
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from bot import db

# Тести навмисно викликають помилки (мережа, зникла тема) — їхні записи в лог лише засмічують
# вивід. Що саме сталося, перевіряють самі тести.
logging.disable(logging.CRITICAL)

USER_ID = 1
THREAD_ID = 77
ADMIN_CHAT = -100123


class DbCase(unittest.IsolatedAsyncioTestCase):
    """Кожен тест отримує чисту базу в пам'яті з одним клієнтом."""

    async def asyncSetUp(self):
        await db.init(":memory:")
        await db.upsert_user(USER_ID, "ivan", "Іван Тест")

    async def asyncTearDown(self):
        await db.close()


async def age_ticket(hours: float, user_id: int = USER_ID) -> None:
    """Робить вигляд, що в зверненні нічого не відбувалося `hours` годин."""
    await db._db.execute("UPDATE tickets SET updated_at = datetime('now', ?) WHERE user_id = ?",
                         (f"-{hours * 60:.0f} minutes", user_id))
    await db._db.commit()


def fake_bot() -> MagicMock:
    bot = MagicMock()
    for name in ("send_message", "copy_message", "reopen_forum_topic", "close_forum_topic"):
        setattr(bot, name, AsyncMock())
    bot.create_forum_topic = AsyncMock(return_value=SimpleNamespace(message_thread_id=THREAD_ID))
    return bot


def client_message(bot: MagicMock, text: str = "Привіт") -> MagicMock:
    """Повідомлення клієнта в особистому чаті."""
    message = MagicMock()
    message.bot, message.text, message.caption = bot, text, None
    message.message_id = 10
    message.chat.id = USER_ID
    message.chat.type = "private"
    message.from_user = SimpleNamespace(id=USER_ID, full_name="Іван Тест", username="ivan")
    message.answer = AsyncMock()
    return message


def admin_message(bot: MagicMock, text: str = "Добрий день!") -> MagicMock:
    """Повідомлення адміністратора в темі клієнта."""
    message = MagicMock()
    message.bot, message.text = bot, text
    message.message_id = 20
    message.message_thread_id = THREAD_ID
    message.chat.id = ADMIN_CHAT
    message.reply = AsyncMock()
    return message


def sent_to(mock: AsyncMock) -> str:
    """Усі тексти, надіслані через message.answer / message.reply, одним рядком."""
    return "\n".join(call.args[0] for call in mock.call_args_list)


def sent_to_topic(bot: MagicMock) -> list[str]:
    """Тексти, які бот надіслав в адмін-групу (send_message(chat_id, text, ...))."""
    return [call.args[1] for call in bot.send_message.call_args_list if call.args[0] == ADMIN_CHAT]
