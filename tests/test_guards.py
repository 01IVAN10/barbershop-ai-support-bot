"""
Юніт-тести захисних перевірок (bot/guards.py) — без моделі і без мережі, за секунду.

Запуск:  python -m unittest tests.test_guards -v

Що тут перевіряємо: гарантії, які дає КОД, а не модель. Модель можна «вмовити»,
регулярний вираз — ні. Тому для медичного режиму ці тести важливіші за eval:
eval показує, як часто модель помиляється, а ці — що код помилку перехопить.
"""
import unittest
from unittest.mock import patch

from bot import guards
from bot.guards import (
    detect_emergency,
    detect_symptom,
    has_medical_advice,
    pre_check,
    resolve,
    strip_promises,
)
from bot.llm import Reason

MEDICAL_ON = {
    "medical": True,
    "price_disclaimer": "Остаточну вартість визначає лікар після огляду.",
}


class EmergencyDetection(unittest.TestCase):
    def test_emergencies_are_detected(self):
        for text in [
            "Собаку збила машина",
            "Кіт отруївся, що робити?",
            "У собаки судоми",
            "Кіт не дихає",
            "Сильна кровотеча з лапи",
            "Пес задихається",
            "У кота важко дихає і хрипить",
            "Кошка выпала из окна",
            "Собака проковтнула кістку",
            "Кіт без свідомості",
            "My dog was hit by a car",
            "Моя собака отравилась",
            "Кіт отримав травму",
        ]:
            with self.subTest(text=text):
                self.assertTrue(detect_emergency(text))

    def test_ordinary_questions_are_not_emergencies(self):
        for text in [
            "Скільки коштує вакцинація?",
            "Які у вас години роботи?",
            "Скільки коштує аналіз крові?",
            "Де ви знаходитесь?",
            "Ви працюєте вночі?",
            "Чи можна оплатити карткою?",
        ]:
            with self.subTest(text=text):
                self.assertFalse(detect_emergency(text))


class SymptomDetection(unittest.TestCase):
    def test_symptoms_are_detected(self):
        for text in [
            "Кіт другий день не їсть, що дати?",
            "Собака кульгає на задню лапу",
            "У кота свербіж",
            "Собаку нудить",
            "The cat is vomiting",
            "Які ліки дати собаці?",
        ]:
            with self.subTest(text=text):
                self.assertTrue(detect_symptom(text))

    def test_service_questions_are_not_symptoms(self):
        for text in [
            "Скільки коштує стерилізація кішки?",
            "Чи працюєте під час відключень світла?",
            "Яка адреса стаціонару?",
            "Чи приймаєте папуг?",
        ]:
            with self.subTest(text=text):
                self.assertFalse(detect_symptom(text))


class MedicalAdviceDetection(unittest.TestCase):
    def test_advice_is_detected(self):
        for text in [
            "Дайте коту 5 мг на кілограм.",
            "Можна дати активоване вугілля.",
            "Дайте йому антибіотик.",
            "Доза — 0,5 мл/кг.",
        ]:
            with self.subTest(text=text):
                self.assertTrue(has_medical_advice(text))

    def test_prices_and_vaccines_are_not_advice(self):
        for text in [
            "Первинний прийом коштує 950 ₴.",
            "Nobivac Rabies — вакцинація проти сказу, 900 ₴.",
            "Стаціонар працює цілодобово.",
        ]:
            with self.subTest(text=text):
                self.assertFalse(has_medical_advice(text))


