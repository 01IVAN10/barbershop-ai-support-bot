"""
Причини, чому розмову треба передати людині.

Окремий модуль без залежностей: причини потрібні і захисним перевіркам (guards),
і передачі адміну (handoff), і обгортці моделі (llm). Раніше Reason жив у llm.py поруч
із клієнтом Gemini — тому guards імпортував його всередині функцій, а юніт-тести
без ключів API не запускались.
"""
from enum import Enum


class Reason(str, Enum):
    """Чому потрібна людина. Фіксований список — щоб код міг на це реагувати."""
    NONE = "none"                    # людина не потрібна
    NO_INFO = "no_info"              # відповіді немає в базі знань
    BOOKING = "booking"              # запис, перенесення, скасування
    HUMAN_REQUEST = "human_request"  # клієнт сам просить живу людину
    COMPLAINT = "complaint"          # скарга, конфлікт, негатив
    # Лише для бізнесів із safety.medical: true (ветклініка тощо):
    EMERGENCY = "emergency"          # невідкладний стан — клієнту одразу телефон, без «чекайте»
    MEDICAL = "medical_question"     # симптоми, стан, ліки, лікування — тільки людина
    # Лише для бізнесів із safety.sensitive у YAML (напр. евтаназія у ветклініці):
    SENSITIVE = "sensitive"          # делікатна тема — співчутливо і до людини


MEDICAL_REASONS = frozenset({Reason.EMERGENCY, Reason.MEDICAL})
