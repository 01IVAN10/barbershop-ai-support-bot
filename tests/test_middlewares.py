"""
Юніт-тести антифлуду, відкидання старих повідомлень і щоденного очищення.

Запуск:  python -m unittest tests.test_middlewares -v
"""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from bot import db
from bot.middlewares import FloodGuard, StaleUpdateMiddleware
from tests.support import USER_ID, DbCase


class Flood(unittest.TestCase):
    def test_limit_per_window(self):
        guard = FloodGuard(limit=3, window=10)
        self.assertEqual([guard.allow(USER_ID, now=t) for t in (0, 1, 2, 3)], [True, True, True, False])

    def test_window_slides(self):
        guard = FloodGuard(limit=2, window=10)
        guard.allow(USER_ID, now=0)
        guard.allow(USER_ID, now=1)
        self.assertFalse(guard.allow(USER_ID, now=5))
        self.assertTrue(guard.allow(USER_ID, now=11.5))   # перші дві відмітки вже за вікном

    def test_rejected_messages_do_not_extend_the_block(self):
        """Відхилене повідомлення не рахується: інакше клієнт, який повторює питання,
        блокував би себе нескінченно."""
        guard = FloodGuard(limit=1, window=10)
        guard.allow(USER_ID, now=0)
        for t in (2, 4, 6, 8):
            self.assertFalse(guard.allow(USER_ID, now=t))
        self.assertTrue(guard.allow(USER_ID, now=10.5))

    def test_clients_are_counted_separately(self):
        guard = FloodGuard(limit=1, window=10)
        self.assertTrue(guard.allow(1, now=0))
        self.assertTrue(guard.allow(2, now=0))


class StaleUpdates(unittest.IsolatedAsyncioTestCase):
    async def run_with_age(self, minutes: float) -> bool:
        handler = AsyncMock()
        event = MagicMock(date=datetime.now(timezone.utc) - timedelta(minutes=minutes))
        await StaleUpdateMiddleware(max_age=600)(handler, event, {})
        return handler.await_count == 1

    async def test_messages_sent_during_restart_are_processed(self):
        self.assertTrue(await self.run_with_age(2))

    async def test_old_messages_are_dropped(self):
        self.assertFalse(await self.run_with_age(30))


class Cleanup(DbCase):
    async def age(self, table: str, column: str, days: int, user_id: int) -> None:
        await db._db.execute(f"UPDATE {table} SET {column} = datetime('now', ?) WHERE user_id = ?",
                             (f"-{days} days", user_id))
        await db._db.commit()

    async def test_inactive_clients_are_deleted_with_their_messages(self):
        await db.add_message(USER_ID, "user", "старе питання")
        await self.age("messages", "created_at", 40, USER_ID)
        await self.age("users", "last_seen", 40, USER_ID)
        self.assertEqual(await db.purge_old_messages(30), 1)
        self.assertEqual(await db.purge_inactive_users(30), 1)
        self.assertEqual((await db.stats())["users_total"], 0)

    async def test_active_clients_and_clients_with_topic_stay(self):
        await db.upsert_user(2, None, "Клієнт З Темою")
        await db.set_ticket_thread(2, 77)
        await self.age("users", "last_seen", 40, 2)
        self.assertEqual(await db.purge_inactive_users(30), 0)   # USER_ID активний, у 2 є тема


if __name__ == "__main__":
    unittest.main()
