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
from bot.reasons import Reason

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

    def test_typical_emergencies_from_review(self):
        """Формулювання, які pre_check пропускав: без моделі їх не ловив ніхто."""
        for text in [
            "Кіт потрапив під машину",
            "Собаку переїхала машина",
            "Кота вкусила змія",
            "Собака з'їла шоколад",
            "Кіт з'їв мої таблетки",
            "Кіт зламав лапу",
            "У собаки перелом лапи",
            "У собаки тепловий удар",
            "Кота вдарило струмом",
            "Собака втратила свідомість",
            "Собаці паралізувало задні лапи",
            "У кота кров із рота",
            "Кішка не може народити",
            "My cat collapsed",
        ]:
            with self.subTest(text=text):
                self.assertTrue(detect_emergency(text))

    def test_other_wordings_of_emergencies(self):
        """Ті самі стани іншими словами: інший порядок слів, інший апостроф, інша мова."""
        for text in [
            "Машина збила собаку",
            "Собаку збило авто",
            "Собака попала під колеса",
            "Кіт впав з 5 поверху",
            "Кіт випив антифриз",
            "Собака наїлась шоколаду",
            "Кіт з’їв лілію",
            "Кіт подавився кісткою",
            "У кота кров з носа",
            "Кіт блює кров'ю",
            "Пес наступив на скло, сильно тече кров",
            "У собаки глибока рана",
            "Кішка не може розродитися",
            "Кіт упав і не встає",
            "Собака не може встати",
            "У кота відмовили задні лапи",
            "Собака зомліла",
            "Собака не приходить до тями",
            "Пес перегрівся на сонці",
            "Кіт обпік лапу",
            "Собаку покусали інші собаки",
            "Собаку вкусила оса",
            "У кота піна з рота",
            "У собаки роздуло живіт",
            "Кіт не може попісяти",
            "Кота придавило дверима",
            "My dog ate chocolate",
            "The dog has a broken leg",
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

    def test_similar_words_are_not_emergencies(self):
        """Слова, схожі на невідкладні: клієнт питає про послугу, а не про біду."""
        for text in [
            "Скільки коштує прийом травматолога?",
            "Чи є у вас травматологія?",
            "Do you have a traumatologist?",
            "Збираюсь приїхати машиною, де припаркуватись?",
            "Ми переїхали в інший район, чи можна перенести картку?",
            "Чи можна здати кров з вени натще?",
            "Чи можна взяти тварину під опіку?",
            "Чи можна собаці шоколад?",
            "Кіт з'їв весь корм, скільки коштує дієтичний?",
            "Скільки коштує рентген лапи?",
            "Чи можна оплатити більшу суму частинами?",
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
            "У кота сильний біль",
            "Собаці боляче ходити",
            "У собаки болить живіт",
            "Кіт млявий і тремтить",
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

    def test_words_that_only_look_like_symptoms(self):
        """«біль» не має ловити «більше», а «температура» й «ліки» — питання про клініку."""
        for text in [
            "Чи дорожче стерилізація для собак більше 20 кг?",
            "Чи можна оплатити більшу суму частинами?",
            "Більш детально про стаціонар можна?",
            "Яка температура в стаціонарі?",
            "Чи є аптека, де купити ліки?",
        ]:
            with self.subTest(text=text):
                self.assertFalse(detect_symptom(text))

    def test_ambiguous_words_about_the_pet_are_symptoms(self):
        """Ті самі «температура» й «ліки», але вже про тварину — це медичне питання."""
        for text in [
            "У кота температура",
            "Температура 40, що робити?",
            "У собаки піднялась температура",
            "Чи можна давати людські ліки?",
            "Є ліки для кота від глистів?",
        ]:
            with self.subTest(text=text):
                self.assertTrue(detect_symptom(text))


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

    def test_price_question_with_weight_is_answered(self):
        """«більше 20 кг» — не «біль»: клієнт бачить ціни, а не «я не оцінюю стан тварини»."""
        answer = "Так: 10–30 кг — 4400 ₴, понад 30 кг — 5500 ₴."
        reason, text = resolve("Чи дорожче стерилізація для собак більше 20 кг?", answer, Reason.NONE)
        self.assertEqual(reason, Reason.NONE)
        self.assertTrue(text.startswith(answer))

    def test_traumatologist_is_not_an_emergency(self):
        self.assertIsNone(pre_check("Скільки коштує прийом травматолога?"))
        reason, _ = resolve("Скільки коштує прийом травматолога?", "Такої ціни в мене немає.", Reason.NO_INFO)
        self.assertEqual(reason, Reason.NO_INFO)


SENSITIVE_ON = {
    **MEDICAL_ON,
    "sensitive": {"words": ["евтаназ", "присипи", "попрощат", "кремац"], "text": "💙 Нам дуже шкода.",
                  "describe": "евтаназія чи прощання з твариною"},
}
EUTHANASIA_PRICE = "Евтаназія котів та малих собак — 1 500 грн."


@patch.dict(guards.SAFETY, SENSITIVE_ON, clear=True)
class ResolveSensitiveTopic(unittest.TestCase):
    """safety.sensitive (евтаназія): завжди людина; текст моделі — лише на пряме питання про ціну."""

    def test_price_question_shows_price_and_goes_to_human(self):
        reason, text = resolve("Скільки коштує евтаназія кота?", EUTHANASIA_PRICE, Reason.NONE)
        self.assertEqual(reason, Reason.SENSITIVE)
        self.assertTrue(text.startswith(EUTHANASIA_PRICE))
        self.assertTrue(text.endswith(MEDICAL_ON["price_disclaimer"]))

    def test_without_price_question_model_text_is_hidden(self):
        """Клієнт не питав ціну — перелік цін у відповідь на горе недоречний."""
        for question in ("Думаємо попрощатися з нашою старенькою кішкою, як це відбувається?",
                         "Чи можна бути поруч під час евтаназії?"):
            with self.subTest(question=question):
                self.assertEqual(resolve(question, EUTHANASIA_PRICE, Reason.NO_INFO), (Reason.SENSITIVE, ""))

    def test_sensitive_wins_over_symptom(self):
        """«Хворіє» — симптом, але людині потрібне співчуття, а не «я не оцінюю стан»."""
        reason, _ = resolve("Пес старий і хворіє, думаємо його присипити", "", Reason.MEDICAL)
        self.assertEqual(reason, Reason.SENSITIVE)

    def test_emergency_wins_over_sensitive(self):
        self.assertEqual(resolve("Кіт помирає, мабуть, треба евтаназія", "", Reason.NONE)[0], Reason.EMERGENCY)
        self.assertEqual(resolve("Думаємо про евтаназію", "", Reason.EMERGENCY)[0], Reason.EMERGENCY)

    def test_medical_advice_hidden_even_with_price(self):
        reason, text = resolve("Скільки коштує евтаназія?", "1 500 грн. Дайте коту 5 мг заспокійливого.",
                               Reason.NONE)
        self.assertEqual((reason, text), (Reason.SENSITIVE, ""))

    def test_other_questions_unaffected(self):
        self.assertEqual(resolve("Скільки коштує стерилізація?", "3 000 грн.", Reason.NONE)[0], Reason.NONE)

    def test_model_catches_what_words_miss(self):
        """Помилка в корені, російська, переказ — слів зі списку немає, але модель поставила sensitive."""
        reason, text = resolve("Скільки коштує евтоназія кота?", EUTHANASIA_PRICE, Reason.SENSITIVE)
        self.assertEqual(reason, Reason.SENSITIVE)
        self.assertTrue(text.startswith(EUTHANASIA_PRICE))  # ціну прямо питали
        self.assertEqual(resolve("Щоб він не мучився, допоможіть йому піти", EUTHANASIA_PRICE,
                                 Reason.SENSITIVE), (Reason.SENSITIVE, ""))

    def test_model_sensitive_wins_over_symptom(self):
        reason, _ = resolve("Кіт старий, болить усе, хочемо щоб заснув назавжди", "", Reason.SENSITIVE)
        self.assertEqual(reason, Reason.SENSITIVE)

    def test_without_section_nothing_changes(self):
        with patch.dict(guards.SAFETY, MEDICAL_ON, clear=True):
            self.assertEqual(resolve("Скільки коштує евтаназія?", EUTHANASIA_PRICE, Reason.NONE)[0], Reason.NONE)
            # схема такої причини не дасть, але якщо раптом — не «делікатна тема» без тексту з YAML
            self.assertEqual(resolve("питання", "текст", Reason.SENSITIVE)[0], Reason.NO_INFO)


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

    def test_advice_from_knowledge_base_reaches_client(self):
        """Відповідь з одного речення з порадою «уточнити» — це факт із бази, а не обіцянка.
        Раніше фільтр вирізав її цілком: клієнт не бачив нічого і нікому нічого не передавалось."""
        answer = "Без запису — лише якщо є вільне вікно, тому краще уточнити заздалегідь."
        reason, text = resolve("Чи можна прийти без запису?", answer, Reason.NONE)
        self.assertEqual((reason, text), (Reason.NONE, answer))

    def test_answer_that_is_only_a_promise_goes_to_human(self):
        """Від відповіді нічого не лишилось → пара (none, "") неможлива: передаємо людині."""
        reason, text = resolve("Є сертифікати?", "Я передам ваше питання адміністратору.", Reason.NONE)
        self.assertEqual((reason, text), (Reason.NO_INFO, ""))

    def test_empty_model_answer_goes_to_human(self):
        reason, text = resolve("Є сертифікати?", "  ", Reason.NONE)
        self.assertEqual((reason, text), (Reason.NO_INFO, ""))

    def test_client_always_gets_text_or_human(self):
        for answer in ["", "Уточню.", "Зараз з'єдную з адміністратором.", "Так, можна.", "Краще уточнити."]:
            with self.subTest(answer=answer):
                reason, text = resolve("питання", answer, Reason.NONE)
                self.assertTrue(text or reason != Reason.NONE)


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

    def test_advice_to_client_is_not_a_promise(self):
        """Порада клієнту, що зробити самому, — не обіцянка бота. Ці фрази є в базах знань."""
        for text in [
            "Без запису — лише якщо є вільне вікно, тому краще уточнити заздалегідь.",
            "Так, на ресепшені є віск. Асортимент і ціни уточнює адміністратор.",
            "Зателефонувати або написати в месенджер: клініка підбере зручний час.",
            "Запишіться через кнопку «Записатися» або зв'яжіться з нами за телефоном.",
            "Уточнюйте наявність за телефоном.",
            "Зателефонуйте дорогою — лікар підготує все до приїзду.",
        ]:
            with self.subTest(text=text):
                self.assertEqual(strip_promises(text), text)

    def test_real_promises_are_still_removed(self):
        """Перша особа і «адміністратор зв'яжеться» — те, чого бот не виконує."""
        for text in [
            "Я передам ваше питання адміністратору.",
            "Передаю ваше питання.",
            "Зараз з'єдную вас з адміністратором.",
            "Адміністратор зв’яжеться з вами.",
            "Адміністратор звʼяжеться з вами.",      # апостроф ʼ (U+02BC) — ним пише частина клавіатур
            "З вами зв'яжуться найближчим часом.",
            "Я вас запишу на завтра.",
            "Я записав вас на 15:00.",
            "Ми уточнимо і повідомимо.",
            "Адміністратор вам зателефонує.",
            "Ми вам передзвонимо.",
            "We will contact you soon.",
        ]:
            with self.subTest(text=text):
                self.assertEqual(strip_promises(text), "")


if __name__ == "__main__":
    unittest.main()
