import logging
import os

import telebot
from telebot import types

from db import create_tables
from client import register_c
from service import register_s
from admin import register_a


BOT_TOKEN = os.environ["BOT_TOKEN"]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s")

bot = telebot.TeleBot(BOT_TOKEN)


# Команда /start
@bot.message_handler(commands=["start", "help"])
def start(message):
    # Сбрасываем незавершённые диалоги
    bot.clear_step_handler_by_chat_id(message.chat.id)

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)

    client_button = types.KeyboardButton("👤 Клиент")
    service_button = types.KeyboardButton("🏢 Сервис")

    markup.add(client_button, service_button)

    bot.send_message(message.chat.id, "Выберите, кто вы:", reply_markup=markup)


register_c(bot)

register_s(bot)

register_a(bot)


# Должен быть последним: ловит всё, что не подошло другим обработчикам
@bot.message_handler(func=lambda message: True)
def unknown(message):
    bot.send_message(
        message.chat.id,
        "Не понял вас 🤔 Нажмите /start, чтобы открыть меню.")


if __name__ == "__main__":
    create_tables()
    bot.infinity_polling()
