import datetime
import os


# Telegram ID администратора: сюда приходят заявки на одобрение
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))

# Города, доступные для регистрации (клиентская часть ищет по тому же списку)
CITIES = ["Петропавловск"]

# Кнопки главного меню: если пользователь нажал их посреди диалога,
# диалог прерывается, а нажатие обрабатывается как обычно
MENU_TEXTS = {"👤 Клиент", "🏢 Сервис"}

# Петропавловск — UTC+5. Сервер может жить в другом часовом поясе,
# поэтому «сегодня» считаем по местному времени.
TZ = datetime.timezone(datetime.timedelta(hours=5))

DAY_SHORT = {1: "Пн", 2: "Вт", 3: "Ср", 4: "Чт", 5: "Пт", 6: "Сб", 7: "Вс"}


def today():
    return datetime.datetime.now(TZ).date()


def get_text(bot, message, retry, *args, interrupts=MENU_TEXTS):
    """
    Безопасно достаёт текст из сообщения внутри step-handler'а.

    Возвращает очищенный текст, либо None, если сообщение уже обработано:
      - пришёл не текст (стикер, фото…) -> просим текст и ждём снова через retry;
      - пришла команда (/start …) или кнопка меню -> диалог прерывается,
        сообщение уходит обычным обработчикам.
    """
    if message.content_type == "text":
        text = message.text.strip()

        if text.startswith("/") or text in interrupts:
            bot.process_new_messages([message])
            return None

        if text:
            return text

    msg = bot.send_message(message.chat.id, "❌ Отправьте ответ текстом.")
    bot.register_next_step_handler(msg, retry, *args)
    return None
