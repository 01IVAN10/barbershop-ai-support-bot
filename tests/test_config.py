"""
Юніт-тести налаштувань (bot/config.py).

Запуск:  python -m unittest tests.test_config -v

Головне тут: модулі бота імпортуються без секретів (свіжий клон без .env запускає тести),
а бот без секретів усе одно зупиняється при старті зі зрозумілою помилкою.
"""
import os
import unittest
from unittest.mock import patch

from bot.config import load_config, require_secrets


class Secrets(unittest.TestCase):
    def test_config_loads_without_secrets(self):
        with patch.dict(os.environ, {"BOT_TOKEN": "", "GEMINI_API_KEY": ""}):
            cfg = load_config()
        self.assertEqual((cfg.bot_token, cfg.gemini_api_key), ("", ""))

    def test_start_without_secrets_stops_and_names_them(self):
        with patch.dict(os.environ, {"BOT_TOKEN": "", "GEMINI_API_KEY": ""}):
            cfg = load_config()
        with self.assertRaises(SystemExit) as stop:
            require_secrets(cfg, "bot_token", "gemini_api_key")
        self.assertIn("BOT_TOKEN", str(stop.exception))
        self.assertIn("GEMINI_API_KEY", str(stop.exception))

    def test_present_secrets_pass(self):
        with patch.dict(os.environ, {"BOT_TOKEN": "123:abc", "GEMINI_API_KEY": "key"}):
            cfg = load_config()
        require_secrets(cfg, "bot_token", "gemini_api_key")  # не зупиняє


if __name__ == "__main__":
    unittest.main()
