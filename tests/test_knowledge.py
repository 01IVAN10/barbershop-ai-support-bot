"""
Юніт-тести перевірки YAML бізнесу при старті (bot/knowledge.py, bot/keyboards.py).

Запуск:  python -m unittest tests.test_knowledge -v

Помилка в YAML має зупиняти бота при старті з поясненням, а не ламати відповідь клієнту.
"""
import copy
import unittest
from unittest.mock import patch

from aiogram.exceptions import TelegramBadRequest
from unittest.mock import AsyncMock, MagicMock

from bot import keyboards, knowledge, prompts
from bot.handlers import menu
from bot.knowledge import KB, check_required


def _without(path: str) -> dict:
    kb = copy.deepcopy(KB)
    *parents, last = path.split(".")
    node = kb
    for key in parents:
        node = node[key]
    del node[last]
    return kb


class RequiredFields(unittest.TestCase):
    def test_current_business_is_valid(self):
        self.assertEqual(check_required(KB), [])

    def test_missing_fields_are_named(self):
        for path in knowledge.REQUIRED:
            with self.subTest(path=path):
                problems = check_required(_without(path))
                self.assertTrue(any(path in p for p in problems), problems)

    def test_unknown_timezone(self):
        kb = copy.deepcopy(KB)
        kb["schedule"]["timezone"] = "Europe/Kyyiv"
        self.assertTrue(any("невідомий часовий пояс" in p for p in check_required(kb)))


class MenuRenderers(unittest.TestCase):
    def test_contacts_without_instagram(self):
        """Раніше: YAML без business.instagram і кнопка render: contacts → KeyError на натискання."""
        business = {"city": "Київ", "address": "вул. Прикладна, 1", "phone": "+380 00 000 00 00"}
        with patch.dict(KB, {"business": business}):
            text = knowledge.format_contacts()
        self.assertNotIn("Instagram", text)
        self.assertIn("+380 00 000 00 00", text)

    def test_render_with_missing_data_stops_at_start(self):
        with patch.dict(KB):
            KB.pop("masters", None)
            with self.assertRaises(SystemExit) as stop:
                keyboards._check_render("masters", "✂️ Майстри")
        self.assertIn("✂️ Майстри", str(stop.exception))

    def test_master_level_note_only_with_levels(self):
        one_level = [{"name": "Стрижка", "duration": 30, "price": {"ціна": 500}}]
        with patch.dict(KB, {"services": one_level}):
            self.assertNotIn("рівня майстра", knowledge.format_prices())


class PromptTime(unittest.TestCase):
    def test_timezone_name_comes_from_yaml(self):
        with patch.dict(KB["schedule"], {"timezone": "Europe/Warsaw"}):
            self.assertIn("(часовий пояс Europe/Warsaw)", prompts.build_system_prompt())

    def test_kyiv_text_is_unchanged(self):
        with patch.dict(KB["schedule"], {"timezone": "Europe/Kyiv"}):
            self.assertIn("(час Києва)", prompts.build_system_prompt())


class PriceButtonErrors(unittest.IsolatedAsyncioTestCase):
    async def press(self, error_text: str):
        query = MagicMock()
        query.message = MagicMock(spec=menu.Message)
        query.message.edit_text = AsyncMock(side_effect=TelegramBadRequest(method=MagicMock(), message=error_text))
        query.answer = AsyncMock()
        with patch.object(menu, "price_callback_view", return_value=("текст", None)):
            await menu.price_section(query, MagicMock())

    async def test_double_tap_is_not_an_error(self):
        await self.press("Bad Request: message is not modified")

    async def test_other_errors_are_not_hidden(self):
        with self.assertRaises(TelegramBadRequest):
            await self.press("Bad Request: can't parse entities")


if __name__ == "__main__":
    unittest.main()
