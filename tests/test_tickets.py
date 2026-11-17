"""
Юніт-тести життєвого циклу звернення (bot/tickets.py) і його даних (bot/db.py).

Запуск:  python -m unittest tests.test_tickets -v

Справжня SQLite в пам'яті: перевіряємо самі переходи між станами, а не те, що «викликали
потрібну функцію». Строк простою тут — tickets.IDLE_HOURS (з YAML, за замовчуванням 2 години).
"""
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

from bot import db, hours, knowledge, tickets
from tests.support import THREAD_ID, USER_ID, DbCase, age_ticket

KYIV = ZoneInfo("Europe/Kyiv")
# Пн–Сб 10–17, неділя вихідний. 2026-11-21 — субота, 2026-11-23 — понеділок.
CLINIC_SCHEDULE = hours.parse_schedule({"regular": {
    **{d: "10:00–17:00" for d in hours.WEEKDAYS[:6]}, "sunday": "вихідний"}})


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


class WorkingHoursIdle(DbCase):
    """З графіком простій рахується лише в робочі години (IDLE_HOURS = 2 за замовчуванням)."""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        patcher = patch.object(knowledge, "SCHEDULE", CLINIC_SCHEDULE)
        patcher.start()
        self.addCleanup(patcher.stop)
        await tickets.remember_topic(USER_ID, THREAD_ID)
        await tickets.start(USER_ID)
        # остання активність: субота, 16:55 за Києвом
        last = datetime(2026, 11, 21, 16, 55, tzinfo=KYIV).astimezone(timezone.utc)
        await db._db.execute("UPDATE tickets SET updated_at = ? WHERE user_id = ?",
                             (last.strftime("%Y-%m-%d %H:%M:%S"), USER_ID))
        await db._db.commit()

    def at(self, day: int, hh: int, mm: int = 0):
        return patch.object(knowledge, "now", return_value=datetime(2026, 11, day, hh, mm, tzinfo=KYIV))

    async def test_saturday_request_survives_sunday(self):
        with self.at(22, 20):  # неділя ввечері: 27 годин за годинником, але лише 5 робочих хвилин
            self.assertIsNone(await tickets.expire(USER_ID))
            self.assertIsNotNone(await tickets.active(USER_ID))
            self.assertEqual(await tickets.count_active(), 1)

    async def test_expires_after_working_hours_on_monday(self):
        with self.at(23, 11, 50):  # 5 хв у суботу + 1 год 50 хв у понеділок < 2 год
            self.assertIsNone(await tickets.expire(USER_ID))
        with self.at(23, 12, 0):   # 5 хв + 2 год — строк минув
            self.assertIsNotNone(await tickets.expire(USER_ID))

    def test_limit_text_says_working_hours(self):
        self.assertEqual(tickets.idle_limit_text(), f"{tickets.IDLE_HOURS:g} робочих год")

    def test_without_schedule_text_is_unchanged(self):
        with patch.object(knowledge, "SCHEDULE", None):
            self.assertEqual(tickets.idle_limit_text(), f"{tickets.IDLE_HOURS:g} год")


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
        st = await db.stats()                            # третій клієнт має тему без розмови
        self.assertEqual((st["tickets_total"], await tickets.count_active()), (3, 1))
        self.assertEqual(st["users_total"], 3)


if __name__ == "__main__":
    unittest.main()
