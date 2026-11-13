"""
Юніт-тести передачі розмови людині: bot/handoff.py, bot/handlers/admin.py, bot/limits.py.

Запуск:  python -m unittest tests.test_handoff -v

База — справжня SQLite в пам'яті, Telegram — заглушка. Перевіряємо, що бачить клієнт,
що бачить адмін і в якому стані лишається звернення після кожної події.
"""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError

from bot import db, handoff, history, limits, tickets
from bot.handlers import admin
from bot.knowledge import format_emergency
from bot.reasons import Reason
from tests.support import (ADMIN_CHAT, THREAD_ID, USER_ID, DbCase, admin_message, age_ticket,
                           client_message, fake_bot, sent_to, sent_to_topic)

PHONE_TEXT = "🚨 Телефонуйте у стаціонар: (000) 000-00-00"


def _error(kind):
    return kind(method=MagicMock(), message="помилка для тесту")


class HandoffCase(DbCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.bot = fake_bot()
        for target in (handoff, admin):
            patcher = patch.object(target, "ADMIN_CHAT_ID", ADMIN_CHAT)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(handoff, "EMERGENCY_TEXT", PHONE_TEXT)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def open_ticket(self):
        await tickets.remember_topic(USER_ID, THREAD_ID)
        await tickets.start(USER_ID)


class RequestHandoff(HandoffCase):
    async def test_first_request_creates_topic_and_opens_conversation(self):
        message = client_message(self.bot)
        await handoff.request_handoff(message, Reason.HUMAN_REQUEST, "Покличте людину")
        self.bot.create_forum_topic.assert_awaited_once()
        self.assertIn("Нове звернення", sent_to_topic(self.bot)[0])
        self.assertEqual((await tickets.active(USER_ID)).thread_id, THREAD_ID)
        self.assertIn(handoff.HANDOFF_CONFIRM, sent_to(message.answer))

    async def test_request_during_open_conversation_reuses_topic(self):
        await self.open_ticket()
        message = client_message(self.bot)
        await handoff.request_handoff(message, Reason.BOOKING, "Запишіть мене")
        self.bot.create_forum_topic.assert_not_awaited()
        self.assertTrue(sent_to_topic(self.bot)[0].startswith("➕"))
        self.assertIn("вже на зв'язку", sent_to(message.answer))

    async def test_without_admin_group_client_gets_phone(self):
        message = client_message(self.bot)
        with patch.object(handoff, "ADMIN_CHAT_ID", None):
            await handoff.request_handoff(message, Reason.HUMAN_REQUEST, "Покличте людину")
        self.assertIn(handoff.KB["business"]["phone"], sent_to(message.answer))
        self.assertIsNone(await tickets.get(USER_ID))

    async def test_telegram_failure_falls_back_to_phone(self):
        self.bot.create_forum_topic.side_effect = _error(TelegramBadRequest)
        message = client_message(self.bot)
        await handoff.request_handoff(message, Reason.HUMAN_REQUEST, "Покличте людину")
        self.assertIn(handoff.KB["business"]["phone"], sent_to(message.answer))
        self.assertIsNone(await tickets.active(USER_ID))


class Emergency(HandoffCase):
    async def test_client_gets_phone_and_bot_keeps_answering(self):
        """Картка йде в тему клієнта, але розмова з адміном НЕ відкривається: уночі адмін
        може не читати, а бот не має мовчати."""
        message = client_message(self.bot)
        await handoff.request_handoff(message, Reason.EMERGENCY, "Собаку збила машина")
        self.assertEqual(sent_to(message.answer), PHONE_TEXT)
        self.assertIn("НЕВІДКЛАДНИЙ", sent_to_topic(self.bot)[0])
        ticket = await tickets.get(USER_ID)
        self.assertEqual((ticket.thread_id, ticket.is_open), (THREAD_ID, False))

    async def test_emergency_during_open_conversation_keeps_it_open(self):
        await self.open_ticket()
        message = client_message(self.bot)
        await handoff.request_handoff(message, Reason.EMERGENCY, "Кіт не дихає")
        self.assertEqual(sent_to(message.answer), PHONE_TEXT)
        self.assertTrue(sent_to_topic(self.bot)[0].startswith("➕"))
        self.assertIsNotNone(await tickets.active(USER_ID))

    async def test_phone_is_sent_even_if_admin_group_fails(self):
        self.bot.create_forum_topic.side_effect = _error(TelegramBadRequest)
        message = client_message(self.bot)
        await handoff.request_handoff(message, Reason.EMERGENCY, "Собаку збила машина")
        self.assertEqual(sent_to(message.answer), PHONE_TEXT)

    def test_safety_text_cannot_break_telegram_markup(self):
        """«<» у тексті невідкладного стану зламав би HTML — і телефон не відправився б."""
        with patch.dict(handoff.SAFETY, {"emergency_text": "Вага <5 кг & більше — телефонуйте"}):
            self.assertEqual(handoff._safety_text("emergency_text"), "Вага &lt;5 кг &amp; більше — телефонуйте")
            self.assertEqual(handoff._safety_text("emergency_text"), format_emergency())


class ForwardToAdmin(HandoffCase):
    async def test_message_in_open_conversation_is_copied_to_topic(self):
        await self.open_ticket()
        message = client_message(self.bot)
        self.assertTrue(await handoff.forward_to_admin(message))
        self.assertEqual(self.bot.copy_message.call_args.kwargs["message_thread_id"], THREAD_ID)
        message.answer.assert_not_awaited()

    async def test_without_conversation_message_goes_to_ai(self):
        message = client_message(self.bot)
        self.assertFalse(await handoff.forward_to_admin(message))
        self.bot.copy_message.assert_not_awaited()

    async def test_expired_conversation_tells_client_and_admin(self):
        """Клієнт подав заявку ввечері, пише вранці: звернення вже прострочене. Він бачив
        «усе, що напишете далі, побачить адміністратор» — тож має дізнатись, що це вже не так."""
        await self.open_ticket()
        await age_ticket(tickets.IDLE_HOURS + 1)
        message = client_message(self.bot)
        self.assertFalse(await handoff.forward_to_admin(message))   # повідомлення піде до AI
        self.assertEqual(sent_to(message.answer), handoff.TICKET_EXPIRED_TEXT)
        self.assertIn("закрито автоматично", sent_to_topic(self.bot)[0])
        self.bot.close_forum_topic.assert_awaited_once()
        self.assertFalse((await tickets.get(USER_ID)).is_open)

    async def test_conversation_within_idle_time_survives(self):
        await self.open_ticket()
        await age_ticket(tickets.IDLE_HOURS / 2)
        self.assertTrue(await handoff.forward_to_admin(client_message(self.bot)))

    async def test_network_error_keeps_conversation_open(self):
        """Мережа чи ліміт запитів — тимчасове: розмова з адміном не має мовчки перейти до AI."""
        await self.open_ticket()
        self.bot.copy_message.side_effect = _error(TelegramNetworkError)
        message = client_message(self.bot)
        self.assertTrue(await handoff.forward_to_admin(message))    # до AI НЕ йде
        self.assertEqual(sent_to(message.answer), handoff.DELIVERY_FAILED_TEXT)
        self.assertIsNotNone(await tickets.active(USER_ID))

    async def test_deleted_topic_closes_conversation(self):
        for error in (TelegramBadRequest, TelegramForbiddenError):
            with self.subTest(error=error.__name__):
                await self.open_ticket()
                self.bot.copy_message.side_effect = _error(error)
                self.assertFalse(await handoff.forward_to_admin(client_message(self.bot)))
                self.assertIsNone(await tickets.active(USER_ID))


class AdminCard(HandoffCase):
    QUESTION = "Є подарункові сертифікати?"
    ANSWER = "Такої інформації в мене немає."

    async def card(self, reason=Reason.NO_INFO) -> str:
        await handoff.request_handoff(client_message(self.bot), reason, self.QUESTION)
        return sent_to_topic(self.bot)[0]

    async def test_current_question_is_shown_once_with_bot_answer(self):
        """AI-шлях: питання і відповідь бота вже в історії. У картці питання — один раз,
        а відповідь на нього підписана як відповідь, а не як «розмова до цього»."""
        await history.add(USER_ID, "user", self.QUESTION)
        await history.add(USER_ID, "assistant", self.ANSWER)
        card = await self.card()
        self.assertEqual(card.count(self.QUESTION), 1)
        self.assertIn(f"🤖 Бот відповів: {self.ANSWER}", card)
        self.assertNotIn("Розмова з ботом до цього", card)

    async def test_earlier_conversation_is_shown_separately(self):
        await history.add(USER_ID, "user", "Скільки коштує стрижка?")
        await history.add(USER_ID, "assistant", "650 грн.")
        await history.add(USER_ID, "user", self.QUESTION)
        await history.add(USER_ID, "assistant", self.ANSWER)
        card = await self.card()
        before = card.split("Розмова з ботом до цього")[1]
        self.assertIn("Скільки коштує стрижка?", before)
        self.assertNotIn(self.QUESTION, before)
        self.assertNotIn(self.ANSWER, before)

    async def test_handoff_mark_is_not_shown_as_bot_answer(self):
        """Запис: текст моделі приховано, в історії лише позначка передачі."""
        await history.add(USER_ID, "user", self.QUESTION)
        await history.add(USER_ID, "assistant", handoff.HANDOFF_MARK)
        card = await self.card(Reason.BOOKING)
        self.assertEqual(card.count(self.QUESTION), 1)
        self.assertNotIn("Бот відповів", card)

    async def test_button_press_keeps_whole_history(self):
        await history.add(USER_ID, "user", "Скільки коштує стрижка?")
        await history.add(USER_ID, "assistant", "650 грн.")
        await handoff.request_handoff(client_message(self.bot), Reason.HUMAN_REQUEST,
                                      f"{handoff.BUTTON_PREFIX} «👤 Адміністратор»")
        card = sent_to_topic(self.bot)[0]
        self.assertIn("Скільки коштує стрижка?", card)
        self.assertIn("650 грн.", card)


class AdminGroup(HandoffCase):
    async def test_close_command_closes_and_tells_client(self):
        await self.open_ticket()
        message = admin_message(self.bot, "/close")
        await admin.close_ticket(message)
        self.assertIsNone(await tickets.active(USER_ID))
        self.assertEqual(self.bot.send_message.call_args_list[0].args[0], USER_ID)
        self.assertIn("закрито", sent_to(message.reply))

    async def test_close_in_foreign_topic(self):
        message = admin_message(self.bot, "/close")
        await admin.close_ticket(message)
        self.assertIn("не пов'язана", sent_to(message.reply))

    async def test_admin_reply_reaches_client_and_reopens_closed_conversation(self):
        await tickets.remember_topic(USER_ID, THREAD_ID)          # тема є, розмова закрита
        await admin.admin_reply(admin_message(self.bot))
        self.assertEqual(self.bot.copy_message.call_args.kwargs["chat_id"], USER_ID)
        self.assertIsNotNone(await tickets.active(USER_ID))

    async def test_admin_reply_revives_stale_conversation(self):
        await self.open_ticket()
        await age_ticket(tickets.IDLE_HOURS + 1)
        await admin.admin_reply(admin_message(self.bot))
        self.assertIsNotNone(await tickets.active(USER_ID))

    async def test_blocked_bot_is_reported_and_conversation_stays_closed(self):
        await tickets.remember_topic(USER_ID, THREAD_ID)
        self.bot.copy_message.side_effect = _error(TelegramForbiddenError)
        message = admin_message(self.bot)
        await admin.admin_reply(message)
        self.assertIn("заблокував", sent_to(message.reply))
        self.assertIsNone(await tickets.active(USER_ID))

    async def test_stats_show_clients_with_topic_and_live_conversations(self):
        await self.open_ticket()
        message = admin_message(self.bot, "/stats")
        await admin.show_stats(message)
        text = sent_to(message.reply)
        self.assertIn("Клієнтів із темою в цій групі: 1", text)
        self.assertIn("Відкритих розмов зараз: 1", text)


class AiLimits(DbCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.bot = fake_bot()
        cfg = SimpleNamespace(ai_limit_user_hour=2, ai_limit_global_day=3, admin_chat_id=ADMIN_CHAT)
        for name, value in (("_cfg", cfg), ("_admin_warned_on", None)):
            patcher = patch.object(limits, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def ask(self, times: int, user_id: int = USER_ID):
        for _ in range(times):
            await db.add_message(user_id, "user", "питання")

    async def test_under_limits_ai_answers(self):
        await self.ask(1)
        self.assertIsNone(await limits.check_ai_quota(self.bot, USER_ID))

    async def test_answers_of_the_bot_do_not_count(self):
        await db.add_message(USER_ID, "assistant", "відповідь")
        await db.add_message(USER_ID, "assistant", "відповідь")
        self.assertIsNone(await limits.check_ai_quota(self.bot, USER_ID))

    async def test_client_hourly_limit(self):
        await self.ask(2)
        self.assertIsNotNone(await limits.check_ai_quota(self.bot, USER_ID))
        await db.upsert_user(2, None, "Другий Клієнт")           # іншого клієнта це не зачіпає
        self.assertIsNone(await limits.check_ai_quota(self.bot, 2))
        self.bot.send_message.assert_not_awaited()                # адміна не турбуємо

    async def test_global_daily_limit_warns_admin_once(self):
        await db.upsert_user(2, None, "Другий Клієнт")
        await self.ask(2)
        await self.ask(1, user_id=2)
        self.assertIsNotNone(await limits.check_ai_quota(self.bot, 2))
        self.assertIsNotNone(await limits.check_ai_quota(self.bot, 2))
        self.assertEqual(len(sent_to_topic(self.bot)), 1)


if __name__ == "__main__":
    unittest.main()
