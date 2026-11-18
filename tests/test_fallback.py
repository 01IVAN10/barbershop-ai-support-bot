"""
Юніт-тести обробника вільних повідомлень (bot/handlers/fallback.py) — без Telegram і без моделі.

Запуск:  python -m unittest tests.test_fallback -v

Перевіряємо шлях повідомлення, а не окремі функції: що клієнт отримає телефон, коли
невідкладний стан написано в підписі до фото; що відмова через ліміт у медичному режимі
не ховає телефон; що клієнт не лишається і без відповіді, і без людини.
"""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from bot import guards, handoff
from bot.handlers import fallback
from bot.reasons import Reason
from tests.run_eval import check

MEDICAL_ON = {"medical": True}
PHONE_TEXT = "🚨 Телефонуйте у стаціонар: (000) 000-00-00"
LIMIT_TEXT = "Зараз помічник перевантажений."
ONLY_TEXT = "Поки що я розумію лише текст"


def _message(text=None, caption=None):
    message = MagicMock()
    message.text, message.caption = text, caption
    message.from_user.id = 1
    message.answer = AsyncMock()
    return message


def _sent(message) -> str:
    """Усе, що бот надіслав клієнту через message.answer, одним рядком."""
    return "\n".join(call.args[0] for call in message.answer.call_args_list)


class FallbackCase(unittest.IsolatedAsyncioTestCase):
    """Спільні заглушки: адмін-група, історія, ліміти, модель."""

    def setUp(self):
        history = MagicMock(add=AsyncMock(), get=AsyncMock(return_value=[]), drop_last=AsyncMock())
        self.request_handoff = AsyncMock()
        self.forward_to_admin = AsyncMock(return_value=False)
        self.check_ai_quota = AsyncMock(return_value=None)
        self.ask_llm = AsyncMock()
        for target, name, mock in [
            (fallback, "history", history),
            (fallback, "request_handoff", self.request_handoff),
            (fallback, "forward_to_admin", self.forward_to_admin),
            (fallback.limits, "check_ai_quota", self.check_ai_quota),
            (fallback, "ask_llm", self.ask_llm),
            (fallback, "build_system_prompt", MagicMock(return_value="prompt")),
            (fallback, "ChatActionSender", MagicMock()),
            (fallback, "flood", fallback.FloodGuard(limit=5, window=10)),
            (handoff, "EMERGENCY_TEXT", PHONE_TEXT),
        ]:
            patcher = patch.object(target, name, mock)
            patcher.start()
            self.addCleanup(patcher.stop)

    def model_says(self, answer: str, reason: Reason = Reason.NONE):
        self.ask_llm.return_value = SimpleNamespace(answer=answer, reason=reason)


@patch.dict(guards.SAFETY, MEDICAL_ON, clear=True)
class MedicalBusiness(FallbackCase):
    async def test_emergency_in_photo_caption_gets_phone(self):
        message = _message(caption="Собаку збила машина")
        await fallback.non_text(message)
        self.request_handoff.assert_awaited_once_with(message, Reason.EMERGENCY, "Собаку збила машина")
        self.assertNotIn(ONLY_TEXT, _sent(message))

    async def test_photo_with_emergency_caption_also_reaches_open_ticket(self):
        message = _message(caption="Кіт не дихає")
        await fallback.non_text(message)
        self.forward_to_admin.assert_awaited_once_with(message)  # адмін бачить і саме фото

    async def test_ordinary_caption_is_not_an_emergency(self):
        message = _message(caption="Ось довідка про щеплення")
        await fallback.non_text(message)
        self.request_handoff.assert_not_awaited()
        self.assertIn(ONLY_TEXT, _sent(message))

    async def test_photo_without_caption(self):
        message = _message()
        await fallback.non_text(message)
        self.request_handoff.assert_not_awaited()
        self.assertIn(ONLY_TEXT, _sent(message))

    async def test_text_emergency_comes_before_ticket_limits_and_model(self):
        message = _message(text="Кіт потрапив під машину")
        await fallback.ai_answer(message)
        self.request_handoff.assert_awaited_once_with(message, Reason.EMERGENCY, "Кіт потрапив під машину")
        self.forward_to_admin.assert_not_awaited()
        self.check_ai_quota.assert_not_awaited()
        self.ask_llm.assert_not_awaited()

    async def test_emergency_is_not_blocked_by_flood(self):
        """Шосте повідомлення за 10 секунд — і саме воно «собака не дихає»."""
        self.model_says("Так.")
        for _ in range(5):
            await fallback.ai_answer(_message(text="Скільки коштує прийом?"))
        message = _message(text="Собака не дихає")
        await fallback.ai_answer(message)
        self.request_handoff.assert_awaited_once_with(message, Reason.EMERGENCY, "Собака не дихає")

    async def test_flood_refusal_shows_emergency_phone(self):
        self.model_says("Так.")
        for _ in range(5):
            await fallback.ai_answer(_message(text="Скільки коштує прийом?"))
        message = _message(text="А ще одне питання")
        await fallback.ai_answer(message)
        self.assertIn("пишете дуже швидко", _sent(message))
        self.assertIn(PHONE_TEXT, _sent(message))
        self.assertEqual(self.ask_llm.await_count, 5)

    async def test_flood_does_not_block_conversation_with_admin(self):
        """Альбом із 10 фото у відкрите звернення: адмін має отримати всі 10."""
        self.forward_to_admin.return_value = True
        for _ in range(10):
            await fallback.non_text(_message())
        for _ in range(10):
            await fallback.ai_answer(_message(text="ще деталь"))
        self.assertEqual(self.forward_to_admin.await_count, 20)
        self.ask_llm.assert_not_awaited()

    async def test_limit_refusal_still_shows_emergency_phone(self):
        """Формулювання, якого немає у списку слів: без моделі його не впізнає ніхто,
        тому текст про ліміт не має лишати клієнта без телефону."""
        self.check_ai_quota.return_value = LIMIT_TEXT
        message = _message(text="Собака якась дивна, язик синій")
        await fallback.ai_answer(message)
        self.ask_llm.assert_not_awaited()
        self.assertIn(LIMIT_TEXT, _sent(message))
        self.assertIn(PHONE_TEXT, _sent(message))



