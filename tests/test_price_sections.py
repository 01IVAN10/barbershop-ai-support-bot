"""
Юніт-тести прайсу по розділах — без Telegram і без моделі.

Запуск:  python -m unittest tests.test_price_sections -v

Перевіряємо: кнопки будуються з YAML, розділ показує саме свої ціни і примітки,
стара кнопка (прайс змінився) не показує чужий розділ.
"""
import unittest
from unittest.mock import patch

from bot.handlers import menu
from bot.keyboards import PriceSection, price_back_keyboard, price_sections_keyboard
from bot.knowledge import format_price_section, price_section_label, prices_version

PRICES = {
    "title": "Ціни",
    "sections": [
        {"name": "Прийом", "items": [{"name": "Первинний прийом", "price": 500}]},
        {"name": "Стаціонар (24 години; категорію визначає лікар)", "items": [
            {"name": "Стаціонар, 1 категорія", "price": "від 900 ₴"}]},
        {"name": "Кастрація та стерилізація", "button": "Стерилізація",
         "items": [{"name": "Кастрація кота", "price": 1500}]},
    ],
    "notes": ["Остаточну вартість визначає лікар після огляду."],
}


def _buttons(markup):
    return [b for row in markup.inline_keyboard for b in row]


class Labels(unittest.TestCase):
    def test_label_drops_parentheses(self):
        self.assertEqual(price_section_label(PRICES["sections"][1]), "Стаціонар")

    def test_explicit_button_label_wins(self):
        self.assertEqual(price_section_label(PRICES["sections"][2]), "Стерилізація")


class SectionText(unittest.TestCase):
    def test_section_has_only_its_prices_and_notes(self):
        text = format_price_section(PRICES, 0)
        self.assertIn("Первинний прийом — 500 ₴", text)
        self.assertNotIn("Кастрація", text)
        self.assertIn("Остаточну вартість визначає лікар", text)

    def test_text_price_kept_as_is(self):
        self.assertIn("від 900 ₴", format_price_section(PRICES, 1))

    def test_missing_section(self):
        self.assertIsNone(format_price_section(PRICES, 3))
        self.assertIsNone(format_price_section(PRICES, -1))


class Keyboards(unittest.TestCase):
    def test_one_button_per_section_plus_site_link(self):
        buttons = _buttons(price_sections_keyboard(PRICES, "v1", url="https://example.com/prices"))
        self.assertEqual([b.text for b in buttons[:3]], ["Прийом", "Стаціонар", "Стерилізація"])
        self.assertEqual(buttons[3].url, "https://example.com/prices")
        self.assertEqual(PriceSection.unpack(buttons[1].callback_data), PriceSection(version="v1", index=1))

    def test_no_link_without_url(self):
        self.assertEqual(len(_buttons(price_sections_keyboard(PRICES, "v1"))), 3)

    def test_long_labels_get_own_row(self):
        long = {"sections": [{"name": "Чіпування та профілактика", "items": []},
                             {"name": "Кастрація та стерилізація", "items": []}]}
        self.assertEqual(len(price_sections_keyboard(long, "v1").inline_keyboard), 2)

    def test_callback_data_fits_telegram_limit(self):
        many = {"sections": [{"name": f"Розділ {i}", "items": []} for i in range(100)]}
        for b in _buttons(price_sections_keyboard(many, prices_version(many))):
            self.assertLessEqual(len(b.callback_data.encode()), 64)

    def test_back_button_opens_list(self):
        (back,) = _buttons(price_back_keyboard("v1"))
        self.assertEqual(PriceSection.unpack(back.callback_data).index, -1)


class Version(unittest.TestCase):
    def test_changes_when_prices_change(self):
        changed = {**PRICES, "notes": []}
        self.assertNotEqual(prices_version(PRICES), prices_version(changed))
        self.assertEqual(prices_version(PRICES), prices_version(dict(PRICES)))


@patch.object(menu, "PRICES", PRICES)
@patch.object(menu, "PRICES_VERSION", "v1")
@patch.dict(menu.KB["business"], {"price_list_url": None})
class CallbackView(unittest.TestCase):
    def test_section(self):
        text, keyboard = menu.price_callback_view(PriceSection(version="v1", index=2))
        self.assertIn("Кастрація кота — 1500 ₴", text)
        self.assertEqual(_buttons(keyboard)[0].text, "← Усі розділи")

    def test_back_to_list(self):
        text, keyboard = menu.price_callback_view(PriceSection(version="v1", index=-1))
        self.assertIn("Оберіть розділ", text)
        self.assertEqual(len(_buttons(keyboard)), 3)

    def test_old_button_after_price_change_shows_list(self):
        text, _ = menu.price_callback_view(PriceSection(version="old", index=0))
        self.assertIn("Прайс оновився", text)
        self.assertNotIn("Первинний прийом", text)

    def test_unknown_index_shows_list(self):
        text, _ = menu.price_callback_view(PriceSection(version="v1", index=9))
        self.assertIn("Прайс оновився", text)


if __name__ == "__main__":
    unittest.main()
