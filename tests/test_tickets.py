"""
Юніт-тести життєвого циклу звернення (bot/tickets.py) і його даних (bot/db.py).

Запуск:  python -m unittest tests.test_tickets -v

Справжня SQLite в пам'яті: перевіряємо самі переходи між станами, а не те, що «викликали
потрібну функцію». Строк простою тут — tickets.IDLE_HOURS (з YAML, за замовчуванням 2 години).
"""
import unittest
from unittest.mock import patch

from bot import db, tickets
from tests.support import THREAD_ID, USER_ID, DbCase, age_ticket


class Lifecycle(DbCase):
    async def test_new_topic_does_not_open_a_conversation(self):
        """Тему створили (напр. для картки невідкладного стану) — бот не має замовкнути."""
        await tickets.remember_topic(USER_ID, THREAD_ID)
        ticket = await tickets.get(USER_ID)
        self.assertEqual((ticket.thread_id, ticket.is_open), (THREAD_ID, False))
        self.assertIsNone(await tickets.active(USER_ID))

    async def test_start_opens_and_close_closes(self):
        await tickets.remember_topic(USER_ID, THREAD_ID)
        await tickets.start(USER_ID)
        self.assertEqual((await tickets.active(USER_ID)).thread_id, THREAD_ID)
        await tickets.close(USER_ID)
        self.assertIsNone(await tickets.active(USER_ID))

    async def test_new_topic_for_open_conversation_keeps_it_open(self):
        """Адмін видалив тему посеред розмови → нова тема, розмова триває."""
        await tickets.remember_topic(USER_ID, THREAD_ID)
        await tickets.start(USER_ID)
        await tickets.remember_topic(USER_ID, 555)
        ticket = await tickets.active(USER_ID)
        self.assertEqual((ticket.thread_id, ticket.is_open), (555, True))

    async def test_stale_conversation_is_not_active_and_expires_once(self):
        await tickets.remember_topic(USER_ID, THREAD_ID)
        await tickets.start(USER_ID)
        await age_ticket(tickets.IDLE_HOURS + 1)
        self.assertIsNone(await tickets.active(USER_ID))          # active нічого не змінює
        self.assertTrue((await tickets.get(USER_ID)).is_open)
        expired = await tickets.expire(USER_ID)                    # expire закриває і повертає
        self.assertEqual(expired.thread_id, THREAD_ID)
        self.assertFalse((await tickets.get(USER_ID)).is_open)
        self.assertIsNone(await tickets.expire(USER_ID))           # вдруге прострочувати нічого

    async def test_fresh_conversation_does_not_expire(self):
        await tickets.remember_topic(USER_ID, THREAD_ID)
        await tickets.start(USER_ID)
        await age_ticket(tickets.IDLE_HOURS / 2)
        self.assertIsNone(await tickets.expire(USER_ID))
        self.assertIsNotNone(await tickets.active(USER_ID))

    async def test_touch_resets_idle_timer(self):
        await tickets.remember_topic(USER_ID, THREAD_ID)
        await tickets.start(USER_ID)
        await age_ticket(tickets.IDLE_HOURS + 1)
        await tickets.touch(USER_ID)
        self.assertIsNotNone(await tickets.active(USER_ID))

    async def test_lookup_by_thread(self):
        await tickets.remember_topic(USER_ID, THREAD_ID)
        self.assertEqual((await tickets.by_thread(THREAD_ID)).user_id, USER_ID)
        self.assertIsNone(await tickets.by_thread(999))

    async def test_client_without_topic(self):
        self.assertIsNone(await tickets.get(USER_ID))
        self.assertIsNone(await tickets.active(USER_ID))
        self.assertIsNone(await tickets.expire(USER_ID))


class IdleHoursSetting(unittest.TestCase):
    def test_default_is_two_hours(self):
        with patch.dict(tickets.UI, {}, clear=True):
            self.assertEqual(tickets._idle_hours(), 2)

    def test_value_comes_from_yaml(self):
        with patch.dict(tickets.UI, {"ticket_idle_hours": 16}):
            self.assertEqual(tickets._idle_hours(), 16)

    def test_bad_value_stops_the_bot_at_start(self):
        for bad in (0, -1, "дві", True):
            with self.subTest(value=bad), patch.dict(tickets.UI, {"ticket_idle_hours": bad}):
                with self.assertRaises(SystemExit):
                    tickets._idle_hours()


class Stats(DbCase):
    async def test_open_count_skips_stale_conversations(self):
        """«Відкритих» — це живі розмови, а не все, що колись відкрили і не закрили."""
        await db.upsert_user(2, None, "Другий Клієнт")
        await db.upsert_user(3, None, "Третій Клієнт")
        for user_id, thread_id in ((USER_ID, 77), (2, 78), (3, 79)):
            await tickets.remember_topic(user_id, thread_id)
        await tickets.start(USER_ID)                     # жива розмова
        await tickets.start(2)
        await age_ticket(tickets.IDLE_HOURS + 1, user_id=2)  # прострочена, але ще значиться open
        st = await db.stats(tickets.IDLE_HOURS)          # третій клієнт має тему без розмови
        self.assertEqual((st["tickets_total"], st["tickets_open"]), (3, 1))
        self.assertEqual(st["users_total"], 3)


if __name__ == "__main__":
    unittest.main()
