"""
Робочий час бізнесу: чи відкрито зараз, коли відкриється, скільки робочих хвилин минуло.

Навіщо: бізнес, що працює не цілодобово, не може писати вночі «передав адміністратору —
він відповість» чи «телефонуйте зараз». Що казати клієнту, вирішує КОД за графіком,
а не модель: модель може помилитися з днем тижня, код — ні.

Чистий модуль без імпортів проєкту (як reasons.py): графік передається параметром,
тож логіку можна перевірити тестами на будь-яких даних, а не лише на YAML поточного бізнесу.

Формат — той самий, що вже є в розділі schedule YAML (і його бачить модель):
  regular:    {monday: "10:00–17:00", ..., sunday: "вихідний"}
  exceptions: [{date: "2026-12-31", hours: "10:00–16:00"}, {date: "2027-01-01", hours: "вихідний"}]
"""
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
# «у понеділок з 10:00» — знахідний відмінок
WEEKDAYS_ACC_UA = ("у понеділок", "у вівторок", "у середу", "у четвер", "у п'ятницю", "у суботу", "у неділю")
CLOSED_WORDS = {"вихідний", "вихідні", "зачинено", "не працює", "closed", "off"}

# «10:00–17:00»: дефіс, коротке чи довге тире, пробіли довкола — як люди пишуть у YAML.
_RANGE = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*[-–—]\s*(\d{1,2}):(\d{2})\s*$")

# Скільки днів наперед шукати відкриття. З хоча б одним робочим днем у тижні відкриття
# знайдеться за 7 днів + винятки; межа — щоб хибні дані не дали нескінченного циклу.
_SEARCH_DAYS = 400

Interval = tuple[time, time] | None  # (відкриття, закриття) або None — вихідний


class ScheduleError(ValueError):
    """Графік у YAML не вдалося прочитати. Текст — зрозумілий автору YAML."""


@dataclass(frozen=True)
class Schedule:
    regular: tuple[Interval, ...]       # 7 днів, з понеділка
    exceptions: dict[date, Interval]    # особливі дні: свята, санітарні дні

    def hours_on(self, day: date) -> Interval:
        if day in self.exceptions:
            return self.exceptions[day]
        return self.regular[day.weekday()]


def parse_hours(value) -> Interval:
    """«10:00–17:00» → (10:00, 17:00); «вихідний» або порожньо → None."""
    if value is None or str(value).strip().lower() in CLOSED_WORDS | {""}:
        return None
    m = _RANGE.match(str(value))
    if not m:
        raise ScheduleError(f"не розумію години {value!r}: потрібно «10:00–17:00» або «вихідний»")
    h1, m1, h2, m2 = map(int, m.groups())
    try:
        start, end = time(h1, m1), time(h2, m2)
    except ValueError as e:
        raise ScheduleError(f"неможливий час у {value!r}") from e
    if end <= start:
        # Нічні зміни («20:00–02:00») поки не підтримуємо: жоден бізнес їх не мав.
        raise ScheduleError(f"у {value!r} закриття не пізніше відкриття")
    return start, end


def _parse_date(value) -> date:
    if isinstance(value, date):  # YAML перетворює 2026-12-31 без лапок на дату сам
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError as e:
        raise ScheduleError(f"дата {value!r} має бути у форматі РРРР-ММ-ДД") from e


def parse_schedule(schedule: dict) -> Schedule:
    """Розділ schedule з YAML → Schedule. Помилка — ScheduleError з поясненням."""
    regular = (schedule or {}).get("regular")
    if not isinstance(regular, dict):
        raise ScheduleError("немає schedule.regular (графік по днях тижня)")
    missing = [d for d in WEEKDAYS if d not in regular]
    if missing:
        raise ScheduleError(f"у schedule.regular бракує днів: {', '.join(missing)} "
                            "(вихідний так і напишіть: «вихідний»)")
    days = tuple(parse_hours(regular[d]) for d in WEEKDAYS)
    if all(d is None for d in days):
        raise ScheduleError("у schedule.regular немає жодного робочого дня")
    exceptions = {}
    for ex in schedule.get("exceptions") or []:
        if not isinstance(ex, dict) or "date" not in ex:
            raise ScheduleError(f"виняток у schedule.exceptions має мати date і hours: {ex!r}")
        exceptions[_parse_date(ex["date"])] = parse_hours(ex.get("hours"))
    return Schedule(days, exceptions)


def is_open(schedule: Schedule, at: datetime) -> bool:
    hours = schedule.hours_on(at.date())
    return hours is not None and hours[0] <= at.time() < hours[1]


def next_opening(schedule: Schedule, at: datetime) -> datetime:
    """Найближчий момент відкриття ПІСЛЯ `at` (або сьогодні пізніше, якщо ще не відкрилися)."""
    for offset in range(_SEARCH_DAYS):
        day = at.date() + timedelta(days=offset)
        hours = schedule.hours_on(day)
        if hours is None:
            continue
        opening = datetime.combine(day, hours[0], tzinfo=at.tzinfo)
        if opening > at:
            return opening
    raise ScheduleError(f"за {_SEARCH_DAYS} днів немає жодного робочого дня")


def describe_opening(at: datetime, opening: datetime) -> str:
    """Коли відкриється — як сказав би адміністратор: «завтра з 10:00», «у понеділок з 10:00».

    Понад тиждень (довгі свята) — з датою, інакше «у понеділок» прозвучало б як найближчий.
    """
    days = (opening.date() - at.date()).days
    clock = f"з {opening:%H:%M}"
    if days == 0:
        return f"сьогодні {clock}"
    if days == 1:
        return f"завтра {clock}"
    weekday = WEEKDAYS_ACC_UA[opening.weekday()]
    if days < 7:
        return f"{weekday} {clock}"
    return f"{weekday}, {opening:%d.%m}, {clock}"


def working_minutes(schedule: Schedule, start: datetime, end: datetime) -> float:
    """Скільки хвилин між start і end припало на робочий час.

    Для простою звернення: заявка в суботу о 16:55 не повинна «згоріти» за неділю,
    коли адміністратора немає, — рахуються лише години, коли він на місці.
    """
    if end <= start:
        return 0.0
    total = 0.0
    day = start.date()
    for _ in range(_SEARCH_DAYS):
        if day > end.date():
            break
        hours = schedule.hours_on(day)
        if hours is not None:
            opened = datetime.combine(day, hours[0], tzinfo=start.tzinfo)
            closed = datetime.combine(day, hours[1], tzinfo=start.tzinfo)
            overlap = (min(closed, end) - max(opened, start)).total_seconds()
            total += max(overlap, 0) / 60
        day += timedelta(days=1)
    return total
