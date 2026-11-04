"""Настройки берутся из переменных окружения или из файла .env (см. .env.example)."""
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # python-dotenv не обязателен: можно задать переменные в системе
    pass

# Токен бота от @BotFather
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# Telegram ID администратора: сюда приходят заявки на одобрение.
# Узнать свой ID можно у @userinfobot. Если не задан — одобрение заявок отключено.
_admin_id = os.getenv("ADMIN_ID", "").strip()
ADMIN_ID = int(_admin_id) if _admin_id.isdigit() else None
