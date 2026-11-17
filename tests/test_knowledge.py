"""
Юніт-тести перевірки YAML бізнесу при старті (bot/knowledge.py, bot/keyboards.py).

Запуск:  python -m unittest tests.test_knowledge -v

Помилка в YAML має зупиняти бота при старті з поясненням, а не ламати відповідь клієнту.
"""
import copy
import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from aiogram.exceptions import TelegramBadRequest
from unittest.mock import AsyncMock, MagicMock

from bot import hours, keyboards, knowledge, prompts
from bot.handlers import menu
from bot.knowledge import KB, check_required


KYIV = ZoneInfo("Europe/Kyiv")
CLINIC_SCHEDULE = hours.parse_schedule({"regular": {
    **{d: "10:00–17:00" for d in hours.WEEKDAYS[:6]}, "sunday": "вихідний"}})


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


class AfterHoursConfig(unittest.TestCase):
    """ui.after_hours вмикає режим «поза графіком»; помилки в ньому — зупинка при старті."""

    def kb_with(self, after: dict, medical: bool = False) -> dict:
        kb = copy.deepcopy(KB)
        kb["ui"]["after_hours"] = after
        kb.setdefault("safety", {})["medical"] = medical
        return kb

    def test_barbershop_has_no_after_hours(self):
        self.assertIsNone(knowledge.SCHEDULE)
        self.assertIsNone(knowledge.closed_until())

    def test_barbershop_schedule_is_enough(self):
        self.assertEqual(check_required(self.kb_with({"handoff_confirm": "Зачинено, {opens}"})), [])

    def test_bad_schedule_stops_start(self):
        kb = self.kb_with({"handoff_confirm": "x"})
        kb["schedule"]["regular"]["sunday"] = "з 11 до 18"
        self.assertTrue(any("графіка" in p and "з 11 до 18" in p for p in check_required(kb)))

    def test_medical_needs_closed_texts(self):
        problems = check_required(self.kb_with({"handoff_confirm": "x"}, medical=True))
        for key in knowledge.AFTER_HOURS_MEDICAL_KEYS:
            self.assertTrue(any(f"ui.after_hours.{key}" in p for p in problems), problems)

    def test_not_a_section(self):
        self.assertTrue(check_required(self.kb_with("так")))  # type: ignore[arg-type]

    def test_opens_placeholder(self):
        with patch.dict(knowledge.AFTER_HOURS, {"x": "Відкриємося {opens}."}):
            self.assertEqual(knowledge.after_hours_text("x", "завтра з 10:00"), "Відкриємося завтра з 10:00.")
        self.assertEqual(knowledge.after_hours_text("немає", "завтра", default="За замовч. {opens}"),
                         "За замовч. завтра")


class SensitivePrompt(unittest.TestCase):
    """Причину sensitive модель бачить лише в бізнесу з safety.sensitive — промпт інших не змінюється."""

    def test_line_only_with_section(self):
        self.assertNotIn("- sensitive —", prompts.build_rules())
        with patch.dict(knowledge.SAFETY, {"sensitive": {"describe": "евтаназія чи прощання з твариною"}}):
            rules = prompts.build_rules()
        self.assertIn("- sensitive — делікатна тема: евтаназія чи прощання з твариною.", rules)
        self.assertIn("з помилками", rules)


class SensitiveConfig(unittest.TestCase):
    def kb_with(self, sensitive) -> dict:
        kb = copy.deepcopy(KB)
        kb.setdefault("safety", {})["sensitive"] = sensitive
        return kb

    def test_valid(self):
        valid = {"words": ["евтаназ"], "text": "💙 Шкода.", "describe": "евтаназія"}
        self.assertEqual(check_required(self.kb_with(valid)), [])

    def test_problems_are_named(self):
        ok = {"words": ["евтаназ"], "text": "x", "describe": "евтаназія"}
        for bad, expected in (({**ok, "words": None}, "words"), ({**ok, "text": ""}, "text"),
                              ({**ok, "words": [""]}, "words"), ({**ok, "describe": ""}, "describe"),
                              ("так", "розділом")):
            with self.subTest(bad=bad):
                self.assertTrue(any(expected in p for p in check_required(self.kb_with(bad))))


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


class PromptOpenStatus(unittest.TestCase):
    """Рядок «чи відкрито зараз» рахує код — і лише для бізнесу з ui.after_hours."""

    def build(self, moment: datetime, schedule=CLINIC_SCHEDULE) -> str:
        with patch.object(knowledge, "SCHEDULE", schedule), patch.object(knowledge, "now", return_value=moment):
            return prompts.build_system_prompt()

    def test_without_schedule_no_status(self):
        self.assertNotIn("ЧИ ВІДКРИТО ЗАРАЗ", self.build(datetime(2026, 11, 22, 12, tzinfo=KYIV), None))

    def test_sunday_closed(self):
        prompt = self.build(datetime(2026, 11, 22, 12, tzinfo=KYIV))
        self.assertIn("ЗАРАЗ: 2026-11-22 12:00, неділя", prompt)
        self.assertIn("зачинено, відкриється завтра з 10:00", prompt)

    def test_weekday_open(self):
        self.assertIn("відкрито, сьогодні до 17:00", self.build(datetime(2026, 11, 17, 11, tzinfo=KYIV)))


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
