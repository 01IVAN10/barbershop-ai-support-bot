"""
Юніт-тести обгортки моделі (bot/llm.py) — без мережі і без ключа API.

Запуск:  python -m unittest tests.test_llm -v
"""
import dataclasses
import unittest
from unittest.mock import patch

from bot import llm
from bot.llm import BotReply, _consistent
from bot.reasons import Reason


class Consistency(unittest.TestCase):
    def check(self, needs_human: bool, reason: Reason) -> tuple[bool, Reason]:
        reply = _consistent(BotReply(answer="текст", needs_human=needs_human, reason=reason))
        return reply.needs_human, reply.reason

    def test_medical_reason_wins_over_needs_human_false(self):
        """Модель суперечить собі щодо невідкладного стану — обираємо безпечніше: людина."""
        for reason in (Reason.EMERGENCY, Reason.MEDICAL):
            with self.subTest(reason=reason):
                self.assertEqual(self.check(False, reason), (True, reason))

    def test_other_reason_without_needs_human_is_dropped(self):
        self.assertEqual(self.check(False, Reason.NO_INFO), (False, Reason.NONE))

    def test_needs_human_without_reason_becomes_no_info(self):
        self.assertEqual(self.check(True, Reason.NONE), (True, Reason.NO_INFO))

    def test_consistent_reply_is_unchanged(self):
        self.assertEqual(self.check(True, Reason.BOOKING), (True, Reason.BOOKING))
        self.assertEqual(self.check(False, Reason.NONE), (False, Reason.NONE))


def _with_key(key: str):
    return patch.object(llm, "_config", dataclasses.replace(llm._config, gemini_api_key=key))


class Client(unittest.TestCase):
    def test_requests_have_a_timeout(self):
        """Без таймауту зависле з'єднання тримало б клієнта з «друкує...» нескінченно."""
        with patch.object(llm, "_client", None), _with_key("test-key"):
            client = llm._get_client()
        self.assertEqual(client._api_client._http_options.timeout, llm.REQUEST_TIMEOUT_MS)

    def test_missing_key_stops_with_clear_message(self):
        with patch.object(llm, "_client", None), _with_key(""):
            with self.assertRaises(SystemExit) as stop:
                llm._get_client()
        self.assertIn("GEMINI_API_KEY", str(stop.exception))


if __name__ == "__main__":
    unittest.main()
