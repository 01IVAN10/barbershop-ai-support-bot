"""
Захисні перевірки відповіді моделі ПЕРЕД тим, як її побачить клієнт.

Логіка: промпт — це ПРОХАННЯ до моделі, а код — ГАРАНТІЯ.
Тест показав: навіть із прямою забороною в промпті модель іноді пише
«передам заявку», «зараз з'єдную». Тому код вирізає такі речення сам.

Для медичних бізнесів (safety.medical: true у YAML) код додатково гарантує:
- невідкладний стан у повідомленні → телефон одразу, БЕЗ моделі (pre_check);
- симптоми в питанні або медична порада у відповіді → текст моделі прихований,
  клієнт отримує фіксований текст, питання йде людині (resolve).
Регулярні вирази навмисно «широкі»: зайвий раз дати телефон клініки безпечніше,
ніж пропустити пораду щодо ліків.
"""
import logging
import re

from bot.knowledge import SAFETY

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

# Речення закінчується на . ! ? лише перед пробілом чи кінцем тексту, або кінцем рядка.
# Тому крапки всередині посилань і чисел («example.com.ua», «1.5») речення не ріжуть.
_SENTENCE = re.compile(r"\S.*?(?:[.!?]+(?=\s|$)|(?=\n)|$)", re.DOTALL)

# Ціна у тексті: «950 ₴», «1 000 грн». Той самий вираз використовує тест-набір.
PRICE_RE = re.compile(r"(\d[\d\s]{0,6}\d|\d)\s*(?:грн|uah|₴|hryvn)", re.IGNORECASE)

_A = r"['’ʼ]?"  # апостроф (три види) або без нього

# Невідкладний стан: укр / рос / англ. Корені слів — щоб ловити різні форми.
EMERGENCY_RE = re.compile(
    r"\b("
    r"отру[їєт]\w*|отрав\w*|poison\w*|"
    r"судом\w*|судорог\w*|конвульс\w*|seizure\w*|convuls\w*|"
    r"кровотеч\w*|кровоточ\w*|кровит\w*|кровотечен\w*|bleed\w*|"
    r"не\s+диха\w*|не\s+дише\w*|не\s+дыш\w*|задиха\w*|задыха\w*|задишк\w*|одышк\w*|"
    r"(важко|погано|тяжко|утруднен\w*|тяжело)\s+(диха\w*|дыш\w*|дих\w*)|"
    r"not\s+breathing|can['’]?t\s+breathe|difficulty\s+breathing|"
    r"травм\w*|trauma\w*|injur\w*|"
    r"(зби|сби)\w*\s+(\w+\s+)?(машин|авто)\w*|hit\s+by\s+a\s+car|"
    r"(впав|впала|випав|випала|выпал\w*|упал\w*)\s+(з|с|из)\s+(вікн|балкон|висот|окн|высот)\w*|"
    r"без\s+свідомост\w*|без\s+сознани\w*|знепритом\w*|непритомн\w*|unconscious|"
    r"не\s+реагу\w*|не\s+реагир\w*|"
    r"(про)?ковтну\w*|проглоти\w*|swallow\w*|"
    r"(безперервн\w*|постійн\w*|непрерывн\w*)\s+(блю\w*|рвот\w*)|"
    r"(різк\w*|резк\w*)\s+(погірш\w*|ухудш\w*)|"
    r"помира\w*|вмира\w*|умира\w*|dying"
    r")",
    re.IGNORECASE,
)

# Симптоми / стан / лікування конкретної тварини → лише людина.
SYMPTOM_RE = re.compile(
    r"\b("
    r"блю\w*|блюв\w*|рвот\w*|нудит\w*|vomit\w*|"
    r"не\s+їсть|не\s+ест|не\s+п" + _A + r"є|не\s+пьет|відмовля\w*\s+від\s+(їж|води)\w*|"
    r"пронос\w*|діаре\w*|понос\w*|diarrh\w*|"
    r"кашл\w*|чха\w*|чиха\w*|cough\w*|sneez\w*|"
    r"кульга\w*|хрома\w*|limp\w*|"
    r"сверб\w*|чеше\w*|чуха\w*|зуд\w*|itch\w*|"
    r"температур\w*|гарячк\w*|fever|"
    r"млява|млявий|млявіст\w*|в" + _A + r"ял\w*|вял\w*|letharg\w*|слабк\w*|"
    r"болить|болит|біль|болі|pain|hurts|"
    r"висип\w*|алергі\w*|аллерги\w*|rash|"
    r"гній\w*|гно[йї]\w*|набряк\w*|опух\w*|отек\w*|отёк\w*|swell\w*|"
    r"шишк\w*|пухлин\w*|новоутвор\w*|lump\w*|"
    r"симптом\w*|захвор\w*|хвор\w*|болі[єю]\w*|болеет|sick|ill|"
    r"що\s+(дати|давати|зробити\s+вдома)|чим\s+(лікувати|напоїти|обробити|годувати)|"
    r"як\s+лікувати|які\s+ліки|ліки|лекарств\w*|дозуван\w*|дозу|доза|"
    r"скільки\s+(дати|давати)|what\s+(should\s+i\s+)?give|medicin\w*|dosage|dose"
    r")",
    re.IGNORECASE,
)