@patch.dict(guards.SAFETY, MEDICAL_ON, clear=True)
class ResolveMedicalMode(unittest.TestCase):
    def test_emergency_skips_model(self):
        self.assertEqual(pre_check("Собаку збила машина"), Reason.EMERGENCY)
        self.assertIsNone(pre_check("Скільки коштує прийом?"))

    def test_symptom_question_goes_to_human_without_model_text(self):
        reason, text = resolve("Кіт не їсть, що робити?", "Спробуйте дати йому воду.", Reason.NONE)
        self.assertEqual(reason, Reason.MEDICAL)
        self.assertEqual(text, "")

    def test_symptom_overrides_booking(self):
        reason, _ = resolve("Запишіть кота, він кашляє", "", Reason.BOOKING)
        self.assertEqual(reason, Reason.MEDICAL)

    def test_medical_advice_in_answer_is_hidden(self):
        reason, text = resolve("Що у вас є в аптеці?", "Дайте коту 5 мг препарату.", Reason.NONE)
        self.assertEqual(reason, Reason.MEDICAL)
        self.assertEqual(text, "")

    def test_model_emergency_and_medical_hide_text(self):
        for model_reason in (Reason.EMERGENCY, Reason.MEDICAL):
            with self.subTest(reason=model_reason):
                reason, text = resolve("питання", "будь-який текст", model_reason)
                self.assertEqual(reason, model_reason)
                self.assertEqual(text, "")

    def test_price_note_is_added_once(self):
        _, text = resolve("Скільки коштує первинний прийом?", "Первинний прийом — 950 ₴.", Reason.NONE)
        self.assertTrue(text.endswith(MEDICAL_ON["price_disclaimer"]))
        _, again = resolve("Скільки коштує прийом?",
                           "Прийом — 950 ₴. Остаточну вартість визначає лікар після огляду.", Reason.NONE)
        self.assertEqual(again.count("Остаточну вартість"), 1)

    def test_no_price_no_note(self):
        _, text = resolve("Де ви?", "вул. Прикладна, 1.", Reason.NONE)
        self.assertEqual(text, "вул. Прикладна, 1.")


@patch.dict(guards.SAFETY, {}, clear=True)
class ResolveRegularBusiness(unittest.TestCase):
    """Бізнес без медичного режиму (барбершоп) — поведінка як до змін."""

    def test_medical_reasons_become_no_info(self):
        for model_reason in (Reason.EMERGENCY, Reason.MEDICAL):
            with self.subTest(reason=model_reason):
                reason, _ = resolve("питання", "текст", model_reason)
                self.assertEqual(reason, Reason.NO_INFO)

    def test_no_emergency_precheck(self):
        self.assertIsNone(pre_check("Мене збила машина"))

    def test_symptom_words_do_not_change_reason(self):
        reason, text = resolve("Болить голова, можна прийти на стрижку?", "Так, можна.", Reason.NONE)
        self.assertEqual(reason, Reason.NONE)
        self.assertEqual(text, "Так, можна.")

    def test_no_price_note(self):
        _, text = resolve("Скільки коштує стрижка?", "Стрижка — 650 грн.", Reason.NONE)
        self.assertEqual(text, "Стрижка — 650 грн.")

    def test_booking_text_hidden_as_before(self):
        reason, text = resolve("Запишіть мене", "Скористайтеся кнопкою.", Reason.BOOKING)
        self.assertEqual((reason, text), (Reason.BOOKING, ""))

    def test_promises_are_stripped(self):
        _, text = resolve("Є сертифікати?", "Такої інформації немає. Я передам ваше питання.", Reason.NONE)
        self.assertEqual(text, "Такої інформації немає.")


class StripPromises(unittest.TestCase):
    """Фільтр обіцянок вирізає лише речення з обіцянкою і не чіпає решту тексту."""

    def test_text_without_promises_is_unchanged(self):
        for text in [
            "Повний прайс: https://example.com.ua/prices/ Остаточну вартість визначає лікар.",
            "Доза 1.5 мл? Ні, це скаже лікар.",
            "Ціни:\n- Стрижка — 650 грн\n- Борода — 400 грн\n\nЗапис через адміністратора.",
        ]:
            with self.subTest(text=text):
                self.assertEqual(strip_promises(text), text)

    def test_promise_removed_link_kept(self):
        text = "Прайс: https://example.com.ua/prices/. Я передам ваше питання адміну. Гарного дня!"
        self.assertEqual(strip_promises(text), "Прайс: https://example.com.ua/prices/. Гарного дня!")

    def test_promise_on_own_line_keeps_other_lines(self):
        text = "Стрижка — 650 грн.\nЯ вас запишу на завтра.\nАдреса: вул. Прикладна, 1."
        self.assertEqual(strip_promises(text), "Стрижка — 650 грн.\nАдреса: вул. Прикладна, 1.")

    def test_english_promise_removed(self):
        text = "We don't have that info. I'll pass your question to the admin."
        self.assertEqual(strip_promises(text), "We don't have that info.")


if __name__ == "__main__":
    unittest.main()
