"""
Юніт-тести за результатами перевірки безпеки.

Запуск:  python -m unittest tests.test_security -v

1. Логи хостингу не містять тексту відповідей моделі: вона може повторити ім'я чи телефон
   клієнта, а логи не чистяться через 30 днів, як база.
2. ADMIN_IDS: якщо задано, писати клієнтам, /close і /stats можуть лише ці учасники групи.
"""
import logging
import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from aiogram import F

from bot import guards
from bot.config import load_config
from bot.handlers import admin
from bot.reasons import Reason

PERSONAL = "Олено, я передам ваш номер 0671234567 адміністратору, вам передзвонять."


class NoClientDataInLogs(unittest.TestCase):
    def setUp(self):
        # Інші тести вимикають логи (tests/support.py) — тут вони потрібні.
        previous = logging.root.manager.disable
        logging.disable(logging.NOTSET)
        self.addCleanup(logging.disable, previous)

    def logs_of(self, call) -> str:
        with self.assertLogs("bot", level="DEBUG") as captured:
            logging.getLogger("bot").debug("маркер, щоб assertLogs не падав на порожньому")
            call()
        return "\n".join(captured.output)

    def test_promise_filter_logs_no_text(self):
        """Сценарій із перевірки: ім'я й номер потрапляли в лог двічі."""
        with patch.dict(guards.SAFETY, {}, clear=True):
            out = self.logs_of(lambda: guards.resolve("Перезвоніть мені", PERSONAL, Reason.NONE))
        self.assertIn("Прибрано обіцянку", out)
        self.assertIn("Порожня відповідь", out)
        self.assertNotIn("0671234567", out)
        self.assertNotIn("Олено", out)

    def test_medical_advice_logs_no_text(self):
        answer = "Олено, дайте коту 5 мг препарату, номер 0671234567 записала."
        with patch.dict(guards.SAFETY, {"medical": True}, clear=True):
            out = self.logs_of(lambda: guards.resolve("Що є в аптеці?", answer, Reason.NONE))
        self.assertIn("медичну пораду", out)
        self.assertNotIn("0671234567", out)


def _group_message(user_id: int | None, text: str = "Добрий день", thread: int | None = 77):
    return SimpleNamespace(
        from_user=SimpleNamespace(id=user_id) if user_id is not None else None,
        text=text, message_thread_id=thread, chat=SimpleNamespace(id=admin.ADMIN_CHAT_ID),
    )


class AdminAllowList(unittest.TestCase):
    def test_without_list_everyone_in_group_is_admin(self):
        with patch.object(admin, "ADMIN_IDS", frozenset()):
            self.assertTrue(admin.is_admin(_group_message(5)))

    def test_with_list_only_listed_members(self):
        with patch.object(admin, "ADMIN_IDS", frozenset({1, 2})):
            self.assertTrue(admin.is_admin(_group_message(2)))
            self.assertFalse(admin.is_admin(_group_message(5)))
            self.assertFalse(admin.is_admin(_group_message(None)))   # анонімний адмін групи

    def test_router_filter_blocks_strangers_before_admin_handlers(self):
        """Той самий фільтр, що в декораторі: сторонній не дійде до /close, /stats і пересилки."""
        stranger_filter = ~F.func(admin.is_admin)
        with patch.object(admin, "ADMIN_IDS", frozenset({1})):
            self.assertTrue(stranger_filter.resolve(_group_message(5)))
            self.assertFalse(stranger_filter.resolve(_group_message(1)))
        handlers = [h.callback.__name__ for h in admin.router.message.handlers]
        guard = handlers.index("not_an_admin")
        for name in ("show_stats", "close_ticket", "admin_reply"):
            self.assertLess(guard, handlers.index(name), name)

    def test_admin_ids_from_env(self):
        with patch.dict(os.environ, {"ADMIN_IDS": "123, 456"}):
            self.assertEqual(load_config().admin_ids, frozenset({123, 456}))
        with patch.dict(os.environ, {"ADMIN_IDS": ""}):
            self.assertEqual(load_config().admin_ids, frozenset())

    def test_bad_admin_ids_stop_with_explanation(self):
        with patch.dict(os.environ, {"ADMIN_IDS": "@ivan"}), self.assertRaises(SystemExit) as stop:
            load_config()
        self.assertIn("ADMIN_IDS", str(stop.exception))

    def test_stranger_is_logged_not_answered(self):
        message = _group_message(5)
        message.reply = MagicMock()
        previous = logging.root.manager.disable
        logging.disable(logging.NOTSET)
        self.addCleanup(logging.disable, previous)
        with self.assertLogs("bot.handlers.admin", level="WARNING"):
            import asyncio
            asyncio.run(admin.not_an_admin(message))
        message.reply.assert_not_called()


if __name__ == "__main__":
    unittest.main()