# Медична порада у ВІДПОВІДІ моделі: дози, «дайте тварині...», назви груп ліків.
MEDICAL_ADVICE_RE = re.compile(
    r"("
    r"\d+[.,]?\d*\s*(мг|мл|mg|ml|таблет\w*|крапл\w*|капсул\w*)(?!\w)|"
    r"(мг|мл|mg|ml)\s*/\s*(кг|kg)|"
    r"\b(дайте|давайте|напоїть|промий\w*|обробіть|прикладіть|змаст\w*|закапа\w*|вколі\w*|"
    r"викличте\s+блюв\w*|не\s+годуйте|give\s+(him|her|it|your))\b|"
    r"\b(антибіотик\w*|знеболю\w*|протизапал\w*|жарознижу\w*|антигістамін\w*|"
    r"парацетамол\w*|ібупрофен\w*|аспірин\w*|но-?шп\w*|вугілл\w*|смект\w*|ентеросгел\w*|"
    r"регідрон\w*|antibiotic\w*|painkiller\w*|ibuprofen|paracetamol|aspirin)"
    r")",
    re.IGNORECASE,
)


def strip_promises(text: str) -> str:
    """Прибирає речення з обіцянками дій. Решту тексту залишає як є — з посиланнями,
    числами і переносами рядків (раніше текст склеювався заново і ламав «example.com.ua»)."""
    dropped = [m for m in _SENTENCE.finditer(text) if PROMISE_PATTERNS.search(m.group())]
    if not dropped:
        return text.strip()
    log.warning("Прибрано обіцянку з відповіді моделі: %r", " ".join(m.group() for m in dropped))
    for m in reversed(dropped):  # з кінця, щоб позиції попередніх речень не зсувались
        start, end = m.start(), m.end()
        while end < len(text) and text[end] in " \t":  # пробіл після вирізаного речення
            end += 1
        if (start == 0 or text[start - 1] == "\n") and text[end:end + 1] == "\n":
            end += 1  # речення займало весь рядок — прибираємо і сам рядок
        text = text[:start] + text[end:]
    text = re.sub(r"[ \t]+(?=\n)", "", text)  # пробіли в кінці рядка
    text = re.sub(r"\n{3,}", "\n\n", text)  # порожні рядки на місці вирізаних
    return text.strip()


def detect_emergency(text: str) -> bool:
    return bool(EMERGENCY_RE.search(text))


def detect_symptom(text: str) -> bool:
    return bool(SYMPTOM_RE.search(text))


def has_medical_advice(text: str) -> bool:
    return bool(MEDICAL_ADVICE_RE.search(text))


def medical_mode() -> bool:
    return bool(SAFETY.get("medical"))


def pre_check(question: str):
    """Перевірка ДО моделі. Повертає Reason.EMERGENCY або None.

    Невідкладний стан не чекає на модель: телефон клієнт отримує одразу,
    навіть якщо Gemini недоступний чи ліміт вичерпано.
    """
    from bot.llm import Reason  # тут, а не нагорі: guards не має залежати від llm при імпорті
    if medical_mode() and detect_emergency(question):
        return Reason.EMERGENCY
    return None


def resolve(question: str, answer: str, reason):
    """Останнє слово за КОДОМ: яка причина насправді і що з тексту моделі побачить клієнт.

    Повертає (reason, text). needs_human = reason != none. text може бути порожнім —
    тоді клієнт бачить лише фіксований текст передачі (handoff.client_notice).

    Використовують і бот (fallback.py), і тест-набір (tests/run_eval.py) — ОДНА функція,
    щоб тест перевіряв саме те, що бачать клієнти, а не свою копію логіки.

    - запис, «покличте людину», скарга: текст моделі НЕ показуємо — лише фіксоване
      повідомлення про передачу. Для запису пробували показувати (заради ціни), але
      живий тест показав суперечність: модель писала «скористайтеся кнопкою або
      зателефонуйте», а система одразу — «передав адміністратору». Ясність важливіша;
    - медичний режим: невідкладний стан / симптом у питанні / порада у відповіді →
      текст моделі НЕ показуємо, лише фіксований безпечний текст;
    - решта: текст моделі без обіцянок дій (+ примітка до ціни, якщо задана).
    """
    from bot.llm import MEDICAL_REASONS, Reason

    if medical_mode():
        if detect_emergency(question):
            reason = Reason.EMERGENCY
        elif reason in (Reason.NONE, Reason.NO_INFO, Reason.BOOKING) and detect_symptom(question):
            log.warning("Симптом у питанні — медичне питання, а не %s", reason.value)
            reason = Reason.MEDICAL
        elif reason in (Reason.NONE, Reason.NO_INFO) and has_medical_advice(answer):
            log.warning("Прибрано медичну пораду з відповіді моделі: %r", answer[:200])
            reason = Reason.MEDICAL
    elif reason in MEDICAL_REASONS:  # бізнес без медичного режиму: таких причин не буває
        reason = Reason.NO_INFO

    if reason in (Reason.BOOKING, Reason.HUMAN_REQUEST, Reason.COMPLAINT, *MEDICAL_REASONS):
        return reason, ""
    return reason, add_price_note(strip_promises(answer))


def add_price_note(text: str) -> str:
    """Є ціна у відповіді → код сам додає примітку з YAML (напр. «остаточну вартість
    визначає лікар після огляду»). Не залежить від того, чи модель про це «пам'ятала»."""
    note = SAFETY.get("price_disclaimer", "").strip()
    if not note or not text or not PRICE_RE.search(text):
        return text
    if note.lower()[:25] in text.lower():  # модель уже написала це саме — не дублюємо
        return text
    return f"{text} {note}"
