"""Робочий час: чи відкрито, коли відкриється, скільки робочих хвилин минуло.

Графік тут свій, а не з YAML бізнесу: модуль чистий, і перевіряємо саму логіку.
Дні: 2026-11-17 — вівторок, 2026-11-21 — субота, 2026-11-22 — неділя.
"""
import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo

from bot.hours import (ScheduleError, describe_opening, is_open, next_opening, parse_hours,
                       parse_schedule, working_minutes)

KYIV = ZoneInfo("Europe/Kyiv")
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday")

# Пн–Сб 10–17, неділя — вихідний (як у клініки з плану)
CLINIC = {
    "regular": {**{d: "10:00–17:00" for d in WEEKDAYS}, "sunday": "вихідний"},
    "exceptions": [
        {"date": "2026-12-31", "hours": "10:00-14:00"},
        {"date": date(2027, 1, 1), "hours": "вихідний"},  # YAML без лапок дає дату
    ],
}


def at(day: int, hh: int, mm: int = 0, month: int = 11, year: int = 2026) -> datetime:
    return datetime(year, month, day, hh, mm, tzinfo=KYIV)


class ParseTest(unittest.TestCase):
    def test_hours_formats(self):
        for text in ("10:00–17:00", "10:00-17:00", "10:00 — 17:00", " 9:30–17:00 "):
            with self.subTest(text=text):
                start, end = parse_hours(text)
                self.assertEqual((end.hour, end.minute), (17, 0))
        for closed in ("вихідний", "Вихідний", None, "", "closed"):
            with self.subTest(closed=closed):
                self.assertIsNone(parse_hours(closed))

    def test_bad_hours(self):
        for text in ("з 10 до 17", "25:00–26:00", "17:00–10:00", "10:00–10:00"):
            with self.subTest(text=text), self.assertRaises(ScheduleError):
                parse_hours(text)

    def test_schedule_needs_all_days(self):
        with self.assertRaisesRegex(ScheduleError, "sunday"):
            parse_schedule({"regular": {d: "10:00–17:00" for d in WEEKDAYS}})
        with self.assertRaisesRegex(ScheduleError, "schedule.regular"):
            parse_schedule({"timezone": "Europe/Kyiv"})

    def test_schedule_needs_working_day(self):
        with self.assertRaisesRegex(ScheduleError, "жодного"):
            parse_schedule({"regular": {d: "вихідний" for d in (*WEEKDAYS, "sunday")}})

    def test_bad_exception_date(self):
        with self.assertRaisesRegex(ScheduleError, "РРРР-ММ-ДД"):
            parse_schedule({**CLINIC, "exceptions": [{"date": "31.12", "hours": "вихідний"}]})

    def test_barbershop_schedule_parses(self):
        """Формат барбершопу (data/business.yaml) читається тим самим кодом."""
        from bot.knowledge import KB
        schedule = parse_schedule(KB["schedule"])
        self.assertEqual(len(schedule.regular), 7)


class OpenTest(unittest.TestCase):
    def setUp(self):
        self.s = parse_schedule(CLINIC)

    def test_boundaries(self):
        self.assertFalse(is_open(self.s, at(17, 9, 59)))
        self.assertTrue(is_open(self.s, at(17, 10, 0)))
        self.assertTrue(is_open(self.s, at(17, 16, 59)))
        self.assertFalse(is_open(self.s, at(17, 17, 0)))  # о 17:00 уже зачинено

    def test_sunday_closed(self):
        self.assertFalse(is_open(self.s, at(22, 12)))

    def test_exceptions(self):
        self.assertFalse(is_open(self.s, at(31, 15, month=12)))  # скорочений день
        self.assertTrue(is_open(self.s, at(31, 13, month=12)))
        self.assertFalse(is_open(self.s, at(1, 12, month=1, year=2027)))  # свято


class NextOpeningTest(unittest.TestCase):
    def setUp(self):
        self.s = parse_schedule(CLINIC)

    def opens(self, moment: datetime) -> str:
        return describe_opening(moment, next_opening(self.s, moment))

    def test_texts(self):
        self.assertEqual(self.opens(at(17, 8)), "сьогодні з 10:00")       # вт, ще не відкрились
        self.assertEqual(self.opens(at(19, 23, 30)), "завтра з 10:00")    # чт уночі
        self.assertEqual(self.opens(at(20, 0, 30)), "сьогодні з 10:00")  # пт по півночі
        self.assertEqual(self.opens(at(21, 17)), "у понеділок з 10:00")  # сб після закриття
        self.assertEqual(self.opens(at(22, 12)), "завтра з 10:00")        # неділя

    def test_saturday_evening_to_monday(self):
        self.assertEqual(next_opening(self.s, at(21, 17)), at(23, 10))

    def test_holidays_skip(self):
        # 31.12 після 14:00 → 1.01 свято → 2.01 (субота) з 10:00
        self.assertEqual(next_opening(self.s, at(31, 15, month=12)), at(2, 10, month=1, year=2027))

    def test_far_opening_has_date(self):
        long_break = {**CLINIC, "exceptions": [
            {"date": f"2026-11-{d}", "hours": "вихідний"} for d in range(23, 30)]}
        s = parse_schedule(long_break)
        moment = at(21, 18)
        self.assertEqual(describe_opening(moment, next_opening(s, moment)), "у понеділок, 30.11, з 10:00")


class WorkingMinutesTest(unittest.TestCase):
    def setUp(self):
        self.s = parse_schedule(CLINIC)

    def test_same_day(self):
        self.assertEqual(working_minutes(self.s, at(17, 11), at(17, 13)), 120)

    def test_night_does_not_count(self):
        self.assertEqual(working_minutes(self.s, at(17, 16), at(18, 11)), 120)  # 16–17 + 10–11

    def test_weekend(self):
        # сб 16:55 → пн 10:30: 5 хв у суботу + 30 хв у понеділок; неділя не рахується
        self.assertEqual(working_minutes(self.s, at(21, 16, 55), at(23, 10, 30)), 35)

    def test_reversed(self):
        self.assertEqual(working_minutes(self.s, at(18, 11), at(17, 11)), 0)


if __name__ == "__main__":
    unittest.main()