SENSITIVE_ON = {"medical": True, "sensitive": {"words": ["евтаназ"], "describe": "евтаназія", "text": "💙"}}


@patch.dict(guards.SAFETY, SENSITIVE_ON, clear=True)
class SensitiveTopic(FallbackCase):
    async def test_price_goes_inside_handoff_message(self):
        """Ціна не надсилається окремо: її покаже передача — після співчуття."""
        question = "Скільки коштує евтаназія кота?"
        self.model_says("Евтаназія котів коштує 1 500 грн.", Reason.SENSITIVE)
        message = _message(text=question)
        await fallback.ai_answer(message)
        message.answer.assert_not_awaited()
        args = self.request_handoff.await_args.args
        self.assertEqual(args[:3], (message, Reason.SENSITIVE, question))
        self.assertIn("1 500 грн", args[3])

    async def test_without_price_question_nothing_extra(self):
        self.model_says("Процедура проходить так…", Reason.SENSITIVE)
        message = _message(text="Як відбувається евтаназія?")
        await fallback.ai_answer(message)
        message.answer.assert_not_awaited()
        self.request_handoff.assert_awaited_once_with(message, Reason.SENSITIVE, "Як відбувається евтаназія?", "")

@patch.dict(guards.SAFETY, {}, clear=True)
class RegularBusiness(FallbackCase):
    async def test_caption_is_not_checked_without_medical_mode(self):
        message = _message(caption="Собаку збила машина")
        await fallback.non_text(message)
        self.request_handoff.assert_not_awaited()
        self.assertIn(ONLY_TEXT, _sent(message))

    async def test_limit_refusal_has_no_medical_text(self):
        self.check_ai_quota.return_value = LIMIT_TEXT
        message = _message(text="Скільки коштує стрижка?")
        await fallback.ai_answer(message)
        self.assertEqual(_sent(message), LIMIT_TEXT)

    async def test_advice_answer_is_shown_to_client(self):
        """Сценарій з рев'ю: відповідь з одного речення з порадою «уточнити» зникала."""
        answer = "Без запису — лише якщо є вільне вікно, тому краще уточнити заздалегідь."
        self.model_says(answer)
        message = _message(text="Чи можна прийти без запису?")
        await fallback.ai_answer(message)
        self.assertEqual(_sent(message), answer)
        self.request_handoff.assert_not_awaited()

    async def test_answer_that_is_only_a_promise_is_handed_to_human(self):
        """Фільтр вирізав усе → клієнт не лишається в порожнечі: питання йде адміну."""
        self.model_says("Я передам ваше питання адміністратору.")
        message = _message(text="Є подарункові сертифікати?")
        await fallback.ai_answer(message)
        message.answer.assert_not_awaited()  # порожній текст не надсилаємо
        self.request_handoff.assert_awaited_once_with(message, Reason.NO_INFO, "Є подарункові сертифікати?")


class EvalOnly(unittest.IsolatedAsyncioTestCase):
    async def test_typo_in_only_names_the_scenario(self):
        """Раніше: --only з помилкою в id → ZeroDivisionError у звіті."""
        from pathlib import Path

        from tests.run_eval import CASES_FILE, run
        with self.assertRaises(SystemExit) as stop:
            await run(1, 0, {"price_haircutt"}, CASES_FILE, Path("unused.md"))
        self.assertIn("price_haircutt", str(stop.exception))


class EvalCheck(unittest.TestCase):
    """Правило тест-набору: клієнт мусить щось побачити (tests/run_eval.py: check)."""

    def test_empty_answer_fails_the_scenario(self):
        problems = check({"needs_human": False}, Reason.NONE, "")
        self.assertTrue(any("нічого не побачив" in p for p in problems))

    def test_visible_answer_passes(self):
        self.assertEqual(check({"needs_human": False}, Reason.NONE, "Так, можна."), [])


if __name__ == "__main__":
    unittest.main()
