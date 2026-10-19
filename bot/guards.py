"""
Захисні перевірки відповіді моделі ПЕРЕД тим, як її побачить клієнт.

Логіка: промпт — це ПРОХАННЯ до моделі, а код — ГАРАНТІЯ.
Тест показав: навіть із прямою забороною в промпті модель іноді пише
«передам заявку», «зараз з'єдную». Тому код вирізає такі речення сам.
"""
import logging
import re

log = logging.getLogger(__name__)

# Обіцянки дій, яких бот не виконує. Корені слів, щоб ловити різні форми:
# «передам», «передаю», «з'єдную», «зв'яжу», «зв'яжеться», «запишу», «уточню»...
PROMISE_PATTERNS = re.compile(
    r"\b("
    r"переда[мюєв]\w*|передам\w*|"
    r"з['’]?єдна\w*|з['’]?єдну\w*|"
    r"зв['’]?яж\w*|"
    r"запиш[уеі]\w*|записав\w*|"
    r"уточн[юи]\w*|"
    r"перетелефону\w*|зателефону[юєв]\w*|"
    r"i will (pass|forward|connect|book|contact)\w*|i['’]ll (pass|forward|connect|book|contact)\w*"
    r")",
    re.IGNORECASE,
)

# Речення = текст до . ! ? (разом із розділовим знаком)
_SENTENCE = re.compile(r"[^.!?]+[.!?]*")


def strip_promises(text: str) -> str:
    """Прибирає речення з обіцянками дій. Решту тексту залишає як є."""
    kept, dropped = [], []
    for sentence in _SENTENCE.findall(text):
        (dropped if PROMISE_PATTERNS.search(sentence) else kept).append(sentence)
    if dropped:
        log.warning("Прибрано обіцянку з відповіді моделі: %r", " ".join(s.strip() for s in dropped))
    return " ".join(s.strip() for s in kept).strip()


def client_visible_text(answer: str, reason) -> str:
    """Що з відповіді моделі реально побачить клієнт.

    Використовують і бот (fallback.py), і тест-набір (tests/run_eval.py) — ОДНА функція,
    щоб тест перевіряв саме те, що бачать клієнти, а не свою копію логіки.

    - запис, «покличте людину», скарга: текст моделі НЕ показуємо — лише фіксоване
      повідомлення про передачу. Для запису пробували показувати (заради ціни), але
      живий тест показав суперечність: модель писала «скористайтеся кнопкою або
      зателефонуйте», а система одразу — «передав адміністратору». Ясність важливіша;
    - решта: текст моделі без обіцянок дій.
    """
    from bot.llm import Reason  # тут, а не нагорі: guards не має залежати від llm при імпорті
    if reason in (Reason.BOOKING, Reason.HUMAN_REQUEST, Reason.COMPLAINT):
        return ""
    return strip_promises(answer)
